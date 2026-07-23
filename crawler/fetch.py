"""후보 URL을 실제로 수집해 코퍼스에 추가한다 (CLAUDE.md 3.4, 4).

입력: data/discovered_candidates.jsonl (태그페이지 수집) + data/websearch_candidates.txt (site: 검색 결과, 탭 구분: outlet_key\\turl)
처리: robots.txt 확인 -> rate limit -> GET -> extract.py -> filter.py(관련성) -> dedup.py(사건군 후보)
출력: data/raw_html/{article_id}.html, data/corpus.jsonl(append), logs/crawl_log.jsonl(append)

전량 자동 확정이 아니라 "후보 코퍼스"를 만드는 단계다. relevance_flag='review'인 기사와
event_cluster가 붙은 기사는 사람이 최종 확인해야 한다 (CLAUDE.md 3.6/3.7).

article_id는 outlet_key 접두(3글자) + 0패딩 4자리(예: ANT-0001)로 발번한다.
발번 기준은 corpus.jsonl에 이미 존재하는 ID의 접두사별 최댓값이다(시드 CSV 기준 아님) —
회차를 거듭해도 ID가 겹치지 않도록, 그리고 발번 직후 전체 코퍼스 ID 유일성을 검증한다.
"""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawler.dedup import cluster_candidates
from crawler.discover import robots_allowed, load_existing_urls
from crawler.extract import classify_access_status, extract_article, load_outlets
from crawler.filter import check_relevance

ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
RAW_HTML_DIR = ROOT / "data" / "raw_html"
LOG_PATH = ROOT / "logs" / "crawl_log.jsonl"
DISCOVERED_PATH = ROOT / "data" / "discovered_candidates.jsonl"
WEBSEARCH_PATH = ROOT / "data" / "websearch_candidates.txt"

ID_PREFIX = {
    "antara": "ANT", "detik": "DET", "cnn_indonesia": "CNN", "liputan6": "LIP",
    "tirto": "TIR", "kumparan": "KUM", "cnbc_indonesia": "CNB", "suara": "SUA",
}
ARTICLE_ID_RE = re.compile(r"^([A-Z]+)-(\d+)$")


def load_already_fetched_urls() -> set[str]:
    if not CORPUS_PATH.exists():
        return set()
    urls = set()
    for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            urls.add(json.loads(line)["url"])
    return urls


def load_candidates(existing_urls: set[str]) -> list[dict]:
    seen = set(existing_urls) | load_already_fetched_urls()
    candidates = []

    if DISCOVERED_PATH.exists():
        for line in DISCOVERED_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["url"] in seen:
                continue
            seen.add(rec["url"])
            candidates.append({"outlet_key": rec["outlet_key"], "url": rec["url"], "source": "tag_page"})

    if WEBSEARCH_PATH.exists():
        for line in WEBSEARCH_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            outlet_key, url = line.split("\t", 1)
            url = url.strip()
            if url in seen:
                continue
            seen.add(url)
            candidates.append({"outlet_key": outlet_key, "url": url, "source": "websearch_site_query"})

    return candidates


def load_existing_article_ids() -> set[str]:
    """corpus.jsonl에 이미 존재하는 article_id 전체."""
    if not CORPUS_PATH.exists():
        return set()
    ids = set()
    for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.add(json.loads(line)["article_id"])
    return ids


def load_prefix_max(existing_ids: set[str]) -> dict:
    """corpus.jsonl의 기존 ID(PREFIX-NNNN)에서 접두사별 최댓값을 읽는다 (시드 CSV 기준 아님)."""
    prefix_max = {p: 0 for p in ID_PREFIX.values()}
    for aid in existing_ids:
        m = ARTICLE_ID_RE.match(aid)
        if m and m.group(1) in prefix_max:
            prefix_max[m.group(1)] = max(prefix_max[m.group(1)], int(m.group(2)))
    return prefix_max


