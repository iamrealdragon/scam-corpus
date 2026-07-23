"""seeds/existing_120.csv 전량을 fetch·추출해 corpus.jsonl에 병합한다 (CLAUDE.md 1번: "본문 전량 재수집으로 승격").

발견 확장(discover.py/fetch.py)과 달리 seeds는 "이미 아는 120건"이라 항상 fetch 대상이고,
실패해도 레코드 자체는 만든다(access_status='접근 제한') — 120건 전량에 대한 설명책임을 위해서다.

corpus_type 규칙(seed '매체' 컬럼 기준):
  - Detik/BBC Indonesia -> 재게재_해외매체
  - Liputan6 Cek Fakta   -> 팩트체크
  - ANTARA Video         -> 영상물
  - 그 외                -> 기사
"""
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawler.dedup import cluster_candidates
from crawler.discover import robots_allowed
from crawler.extract import classify_access_status, extract_article, load_outlets
from crawler.fetch import ID_PREFIX, load_existing_article_ids, load_prefix_max, append_jsonl
from crawler.filter import check_relevance

ROOT = Path(__file__).resolve().parent.parent
SEEDS_PATH = ROOT / "seeds" / "existing_120.csv"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
RAW_HTML_DIR = ROOT / "data" / "raw_html"
LOG_PATH = ROOT / "logs" / "crawl_log.jsonl"

OUTLET_DISPLAY_TO_KEY = {
    "ANTARA": "antara",
    "Detik": "detik",
    "CNN Indonesia": "cnn_indonesia",
    "Liputan6": "liputan6",
    "Tirto": "tirto",
    "Kumparan": "kumparan",
    "CNBC Indonesia": "cnbc_indonesia",
    "Suara": "suara",
}


def resolve_outlet_key(seed_media_label: str) -> str | None:
    for display, key in OUTLET_DISPLAY_TO_KEY.items():
        if seed_media_label.startswith(display):
            return key
    return None


def resolve_corpus_type(seed_media_label: str) -> str:
    if seed_media_label == "Detik/BBC Indonesia":
        return "재게재_해외매체"
    if seed_media_label == "Liputan6 Cek Fakta":
        return "팩트체크"
    if seed_media_label == "ANTARA Video":
        return "영상물"
    return "기사"


