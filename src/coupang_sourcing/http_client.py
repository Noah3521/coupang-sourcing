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

# curl_cffi's available chrome impersonation (JA3) targets, ascending.
_CHROME_IMPERSONATE = [99, 100, 101, 104, 107, 110, 116, 119, 120, 123, 124, 131, 136, 142, 145, 146]
_IDENT: dict[str, str] | None = None


def _closest_impersonate(major: int) -> str:
    usable = [v for v in _CHROME_IMPERSONATE if v <= major] or _CHROME_IMPERSONATE
    return f"chrome{usable[-1]}"


def _ident() -> dict[str, str]:
    """UA / sec-ch-ua / curl impersonate aligned to the installed Chrome (cached).

    Akamai re-challenges when the replayed JA3/UA disagree with the Chrome that minted the
    cookies, so we match the real major version (falling back to 136 if Chrome isn't found).
    """
    global _IDENT
    if _IDENT is None:
        try:
            from .browser import chrome_major_version
            major = chrome_major_version() or 136
        except Exception:
            major = 136
        _IDENT = {
            "ua": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
            ),
            "sec_ch_ua": f'"Chromium";v="{major}", "Google Chrome";v="{major}", "Not.A/Brand";v="99"',
            "impersonate": _closest_impersonate(major),
        }
    return _IDENT


def shop_headers(store_url: str) -> dict[str, str]:
    ident = _ident()
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "content-type": "application/json;charset=UTF-8",
        "origin": BASE_SHOP,
        "referer": store_url,
        "sec-ch-ua": ident["sec_ch_ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "user-agent": ident["ua"],
    }


def review_headers(referer: str | None = None) -> dict[str, str]:
    ident = _ident()
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "referer": referer or f"{BASE_WWW}/",
        "sec-ch-ua": ident["sec_ch_ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "user-agent": ident["ua"],
    }


def html_headers(referer: str | None = None) -> dict[str, str]:
    """Headers for fetching server-rendered HTML pages (e.g. /np/best100/*, /np/search)."""
    ident = _ident()
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "referer": referer or f"{BASE_WWW}/",
        "sec-ch-ua": ident["sec_ch_ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "upgrade-insecure-requests": "1",
        "user-agent": ident["ua"],
    }


class CoupangClient:
    """Reusable session. Warms up lazily per host, throttles, retries with backoff."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session(impersonate=_ident()["impersonate"])
        self._warmed: set[str] = set()
        self._rng = random.Random()
        self._cookies_loaded = False

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
            self.session.get(
                url, headers={"accept": accept, "user-agent": _ident()["ua"]},
                timeout=self.config.timeout,
            )
        except Exception:
            pass

    def _request(self, method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                self._throttle()
                response = self.session.request(
                    method, url, headers=headers, timeout=self.config.timeout, **kwargs
                )
                response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(self.config.retry_delay * (attempt + 1))
        raise RuntimeError(f"request failed: {method} {url}: {last_error!r}")

    def request_json(self, method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> Any:
        return self._request(method, url, headers=headers, **kwargs).json()

    def request_text(self, method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> str:
        return self._request(method, url, headers=headers, **kwargs).text

    # --- Akamai-gated routes (search, vendoritems): need browser-minted cookies ---------

    def _apply_cookies(self, cookies: list[dict[str, str]]) -> None:
        # Clear first so a re-mint can't leave a stale duplicate (e.g. two _abck on
        # different domains) that keeps Akamai challenging.
        try:
            self.session.cookies.clear()
        except Exception:
            pass
        for c in cookies:
            self.session.cookies.set(c["name"], c["value"], domain=c["domain"].lstrip("."))
        self._cookies_loaded = True

    def ensure_cookies(self, *, progress=None) -> None:
        """Load cached Akamai cookies, minting them via a browser if absent/stale."""
        if self._cookies_loaded:
            return
        from . import cookies as cookie_cache  # local import: browser/Chrome only needed here
        cached = cookie_cache.load_cookies()
        if cached:
            self._apply_cookies(cached)
            return
        self.remint(progress=progress)

    def remint(self, *, progress=None) -> None:
        """Force a fresh browser cookie mint and persist it."""
        from . import cookies as cookie_cache
        from .browser import mint_cookies
        fresh = mint_cookies(progress=progress)
        cookie_cache.save_cookies(fresh)
        self._apply_cookies(fresh)

    @staticmethod
    def _is_blocked(response: Any) -> bool:
        if response.status_code in (401, 403, 429):
            return True
        if "text/html" in response.headers.get("content-type", ""):
            body = response.text
            return "sec-if-cpt-container" in body or "Access Denied" in body
        return False

    def gated_request(self, method: str, url: str, *, headers: dict[str, str],
                      progress=None, **kwargs: Any) -> Any:
        """Request an Akamai-gated route, refreshing (and re-minting once) if blocked.

        Akamai's challenge is served as a 200 HTML interstitial, and a plain refresh with
        the same cookies usually clears it (as a human reload does). So we retry the request
        a few times, re-minting cookies once midway, and raise a clear error only if it
        stays blocked through all attempts.
        """
        self.ensure_cookies(progress=progress)
        minted = False
        last = None
        for attempt in range(4):
            self._throttle()
            last = self.session.request(
                method, url, headers=headers, timeout=self.config.timeout, **kwargs
            )
            if not self._is_blocked(last):
                return last
            # One quick refresh handles a transient soft-challenge with still-valid cookies;
            # past that, only a browser re-mint clears it (curl can't run the sensor).
            if attempt == 0:
                if progress:
                    progress("Akamai challenge — refreshing…")
            elif not minted:
                if progress:
                    progress("re-minting cookies (browser)…")
                self.remint(progress=progress)
                minted = True
        raise RuntimeError(
            f"blocked by Akamai after retries: {method} {url} (last status {last.status_code})"
        )

    def gated_json(self, method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> Any:
        return self.gated_request(method, url, headers=headers, **kwargs).json()

    def gated_text(self, method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> str:
        return self.gated_request(method, url, headers=headers, **kwargs).text
