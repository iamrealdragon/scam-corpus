"""신규 기사 후보 URL 발견 (CLAUDE.md 3.2).

소스:
  (a) seeds/existing_120.csv 시드 (기존 커버리지 확인용, 발견 대상 아님)
  (b) config/outlets.yaml / config/queries.yaml의 태그 페이지 순회
  (c) 외부에서 수집한 후보 URL 목록 병합 (예: WebSearch의 site: 검색 결과 - robots.txt가
      금지한 매체 자체 검색창 대신 외부 검색엔진을 사용해 매체 서버 부하를 주지 않는다)

기존 120건과 URL이 겹치는 후보는 자동 제외한다.
"""
import csv
import json
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUTLETS_PATH = ROOT / "config" / "outlets.yaml"
QUERIES_PATH = ROOT / "config" / "queries.yaml"
EXISTING_SEEDS_PATH = ROOT / "seeds" / "existing_120.csv"

ARTICLE_URL_HINT = re.compile(r"/\d{4,}|-\d{6,}|/d-\d+|/berita/\d+", re.IGNORECASE)
EXCLUDE_PATH_HINT = re.compile(
    r"/tag/|/search|/index|/kategori|/category|/topik|/author|/foto/|/video/index|"
    r"#|javascript:|mailto:",
    re.IGNORECASE,
)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_existing_urls() -> set[str]:
    with open(EXISTING_SEEDS_PATH, encoding="utf-8-sig") as f:
        return {row["출처URL"].strip() for row in csv.DictReader(f) if row.get("출처URL")}


_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}


def robots_allowed(url: str, user_agent: str) -> bool:
    """robots.txt 확인. 일부 매체는 기본 urllib User-Agent로 robots.txt를 요청하면
    403을 반환해 RobotFileParser가 오판(disallow_all)하므로, 실제 크롤링에 쓰는
    User-Agent로 requests를 통해 직접 받아와 parse()에 넘긴다."""
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if root not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = requests.get(urljoin(root, "/robots.txt"), headers={"User-Agent": user_agent}, timeout=10)
            if resp.status_code == 404:
                rp.allow_all = True
            elif resp.status_code >= 400:
                _robots_cache[root] = None  # 조회 자체가 안 되면 판단 보류(허용으로 취급하지 않음)
                return False
            else:
                rp.parse(resp.text.splitlines())
        except requests.RequestException:
            _robots_cache[root] = None
            return False
        _robots_cache[root] = rp
    rp = _robots_cache[root]
    if rp is None:
        return False
    return rp.can_fetch(user_agent, url)


def harvest_links(html: str, base_url: str, outlet_domains: list[str]) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    found = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        parsed = urlparse(href)
        if not any(parsed.netloc == d or parsed.netloc.endswith("." + d) for d in outlet_domains):
            continue
        if EXCLUDE_PATH_HINT.search(href):
            continue
        if not ARTICLE_URL_HINT.search(href):
            continue
        found.add(href.split("#")[0])
    return found


def discover_from_tag_pages(outlets: dict, queries_cfg: dict, delay: float = 2.0) -> dict:
    """{outlet_key: set(candidate_urls)} 반환."""
    user_agent = outlets["fetch"]["user_agent"]
    results: dict[str, set[str]] = {}

    tag_pages_cfg = queries_cfg.get("tag_pages", {})
    for outlet_key, tag_urls in tag_pages_cfg.items():
        cfg = outlets["tier1"].get(outlet_key)
        if not cfg:
            continue
        domains = cfg["domains"]
        results.setdefault(outlet_key, set())
        for tag_url in tag_urls:
            if not robots_allowed(tag_url, user_agent):
                print(f"  [skip:robots] {tag_url}")
                continue
            try:
                r = requests.get(tag_url, headers={"User-Agent": user_agent}, timeout=15)
                time.sleep(delay)
            except requests.RequestException as e:
                print(f"  [error] {tag_url}: {e}")
                continue
            if r.status_code != 200:
                print(f"  [status={r.status_code}] {tag_url}")
                continue
            links = harvest_links(r.text, tag_url, domains)
            print(f"  [{outlet_key}] {tag_url} -> {len(links)}개 링크")
            results[outlet_key] |= links

    return results


def main():
    outlets = load_yaml(OUTLETS_PATH)
    queries_cfg = load_yaml(QUERIES_PATH)
    existing_urls = load_existing_urls()

    print(f"기존 시드 URL {len(existing_urls)}개 로드")
    print("태그 페이지 순회 시작...")
    by_outlet = discover_from_tag_pages(outlets, queries_cfg)

    candidates = []
    for outlet_key, urls in by_outlet.items():
        new_urls = urls - existing_urls
        for u in sorted(new_urls):
            candidates.append({"outlet_key": outlet_key, "url": u, "source": "tag_page"})

    out_path = ROOT / "data" / "discovered_candidates.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n신규 후보 URL {len(candidates)}개 -> {out_path}")
    return candidates


if __name__ == "__main__":
    main()
