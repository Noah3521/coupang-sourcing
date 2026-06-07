"""File exporters: per-product JSON record + reviews CSV.

CSV writer ported from tools/coupang_shop_cli.py:write_review_csv (718).
"""
from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

from . import storage
from .models import ProductRecord
from .normalize import public_product_row, public_review_row

REVIEW_FIELDS = [
    "sourceProductId", "sourceVendorItemId", "sourceTitle", "sourceLink",
    "reviewId", "productId", "itemId", "vendorItemId", "rating", "title", "content",
    "itemName", "itemImagePath", "displayName", "displayWriter", "vendorName",
    "reviewAt", "createdAt", "helpfulCount", "helpfulTrueCount", "helpfulFalseCount",
    "commentCount", "attachmentCount", "attachmentImages", "videoCount", "videoUrls",
]


def write_review_csv(path: Path, record: ProductRecord) -> None:
    source = public_product_row(record.product)
    rows = [public_review_row(r, source) for r in record.reviews.get("reviews", [])]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_record_json(path: Path, record: ProductRecord) -> None:
    path.write_text(json.dumps(dataclasses.asdict(record), ensure_ascii=False, indent=2), encoding="utf-8")


def export_product(out_dir: Path, record: ProductRecord) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pid = record.product_id
    json_path = out_dir / f"product_{pid}_full.json"
    csv_path = out_dir / f"product_{pid}_reviews.csv"
    write_record_json(json_path, record)
    write_review_csv(csv_path, record)
    return {"record": str(json_path.resolve()), "reviewsCsv": str(csv_path.resolve())}


def rows_to_csv(path: Path, rows: list[dict]) -> None:
    """Write list-of-dict rows to CSV, using the union of keys as header."""
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def rows_to_json(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_filename(table: str, fmt: str) -> str:
    return f"coupang_{table}.{fmt}"


def export_table(
    db_path: Path, table: str, fmt: str, out: Path | None,
    *, store: str | None = None, min_score: float | None = None,
) -> tuple[Path, int]:
    """Export one DB table (or the products view) to CSV/JSON. Returns (path, row_count)."""
    conn = storage.connect(db_path)
    try:
        if table == "products":
            rows = storage.fetch_products(conn, store=store, min_score=min_score)
        else:
            rows = storage.fetch_table(conn, table)
    finally:
        conn.close()
    path = out or Path(_default_filename(table, fmt))
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        rows_to_json(path, rows)
    else:
        rows_to_csv(path, rows)
    return path.resolve(), len(rows)
