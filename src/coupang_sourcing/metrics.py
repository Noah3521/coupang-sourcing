"""Sourcing metrics and composite score (pure functions).

Ported from tools/coupang_product_full.py:sourcing_metrics (128) and extended
with a configurable composite score.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


def _months_ago(ts_ms: Any, now: datetime) -> int | None:
    try:
        dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
        return (now.year - dt.year) * 12 + (now.month - dt.month)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _price_range(variants: list[dict[str, Any]]) -> dict[str, int] | None:
    prices = [v.get("price") for v in variants if v.get("price")]
    return {"min": min(prices), "max": max(prices)} if prices else None


def channel_of(variants: list[dict[str, Any]]) -> str:
    if any(v.get("rocket") for v in variants):
        return "rocket"
    if any(v.get("overseasLike") for v in variants):
        return "overseas"
    return "domestic"


def sourcing_metrics(
    variants: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    rating_summary: dict[str, Any],
    *,
    complaint_keywords: list[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    buckets: Counter[int] = Counter()
    for r in reviews:
        m = _months_ago(r.get("reviewAt"), now)
        if m is not None and m >= 0:
            buckets[m] += 1

    def velocity(n: int) -> int:
        return sum(count for month, count in buckets.items() if month < n)

    ratings = [r.get("rating") for r in reviews if isinstance(r.get("rating"), int)]
    negatives = [r for r in reviews if isinstance(r.get("rating"), int) and r["rating"] <= 3]
    complaint_hits: Counter[str] = Counter()
    for r in negatives:
        text = f"{r.get('title', '')} {r.get('content', '')}"
        for kw in complaint_keywords:
            if kw in text:
                complaint_hits[kw] += 1
    option_counts = Counter(r.get("itemName") for r in reviews if r.get("itemName"))
    with_media = sum(1 for r in reviews if (r.get("attachments") or r.get("videoAttachments")))

    return {
        "reviewVelocity": {
            "last1mo": velocity(1), "last3mo": velocity(3),
            "last6mo": velocity(6), "last12mo": velocity(12),
        },
        "ratingAverage": rating_summary.get("ratingAverage"),
        "ratingCount": rating_summary.get("ratingCount"),
        "ratingDistribution": rating_summary.get("ratingSummaries"),
        "negativeRate": round(len(negatives) / len(ratings), 3) if ratings else None,
        "complaintKeywords": complaint_hits.most_common(8),
        "bestOptions": option_counts.most_common(5),
        "photoReviewRate": round(with_media / len(reviews), 3) if reviews else 0.0,
        "priceRange": _price_range(variants),
        "discountRate": max((v.get("discountRate") or 0) for v in variants) if variants else 0,
        "channel": channel_of(variants),
    }


def estimate_monthly_sales(
    metrics: dict[str, Any],
    *,
    sale_multiplier: float,
    prior_snapshot: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Estimate monthly sales. Prefers snapshot delta; falls back to last-month velocity."""
    now = now or datetime.now(timezone.utc)
    current_total = metrics.get("ratingCount") or 0
    if prior_snapshot and prior_snapshot.get("review_total") is not None and prior_snapshot.get("crawled_at"):
        try:
            prev_dt = datetime.fromisoformat(prior_snapshot["crawled_at"])
            days = max((now - prev_dt).total_seconds() / 86400, 1e-6)
            delta = max(current_total - (prior_snapshot["review_total"] or 0), 0)
            per_month_reviews = delta / days * 30
            return {"method": "snapshot_delta", "estimatedReviewsPerMonth": round(per_month_reviews, 1),
                    "estimatedSalesPerMonth": round(per_month_reviews * sale_multiplier, 0)}
        except (ValueError, TypeError):
            pass
    rpm = (metrics.get("reviewVelocity") or {}).get("last1mo") or 0
    return {"method": "review_velocity_fallback", "estimatedReviewsPerMonth": rpm,
            "estimatedSalesPerMonth": round(rpm * sale_multiplier, 0)}


def sourcing_score(metrics: dict[str, Any], weights: dict[str, float]) -> float:
    """Composite 0-100ish score: weighted demand + quality - risk. Transparent & tunable."""
    vel = (metrics.get("reviewVelocity") or {}).get("last3mo") or 0
    demand = min(vel / 50.0, 1.0)                          # 50 reviews/3mo -> full demand
    rating = metrics.get("ratingAverage") or 0
    quality = max((rating - 3.0) / 2.0, 0.0)               # maps 3.0..5.0 -> 0..1
    risk = metrics.get("negativeRate") or 0.0              # 0..1, fraction of <=3 star
    w = weights
    raw = w.get("demand", 1.0) * demand + w.get("quality", 1.0) * quality - w.get("risk", 1.0) * risk
    total_w = w.get("demand", 1.0) + w.get("quality", 1.0)
    return round(max(raw, 0.0) / total_w * 100, 1) if total_w else 0.0
