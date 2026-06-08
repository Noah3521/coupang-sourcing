"""Persistent cache for browser-minted Akamai cookies (Tier-2 gated routes).

Cookies live at ~/.config/coupang-sourcing/cookies.json with a save timestamp; the
client reuses them across runs and only re-mints (launches Chrome) when they are missing,
stale, or rejected with a 403/challenge.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Akamai's cookie set stays usable for a while; treat older than this as stale.
MAX_AGE_SECONDS = 60 * 60  # 1 hour


def cookie_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "coupang-sourcing" / "cookies.json"


def load_cookies(max_age: float = MAX_AGE_SECONDS) -> list[dict[str, str]] | None:
    """Return cached cookies, or None if absent/unreadable/stale."""
    path = cookie_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if max_age and (time.time() - data.get("savedAt", 0)) > max_age:
        return None
    cookies = data.get("cookies") or []
    return cookies or None


def save_cookies(cookies: list[dict[str, str]]) -> None:
    path = cookie_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"savedAt": time.time(), "cookies": cookies}, ensure_ascii=False),
        encoding="utf-8",
    )


def clear_cookies() -> None:
    cookie_path().unlink(missing_ok=True)
