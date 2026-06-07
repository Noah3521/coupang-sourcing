import plistlib
from pathlib import Path

import pytest

from coupang_sourcing import scheduler


def test_build_plist_daily():
    args = ["/bin/coupang-sourcing", "refresh", "--all", "--db", "/tmp/s.db"]
    xml = scheduler.build_plist(args, "daily", "09:30")
    spec = plistlib.loads(xml.encode())
    assert spec["Label"] == scheduler.LABEL
    assert spec["ProgramArguments"] == args
    assert spec["StartCalendarInterval"] == {"Hour": 9, "Minute": 30}
    assert spec["RunAtLoad"] is False


def test_build_plist_hourly_uses_interval():
    xml = scheduler.build_plist(["x"], "hourly", None)
    spec = plistlib.loads(xml.encode())
    assert spec["StartInterval"] == 3600
    assert "StartCalendarInterval" not in spec


def test_build_plist_weekly_has_weekday():
    xml = scheduler.build_plist(["x"], "weekly", None)
    spec = plistlib.loads(xml.encode())
    assert spec["StartCalendarInterval"]["Weekday"] == 1
    assert spec["StartCalendarInterval"]["Hour"] == 3  # default 03:00


def test_build_plist_rejects_bad_interval():
    with pytest.raises(ValueError):
        scheduler.build_plist(["x"], "yearly", None)


def test_parse_at_validation():
    with pytest.raises(ValueError):
        scheduler.build_plist(["x"], "daily", "25:00")


def test_build_program_args_includes_refresh_and_db(tmp_path):
    db = tmp_path / "s.db"
    args = scheduler.build_program_args(["--store", "A1"], db)
    assert "refresh" in args
    assert args[-2] == "--db"
    assert args[-1] == str(db.resolve())


def test_crontab_line_daily():
    line = scheduler.crontab_line(["--all"], Path("/tmp/s.db"), "daily", "06:15")
    assert line.startswith("15 6 * * *")
    assert "refresh" in line