def append_jsonl(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(limit: int | None = None, delay: float = 2.0):
    outlets = load_outlets()
    existing_urls = load_existing_urls()
    candidates = load_candidates(existing_urls)
    if limit:
        candidates = candidates[:limit]

    print(f"후보 {len(candidates)}건 처리 시작 (기존 시드 {len(existing_urls)}건과 중복 제외됨)")

    existing_article_ids = load_existing_article_ids()
    prefix_max = load_prefix_max(existing_article_ids)
    user_agent = outlets["fetch"]["user_agent"]

    fetched_records = []
    stats = {"ok": 0, "relevant": 0, "review": 0, "robots_skip": 0, "http_error": 0, "no_body": 0}

    for i, cand in enumerate(candidates, start=1):
        url = cand["url"]
        outlet_key = cand["outlet_key"]
        log_entry = {
            "url": url, "outlet_key": outlet_key, "query_source": cand["source"],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

        if not robots_allowed(url, user_agent):
            log_entry["status"] = "robots_disallowed"
            append_jsonl(LOG_PATH, log_entry)
            stats["robots_skip"] += 1
            continue

        try:
            r = requests.get(url, headers={"User-Agent": user_agent}, timeout=15)
        except requests.RequestException as e:
            log_entry["status"] = f"error:{e}"
            append_jsonl(LOG_PATH, log_entry)
            stats["http_error"] += 1
            time.sleep(delay)
            continue

        log_entry["http_status"] = r.status_code
        if r.status_code != 200:
            log_entry["status"] = "http_error"
            append_jsonl(LOG_PATH, log_entry)
            stats["http_error"] += 1
            time.sleep(delay)
            continue

        result = extract_article(r.text, url, outlets)
        if not result.body_text:
            log_entry["status"] = "no_body_extracted"
            append_jsonl(LOG_PATH, log_entry)
            stats["no_body"] += 1
            time.sleep(delay)
            continue

        prefix = ID_PREFIX[outlet_key]
        prefix_max[prefix] += 1
        article_id = f"{prefix}-{prefix_max[prefix]:04d}"

        relevance = check_relevance(result.body_text)

        (RAW_HTML_DIR / f"{article_id}.html").write_text(r.text, encoding="utf-8")

        record = {
            "article_id": article_id,
            "outlet": outlets["tier1"][outlet_key]["name"],
            "outlet_key": outlet_key,
            "media_type": outlets["tier1"][outlet_key].get("media_type_code"),
            "url": url,
            "title": result.title,
            "byline": result.byline,
            "pub_date": result.pub_date,
            "year": int(result.pub_date[:4]) if result.pub_date else None,
            "body_text": result.body_text,
            "word_count": result.word_count,
            "lang": result.lang,
            "access_status": classify_access_status(result.word_count, result.title, result.pub_date),
            "content_hash": hashlib.sha256((result.body_text or "").encode("utf-8")).hexdigest(),
            "extraction_method": result.extraction_method,
            "relevance_flag": relevance["relevance_flag"],
            "matched_subject_terms": relevance["matched_subject"],
            "matched_issue_terms": relevance["matched_issue"],
            "search_query": cand["source"],
            "http_status": r.status_code,
            "retrieved_at": log_entry["retrieved_at"],
            "raw_html_path": f"data/raw_html/{article_id}.html",
        }
        fetched_records.append(record)

        log_entry["status"] = "ok"
        append_jsonl(LOG_PATH, log_entry)
        stats["ok"] += 1
        if relevance["relevance_flag"] == "포함":
            stats["relevant"] += 1
        else:
            stats["review"] += 1

        print(f"[{i}/{len(candidates)}] {article_id} {outlet_key}: {result.title[:50] if result.title else '(제목 없음)'} "
              f"[{relevance['relevance_flag']}]")

        time.sleep(delay)

    print("\n사건군 후보 클러스터링 중...")
    fetched_records = cluster_candidates(fetched_records)

    new_ids = [r["article_id"] for r in fetched_records]
    assert len(new_ids) == len(set(new_ids)), (
        f"이번 배치 내부에서 article_id가 중복됨: "
        f"{[i for i in set(new_ids) if new_ids.count(i) > 1]}"
    )
    colliding = existing_article_ids & set(new_ids)
    assert not colliding, f"기존 corpus.jsonl과 article_id 충돌: {sorted(colliding)}"

    for rec in fetched_records:
        append_jsonl(CORPUS_PATH, rec)

    print("\n=== 수집 요약 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"corpus.jsonl에 {len(fetched_records)}건 추가 -> {CORPUS_PATH}")

    n_clusters = len({r["event_cluster"] for r in fetched_records if r.get("cluster_size", 1) > 1})
    print(f"사건군 후보(2건 이상 클러스터): {n_clusters}개")

    return fetched_records, stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    run(limit=args.limit, delay=args.delay)
