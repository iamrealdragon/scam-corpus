"""중복/사건군 후보 탐지 (CLAUDE.md 3.7).

매체 간 동일사건 중복 보도는 삭제하지 않고 사건군(event_cluster) 후보로만 묶는다.
자동 배정되는 cluster id는 사람이 검토해 KH-249-2026 형식의 최종 사건군 코드로 다시 부여한다.
"""
import re
from difflib import SequenceMatcher


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def find_url_duplicates(candidate_urls: list[str], existing_urls: set[str]) -> set[str]:
    """기존 코퍼스에 이미 있는 URL을 제거 대상으로 반환한다."""
    return {u for u in candidate_urls if u in existing_urls}


def cluster_candidates(
    articles: list[dict],
    title_key: str = "title",
    date_key: str = "pub_date",
    similarity_threshold: float = 0.55,
    date_window_days: int = 5,
) -> list[dict]:
    """제목 유사도 + 발행일 근접성으로 사건군 후보를 묶는다.

    articles의 각 dict에 'event_cluster_candidate' 필드를 추가해 반환한다.
    최종 사건군 코드(KH-249-2026 등)는 사람이 검토 후 확정한다.
    """
    from datetime import datetime

    def parse_date(s):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except (TypeError, ValueError):
            return None

    clusters: list[list[int]] = []
    assigned = [-1] * len(articles)

    for i, art in enumerate(articles):
        if assigned[i] != -1:
            continue
        clusters.append([i])
        assigned[i] = len(clusters) - 1
        d_i = parse_date(art.get(date_key))
        for j in range(i + 1, len(articles)):
            if assigned[j] != -1:
                continue
            sim = title_similarity(art.get(title_key, ""), articles[j].get(title_key, ""))
            if sim < similarity_threshold:
                continue
            d_j = parse_date(articles[j].get(date_key))
            if d_i and d_j and abs((d_i - d_j).days) > date_window_days:
                continue
            clusters[assigned[i]].append(j)
            assigned[j] = assigned[i]

    for cluster_idx, indices in enumerate(clusters):
        for i in indices:
            articles[i]["event_cluster_candidate"] = f"AUTO-{cluster_idx:03d}"
            articles[i]["cluster_size"] = len(indices)

    return articles
