"""Resolve a ranked/searched productId to its seller (store) via the vendoritems JSON.

best100/search cards expose only product/item/vendorItem ids, not the seller. The
`www.coupang.com/vp/products/{pid}/vendoritems/{vid}` JSON (Akamai-gated → needs minted
cookies) carries `vendor.id` — the store url-name (e.g. "A01388313") — plus the vendor name
and shop link. `vendor.id` plugs straight into the existing store flow
(`parse_store`/`resolve_store` → `listing`) for full-catalog collection.

Resolution is ~once per *seller* (cache by store id); the heavy catalog pull then runs on
the cookie-free, bulk-safe `listing` API. Coupang-direct (로켓 직매입) items return no
marketplace vendor and resolve to None.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import BASE_WWW
from ..http_client import CoupangClient, review_headers

Progress = Callable[[str], None]


def vendoritems_url(product_id: str, vendor_item_id: str) -> str:
    return f"{BASE_WWW}/vp/products/{product_id}/vendoritems/{vendor_item_id}"


def parse_vendor(payload: dict[str, Any]) -> dict[str, str] | None:
    """Extract the seller from a vendoritems payload, or None for coupang-direct/unknown. Pure."""
    vendor = payload.get("vendor") or {}
    store = vendor.get("id")
    if not store:
        return None
    return {
        "storeUrlName": str(store),
        "vendorName": vendor.get("name") or "",
        "link": vendor.get("link") or "",
    }


def resolve_seller(
    client: CoupangClient, product_id: str, vendor_item_id: str, *, progress: Progress | None = None
) -> dict[str, str] | None:
    """Resolve one product to its seller store. Returns None for coupang-direct items."""
    url = vendoritems_url(product_id, vendor_item_id)
    payload = client.gated_json(
        "GET", url, headers=review_headers(f"{BASE_WWW}/vp/products/{product_id}"), progress=progress
    )
    return parse_vendor(payload)


def resolve_sellers(
    client: CoupangClient, items: list[dict[str, Any]], *, progress: Progress | None = None
) -> dict[str, dict[str, str]]:
    """Resolve a batch of ranking/search rows to sellers.

    Annotates each item in place with `store` (the seller store url-name, or None) and
    returns {storeUrlName: seller} for the unique marketplace sellers found — ready to feed
    into the existing (product, store) full-collection flow.
    """
    sellers: dict[str, dict[str, str]] = {}
    by_product: dict[str, str | None] = {}
    for it in items:
        pid, vit = it.get("productId"), it.get("vendorItemId")
        if not pid or not vit:
            it["store"] = None
            continue
        if pid in by_product:
            it["store"] = by_product[pid]
            continue
        try:
            seller = resolve_seller(client, str(pid), str(vit), progress=progress)
        except Exception as exc:  # noqa: BLE001 — one bad product shouldn't abort the batch
            if progress:
                progress(f"resolve failed for {pid}: {exc!r}"[:120])
            seller = None
        store = seller["storeUrlName"] if seller else None
        by_product[pid] = store
        it["store"] = store
        if seller:
            sellers.setdefault(store, seller)
            if progress:
                progress(f"resolved {pid} → {store} ({seller['vendorName']})")
    return sellers
