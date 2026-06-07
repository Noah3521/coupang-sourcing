"""Batch collection: group inputs by store, scan each store's listing only once."""
from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path

from ..config import Config
from ..http_client import CoupangClient
from ..models import ProductRecord
from ..urls import parse_product, parse_store
from . import product as product_mod
from . import store as store_mod

Progress = Callable[[str], None]


def read_pairs(csv_path: Path) -> list[tuple[str, str]]:
    """Read (product, store) pairs from a CSV. Accepts headers product,store or 2 columns."""
    pairs: list[tuple[str, str]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        has_header = "product" in sample.lower().splitlines()[0] if sample else False
        if has_header:
            for row in csv.DictReader(handle):
                prod = (row.get("product") or row.get("product_url") or "").strip()
                store = (row.get("store") or row.get("store_url") or "").strip()
                if prod and store:
                    pairs.append((prod, store))
        else:
            for row in csv.reader(handle):
                if len(row) >= 2 and row[0].strip() and row[1].strip():
                    pairs.append((row[0].strip(), row[1].strip()))
    return pairs


def collect_batch(
    client: CoupangClient,
    pairs: list[tuple[str, str]],
    config: Config,
    *,
    fetch_reviews: bool = True,
    progress: Progress | None = None,
    on_record: Callable[[ProductRecord], None] | None = None,
) -> list[ProductRecord]:
    """Group by store, scan each store listing once, then collect each product."""
    # group product inputs by resolved store id
    by_store: dict[str, list[dict[str, str | None]]] = {}
    for product_input, store_input in pairs:
        store = parse_store(store_input)
        ids = parse_product(product_input)
        by_store.setdefault(store, []).append(ids)

    records: list[ProductRecord] = []
    for store, product_id_list in by_store.items():
        if progress:
            progress(f"store {store}: resolving + scanning listing once for {len(product_id_list)} products")
        store_info = store_mod.resolve_store(client, store)
        index = store_mod.build_listing_index(client, store_info, config, progress)
        for ids in product_id_list:
            pid = str(ids["productId"])
            variants = index.get(pid)
            if not variants:
                if progress:
                    progress(f"  productId={pid} not found in store {store} — skipped")
                continue
            record = product_mod.collect_product(
                client, ids, store_info, config,
                fetch_reviews=fetch_reviews, variants=variants, progress=progress,
            )
            records.append(record)
            if on_record:
                on_record(record)
    return records
