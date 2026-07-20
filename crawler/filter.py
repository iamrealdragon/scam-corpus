"""관련성 필터 (CLAUDE.md 3.6).

포함 기준: 본문에 WNI(또는 orang Indonesia) 관련어 + [모집/이동/노동/폭력/착취-강요/피해] 범주 중
최소 1개가 함께 등장해야 한다. 애매하면 삭제 대신 relevance_flag='review'로 표시해 사람이 확인한다.
"""
import re

SUBJECT_TERMS = [
    "wni", "warga negara indonesia", "orang indonesia", "tenaga kerja indonesia", "tki",
]

ISSUE_TERMS = [
    # 모집
    "lowongan", "rekrut", "loker", "calo", "agen tenaga kerja", "iklan kerja",
    # 이동/밀입국
    "penyelundupan", "diselundupkan", "diberangkatkan", "dikirim ke luar negeri",
    # 노동착취/감금
    "kerja paksa", "disekap", "disandera", "paspor ditahan", "tidak digaji",
    "gaji tidak dibayar", "jam kerja panjang",
    # 폭력
    "kekerasan", "disiksa", "penganiayaan", "penyiksaan",
    # 온라인 스캠/도박
    "online scam", "penipuan online", "penipuan daring", "judi online", "scam", "scammer",
    # 인신매매
    "tppo", "perdagangan orang", "human trafficking",
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def check_relevance(body_text: str) -> dict:
    if not body_text:
        return {"relevance_flag": "review", "matched_subject": [], "matched_issue": []}

    norm = _normalize(body_text)
    matched_subject = [t for t in SUBJECT_TERMS if t in norm]
    matched_issue = [t for t in ISSUE_TERMS if t in norm]

    if matched_subject and matched_issue:
        flag = "포함"
    else:
        flag = "review"

    return {
        "relevance_flag": flag,
        "matched_subject": matched_subject,
        "matched_issue": matched_issue,
    }
