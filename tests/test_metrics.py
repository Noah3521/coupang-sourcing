from datetime import datetime, timezone

from coupang_sourcing.config import DEFAULT_COMPLAINT_KEYWORDS, DEFAULT_SCORING_WEIGHTS
from coupang_sourcing.metrics import (
    channel_of,
    estimate_monthly_sales,
    sourcing_metrics,
    sourcing_score,
)
from coupang_sourcing.normalize import normalize_product, parse_review_payload

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _metrics(raw_product, review_payload):
    variants = [normalize_product(raw_product, "A00333576", 29119)]
    reviews = parse_review_payload(review_payload)["reviews"]
    summary = parse_review_payload(review_payload)["ratingSummary"]
    return sourcing_metrics(variants, reviews, summary,
                            complaint_keywords=DEFAULT_COMPLAINT_KEYWORDS, now=NOW)


def test_sourcing_metrics_basic(raw_product, review_payload):
    m = _metrics(raw_product, review_payload)
    assert m["ratingAverage"] == 4.5
    assert m["ratingCount"] == 503
    assert m["negativeRate"] == 0.5  # 1 of 2 reviews is rating<=3
    assert m["channel"] == "rocket"
    # complaint keywords "배송", "파손" present in the 2-star review
    kws = dict(m["complaintKeywords"])
    assert "파손" in kws


def test_channel_of():
    assert channel_of([{"rocket": True}]) == "rocket"
    assert channel_of([{"rocket": False, "overseasLike": True}]) == "overseas"
    assert channel_of([{"rocket": False, "overseasLike": False}]) == "domestic"


def test_estimate_sales_snapshot_delta():
    metrics = {"ratingCount": 120, "reviewVelocity": {"last1mo": 5}}
    prior = {"crawled_at": datetime(2025, 12, 2, tzinfo=timezone.utc).isoformat(), "review_total": 90}
    est = estimate_monthly_sales(metrics, sale_multiplier=10, prior_snapshot=prior, now=NOW)
    assert est["method"] == "snapshot_delta"
    assert est["estimatedReviewsPerMonth"] > 0


def test_estimate_sales_fallback():
    metrics = {"ratingCount": 120, "reviewVelocity": {"last1mo": 8}}
    est = estimate_monthly_sales(metrics, sale_multiplier=10, prior_snapshot=None, now=NOW)
    assert est["method"] == "review_velocity_fallback"
    assert est["estimatedSalesPerMonth"] == 80


def test_sourcing_score_bounds():
    high = sourcing_score({"reviewVelocity": {"last3mo": 100}, "ratingAverage": 5.0, "negativeRate": 0.0},
                          DEFAULT_SCORING_WEIGHTS)
    low = sourcing_score({"reviewVelocity": {"last3mo": 0}, "ratingAverage": 3.0, "negativeRate": 0.9},
                         DEFAULT_SCORING_WEIGHTS)
    assert 0 <= low <= high <= 100
