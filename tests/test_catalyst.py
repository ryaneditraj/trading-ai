from datetime import datetime, timezone

from btc_radar.catalyst import MacroMode, extract_catalyst


def test_low_override_never_blocks():
    c = extract_catalyst(override=MacroMode.LOW)
    assert c.force_no_trade is False
    assert c.risk_label == "LOW"


def test_elevated_override_blocks_unless_forced():
    blocked = extract_catalyst(override=MacroMode.ELEVATED, force=False)
    forced = extract_catalyst(override=MacroMode.ELEVATED, force=True)
    assert blocked.force_no_trade is True
    assert forced.force_no_trade is False


def test_auto_window_around_listed_cpi():
    # Calendar lists 2026-08-12 12:30 UTC CPI with 6h before / 2h after.
    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    c = extract_catalyst(override=MacroMode.AUTO, now=now)
    assert c.risk_label == "ELEVATED"
    assert c.force_no_trade is True
    assert "CPI" in c.next_event


def test_auto_quiet_day_is_low():
    now = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
    c = extract_catalyst(override=MacroMode.AUTO, now=now)
    assert c.risk_label == "LOW"
    assert c.force_no_trade is False
