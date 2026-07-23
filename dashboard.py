"""인도네시아 온라인스캠센터 보도 코퍼스 구축 현황 대시보드.

seeds/existing_120.csv(기존 시드) + data/corpus.jsonl(발견 확장분)을 통합해
수집 진행 상황을 모니터링한다. 아직 LLM 프리코딩 이전 단계라 B~H 프레이밍
변수 분석은 포함하지 않는다 — 코퍼스 구축 현황판.
"""
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="온라인스캠센터 보도 코퍼스 현황",
    page_icon="🗞️",
    layout="wide",
)

ROOT = Path(__file__).resolve().parent

# 8개 1차 매체, 고정 순서·고정 색상(Okabe-Ito 색맹 안전 팔레트)
OUTLET_ORDER = ["ANTARA", "Detik", "CNN Indonesia", "Liputan6", "Tirto", "Kumparan", "CNBC Indonesia", "Suara"]
OUTLET_COLOR = {
    "ANTARA": "#E69F00",
    "Detik": "#56B4E9",
    "CNN Indonesia": "#009E73",
    "Liputan6": "#D8B70A",
    "Tirto": "#0072B2",
    "Kumparan": "#D55E00",
    "CNBC Indonesia": "#CC79A7",
    "Suara": "#666666",
}


def normalize_outlet(name: str) -> str:
    for base in OUTLET_ORDER:
        if isinstance(name, str) and name.startswith(base):
            return base
    return name


@st.cache_data(ttl=60)
def load_seed() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "seeds" / "existing_120.csv", encoding="utf-8-sig")
    df["outlet_norm"] = df["매체"].apply(normalize_outlet)
    return df


@st.cache_data(ttl=60)
def load_corpus() -> pd.DataFrame:
    path = ROOT / "data" / "corpus.jsonl"
    if not path.exists():
        return pd.DataFrame()
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    df = pd.DataFrame(records)
    df["outlet_norm"] = df["outlet"].apply(normalize_outlet)
    return df


seed_df = load_seed()
corpus_df = load_corpus()

PAGES = ["연구 소개", "수집 현황", "매체별 현황", "연도별 추이", "검토 대기", "코퍼스 탐색"]
page = st.sidebar.radio("페이지", PAGES)

st.sidebar.markdown("---")
st.sidebar.caption(f"기존 시드: {len(seed_df)}건 · 발견 확장: {len(corpus_df)}건")


