"""Store resolution + listing scan over the stable shop.coupang.com APIs.

Logic ported from tools/coupang_product_full.py:collect_metadata (45) and
tools/coupang_shop_cli.py:collect_store (361, listing-pagination portion).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import BASE_SHOP, Config
from ..http_client import CoupangClient, shop_headers
from ..normalize import is_overseas_like, normalize_product

Progress = Callable[[str], None]
AUTO_MAX_LISTING_PAGES = 500


def resolve_store(client: CoupangClient, store: str) -> dict[str, Any]:
    """Return {storeId, vendorId, storeName, storeUrl} via getStoreInfo."""
    store_url = f"{BASE_SHOP}/{store}"
    client.warm(store_url)
    headers = shop_headers(store_url)
    info = client.request_json(
        "GET", f"{BASE_SHOP}/api/v1/store/getStoreInfo",
        headers=headers, params={"urlName": store},
    )
    return {
        "storeId": info["id"],
        "vendorId": info["vendorId"],
        "storeName": (info.get("displayName") or {}).get("ko_KR") or store,
        "storeUrl": store_url,
        "urlName": store,
    }


def _listing_pages(client: CoupangClient, store_info: dict[str, Any], config: Config):
    """Yield (page_index, products) over the store listing until exhausted."""
    headers = shop_headers(store_info["storeUrl"])
    page, empty = 0, 0
    limit = AUTO_MAX_LISTING_PAGES if config.listing_max_pages <= 0 else config.listing_max_pages
    while page < limit:
        body: dict[str, Any] = {
            "storeId": store_info["storeId"],
            "vendorId": store_info["vendorId"],
            "enableAdultItemDisplay": True,
        }
        if page:
            body["nextPageKey"] = page
        data = client.request_json("POST", f"{BASE_SHOP}/api/v1/listing", headers=headers, json=body)
        products = (data.get("data") or {}).get("products") or []
        yield page, products
        empty = empty + 1 if not products else 0
        if empty >= 3:
            return
        page += 1


def find_product_variants(
    client: CoupangClient,
    store_info: dict[str, Any],
    target_product_id: str,
    config: Config,
    progress: Progress | None = None,
) -> list[dict[str, Any]]:
    """Scan listing pages, return normalized variants for one productId (early-stop)."""
    target = str(target_product_id)
    variants_raw: list[dict[str, Any]] = []
    scanned = 0
    for page, products in _listing_pages(client, store_info, config):
        scanned += len(products)
        page_hits = [p for p in products if str(p.get("productId")) == target]
        variants_raw.extend(page_hits)
        if progress:
            progress(f"listing page {page + 1}: scanned {scanned}, {len(variants_raw)} variants for {target}")
        # Once we have hits and a later page yields none, the variants block is done.
        if variants_raw and page > 0 and not page_hits:
            break
        if variants_raw and not products:
            break
    return _normalize(variants_raw, store_info)


def build_listing_index(
    client: CoupangClient,
    store_info: dict[str, Any],
    config: Config,
    progress: Progress | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Scan the whole store once; return {productId: [normalized variants]} for batch reuse."""
    index: dict[str, list[dict[str, Any]]] = {}
    scanned = 0
    for page, products in _listing_pages(client, store_info, config):
        scanned += len(products)
        for raw in products:
            index.setdefault(str(raw.get("productId")), []).append(raw)
        if progress:
            progress(f"listing page {page + 1}: scanned {scanned}, {len(index)} products indexed")
    return {pid: _normalize(rows, store_info) for pid, rows in index.items()}


def _normalize(raw_rows: list[dict[str, Any]], store_info: dict[str, Any]) -> list[dict[str, Any]]:
    out = [normalize_product(r, store_info["vendorId"], store_info["storeId"]) for r in raw_rows]
    for v in out:
        v["overseasLike"] = is_overseas_like(v)
    return out
