"""URL parsing and endpoint builders (pure, no network).

Ported from the validated prototype:
  parse_store      <- tools/coupang_shop_cli.py:28
  absolute_url     <- tools/coupang_shop_cli.py:71
  review_url       <- tools/coupang_shop_cli.py:184
  parse_product    <- tools/coupang_product_full.py:27
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse

from .config import BASE_WWW

STORE_ID_RE = re.compile(r"^[A-Z]\d{5,}$")


def parse_store(value: str) -> str:
    """Extract a store url-name (e.g. A00333576) from a shop URL or raw id."""
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        for key in ("vendorId", "lptag", "urlName"):
            for candidate in query.get(key, []):
                if STORE_ID_RE.match(candidate):
                    return candidate
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            if path_parts[0] == "vid" and len(path_parts) > 1:
                return path_parts[1]
            if STORE_ID_RE.match(path_parts[0]):
                return path_parts[0]
        for values in query.values():
            for candidate in values:
                if STORE_ID_RE.match(candidate):
                    return candidate
        raise ValueError(f"Could not parse store id from URL: {value}")
    return value.strip("/")


def parse_product(value: str) -> dict[str, str | None]:
    """Extract productId/itemId/vendorItemId/sourceType from a product URL or raw id."""
    value = value.strip()
    if value.startswith("http"):
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        match = re.search(r"/products/(\d+)", parsed.path)
        if not match:
            raise ValueError(f"Could not find productId in URL: {value}")
        return {
            "productId": match.group(1),
            "itemId": (query.get("itemId") or [None])[0],
            "vendorItemId": (query.get("vendorItemId") or [None])[0],
            "sourceType": (query.get("sourceType") or [None])[0],
            "link": value,
        }
    return {"productId": value, "itemId": None, "vendorItemId": None, "sourceType": None, "link": None}


def absolute_url(value: str | None, base: str = "https:") -> str:
    if not value:
        return ""
    if value.startswith("//"):
        return f"{base}{value}"
    if value.startswith("/"):
        return f"{BASE_WWW}{value}"
    return value


def review_url(product_id: int | str, *, page: int, size: int, sort_by: str = "ORDER_SCORE_ASC") -> str:
    params = [
        ("productId", str(product_id)),
        ("page", str(page)),
        ("size", str(size)),
        ("sortBy", sort_by),
        ("ratingSummary", "true"),
        ("ratings", ""),
        ("market", ""),
    ]
    return f"{BASE_WWW}/next-api/review?{urlencode(params)}"