# ── 연구 소개 ────────────────────────────────────────────────────────────────
if page == "연구 소개":
    st.title("🗞️ 인도네시아 언론 온라인스캠센터 보도 코퍼스")
    st.markdown(
        """
### 연구 개요
인도네시아 언론(ANTARA·Detik·CNN Indonesia·Liputan6·Tirto·Kumparan·CNBC Indonesia·Suara)의
동남아 온라인 스캠센터(캄보디아·미얀마) 관련 WNI(인도네시아 국민) 피해 보도를 SSCI 투고용
내용분석 코퍼스로 구축하는 프로젝트.

- 분석단위: 개별 기사
- 이론 골격: Entman 프레이밍 + Iyengar 에피소드/주제 프레임 + 플랫폼 책임 가시화 + 강제범죄화
- 방법론 템플릿: Meghan Sobel(2015 FGC, 2016 Thai sex trafficking) — 아카이브 기반 목적표집 + Krippendorff's α

### 현재 단계
**발견 확장(discovery) 1회차 완료.** LLM 프리코딩은 착수 전 — 검토 대기 항목(관련성 제외 후보,
사건군 후보, 데이터 이상)을 사람이 확인한 뒤 진행 예정.
        """
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("기존 시드", f"{len(seed_df)}건")
    c2.metric("발견 확장", f"{len(corpus_df)}건")
    c3.metric("누적 코퍼스", f"{len(seed_df) + len(corpus_df)}건")


# ── 수집 현황 ────────────────────────────────────────────────────────────────
elif page == "수집 현황":
    st.title("수집 현황")

    st.subheader("기존 시드 (seeds/existing_120.csv)")
    seed_status = seed_df["접근상태"].value_counts().reindex(
        ["본문 확인", "검색결과 확인", "링크 확인(본문 미검증)"]
    ).fillna(0).astype(int)
    c1, c2, c3 = st.columns(3)
    c1.metric("본문 확인", int(seed_status.get("본문 확인", 0)))
    c2.metric("검색결과 확인", int(seed_status.get("검색결과 확인", 0)))
    c3.metric("링크 확인(본문 미검증)", int(seed_status.get("링크 확인(본문 미검증)", 0)))

    fig = px.bar(
        seed_status.rename_axis("접근상태").reset_index(name="건수"),
        x="접근상태", y="건수", text="건수",
        color_discrete_sequence=["#0072B2"],
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(yaxis_title="건수", xaxis_title=None, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("발견 확장 (data/corpus.jsonl)")
    if corpus_df.empty:
        st.info("아직 발견 확장 데이터 없음.")
    else:
        rel_counts = corpus_df["relevance_flag"].value_counts()
        c1, c2, c3 = st.columns(3)
        c1.metric("전체 fetch", len(corpus_df))
        c2.metric("관련성 '포함'", int(rel_counts.get("포함", 0)))
        c3.metric("검토 대상('review')", int(rel_counts.get("review", 0)))

        method_counts = corpus_df["extraction_method"].value_counts()
        fig2 = px.bar(
            method_counts.rename_axis("추출 방식").reset_index(name="건수"),
            x="추출 방식", y="건수", text="건수",
            color_discrete_sequence=["#009E73"],
        )
        fig2.update_traces(textposition="outside")
        fig2.update_layout(yaxis_title="건수", xaxis_title=None, showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

        n_clusters = corpus_df[corpus_df.get("cluster_size", pd.Series(dtype=int)).fillna(1) > 1]
        n_cluster_ids = n_clusters["event_cluster"].nunique() if not n_clusters.empty else 0
        st.caption(f"사건군 후보 클러스터: {n_cluster_ids}개 ({len(n_clusters)}건) — '검토 대기' 페이지에서 확인")


# ── 매체별 현황 ──────────────────────────────────────────────────────────────
elif page == "매체별 현황":
    st.title("매체별 현황")

    seed_by_outlet = seed_df["outlet_norm"].value_counts().reindex(OUTLET_ORDER).fillna(0).astype(int)
    corpus_by_outlet = (
        corpus_df["outlet_norm"].value_counts().reindex(OUTLET_ORDER).fillna(0).astype(int)
        if not corpus_df.empty else pd.Series(0, index=OUTLET_ORDER)
    )

    combined = pd.DataFrame({"기존 시드": seed_by_outlet, "발견 확장": corpus_by_outlet})
    combined = combined.rename_axis("매체").reset_index()
    combined_long = combined.melt(id_vars="매체", var_name="구분", value_name="건수")

    fig = px.bar(
        combined_long, x="매체", y="건수", color="구분", barmode="group", text="건수",
        category_orders={"매체": OUTLET_ORDER},
        color_discrete_map={"기존 시드": "#666666", "발견 확장": "#0072B2"},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(yaxis_title="건수", xaxis_title=None, legend_title=None)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("매체별 상세")
    combined["합계"] = combined["기존 시드"] + combined["발견 확장"]
    st.dataframe(combined.set_index("매체"), use_container_width=True)

    if not corpus_df.empty:
        st.subheader("매체별 관련성 판정 비율 (발견 확장분)")
        rel_by_outlet = (
            corpus_df.groupby(["outlet_norm", "relevance_flag"]).size().reset_index(name="건수")
        )
        fig3 = px.bar(
            rel_by_outlet, x="outlet_norm", y="건수", color="relevance_flag", barmode="stack",
            category_orders={"outlet_norm": OUTLET_ORDER},
            color_discrete_map={"포함": "#009E73", "review": "#D55E00"},
            labels={"outlet_norm": "매체"},
        )
        fig3.update_layout(xaxis_title=None, legend_title=None)
        st.plotly_chart(fig3, use_container_width=True)


# ── 연도별 추이 ──────────────────────────────────────────────────────────────
elif page == "연도별 추이":
    st.title("연도별 추이")

    seed_year = seed_df["연도"].value_counts().sort_index()
    if not corpus_df.empty:
        corpus_year = corpus_df["year"].value_counts().sort_index()
        # 1970 등 파싱 오류 연도는 그래프에서 제외 ('검토 대기'에서 별도 표시)
        corpus_year = corpus_year[corpus_year.index >= 2020]
    else:
        corpus_year = pd.Series(dtype=int)

    years = sorted(set(seed_year.index) | set(corpus_year.index))
    trend = pd.DataFrame({
        "연도": years,
        "기존 시드": [int(seed_year.get(y, 0)) for y in years],
        "발견 확장": [int(corpus_year.get(y, 0)) for y in years],
    })
    trend_long = trend.melt(id_vars="연도", var_name="구분", value_name="건수")

    fig = px.line(
        trend_long, x="연도", y="건수", color="구분", markers=True,
        color_discrete_map={"기존 시드": "#666666", "발견 확장": "#0072B2"},
    )
    fig.update_layout(xaxis_title=None, yaxis_title="건수", legend_title=None)
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("2026년은 아직 연중 — 하반기 반영 전 수치임에 유의.")


# ── 검토 대기 ────────────────────────────────────────────────────────────────
elif page == "검토 대기":
    st.title("검토 대기")
    st.caption("자동 파이프라인이 확정하지 않고 사람 확인을 남겨둔 항목.")

    if corpus_df.empty:
        st.info("발견 확장 데이터 없음.")
    else:
        st.subheader("관련성 제외 후보 (relevance_flag = 'review')")
        review_df = corpus_df[corpus_df["relevance_flag"] == "review"][
            ["article_id", "outlet_norm", "title", "url"]
        ].rename(columns={"outlet_norm": "매체"})
        st.dataframe(review_df, use_container_width=True, hide_index=True)

        st.subheader("사건군 후보 클러스터")
        if "cluster_size" in corpus_df.columns:
            clustered = corpus_df[corpus_df["cluster_size"].fillna(1) > 1].sort_values(
                "event_cluster"
            )
            for cid, group in clustered.groupby("event_cluster"):
                with st.expander(f"{cid} — {len(group)}건"):
                    st.dataframe(
                        group[["article_id", "outlet_norm", "title", "pub_date", "url"]].rename(
                            columns={"outlet_norm": "매체"}
                        ),
                        use_container_width=True, hide_index=True,
                    )
        else:
            st.info("사건군 후보 없음.")

        st.subheader("데이터 이상 항목")
        issues = corpus_df[(corpus_df["title"].isna()) | (corpus_df["year"] < 2020)]
        if issues.empty:
            st.write("이상 없음.")
        else:
            st.dataframe(
                issues[["article_id", "outlet_norm", "title", "pub_date", "url"]].rename(
                    columns={"outlet_norm": "매체"}
                ),
                use_container_width=True, hide_index=True,
            )


# ── 코퍼스 탐색 ──────────────────────────────────────────────────────────────
elif page == "코퍼스 탐색":
    st.title("코퍼스 탐색")

    if corpus_df.empty:
        st.info("발견 확장 데이터 없음.")
    else:
        col1, col2 = st.columns(2)
        outlet_filter = col1.multiselect("매체", OUTLET_ORDER, default=OUTLET_ORDER)
        relevance_filter = col2.multiselect(
            "관련성", ["포함", "review"], default=["포함", "review"]
        )
        keyword = st.text_input("제목 검색어")

        filtered = corpus_df[
            corpus_df["outlet_norm"].isin(outlet_filter)
            & corpus_df["relevance_flag"].isin(relevance_filter)
        ]
        if keyword:
            filtered = filtered[filtered["title"].fillna("").str.contains(keyword, case=False)]

        st.caption(f"{len(filtered)}건 표시 중")
        for _, row in filtered.iterrows():
            with st.expander(f"[{row['article_id']}] {row['outlet_norm']} · {row['title'] or '(제목 없음)'}"):
                st.write(f"발행일: {row['pub_date']} · 단어수: {row['word_count']} · "
                         f"관련성: {row['relevance_flag']} · 추출방식: {row['extraction_method']}")
                st.write(f"[원문 링크]({row['url']})")
                st.text(row["body_text"][:600] + ("..." if len(row["body_text"] or "") > 600 else ""))
