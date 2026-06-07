"""Product review collection via the stable www.coupang.com/next-api/review endpoint.

Ported from tools/coupang_product_full.py:collect_reviews (97).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import BASE_WWW, Config
from ..http_client import CoupangClient, review_headers
from ..normalize import parse_review_payload
from ..urls import review_url

Progress = Callable[[str], None]


def collect_reviews(
    client: CoupangClient,
    product_id: str,
    referer: str | None,
    config: Config,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Fetch rating summary + all reviews for one productId."""
    client.warm(BASE_WWW)
    size = max(1, min(config.review_size, 30))
    referer = referer or f"{BASE_WWW}/vp/products/{product_id}"

    rating_summary: dict[str, Any] = {}
    total_count = total_page = 0
    reviews: list[dict[str, Any]] = []
    page = 1
    while True:
        if progress:
            progress(f"review page {page} for productId={product_id}")
        payload = client.request_json(
            "GET",
            review_url(product_id, page=page, size=size, sort_by=config.review_sort),
            headers=review_headers(referer),
        )
        parsed = parse_review_payload(payload)
        if not parsed["ok"]:
            raise RuntimeError(f"review API error {parsed['rCode']}: {parsed['rMessage']}")
        if page == 1:
            rating_summary = parsed["ratingSummary"]
            total_count = parsed["totalCount"]
            total_page = parsed["totalPage"]
        reviews.extend(parsed["reviews"])
        limit = total_page if config.max_review_pages <= 0 else min(total_page, config.max_review_pages)
        if page >= (limit or page) or not parsed["reviews"]:
            break
        page += 1

    return {
        "ratingSummary": rating_summary,
        "totalCount": total_count,
        "totalPage": total_page,
        "pagesFetched": page,
        "reviews": reviews,
    }
