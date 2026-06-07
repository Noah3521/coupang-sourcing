"""SQLite persistence: schema, upsert (current snapshot), append (time series), queries.

Expands tools/coupang_product_full.py:upsert_sqlite (179) with a normalized
variants table, a stores table, and a schema_version for future migrations.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ProductRecord

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER);
CREATE TABLE IF NOT EXISTS stores(
  store_id TEXT PRIMARY KEY, vendor_id TEXT, url_name TEXT,
  display_name TEXT, last_listing_crawled TEXT);
CREATE TABLE IF NOT EXISTS products(
  product_id TEXT PRIMARY KEY, representative_vendor_item_id TEXT, item_id TEXT,
  title TEXT, store_id TEXT, store_name TEXT, vendor_id TEXT,
  latest_price INTEGER, original_price INTEGER, discount_rate INTEGER,
  rating_avg REAL, review_total INTEGER, channel TEXT, is_ad INTEGER,
  sourcing_score REAL, metrics_json TEXT, link TEXT,
  first_seen TEXT, last_crawled TEXT);
CREATE TABLE IF NOT EXISTS product_variants(
  vendor_item_id TEXT PRIMARY KEY, product_id TEXT, title TEXT, price INTEGER,
  sold_out INTEGER, delivery_text TEXT, image TEXT);
CREATE TABLE IF NOT EXISTS product_snapshots(
  product_id TEXT, crawled_at TEXT, price INTEGER, review_total INTEGER, rating_avg REAL);
CREATE TABLE IF NOT EXISTS reviews(
  review_id TEXT PRIMARY KEY, product_id TEXT, rating INTEGER, title TEXT,
  content TEXT, option_name TEXT, review_at INTEGER, helpful_count INTEGER, has_media INTEGER);
CREATE TABLE IF NOT EXISTS vendor_map(vendor_name TEXT PRIMARY KEY, vendor_id TEXT, store_id TEXT);
CREATE INDEX IF NOT EXISTS idx_snapshots_product ON product_snapshots(product_id);
CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            conn.execute("INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,))
        conn.commit()
    finally:
        conn.close()


def get_prior_snapshot(conn: sqlite3.Connection, product_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT crawled_at, review_total, price, rating_avg FROM product_snapshots "
        "WHERE product_id=? ORDER BY crawled_at DESC LIMIT 1",
        (str(product_id),),
    ).fetchone()
    return dict(row) if row else None


def upsert_record(conn: sqlite3.Connection, record: ProductRecord) -> None:
    now = datetime.now(timezone.utc).isoformat()
    p = record.product
    pid = record.product_id
    store = record.store
    metrics = record.metrics

    conn.execute(
        "INSERT OR REPLACE INTO stores VALUES(?,?,?,?,?)",
        (str(store["storeId"]), store["vendorId"], store.get("urlName"), store.get("storeName"), now),
    )

    first_seen_row = conn.execute("SELECT first_seen FROM products WHERE product_id=?", (pid,)).fetchone()
    first_seen = first_seen_row[0] if first_seen_row else now
    conn.execute(
        "INSERT OR REPLACE INTO products VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            pid, str(p.get("vendorItemId")), str(p.get("itemId")), p.get("title"),
            str(store["storeId"]), store.get("storeName"), store.get("vendorId"),
            p.get("price"), p.get("originalPrice"), p.get("discountRate"),
            metrics.get("ratingAverage"), metrics.get("ratingCount"),
            metrics.get("channel"), 1 if record.is_ad else 0,
            metrics.get("sourcingScore"), json.dumps(metrics, ensure_ascii=False),
            p.get("link"), first_seen, now,
        ),
    )

    for v in record.variants:
        conn.execute(
            "INSERT OR REPLACE INTO product_variants VALUES(?,?,?,?,?,?,?)",
            (str(v.get("vendorItemId")), pid, v.get("title"), v.get("price"),
             1 if v.get("soldOut") else 0, v.get("deliveryText"), v.get("image")),
        )

    conn.execute(
        "INSERT INTO product_snapshots VALUES(?,?,?,?,?)",
        (pid, now, p.get("price"), metrics.get("ratingCount"), metrics.get("ratingAverage")),
    )

    for r in record.reviews.get("reviews", []):
        conn.execute(
            "INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",
            (str(r.get("reviewId")), pid, r.get("rating"), r.get("title"), r.get("content"),
             r.get("itemName"), r.get("reviewAt"), r.get("helpfulCount") or 0,
             1 if (r.get("attachments") or r.get("videoAttachments")) else 0),
        )

    if store.get("vendorId") and store.get("storeName"):
        conn.execute(
            "INSERT OR REPLACE INTO vendor_map VALUES(?,?,?)",
            (store["storeName"], store["vendorId"], str(store["storeId"])),
        )


def save_record(db_path: Path, record: ProductRecord) -> None:
    conn = connect(db_path)
    try:
        upsert_record(conn, record)
        conn.commit()
    finally:
        conn.close()


def list_products_for_refresh(
    conn: sqlite3.Connection, *, store: str | None = None, older_than_days: int | None = None
) -> list[dict[str, Any]]:
    """Return rows {product_id, item_id, vendor_item_id, url_name} to re-crawl."""
    query = (
        "SELECT p.product_id, p.item_id, p.representative_vendor_item_id, s.url_name, p.last_crawled "
        "FROM products p JOIN stores s ON p.store_id = s.store_id WHERE 1=1"
    )
    params: list[Any] = []
    if store:
        query += " AND s.url_name = ?"
        params.append(store)
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_days * 86400
        query += " AND (p.last_crawled IS NULL OR strftime('%s', p.last_crawled) < ?)"
        params.append(str(int(cutoff)))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def table_counts(db_path: Path) -> dict[str, int]:
    conn = connect(db_path)
    try:
        tables = ["stores", "products", "product_variants", "product_snapshots", "reviews", "vendor_map"]
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()


# Tables that `export` is allowed to dump (whitelist guards the f-string query).
EXPORTABLE_TABLES = ("products", "reviews", "product_snapshots", "product_variants", "stores", "vendor_map")


def fetch_products(
    conn: sqlite3.Connection, *, store: str | None = None, min_score: float | None = None
) -> list[dict[str, Any]]:
    """Products joined with store url-name, newest crawl first, optionally filtered."""
    query = (
        "SELECT p.product_id, p.title, p.store_name, s.url_name AS store, p.vendor_id, "
        "p.latest_price, p.original_price, p.discount_rate, p.rating_avg, p.review_total, "
        "p.channel, p.is_ad, p.sourcing_score, p.link, p.first_seen, p.last_crawled "
        "FROM products p LEFT JOIN stores s ON p.store_id = s.store_id WHERE 1=1"
    )
    params: list[Any] = []
    if store:
        query += " AND s.url_name = ?"
        params.append(store)
    if min_score is not None:
        query += " AND p.sourcing_score >= ?"
        params.append(min_score)
    query += " ORDER BY p.sourcing_score DESC, p.review_total DESC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def fetch_table(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Dump a whitelisted table as a list of dict rows."""
    if table not in EXPORTABLE_TABLES:
        raise ValueError(f"table not exportable: {table}")
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
