"""CoupangClient: a single chrome-impersonating session with warmup, retry, rate-limit.

Wraps the validated helpers from tools/coupang_shop_cli.py
  make_session 317, request_json 338, shop_headers 321, review_headers 197.

Only the stable, non-403 endpoints are used:
  shop.coupang.com/api/v1/{store/getStoreInfo, listing, store/getStoreReview, main_category}
  www.coupang.com/next-api/review
The 403-prone product-detail routes (vp/np pages, btf JSON, /vp/product/reviews HTML)
are intentionally NOT used.
"""
from __future__ import annotations

import random
import time
from typing import Any

from curl_cffi import requests

from .config import BASE_SHOP, BASE_WWW, Config

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
_SEC_CH_UA = '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"'


def shop_headers(store_url: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "content-type": "application/json;charset=UTF-8",
        "origin": BASE_SHOP,
        "referer": store_url,
        "sec-ch-ua": _SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "user-agent": _UA,
    }


def review_headers(referer: str | None = None) -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "referer": referer or f"{BASE_WWW}/",
        "sec-ch-ua": _SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "user-agent": _UA,
    }


class CoupangClient:
    """Reusable session. Warms up lazily per host, throttles, retries with backoff."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session(impersonate="chrome136")
        self._warmed: set[str] = set()
        self._rng = random.Random()

    def _throttle(self) -> None:
        delay = self.config.rate_delay + self._rng.uniform(0, self.config.jitter)
        if delay > 0:
            time.sleep(delay)

    def warm(self, url: str, *, accept: str = "text/html,*/*") -> None:
        """Best-effort warmup GET (sets cookies) for a host; runs once per url."""
        if url in self._warmed:
            return
        self._warmed.add(url)
        try:
            self.session.get(url, headers={"accept": accept, "user-agent": _UA}, timeout=self.config.timeout)
        except Exception:
            pass

    def request_json(self, method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                self._throttle()
                response = self.session.request(
                    method, url, headers=headers, timeout=self.config.timeout, **kwargs
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(self.config.retry_delay * (attempt + 1))
        raise RuntimeError(f"request failed: {method} {url}: {last_error!r}")
