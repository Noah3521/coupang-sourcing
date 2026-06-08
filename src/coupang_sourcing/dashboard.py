"""Streamlit 소싱 대시보드 — DB 시각화 + UI에서 직접 수집.

실행:  coupang-sourcing dashboard   (경로/의존성 처리)
"왼쪽 수집" 패널은 MCP 도구와 동일한 service 연산을 호출하므로 같은 DB에 쌓이고 차트가 갱신됩니다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from coupang_sourcing import service, storage

ACCENT = "#C81E2E"            # Coupang red
PALETTE = ["#C81E2E", "#1E3A8A", "#0F766E", "#B45309", "#6D28D9", "#0EA5E9"]
RED_SCALE = ["#FCA5A5", "#C81E2E"]


def _db() -> str:
    return str(service.db_path())


@st.cache_data(ttl=20, show_spinner=False)
def q(sql: str, db: str, params: tuple = ()) -> pd.DataFrame:
    try:
        with sqlite3.connect(db) as conn:
            return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame()


def _refresh():
    st.cache_data.clear()
    st.rerun()


def style(fig, height: int = 330, title: str | None = None):
    if title:
        fig.update_layout(title=title)
    has_title = bool(title or (fig.layout.title and fig.layout.title.text))
    fig.update_layout(
        template="plotly_white", height=height,
        margin=dict(l=8, r=8, t=44 if has_title else 12, b=8),
        font=dict(family="Pretendard, -apple-system, sans-serif", size=13, color="#1f2937"),
        colorway=PALETTE, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=""),
        coloraxis_showscale=False,
    )
    fig.update_xaxes(gridcolor="#eef0f3", zeroline=False)
    fig.update_yaxes(gridcolor="#eef0f3", zeroline=False)
    return fig


def inject_css():
    st.markdown(
        """
        <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
        html, body, [class*="css"], .stMarkdown, button, input, textarea, select {
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif !important;
        }
        .stApp { background: #f4f6f9; }
        header[data-testid="stHeader"] { background: transparent; }
        #MainMenu, footer { visibility: hidden; }
        .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1300px; }
        h1, h2, h3 { color: #0f172a; letter-spacing: -0.02em; }
        /* metric -> card */
        div[data-testid="stMetric"] {
            background: #fff; border: 1px solid #e9edf2; border-radius: 14px;
            padding: 14px 18px; box-shadow: 0 1px 3px rgba(16,24,40,.04);
        }
        div[data-testid="stMetricValue"] { font-weight: 700; color: #0f172a; }
        div[data-testid="stMetricLabel"] { color: #64748b; font-weight: 500; }
        /* tabs -> pills */
        div[data-baseweb="tab-list"] { gap: 6px; border-bottom: none; }
        button[data-baseweb="tab"] {
            background: #eef1f5; border-radius: 999px; padding: 6px 16px; font-weight: 600;
            color: #475569;
        }
        button[data-baseweb="tab"][aria-selected="true"] { background: #C81E2E; color: #fff; }
        div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] { display: none; }
        /* dataframe + sidebar polish */
        [data-testid="stDataFrame"] { border: 1px solid #e9edf2; border-radius: 12px; }
        section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e9edf2; }
        .stButton button, .stFormSubmitButton button {
            border-radius: 10px; font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def collect_sidebar():
    st.sidebar.markdown("### ➕ 수집")
    st.sidebar.caption(f"DB · {_db()}")

    with st.sidebar.expander("상품 찾기 (best100 / 검색)", expanded=True):
        with st.form("find"):
            query = st.text_input("검색어 (비우면 best100)", "")
            board = st.selectbox("보드", ["bestseller", "trending"],
                                 format_func=lambda b: "7일 베스트" if b == "bestseller" else "실시간 급상승")
            category = st.text_input("카테고리 (all 또는 categoryId)", "all")
            top = st.number_input("개수(top)", 1, 100, 30)
            c1, c2, c3 = st.columns(3)
            min_rating = c1.number_input("최소평점", 0.0, 5.0, 0.0, 0.5)
            min_reviews = c2.number_input("최소리뷰", 0, 100000, 0, 100)
            max_price = c3.number_input("최대가격", 0, 10_000_000, 0, 1000)
            collect = st.checkbox("판매자 전체수집(--collect)", value=False)
            if st.form_submit_button("찾아서 저장", width="stretch"):
                with st.spinner("수집 중… (검색/전체수집은 Chrome이 잠깐 뜰 수 있음)"):
                    r = service.find_products(
                        query=query, board=board, category=category or "all", top=int(top),
                        min_rating=float(min_rating), max_price=int(max_price),
                        min_reviews=int(min_reviews), collect=collect)
                if r.get("error"):
                    st.error(r["error"])
                else:
                    st.success(f"{r['count']}개 · DB {r['inDb']}/신규 {r['new']} · 수집 {r['collected']}")
                    _refresh()

    with st.sidebar.expander("상품 링크 조회"):
        url = st.text_input("상품 URL", key="pi_url")
        store_url = st.text_input("스토어 URL (선택)", key="pi_store")
        if st.button("상품 수집", width="stretch"):
            with st.spinner("상품 수집 중…"):
                r = service.product_info(url=url, store_url=store_url)
            if r.get("error"):
                st.error(r["error"])
            else:
                st.success(f"{r.get('title')} · 점수 {r.get('sourcingScore')}")
                _refresh()

    with st.sidebar.expander("판매자 카탈로그 수집"):
        sstore = st.text_input("스토어 URL 또는 ID", key="cs_store")
        slimit = st.number_input("개수 제한", 1, 500, 50, key="cs_limit")
        if st.button("판매자 수집", width="stretch"):
            with st.spinner("판매자 카탈로그 수집 중…"):
                r = service.collect_seller(store=sstore, limit=int(slimit))
            if r.get("error"):
                st.error(r["error"])
            else:
                st.success(f"{r.get('storeName')} · {r.get('collected')}/{r.get('catalogSize')} 수집")
                _refresh()

    if st.sidebar.button("🔄 Akamai 쿠키 갱신", width="stretch"):
        with st.spinner("쿠키 발급 중…"):
            r = service.refresh_cookies()
        if r.get("error"):
            st.sidebar.error(r["error"])
        else:
            st.sidebar.success("쿠키 갱신됨")


def tab_overview(db: str):
    counts = storage.table_counts(Path(db)) if Path(db).exists() else {}
    labels = [("상품", "products"), ("랭킹 스냅샷", "rank_snapshots"),
              ("검색 스냅샷", "search_snapshots"), ("리뷰", "reviews"), ("스토어", "stores")]
    for col, (ko, key) in zip(st.columns(5), labels, strict=False):
        col.metric(ko, f"{counts.get(key, 0):,}")
    st.markdown("#### 🏅 소싱 후보 Top (점수순)")
    df = q("SELECT product_id,title,store_name,latest_price,rating_avg,review_total,"
           "sourcing_score,channel,link FROM products ORDER BY sourcing_score DESC LIMIT 25", db)
    if df.empty:
        st.info("아직 데이터가 없습니다 — 왼쪽 **➕ 수집**에서 best100/검색을 실행하세요.")
        return
    bar = df.head(12).iloc[::-1]
    fig = px.bar(bar, x="sourcing_score", y="title", orientation="h",
                 color="sourcing_score", color_continuous_scale=RED_SCALE,
                 hover_data=["latest_price", "rating_avg", "review_total"])
    fig.update_yaxes(title="")
    fig.update_xaxes(title="소싱점수")
    st.plotly_chart(style(fig, height=420), width="stretch")
    smax = float(max(1, df["sourcing_score"].max()))
    st.dataframe(
        df, hide_index=True, width="stretch",
        column_config={
            "link": st.column_config.LinkColumn("link", display_text="열기"),
            "sourcing_score": st.column_config.ProgressColumn("점수", min_value=0, max_value=smax),
        })


def tab_products(db: str):
    df = q("SELECT product_id,title,store_name,latest_price,original_price,discount_rate,"
           "rating_avg,review_total,channel,is_ad,sourcing_score,link FROM products", db)
    if df.empty:
        st.info("데이터 없음.")
        return
    c1, c2 = st.columns(2)
    min_score = c1.slider("최소 소싱점수", 0.0, float(max(1.0, df["sourcing_score"].max())), 0.0)
    chans = c2.multiselect("채널", sorted(df["channel"].dropna().unique().tolist()))
    f = df[df["sourcing_score"] >= min_score]
    if chans:
        f = f[f["channel"].isin(chans)]
    st.dataframe(f, hide_index=True, width="stretch",
                 column_config={"link": st.column_config.LinkColumn("link", display_text="열기")})
    g1, g2 = st.columns(2)
    with g1:
        fig = px.histogram(f, x="sourcing_score", nbins=20, title="소싱점수 분포")
        fig.update_traces(marker_color=ACCENT)
        st.plotly_chart(style(fig), width="stretch")
    with g2:
        sc = f.dropna(subset=["rating_avg", "latest_price"])
        if not sc.empty:
            fig = px.scatter(sc, x="rating_avg", y="latest_price", size="review_total",
                             color="channel", hover_name="title", title="가격 ↔ 평점 (크기=리뷰수)")
            st.plotly_chart(style(fig), width="stretch")


def tab_trends(db: str):
    prods = q("SELECT DISTINCT s.product_id, p.title FROM product_snapshots s "
              "LEFT JOIN products p ON p.product_id=s.product_id", db)
    if prods.empty:
        st.info("스냅샷이 아직 없습니다 (상품 수집 후 refresh 하면 시계열이 쌓입니다).")
        return
    labels = {f"{(r.title or '')[:46]}  ·  {r.product_id}": r.product_id for r in prods.itertuples()}
    pid = labels[st.selectbox("상품 선택", list(labels))]
    snap = q("SELECT crawled_at,price,review_total FROM product_snapshots "
             "WHERE product_id=? ORDER BY crawled_at", db, (pid,))
    if not snap.empty:
        c1, c2 = st.columns(2)
        f1 = px.line(snap, x="crawled_at", y="price", markers=True, title="가격 추이")
        c1.plotly_chart(style(f1), width="stretch")
        f2 = px.line(snap, x="crawled_at", y="review_total", markers=True, title="리뷰수 추이")
        f2.update_traces(line_color=PALETTE[1])
        c2.plotly_chart(style(f2), width="stretch")
    rk = q("SELECT captured_at,board,rank FROM rank_snapshots WHERE product_id=? "
           "ORDER BY captured_at", db, (pid,))
    if not rk.empty:
        f3 = px.line(rk, x="captured_at", y="rank", color="board", markers=True,
                     title="best100 랭크 변동 (1 = 상위)")
        f3.update_yaxes(autorange="reversed")
        st.plotly_chart(style(f3), width="stretch")


def tab_discovery(db: str):
    st.markdown("#### 🔥 best100 랭킹 (최신)")
    rs = q("SELECT board,category,captured_at,rank,product_id,title,price,channel,in_products "
           "FROM rank_snapshots ORDER BY captured_at DESC, rank LIMIT 300", db)
    if not rs.empty:
        cur = rs[rs["captured_at"] == rs["captured_at"].max()]
        c1, c2 = st.columns([3, 1])
        c1.dataframe(cur.drop(columns=["captured_at"]), hide_index=True, width="stretch")
        pie = cur["in_products"].map({1: "DB보유", 0: "신규"}).value_counts().reset_index()
        pie.columns = ["구분", "개수"]
        fig = px.pie(pie, names="구분", values="개수", hole=0.55,
                     color="구분", color_discrete_map={"DB보유": ACCENT, "신규": "#cbd5e1"})
        c2.plotly_chart(style(fig, height=240, title="DB보유 vs 신규"), width="stretch")
    st.markdown("#### 🔎 검색결과 — 광고 vs 일반")
    ss = q("SELECT query, SUM(is_ad) ads, SUM(1-is_ad) organic FROM search_snapshots GROUP BY query", db)
    if not ss.empty:
        m = ss.melt(id_vars="query", value_vars=["organic", "ads"], var_name="유형", value_name="개수")
        m["유형"] = m["유형"].map({"organic": "일반", "ads": "광고"})
        fig = px.bar(m, x="query", y="개수", color="유형", barmode="stack",
                     color_discrete_map={"일반": PALETTE[1], "광고": ACCENT})
        st.plotly_chart(style(fig), width="stretch")
    else:
        st.caption("검색 수집 기록 없음 — 왼쪽에서 검색어로 찾아보세요.")


def tab_sellers(db: str):
    df = q("SELECT store_name, COUNT(*) 상품수, ROUND(AVG(sourcing_score),1) 평균점수, "
           "SUM(review_total) 총리뷰 FROM products WHERE store_name IS NOT NULL "
           "GROUP BY store_name ORDER BY 상품수 DESC", db)
    if df.empty:
        st.info("판매자 데이터 없음.")
        return
    st.dataframe(df, hide_index=True, width="stretch")
    top = df.head(20)
    fig = px.bar(top, x="store_name", y="상품수", color="평균점수",
                 color_continuous_scale=RED_SCALE, title="판매자별 수집 상품 수 (Top 20)")
    fig.update_xaxes(title="")
    st.plotly_chart(style(fig), width="stretch")


def main():
    st.set_page_config(page_title="Coupang Sourcing", page_icon="🛒", layout="wide")
    inject_css()
    st.markdown(
        "<h1 style='margin-bottom:0'>🛒 Coupang Sourcing</h1>"
        "<p style='color:#64748b;margin-top:2px'>소싱 데이터 시각화 · 대시보드에서 바로 수집</p>",
        unsafe_allow_html=True,
    )
    db = _db()
    collect_sidebar()
    t1, t2, t3, t4, t5 = st.tabs(["📊 개요", "🏆 상품", "📈 트렌드", "🔎 발굴", "🏬 판매자"])
    with t1:
        tab_overview(db)
    with t2:
        tab_products(db)
    with t3:
        tab_trends(db)
    with t4:
        tab_discovery(db)
    with t5:
        tab_sellers(db)


if __name__ == "__main__":
    main()
