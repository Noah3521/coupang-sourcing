"""Streamlit sourcing dashboard — visualize the SQLite DB AND collect more from the UI.

Launch via the CLI (handles paths/deps):  coupang-sourcing dashboard
or directly:  streamlit run -m ...  ->  COUPANG_SOURCING_DB=... streamlit run dashboard.py

The "Collect" sidebar runs the same operations as the MCP tools (service.py), so new data
lands in the same DB and the charts update.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from coupang_sourcing import service, storage


def _db() -> Path:
    return service.db_path()


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


def collect_sidebar():
    st.sidebar.header("➕ 수집 (Collect)")
    st.sidebar.caption(f"DB: {_db()}")

    with st.sidebar.expander("Find products (best100 / search)", expanded=True):
        with st.form("find"):
            query = st.text_input("검색어 (비우면 best100)", "")
            board = st.selectbox("board", ["bestseller", "trending"])
            category = st.text_input("category", "all")
            top = st.number_input("top", 1, 100, 30)
            c1, c2, c3 = st.columns(3)
            min_rating = c1.number_input("min_rating", 0.0, 5.0, 0.0, 0.5)
            min_reviews = c2.number_input("min_reviews", 0, 100000, 0, 100)
            max_price = c3.number_input("max_price", 0, 10_000_000, 0, 1000)
            collect = st.checkbox("판매자 전체수집(--collect)", value=False)
            if st.form_submit_button("Find & save", width="stretch"):
                with st.spinner("수집 중… (검색/수집은 Chrome이 잠깐 뜰 수 있음)"):
                    r = service.find_products(
                        query=query, board=board, category=category or "all", top=int(top),
                        min_rating=float(min_rating), max_price=int(max_price),
                        min_reviews=int(min_reviews), collect=collect)
                if r.get("error"):
                    st.error(r["error"])
                else:
                    st.success(
                        f"{r['count']}개 · DB {r['inDb']} / 신규 {r['new']} · 전체수집 {r['collected']}")
                    _refresh()

    with st.sidebar.expander("Product link → info"):
        url = st.text_input("상품 URL", key="pi_url")
        store_url = st.text_input("스토어 URL (선택)", key="pi_store")
        if st.button("Collect product", width="stretch"):
            with st.spinner("상품 수집 중…"):
                r = service.product_info(url=url, store_url=store_url)
            if r.get("error"):
                st.error(r["error"])
            else:
                st.success(f"{r.get('title')} · score {r.get('sourcingScore')}")
                _refresh()

    with st.sidebar.expander("Collect seller catalog"):
        sstore = st.text_input("스토어 URL 또는 ID", key="cs_store")
        slimit = st.number_input("limit", 1, 500, 50, key="cs_limit")
        if st.button("Collect seller", width="stretch"):
            with st.spinner("판매자 카탈로그 수집 중…"):
                r = service.collect_seller(store=sstore, limit=int(slimit))
            if r.get("error"):
                st.error(r["error"])
            else:
                st.success(f"{r.get('storeName')}: {r.get('collected')}/{r.get('catalogSize')} 수집")
                _refresh()

    if st.sidebar.button("🔄 Akamai 쿠키 갱신"):
        with st.spinner("쿠키 발급 중…"):
            r = service.refresh_cookies()
        if r.get("error"):
            st.sidebar.error(r["error"])
        else:
            st.sidebar.success("쿠키 갱신됨")


def tab_overview(db: str):
    counts = storage.table_counts(Path(db)) if Path(db).exists() else {}
    keys = ["products", "rank_snapshots", "search_snapshots", "reviews", "stores"]
    for col, key in zip(st.columns(5), keys, strict=False):
        col.metric(key, counts.get(key, 0))
    st.subheader("소싱 후보 Top (점수순)")
    df = q("SELECT product_id,title,store_name,latest_price,rating_avg,review_total,"
           "sourcing_score,channel,link FROM products ORDER BY sourcing_score DESC LIMIT 25", db)
    if df.empty:
        st.info("아직 데이터가 없습니다 — 왼쪽 '수집'에서 best100/검색을 실행하세요.")
        return
    st.dataframe(df, width="stretch", hide_index=True,
                 column_config={"link": st.column_config.LinkColumn("link")})
    top = df.head(15).set_index("title")["sourcing_score"]
    st.bar_chart(top)


def tab_products(db: str):
    df = q("SELECT product_id,title,store_name,latest_price,original_price,discount_rate,"
           "rating_avg,review_total,channel,is_ad,sourcing_score,link FROM products", db)
    if df.empty:
        st.info("데이터 없음.")
        return
    c1, c2 = st.columns(2)
    min_score = c1.slider("min sourcing_score", 0.0, float(max(1.0, df["sourcing_score"].max())), 0.0)
    chans = c2.multiselect("channel", sorted(df["channel"].dropna().unique().tolist()))
    f = df[df["sourcing_score"] >= min_score]
    if chans:
        f = f[f["channel"].isin(chans)]
    st.dataframe(f, width="stretch", hide_index=True,
                 column_config={"link": st.column_config.LinkColumn("link")})
    c3, c4 = st.columns(2)
    with c3:
        st.caption("소싱점수 분포")
        st.bar_chart(f["sourcing_score"].value_counts().sort_index())
    with c4:
        st.caption("가격 vs 평점 (크기=리뷰수)")
        sc = f.dropna(subset=["rating_avg", "latest_price"])
        if not sc.empty:
            st.scatter_chart(sc, x="rating_avg", y="latest_price", size="review_total", color="channel")


def tab_trends(db: str):
    prods = q("SELECT DISTINCT s.product_id, p.title FROM product_snapshots s "
              "LEFT JOIN products p ON p.product_id=s.product_id", db)
    if prods.empty:
        st.info("스냅샷이 아직 없습니다 (product 수집 후 refresh 하면 시계열이 쌓입니다).")
        return
    labels = {f"{r.product_id} · {(r.title or '')[:40]}": r.product_id for r in prods.itertuples()}
    pick = st.selectbox("상품", list(labels))
    pid = labels[pick]
    snap = q("SELECT crawled_at,price,review_total,rating_avg FROM product_snapshots "
             "WHERE product_id=? ORDER BY crawled_at", db, (pid,))
    if not snap.empty:
        snap = snap.set_index("crawled_at")
        c1, c2 = st.columns(2)
        c1.caption("가격 추이")
        c1.line_chart(snap[["price"]])
        c2.caption("리뷰수 추이")
        c2.line_chart(snap[["review_total"]])
    rk = q("SELECT captured_at,board,rank FROM rank_snapshots WHERE product_id=? "
           "ORDER BY captured_at", db, (pid,))
    if not rk.empty:
        st.caption("best100 랭크 변동 (1=상위)")
        st.line_chart(rk.pivot_table(index="captured_at", columns="board", values="rank"))


def tab_discovery(db: str):
    st.subheader("best100 랭킹")
    rs = q("SELECT board,category,captured_at,rank,product_id,title,price,channel,in_products "
           "FROM rank_snapshots ORDER BY captured_at DESC, rank LIMIT 300", db)
    if not rs.empty:
        latest = rs["captured_at"].max()
        cur = rs[rs["captured_at"] == latest]
        c1, c2 = st.columns([3, 1])
        c1.dataframe(cur, width="stretch", hide_index=True)
        c2.caption("DB 보유 vs 신규")
        c2.bar_chart(cur["in_products"].map({1: "DB보유", 0: "신규"}).value_counts())
    st.subheader("검색결과 — 광고 vs 일반")
    ss = q("SELECT query, SUM(is_ad) ads, SUM(1-is_ad) organic FROM search_snapshots GROUP BY query", db)
    if not ss.empty:
        st.bar_chart(ss.set_index("query")[["organic", "ads"]])
    else:
        st.caption("검색 수집 기록 없음.")


def tab_sellers(db: str):
    df = q("SELECT store_name, COUNT(*) products, ROUND(AVG(sourcing_score),1) avg_score, "
           "SUM(review_total) total_reviews FROM products WHERE store_name IS NOT NULL "
           "GROUP BY store_name ORDER BY products DESC", db)
    if df.empty:
        st.info("판매자 데이터 없음.")
        return
    st.dataframe(df, width="stretch", hide_index=True)
    st.caption("판매자별 수집 상품 수 (Top 20)")
    st.bar_chart(df.head(20).set_index("store_name")["products"])


def main():
    st.set_page_config(page_title="Coupang Sourcing", page_icon="🛒", layout="wide")
    st.title("🛒 Coupang Sourcing Dashboard")
    db = str(_db())
    collect_sidebar()
    t1, t2, t3, t4, t5 = st.tabs(["📊 Overview", "🏆 Products", "📈 Trends", "🔎 Discovery", "🏬 Sellers"])
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
