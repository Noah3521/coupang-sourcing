"""Orchestrator: collect one product's full record from product+store input.

Mirrors tools/coupang_product_full.py:main (223) but as a reusable function.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..config import Config
from ..http_client import CoupangClient
from ..metrics import estimate_monthly_sales, sourcing_metrics, sourcing_score
from ..models import ProductRecord
from . import reviews as reviews_mod
from . import store as store_mod

Progress = Callable[[str], None]


def _representative(variants: list[dict[str, Any]]) -> dict[str, Any]:
    return max(variants, key=lambda v: v.get("reviewCount") or 0)


def assemble_record(
    *,
    variants: list[dict[str, Any]],
    store_info: dict[str, Any],
    review_data: dict[str, Any],
    config: Config,
    is_ad: bool,
    prior_snapshot: dict[str, Any] | None,
    elapsed: float,
) -> ProductRecord:
    rep = _representative(variants)
    metrics = sourcing_metrics(
        variants, review_data["reviews"], review_data["ratingSummary"],
        complaint_keywords=config.complaint_keywords,
    )
    metrics["estimatedSales"] = estimate_monthly_sales(
        metrics, sale_multiplier=config.sale_multiplier, prior_snapshot=prior_snapshot,
    )
    metrics["sourcingScore"] = sourcing_score(metrics, config.scoring_weights)
    return ProductRecord(
        product=rep,
        variants=variants,
        store=store_info,
        reviews=review_data,
        metrics=metrics,
        is_ad=is_ad,
        collected_at=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=round(elapsed, 2),
    )


def collect_product(
    client: CoupangClient,
    product_ids: dict[str, str | None],
    store_info: dict[str, Any],
    config: Config,
    *,
    fetch_reviews: bool = True,
    prior_snapshot: dict[str, Any] | None = None,
    variants: list[dict[str, Any]] | None = None,
    progress: Progress | None = None,
) -> ProductRecord:
    """Collect one product. `variants` may be supplied (batch reuse) to skip the listing scan."""
    started = time.monotonic()
    pid = str(product_ids["productId"])

    if variants is None:
        variants = store_mod.find_product_variants(client, store_info, pid, config, progress)
    if not variants:
        raise LookupError(f"productId={pid} not found in store {store_info.get('urlName')}")

    rep = _representative(variants)
    review_data: dict[str, Any] = {"ratingSummary": {}, "totalCount": 0, "totalPage": 0,
                                   "pagesFetched": 0, "reviews": []}
    if fetch_reviews:
        review_data = reviews_mod.collect_reviews(
            client, pid, rep.get("link") or product_ids.get("link"), config, progress,
        )

    source_type = product_ids.get("sourceType")
    is_ad = source_type not in (None, "", "brandstore")
    return assemble_record(
        variants=variants, store_info=store_info, review_data=review_data, config=config,
        is_ad=is_ad, prior_snapshot=prior_snapshot, elapsed=time.monotonic() - started,
    )
