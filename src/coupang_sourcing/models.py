"""Lightweight result containers passed between collectors, storage, and exporters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProductRecord:
    """Everything collected for a single product."""

    product: dict[str, Any]                     # representative normalized variant
    variants: list[dict[str, Any]]              # all normalized variants for this productId
    store: dict[str, Any]                       # {storeId, vendorId, storeName, storeUrl, urlName}
    reviews: dict[str, Any]                     # {ratingSummary, totalCount, reviews, ...}
    metrics: dict[str, Any]                     # sourcing_metrics output (+ score/sales added)
    is_ad: bool = False
    collected_at: str = ""
    elapsed_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def product_id(self) -> str:
        return str(self.product.get("productId"))
