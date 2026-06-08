"""Search-results (SRP) collection over /np/search.

Unlike best100, `/np/search` is hard-gated by Akamai, so it needs browser-minted cookies
(see browser.py / CoupangClient.gated_*). The modern SRP is a server-rendered React build
(`ProductUnit_*` CSS-module classes + Tailwind `fw-*` utilities), so we anchor on the
stable bits: the `/vp/products/...` href (ids + sourceType), the product-name class, the
star block's `aria-label`, and the `광고` / `sourceType=srp_product_ads` ad markers.

Ad vs organic is explicit: the product href carries `sourceType=search` (organic) or
`sourceType=srp_product_ads` (ad). Ads can duplicate organic items; every card keeps its
page position as `rank` plus an `isAd` flag so the two are cleanly separable downstream.
"""
from __future__ import annotations

import html as _html
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from ..config import BASE_WWW
from ..http_client import CoupangClient, html_headers
from ..normalize import parse_price
from ..urls import absolute_url

Progress = Callable[[str], None]

_CARD = re.compile(r'<li class="ProductUnit_productUnit__[^"]*"\s+data-id="(\d+)"')
_HREF = re.compile(r'href="(/vp/products/\d+[^"]*)"')
_PID = re.compile(r'/vp/products/(\d+)')
_ITEMID = re.compile(r'itemId=(\d+)')
_VITEMID = re.compile(r'vendorItemId=(\d+)')
_SOURCETYPE = re.compile(r'sourceType=([a-zA-Z_]+)')
_NAME = re.compile(r'class="ProductUnit_productName[^"]*"[^>]*>([^<]+)')
_RATING = re.compile(r'aria-label="([\d.]+)"')
_WON = re.compile(r'([\d,]+)\s*원')
_DISCOUNT = re.compile(r'(\d+)<!-- -->%')
_PAREN_NUM = re.compile(r'\(\s*([\d,]+)\s*\)')
_IMG = re.compile(r'(?<![-\w])src="(//[^"]+|https://[^"]+)"')


def build_search_url(query: str, *, page: int = 1, list_size: int = 0) -> str:
    params: list[tuple[str, str]] = [("q", query), ("channel", "user")]
    if page and page > 1:
        params.append(("page", str(page)))
    if list_size and list_size > 0:
        params.append(("listSize", str(list_size)))
    return f"{BASE_WWW}/np/search?{urlencode(params)}"


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None


def parse_search(page_html: str) -> list[dict[str, Any]]:
    """Parse SRP HTML into ordered result rows (organic + ads, each flagged). Pure."""
    matches = list(_CARD.finditer(page_html))
    if not matches:
        return []
    bounds = [m.start() for m in matches[1:]] + [len(page_html)]
    items: list[dict[str, Any]] = []
    for rank, (match, end) in enumerate(zip(matches, bounds, strict=True), start=1):
        card = page_html[match.start():end]
        href = _html.unescape(_first(_HREF, card) or "")
        source_type = _first(_SOURCETYPE, href)
        is_ad = source_type == "srp_product_ads" or bool(re.search(r">\s*광고\s*<", card))
        head = card.split("ProductRating", 1)[0]          # prices live above the rating block
        prices = [parse_price(p) for p in _WON.findall(head)]
        tail = card[card.find("ProductRating"):] if "ProductRating" in card else ""
        review = _first(_PAREN_NUM, re.sub(r"<[^>]+>", "", tail))
        rating = _first(_RATING, card)
        name = _first(_NAME, card)
        items.append(
            {
                "rank": rank,
                "productId": _first(_PID, href),
                "itemId": _first(_ITEMID, href) or _first(_ITEMID, card),
                "vendorItemId": _first(_VITEMID, href) or match.group(1),
                "sourceType": source_type,
                "isAd": is_ad,
                "title": _html.unescape(name.strip()) if name else "",
                "price": prices[-1] if prices else None,
                "originalPrice": prices[0] if len(prices) > 1 else None,
                "discountRate": int(_first(_DISCOUNT, head) or 0),
                "ratingAverage": float(rating) if rating else None,
                "reviewCount": parse_price(review) or 0,
                "image": absolute_url(_first(_IMG, card)),
                "link": absolute_url(href),
            }
        )
    return items


def collect_search(
    client: CoupangClient,
    query: str,
    *,
    page: int = 1,
    top: int = 0,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Fetch + parse one search-results page (mints/loads Akamai cookies as needed)."""
    url = build_search_url(query, page=page)
    if progress:
        progress(f"fetching search results for {query!r}")
    page_html = client.gated_text("GET", url, headers=html_headers(f"{BASE_WWW}/"), progress=progress)
    items = parse_search(page_html)
    if not items:
        raise RuntimeError(f"no search results parsed from {url}")
    if top and top > 0:
        items = items[:top]
    organic = sum(1 for it in items if not it["isAd"])
    if progress:
        progress(f"parsed {len(items)} results ({organic} organic, {len(items) - organic} ads)")
    return {
        "query": query,
        "page": page,
        "url": url,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