def load_seed_rows() -> list[dict]:
    with open(SEEDS_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def run(delay: float = 2.0):
    outlets = load_outlets()
    user_agent = outlets["fetch"]["user_agent"]

    seed_rows = load_seed_rows()

    corpus_urls = set()
    if CORPUS_PATH.exists():
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                corpus_urls.add(json.loads(line)["url"])

    existing_article_ids = load_existing_article_ids()
    prefix_max = load_prefix_max(existing_article_ids)

    new_records = []
    stats = {"이미있음_스킵": 0, "fetch성공": 0, "robots_차단": 0, "http_오류": 0, "본문없음": 0}
    failed_urls = []

    for i, row in enumerate(seed_rows, start=1):
        url = row["출처URL"].strip()
        seed_id = row["ID"]
        seed_media_label = row["매체"]
        seed_access_status = row["접근상태"]

        if url in corpus_urls:
            stats["이미있음_스킵"] += 1
            continue

        outlet_key = resolve_outlet_key(seed_media_label)
        if outlet_key is None:
            print(f"[{i}/{len(seed_rows)}] {seed_id}: outlet_key 매핑 실패 ({seed_media_label}) -> 스킵")
            continue

        corpus_type = resolve_corpus_type(seed_media_label)

        log_entry = {
            "url": url, "outlet_key": outlet_key, "query_source": "seed_merge",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

        def make_failed_record(reason: str, http_status=None):
            prefix = ID_PREFIX[outlet_key]
            prefix_max[prefix] += 1
            article_id = f"{prefix}-{prefix_max[prefix]:04d}"
            return {
                "article_id": article_id,
                "legacy_article_id": seed_id,
                "outlet": outlets["tier1"][outlet_key]["name"],
                "outlet_key": outlet_key,
                "media_type": outlets["tier1"][outlet_key].get("media_type_code"),
                "corpus_type": corpus_type,
                "url": url,
                "title": None,
                "byline": None,
                "pub_date": None,
                "year": None,
                "body_text": None,
                "word_count": None,
                "lang": None,
                "access_status": "접근 제한",
                "content_hash": None,
                "extraction_method": "none",
                "relevance_flag": "review",
                "matched_subject_terms": [],
                "matched_issue_terms": [],
                "search_query": "seed_merge",
                "http_status": http_status,
                "retrieved_at": log_entry["retrieved_at"],
                "raw_html_path": None,
                "seed_access_status": seed_access_status,
                "fetch_fail_reason": reason,
            }

        if not robots_allowed(url, user_agent):
            log_entry["status"] = "robots_disallowed"
            append_jsonl(LOG_PATH, log_entry)
            stats["robots_차단"] += 1
            new_records.append(make_failed_record("robots_disallowed"))
            failed_urls.append({"legacy_article_id": seed_id, "url": url, "reason": "robots_disallowed"})
            print(f"[{i}/{len(seed_rows)}] {seed_id}: robots 차단")
            continue

        try:
            r = requests.get(url, headers={"User-Agent": user_agent}, timeout=15)
        except requests.RequestException as e:
            log_entry["status"] = f"error:{e}"
            append_jsonl(LOG_PATH, log_entry)
            stats["http_오류"] += 1
            new_records.append(make_failed_record(f"request_error:{e}"))
            failed_urls.append({"legacy_article_id": seed_id, "url": url, "reason": f"request_error:{e}"})
            print(f"[{i}/{len(seed_rows)}] {seed_id}: 요청 오류 {e}")
            time.sleep(delay)
            continue

        log_entry["http_status"] = r.status_code
        if r.status_code != 200:
            log_entry["status"] = "http_error"
            append_jsonl(LOG_PATH, log_entry)
            stats["http_오류"] += 1
            new_records.append(make_failed_record(f"http_{r.status_code}", http_status=r.status_code))
            failed_urls.append({"legacy_article_id": seed_id, "url": url, "reason": f"http_{r.status_code}"})
            print(f"[{i}/{len(seed_rows)}] {seed_id}: HTTP {r.status_code}")
            time.sleep(delay)
            continue

        result = extract_article(r.text, url, outlets)
        if not result.body_text:
            log_entry["status"] = "no_body_extracted"
            append_jsonl(LOG_PATH, log_entry)
            stats["본문없음"] += 1
            new_records.append(make_failed_record("no_body_extracted", http_status=r.status_code))
            failed_urls.append({"legacy_article_id": seed_id, "url": url, "reason": "no_body_extracted"})
            print(f"[{i}/{len(seed_rows)}] {seed_id}: 본문 추출 실패")
            time.sleep(delay)
            continue

        prefix = ID_PREFIX[outlet_key]
        prefix_max[prefix] += 1
        article_id = f"{prefix}-{prefix_max[prefix]:04d}"

        relevance = check_relevance(result.body_text)
        (RAW_HTML_DIR / f"{article_id}.html").write_text(r.text, encoding="utf-8")

        record = {
            "article_id": article_id,
            "legacy_article_id": seed_id,
            "outlet": outlets["tier1"][outlet_key]["name"],
            "outlet_key": outlet_key,
            "media_type": outlets["tier1"][outlet_key].get("media_type_code"),
            "corpus_type": corpus_type,
            "url": url,
            "title": result.title,
            "byline": result.byline,
            "pub_date": result.pub_date,
            "year": int(result.pub_date[:4]) if result.pub_date else None,
            "body_text": result.body_text,
            "word_count": result.word_count,
            "lang": result.lang,
            "access_status": classify_access_status(result.word_count, result.title, result.pub_date),
            "content_hash": hashlib.sha256(result.body_text.encode("utf-8")).hexdigest(),
            "extraction_method": result.extraction_method,
            "relevance_flag": relevance["relevance_flag"],
            "matched_subject_terms": relevance["matched_subject"],
            "matched_issue_terms": relevance["matched_issue"],
            "search_query": "seed_merge",
            "http_status": r.status_code,
            "retrieved_at": log_entry["retrieved_at"],
            "raw_html_path": f"data/raw_html/{article_id}.html",
            "seed_access_status": seed_access_status,
        }
        new_records.append(record)

        log_entry["status"] = "ok"
        append_jsonl(LOG_PATH, log_entry)
        stats["fetch성공"] += 1
        print(f"[{i}/{len(seed_rows)}] {article_id} (legacy={seed_id}) {outlet_key}: "
              f"{result.title[:50] if result.title else '(제목 없음)'} [{record['access_status']}]")

        time.sleep(delay)

    print("\n사건군 후보 클러스터링 중...")
    new_records = cluster_candidates(new_records)

    new_ids = [r["article_id"] for r in new_records]
    assert len(new_ids) == len(set(new_ids)), (
        f"이번 배치 내부에서 article_id가 중복됨: "
        f"{[i for i in set(new_ids) if new_ids.count(i) > 1]}"
    )
    colliding = existing_article_ids & set(new_ids)
    assert not colliding, f"기존 corpus.jsonl과 article_id 충돌: {sorted(colliding)}"

    for rec in new_records:
        append_jsonl(CORPUS_PATH, rec)

    print("\n=== seed 병합 요약 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"corpus.jsonl에 {len(new_records)}건 추가 -> {CORPUS_PATH}")

    return new_records, stats, failed_urls


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    run(delay=args.delay)
