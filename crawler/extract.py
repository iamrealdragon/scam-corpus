"""기사 HTML에서 제목·발행일·본문을 추출한다 (CLAUDE.md 3.5).

우선순위: config/outlets.yaml에 정의된 매체별 CSS 셀렉터 -> 실패 시 trafilatura -> newspaper3k.
언어감지로 인도네시아어(lang == 'id') 여부를 판정한다.
"""
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import trafilatura
import yaml
from bs4 import BeautifulSoup
from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0  # langdetect 결과 재현성 고정

ROOT = Path(__file__).resolve().parent.parent
OUTLETS_PATH = ROOT / "config" / "outlets.yaml"

_PUB_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def classify_access_status(word_count: int | None, title: str | None, pub_date: str | None) -> str:
    """본문 품질 기준 access_status 분류.

    본문추출_자동: 어절수>=120, 제목 존재, 발행일 파싱 성공 — 셋 다 만족해야 한다.
    검수필요: 위 조건 중 하나라도 미달. '본문 확인'은 사람 검수를 통과한 레코드에만 부여하는
    값이라 자동 파이프라인에서는 쓰지 않는다.
    """
    date_ok = bool(pub_date) and bool(_PUB_DATE_RE.match(str(pub_date))) and str(pub_date) != "1970-01-01"
    if (word_count or 0) >= 120 and bool(title) and date_ok:
        return "본문추출_자동"
    return "검수필요"


@dataclass
class ExtractResult:
    title: str | None
    pub_date: str | None
    body_text: str | None
    word_count: int | None
    lang: str | None
    outlet_key: str | None
    extraction_method: str
    access_status: str
    byline: str | None = None


def load_outlets(path: Path = OUTLETS_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def match_outlet(url: str, outlets: dict) -> str | None:
    """URL의 도메인으로 config/outlets.yaml의 tier1 매체를 찾는다."""
    host = urlparse(url).netloc.lower()
    for key, cfg in outlets.get("tier1", {}).items():
        for domain in cfg.get("domains", []):
            if host == domain or host.endswith("." + domain):
                return key
    return None


def _extract_ld_json_field(soup: BeautifulSoup, field: str) -> str | None:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict) and field in item:
                return item[field]
    return None


def _extract_date(soup: BeautifulSoup, date_cfg: dict) -> str | None:
    strategy = date_cfg.get("strategy")
    raw = None
    if strategy == "ld_json":
        raw = _extract_ld_json_field(soup, date_cfg["json_field"])
        if raw is None and date_cfg.get("fallback"):
            meta = soup.select_one(date_cfg["fallback"])
            raw = meta.get("content") if meta else None
    elif strategy == "meta":
        meta = soup.find("meta", attrs={"property": date_cfg["meta_property"]})
        raw = meta.get("content") if meta else None
    if not raw:
        return None
    # ISO 형식 앞 10글자(YYYY-MM-DD)만 표준화해 반환
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else raw


def _extract_title(soup: BeautifulSoup, selector: str) -> str | None:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else None


def _extract_body_by_selector(soup: BeautifulSoup, selector: str) -> str | None:
    el = soup.select_one(selector)
    if not el:
        return None
    text = el.get_text("\n", strip=True)
    return text if text else None


def _extract_byline(soup: BeautifulSoup) -> str:
    """ld+json author -> meta author -> 흔한 byline 클래스 순으로 시도, 없으면 빈 문자열."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            author = item.get("author")
            if isinstance(author, dict) and author.get("name"):
                return author["name"].strip()
            if isinstance(author, list) and author:
                first = author[0]
                if isinstance(first, dict) and first.get("name"):
                    return first["name"].strip()
                if isinstance(first, str):
                    return first.strip()
            if isinstance(author, str) and author.strip():
                return author.strip()

    for attrs in ({"name": "author"}, {"property": "article:author"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            return meta["content"].strip()

    for cls in ["detail__author", "author-name", "read-page--header--author", "byline", "penulis"]:
        el = soup.find(class_=re.compile(cls))
        if el:
            text = el.get_text(strip=True)
            if text:
                return text

    return ""


def extract_article(html: str, url: str, outlets: dict | None = None) -> ExtractResult:
    outlets = outlets or load_outlets()
    outlet_key = match_outlet(url, outlets)
    soup = BeautifulSoup(html, "lxml")

    title = None
    pub_date = None
    body_text = None
    method = "none"

    cfg = outlets.get("tier1", {}).get(outlet_key) if outlet_key else None
    if cfg:
        selectors = cfg["selectors"]
        title = _extract_title(soup, selectors["title"])
        pub_date = _extract_date(soup, selectors["date"])
        body_selector = selectors["body"]
        if isinstance(body_selector, str):
            body_text = _extract_body_by_selector(soup, body_selector)
            if body_text:
                method = "css_selector"

    # 1차 폴백: trafilatura
    if not body_text:
        body_text = trafilatura.extract(html, include_comments=False)
        if body_text:
            method = "trafilatura_fallback"
            metadata = trafilatura.extract_metadata(html)
            if metadata:
                title = title or metadata.title
                pub_date = pub_date or metadata.date

    # 2차 폴백: newspaper3k
    if not body_text:
        try:
            from newspaper import Article

            art = Article(url)
            art.set_html(html)
            art.parse()
            if art.text:
                body_text = art.text
                title = title or art.title
                pub_date = pub_date or (
                    art.publish_date.strftime("%Y-%m-%d") if art.publish_date else None
                )
                method = "newspaper3k_fallback"
        except Exception:
            pass

    word_count = len(body_text.split()) if body_text else None

    lang = None
    if body_text:
        try:
            lang = detect(body_text)
        except Exception:
            lang = None

    access_status = "본문 확인" if body_text else "접근 제한"
    byline = _extract_byline(soup)

    return ExtractResult(
        title=title,
        pub_date=pub_date,
        body_text=body_text,
        word_count=word_count,
        lang=lang,
        outlet_key=outlet_key,
        extraction_method=method,
        access_status=access_status,
        byline=byline,
    )


if __name__ == "__main__":
    import sys

    html_path, url = sys.argv[1], sys.argv[2]
    result = extract_article(Path(html_path).read_text(encoding="utf-8"), url)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
