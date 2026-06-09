"""Shared sourcing operations used by both the MCP server and the Streamlit dashboard.

Plain functions (no MCP / no Streamlit deps) that orchestrate the collectors + storage and
return JSON-friendly dicts. The same SQLite DB accumulates data across calls.

Env:
  COUPANG_SOURCING_DB        SQLite path (default ~/.coupang-sourcing/sourcing.db)
  COUPANG_MAX_REVIEW_PAGES   review pages per product on collection (default 3; 0 = all)
  COUPANG_CHROME / COUPANG_NODE   browser/node paths for cookie minting (gated routes)
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import storage
from .collectors import batch as batch_mod
from .collectors import product as product_mod
from .collectors import ranking, seller
from .collectors import search as search_mod
from .collectors import store as store_mod
from .config import Config
from .http_client import CoupangClient
from .models import ProductRecord
from .urls import parse_product, parse_store


def db_path() -> Path:
    return Path(os.environ.get(
        "COUPANG_SOURCING_DB", str(Path.home() / ".coupang-sourcing" / "sourcing.db")
    ))


def _config() -> Config:
    cfg = Config.load()
    return cfg.override(
        db_path=str(db_path()),
        max_review_pages=int(os.environ.get("COUPANG_MAX_REVIEW_PAGES", "3")),
    )


def _ready() -> tuple[Config, CoupangClient]:
    cfg = _config()
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    storage.init_db(cfg.db_path)
    return cfg, CoupangClient(cfg)


def _filter(items: list[dict], min_rating: float, max_price: int, min_reviews: int) -> list[dict]:
    out = []
    for it in items:
        if min_rating and (it.get("ratingAverage") or 0) < min_rating:
            continue
        if max_price and it.get("price") and it["price"] > max_price:
            continue
        if min_reviews and (it.get("reviewCount") or 0) < min_reviews:
            continue
        out.append(it)
    return out


def _mark_in_db(cfg: Config, items: list[dict]) -> int:
    conn = storage.connect(cfg.db_path)
    known = storage.existing_product_ids(conn)
    conn.close()
    for it in items:
        it["inDb"] = str(it.get("productId")) in known
    return sum(1 for it in items if it["inDb"])


def _slim(it: dict) -> dict:
    out = {k: it.get(k) for k in
           ("rank", "productId", "itemId", "vendorItemId", "title", "price",
            "ratingAverage", "reviewCount", "link")}
    for opt in ("isAd", "channel", "store", "inDb"):
        if opt in it:
            out[opt] = it[opt]
    return out


def _record_summary(record: ProductRecord) -> dict:
    m = record.metrics
    return {
        "productId": record.product_id,
        "title": record.product.get("title"),
        "store": record.store.get("storeName"),
        "storeId": record.store.get("urlName"),
        "vendorId": record.store.get("vendorId"),
        "price": record.product.get("price"),
        "originalPrice": record.product.get("originalPrice"),
        "discountRate": record.product.get("discountRate"),
        "ratingAverage": m.get("ratingAverage"),
        "reviewTotal": m.get("ratingCount"),
        "reviewsCollected": len(record.reviews.get("reviews", [])),
        "channel": m.get("channel"),
        "negativeRate": m.get("negativeRate"),
        "estimatedSales": m.get("estimatedSales"),
        "sourcingScore": m.get("sourcingScore"),
        "link": record.product.get("link"),
    }


def _collect_resolved(client: CoupangClient, cfg: Config, items: list[dict]) -> int:
    """Resolve sellers then full-collect marketplace items (annotates items with `store`)."""
    seller.resolve_sellers(client, items)
    pairs = [(str(it["productId"]), it["store"]) for it in items if it.get("store")]
    if not pairs:
        return 0
    records = batch_mod.collect_batch(
        client, pairs, cfg, on_record=lambda rec: storage.save_record(cfg.db_path, rec)
    )
    return len(records)


# --- operations ---------------------------------------------------------------

def find_products(
    query: str = "",
    board: str = "bestseller",
    category: str = "all",
    top: int = 20,
    min_rating: float = 0,
    max_price: int = 0,
    min_reviews: int = 0,
    collect: bool = False,
) -> dict:
    """Find products and save them to the sourcing DB.

    With `query`: searches /np/search (organic + ads, each flagged `isAd`) — gated, may mint
    Akamai cookies via a brief Chrome window on first use. Without `query`: best100 ranking
    (`board`=trending|bestseller, `category`='all' or a categoryId from list_categories) — no
    browser needed. Filters: `min_rating`, `max_price`, `min_reviews`. Set `collect=true` to
    also resolve each result's marketplace seller and fully collect their products.
    """
    try:
        cfg, client = _ready()
        if query:
            res = search_mod.collect_search(client, query, top=top)
        else:
            if board not in ranking.BOARDS:
                return {"error": f"board must be one of {ranking.BOARDS}"}
            res = ranking.collect_ranking(client, board, category, top=top)
        items = _filter(res["items"], min_rating, max_price, min_reviews)
        known = _mark_in_db(cfg, items)
        collected = _collect_resolved(client, cfg, items) if collect else 0
        if query:
            storage.save_search(cfg.db_path, query, items)
        else:
            storage.save_ranking(cfg.db_path, board, str(category), items)
        return {
            "source": "search:" + query if query else f"best100:{board}/{category}",
            "count": len(items), "inDb": known, "new": len(items) - known,
            "collected": collected, "db": str(cfg.db_path),
            "products": [_slim(it) for it in items],
        }
    except (RuntimeError, ValueError, LookupError) as exc:
        return {"error": str(exc)}


def product_info(url: str, store_url: str = "") -> dict:
    """Collect full info for a single product link and save it to the DB.

    Returns price, discount, rating, channel, review/sourcing metrics. If `store_url` is given
    it is used directly (no browser). Otherwise the seller is resolved from the link's
    vendorItemId via the gated vendoritems endpoint (may briefly open Chrome). A bare
    /vp/products/{id} link without vendorItemId can't be resolved — pass `store_url` then.
    """
    try:
        cfg, client = _ready()
        ids = parse_product(url)
        store = parse_store(store_url) if store_url else None
        if not store:
            vid = ids.get("vendorItemId")
            if not vid:
                return {"error": "link has no vendorItemId — pass store_url (shop.coupang.com/...)."}
            resolved = seller.resolve_seller(client, str(ids["productId"]), str(vid))
            if not resolved:
                return {"error": "no marketplace seller (coupang-direct?) — pass store_url."}
            store = resolved["storeUrlName"]
        store_info = store_mod.resolve_store(client, store)
        conn = storage.connect(cfg.db_path)
        prior = storage.get_prior_snapshot(conn, str(ids["productId"]))
        conn.close()
        record = product_mod.collect_product(client, ids, store_info, cfg, prior_snapshot=prior)
        storage.save_record(cfg.db_path, record)
        return _record_summary(record)
    except (RuntimeError, ValueError, LookupError) as exc:
        return {"error": str(exc)}


def collect_seller(store: str, limit: int = 50) -> dict:
    """Collect a seller's catalog into the DB. `store` = shop URL or store id (e.g. A00333576).

    Scans the store's listing once and collects up to `limit` products (price + reviews +
    metrics). Returns how many were in the catalog vs collected.
    """
    try:
        cfg, client = _ready()
        s = parse_store(store)
        store_info = store_mod.resolve_store(client, s)
        index = store_mod.build_listing_index(client, store_info, cfg)
        collected = 0
        for pid, variants in list(index.items())[: max(1, limit)]:
            ids = {"productId": pid, "itemId": None, "vendorItemId": None,
                   "sourceType": None, "link": None}
            record = product_mod.collect_product(client, ids, store_info, cfg, variants=variants)
            storage.save_record(cfg.db_path, record)
            collected += 1
        return {"store": s, "storeName": store_info.get("storeName"),
                "catalogSize": len(index), "collected": collected, "db": str(cfg.db_path)}
    except (RuntimeError, ValueError, LookupError) as exc:
        return {"error": str(exc)}


def query_db(table: str = "products", min_score: float = 0, store: str = "", limit: int = 50) -> dict:
    """Query accumulated sourcing data.

    `table`: products | rank_snapshots | search_snapshots | reviews | product_variants |
    product_snapshots | stores | vendor_map. For `products`, `min_score`/`store` filter and
    rows are sorted by sourcing score.
    """
    try:
        db = db_path()
        if not db.exists():
            return {"error": "no DB yet — run find_products / product_info first.", "db": str(db)}
        conn = storage.connect(db)
        try:
            if table == "products":
                rows = storage.fetch_products(conn, store=store or None, min_score=min_score or None)
            else:
                rows = storage.fetch_table(conn, table)
        finally:
            conn.close()
        return {"table": table, "count": len(rows), "rows": rows[: max(1, limit)]}
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc)}


def list_categories(board: str = "bestseller", category: str = "all") -> dict:
    """List best100 categoryIds available on a board page (for drilling into find_products)."""
    try:
        _, client = _ready()
        return {"board": board, "category": category,
                "categories": ranking.collect_categories(client, board, category)}
    except (RuntimeError, ValueError) as exc:
        return {"error": str(exc)}


def refresh_cookies() -> dict:
    """Force-refresh the Akamai cookies used for gated routes (opens a brief Chrome window)."""
    try:
        _, client = _ready()
        client.remint()
        return {"ok": True, "note": "Akamai cookies re-minted and cached."}
    except RuntimeError as exc:
        return {"error": str(exc)}


# ── 1688 origin sourcing (integration/aliprice-1688, Node bridge) ──────────────

def _aliprice_pipeline() -> Path:
    return Path(__file__).resolve().parents[2] / "integration" / "aliprice-1688" / "sourcing-pipeline.js"


def source_1688(product_id: str = "", limit: int = 0, top: int = 10,
                headless_top: int = 3, resource: bool = False) -> dict:
    """Find 1688 origin offers for Coupang product(s) via AliPrice image search.

    For each Coupang product, image-searches 1688 and stores the top-N offers with full
    metadata (price/sales history, seller metrics, SKU, specs, price ladder, gallery) into
    the same DB as children of the product (`s1688_*` tables; read them with `query_1688`).
    Idempotent: products already sourced ('ok') are skipped unless `resource=True`.

    Args:
      product_id: source one product (else all un-sourced, sourcing_score order).
      limit: cap number of products processed.
      top: 1688 offers stored per product (default 10).
      headless_top: how many top offers get full headless scrape (SKU/specs/ladder/gallery).
      resource: re-source products already done.

    Requires Node + integration deps (`bash integration/aliprice-1688/install.sh`) and valid
    AliPrice/1688 session cookies (`node decrypt-cookies.js` in that dir). Set COUPANG_NODE to
    override the node binary. Long-running (headless renders) — minutes for many products.
    """
    from . import browser
    script = _aliprice_pipeline()
    if not script.exists():
        return {"error": f"1688 sourcing not installed: {script} missing"}
    try:
        node = browser.find_node()
    except RuntimeError as exc:
        return {"error": str(exc)}
    args = [node, str(script), "--db", str(db_path()), "--top", str(int(top)),
            "--headless-top", str(int(headless_top))]
    if product_id:
        args += ["--product-id", str(product_id)]
    if limit:
        args += ["--limit", str(int(limit))]
    if resource:
        args += ["--resource"]
    try:
        proc = subprocess.run(args, cwd=str(script.parent), capture_output=True,
                              text=True, timeout=3600)
    except FileNotFoundError:
        return {"error": "node not executable; set COUPANG_NODE=/path/to/node"}
    except subprocess.TimeoutExpired:
        return {"error": "1688 sourcing timed out (>1h) — narrow with --limit/--product-id"}
    log_tail = "\n".join((proc.stderr or "").strip().splitlines()[-10:])
    if proc.returncode != 0:
        return {"error": "1688 sourcing failed (cookies/deps?)",
                "returncode": proc.returncode, "log": log_tail,
                "hint": "run integration/aliprice-1688: `bash install.sh` then `node decrypt-cookies.js`"}
    run = {}
    db = db_path()
    if db.exists():
        conn = storage.connect(db)
        try:
            row = conn.execute(
                "SELECT run_id,status,products_done,products_failed,offers_written "
                "FROM sourcing_runs ORDER BY started_at DESC LIMIT 1").fetchone()
            if row:
                run = dict(row)
        finally:
            conn.close()
    return {"ok": True, "run": run, "log": log_tail}


def query_1688(product_id: str = "", limit: int = 10) -> dict:
    """Read stored 1688 sourcing results (origin candidates).

    `product_id` given → that Coupang product's ranked 1688 offers (price/sales + seller).
    No `product_id` → Coupang products that have been sourced, with offer count and cheapest
    1688 price (¥). Populate with `source_1688` first.
    """
    db = db_path()
    if not db.exists():
        return {"error": "no DB yet — run source_1688 first."}
    conn = storage.connect(db)
    try:
        has = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='s1688_offers'").fetchone()
        if not has:
            return {"error": "no 1688 data yet — run source_1688 first."}
        n = max(1, int(limit))
        if product_id:
            rows = conn.execute(
                "SELECT o.rank, o.offer_id, o.title, o.price_cny, o.price_min_cny, o.price_max_cny, "
                "o.month_sold, o.total_sales, o.repurchase_rate, o.category_name, o.detail_url, "
                "sh.shop_name, sh.tpyear, sh.superfactory "
                "FROM s1688_offers o LEFT JOIN s1688_shop sh USING(match_id) "
                "WHERE o.coupang_product_id=? ORDER BY o.rank LIMIT ?",
                (str(product_id), n)).fetchall()
        else:
            rows = conn.execute(
                "SELECT o.coupang_product_id, p.title AS coupang_title, p.latest_price AS coupang_price, "
                "COUNT(*) AS offers, MIN(o.price_cny) AS min_cny_1688 "
                "FROM s1688_offers o LEFT JOIN products p ON p.product_id=o.coupang_product_id "
                "GROUP BY o.coupang_product_id ORDER BY offers DESC LIMIT ?", (n,)).fetchall()
        return {"product_id": product_id or None, "count": len(rows), "rows": [dict(r) for r in rows]}
    finally:
        conn.close()
