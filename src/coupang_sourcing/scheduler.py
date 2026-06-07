"""Scheduling via macOS launchd (LaunchAgent) that runs `coupang-sourcing refresh`.

The plist builder is pure (testable); install/uninstall/status shell out to launchctl.
On non-macOS platforms, callers should fall back to printing a crontab line.
"""
from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.coupang-sourcing.refresh"
INTERVALS = ("hourly", "daily", "weekly")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "coupang-sourcing-refresh.log"


def resolve_program() -> list[str]:
    """Absolute command to invoke the CLI (prefers the installed entry script)."""
    exe = shutil.which("coupang-sourcing")
    if exe:
        return [exe]
    return [sys.executable, "-m", "coupang_sourcing"]


def build_program_args(refresh_args: list[str], db_path: Path) -> list[str]:
    return [*resolve_program(), "refresh", *refresh_args, "--db", str(Path(db_path).resolve())]


def build_plist(program_args: list[str], interval: str, at: str | None) -> str:
    """Return the LaunchAgent plist XML for the given schedule (pure)."""
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {INTERVALS}")
    spec: dict = {
        "Label": LABEL,
        "ProgramArguments": program_args,
        "RunAtLoad": False,
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
    }
    if interval == "hourly":
        spec["StartInterval"] = 3600
    else:
        hour, minute = _parse_at(at, default="03:00")
        cal: dict = {"Hour": hour, "Minute": minute}
        if interval == "weekly":
            cal["Weekday"] = 1  # Monday
        spec["StartCalendarInterval"] = cal
    return plistlib.dumps(spec).decode("utf-8")


def _parse_at(at: str | None, *, default: str) -> tuple[int, int]:
    raw = at or default
    try:
        hh, mm = raw.split(":")
        hour, minute = int(hh), int(mm)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"--at must be HH:MM (got {raw!r})") from exc


def crontab_line(refresh_args: list[str], db_path: Path, interval: str, at: str | None) -> str:
    """Fallback cron schedule line for non-macOS hosts."""
    cmd = " ".join(build_program_args(refresh_args, db_path))
    if interval == "hourly":
        return f"0 * * * * {cmd}"
    hour, minute = _parse_at(at, default="03:00")
    if interval == "weekly":
        return f"{minute} {hour} * * 1 {cmd}"
    return f"{minute} {hour} * * * {cmd}"


def is_macos() -> bool:
    return sys.platform == "darwin"


def install(refresh_args: list[str], db_path: Path, interval: str, at: str | None) -> Path:
    """Write the plist and (re)load it into launchd."""
    program_args = build_program_args(refresh_args, db_path)
    content = build_plist(program_args, interval, at)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(path)], check=True, capture_output=True)
    return path


def uninstall() -> bool:
    """Unload and remove the plist. Returns True if a plist existed."""
    path = plist_path()
    if not path.exists():
        return False
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    path.unlink()
    return True


def status() -> dict:
    """Report whether the agent is installed and currently loaded."""
    path = plist_path()
    loaded = False
    if path.exists():
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        loaded = LABEL in result.stdout
    return {
        "label": LABEL,
        "installed": path.exists(),
        "loaded": loaded,
        "plist": str(path),
        "log": str(log_path()),
    }
