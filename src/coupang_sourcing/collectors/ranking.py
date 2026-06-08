"""best100 ranking collection (trending / bestseller) over the open /np/best100 pages.

Unlike `/np/search` (Akamai-gated), the `/np/best100/*` pages pass with TLS
impersonation alone — no browser, no Akamai sensor solve — and embed the full
page-1 ranking as server-rendered HTML. We parse the product cards with the stdlib
only (regex); no bs4 dependency is added.

Card shape (legacy SRP markup):
  <li class="search-product " id="{productId}" data-vendor-item-id="{vendorItemId}" ...>
    <a href="/vp/products/{productId}?itemId={itemId}&vendorItemId={vendorItemId}"
       data-log-click='{"viewType":"toprank_unit","productId":...}'>
      <div class="name">…</div> <strong class="price-value">39,490</strong>
      <img data-badge-id="ROCKET"> <em class="rating">5.0</em>
      <span class="rating-total-count">(23474)</span>

`data-log-click.viewType` separates `toprank_unit` (the real ranking) from
`bottom_widget` (recommendation strip) — only the former is kept.
"""
from __future__ import annotations

import html as _html
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..config import BASE_WWW
from ..http_client import CoupangClient, html_headers
from ..normalize import parse_price
from ..urls import BEST100_BOARDS, absolute_url, best100_url

Progress = Callable[[str], None]

BOARDS = BEST100_BOARDS

# data-badge-id -> channel (판매 유형). Priority order: most specific first.
_CHANNEL_PRIORITY = [
    ("ROCKET_FRESH", "rocket_fresh"),       # 로켓프레시
    ("ROCKET_MERCHANT", "rocket_merchant"),  # 로켓그로스 (판매자로켓)
    ("ROCKET", "rocket"),                    # 로켓배송
    ("TOMORROW", "tomorrow"),                # 내일도착
]

_CARD_START = re.compile(r'<li class="(search-product[^"]*)"\s+id="(\d+)"')
_LOG_CLICK = re.compile(r"data-log-click='(\{.*?\})'", re.S)
_HREF = re.compile(r'href="(/vp/products/\d+[^"]*)"')
_NAME = re.compile(r'<div class="name">(.*?)</div>', re.S)
_PRICE = re.compile(r'<strong class="price-value">([^<]+)</strong>')
_RATING = re.compile(r'<em class="rating"[^>]*>([\d.]+)</em>')
_RCOUNT = re.compile(r'<span class="rating-total-count">([^<]*)</span>')
_IMG = re.compile(r'(?<![-\w])src="([^"]+)"')
_BADGE = re.compile(r'data-badge-id="([^"]+)"')
_ITEMID = re.compile(r'itemId=(\d+)')
_VITEMID = re.compile(r'vendorItemId=(\d+)')
# category nav links present on every best100 page (top + current category's children)
_CAT_LINK = re.compile(r'href="/np/best100/(?:bestseller|trending)/(\d+)"[^>]*>([^<]{1,30})')


def _channel_from_badges(badges: set[str]) -> str:
    for badge, channel in _CHANNEL_PRIORITY:
        if badge in badges:
            return channel
    return "seller"  # no rocket-family badge → 판매자배송 (marketplace)


def _log_click(card: str) -> dict[str, Any]:
    m = _LOG_CLICK.search(card)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None


def parse_ranking(page_html: str) -> list[dict[str, Any]]:
    """Parse best100 HTML into ordered ranking rows (toprank_unit only). Pure, no network."""
    matches = list(_CARD_START.finditer(page_html))
    if not matches:
        return []
    bounds = [m.start() for m in matches[1:]] + [len(page_html)]
    items: list[dict[str, Any]] = []
    rank = 0
    for match, end in zip(matches, bounds, strict=True):
        card = page_html[match.start():end]
        log = _log_click(card)
        # Drop the bottom recommendation widget; keep the true ranking unit.
        if log.get("viewType") and log.get("viewType") != "toprank_unit":
            continue
        href = _html.unescape(_first(_HREF, card) or "")
        product_id = log.get("productId") or match.group(2)
        item_id = log.get("itemId") or _first(_ITEMID, href)
        vendor_item_id = log.get("vendorItemId") or _first(_VITEMID, href)
        badges = set(_BADGE.findall(card))
        name = _first(_NAME, card)
        rating = _first(_RATING, card)
        rank += 1
        items.append(
            {
                "rank": rank,
                "productId": str(product_id) if product_id else None,
                "itemId": str(item_id) if item_id else None,
                "vendorItemId": str(vendor_item_id) if vendor_item_id else None,
                "title": _html.unescape(name.strip()) if name else "",
                "price": parse_price(_first(_PRICE, card)),
                "ratingAverage": float(rating) if rating else None,
                "reviewCount": parse_price(_first(_RCOUNT, card)) or 0,
                "channel": _channel_from_badges(badges),
                "badges": sorted(badges),
                "soldOut": "soldout" in match.group(1),
                "image": absolute_url(_first(_IMG, card)),
                "link": absolute_url(href),
            }
        )
    return items


def discover_categories(page_html: str) -> list[dict[str, str]]:
    """Extract child/sibling category links {categoryId, name} from a best100 page. Pure."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for cid, name in _CAT_LINK.findall(page_html):
        name = name.strip()
        if not name or cid in seen:
            continue
        seen.add(cid)
        out.append({"categoryId": cid, "name": _html.unescape(name)})
    return out


def collect_ranking(
    client: CoupangClient,
    board: str,
    category: str = "all",
    *,
    top: int = 0,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Fetch + parse one best100 board/category page. `top>0` trims to the first N rows."""
    url = best100_url(board, category)
    client.warm(BASE_WWW)
    if progress:
        progress(f"fetching {url}")
    page_html = client.request_text(
        "GET", url, headers=html_headers(best100_url(board, "all"))
    )
    if "sec-if-cpt-container" in page_html or "behavioral-content" in page_html:
        raise RuntimeError(f"best100 page blocked by Akamai challenge: {url}")
    items = parse_ranking(page_html)
    if not items:
        raise RuntimeError(f"no ranking items parsed from {url}")
    if top and top > 0:
        items = items[:top]
    if progress:
        progress(f"parsed {len(items)} ranked items")
    return {
        "board": board,
        "category": str(category),
        "url": url,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "categories": discover_categories(page_html),
    }


def collect_categories(
    client: CoupangClient,
    board: str = "bestseller",
    category: str = "all",
    progress: Progress | None = None,
) -> list[dict[str, str]]:
    """Fetch a best100 page and return its available category links (for drill-down)."""
    url = best100_url(board, category)
    client.warm(BASE_WWW)
    if progress:
        progress(f"fetching categories from {url}")
    page_html = client.request_text("GET", url, headers=html_headers(best100_url(board, "all")))
    if "sec-if-cpt-container" in page_html or "behavioral-content" in page_html:
        raise RuntimeError(f"best100 page blocked by Akamai challenge: {url}")
    return discover_categories(page_html)
