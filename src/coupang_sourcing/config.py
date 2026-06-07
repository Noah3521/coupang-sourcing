"""Configuration: defaults + optional config.toml + CLI overrides."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import tomllib

BASE_SHOP = "https://shop.coupang.com"
BASE_WWW = "https://www.coupang.com"

# Default complaint keywords used for negative-review risk tagging.
DEFAULT_COMPLAINT_KEYWORDS = [
    "불량", "파손", "환불", "반품", "지연", "느림", "오배송",
    "하자", "고장", "냄새", "최악", "별로", "찢", "터짐",
]

# Default sourcing-score weights (see metrics.sourcing_score).
DEFAULT_SCORING_WEIGHTS = {"demand": 1.0, "quality": 1.0, "risk": 1.0}


@dataclass(frozen=True)
class Config:
    db_path: Path = Path("coupang_sourcing.db")
    rate_delay: float = 0.3          # base polite delay between requests (s)
    jitter: float = 0.2             # added random jitter up to this many seconds
    timeout: float = 12.0
    retries: int = 2
    retry_delay: float = 0.3
    review_size: int = 30            # capped to 30 by the review API
    max_review_pages: int = 0        # 0 = all
    listing_max_pages: int = 0       # 0 = scan until found / exhausted
    review_sort: str = "ORDER_SCORE_ASC"
    sale_multiplier: float = 10.0    # est. sales per review (rough heuristic)
    complaint_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_COMPLAINT_KEYWORDS))
    scoring_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SCORING_WEIGHTS))

    @staticmethod
    def load(path: Path | None = None) -> Config:
        """Load config from a TOML file if present, else return defaults."""
        cfg = Config()
        candidates = [path] if path else [
            Path("config.toml"),
            Path.home() / ".config" / "coupang-sourcing" / "config.toml",
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                data = tomllib.loads(candidate.read_text(encoding="utf-8"))
                fields = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
                if "db_path" in fields:
                    fields["db_path"] = Path(fields["db_path"])
                cfg = replace(cfg, **fields)
                break
        return cfg

    def override(self, **kwargs) -> Config:
        """Return a copy with non-None overrides applied (for CLI flags)."""
        clean = {k: v for k, v in kwargs.items() if v is not None}
        if "db_path" in clean:
            clean["db_path"] = Path(clean["db_path"])
        return replace(self, **clean)
