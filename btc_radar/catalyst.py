"""Macro / catalyst risk window for the next ~48h."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path


class MacroMode(str, Enum):
    AUTO = "auto"
    LOW = "low"
    ELEVATED = "elevated"
    EVENT_BULL = "event_bull"
    EVENT_BEAR = "event_bear"


@dataclass
class CatalystFeatures:
    mode: MacroMode
    risk_label: str  # LOW / ELEVATED / EVENT_BULL / EVENT_BEAR
    force_no_trade: bool
    bullish_bias: bool
    bearish_bias: bool
    next_event: str
    hours_to_event: float | None
    detail: str


_CALENDAR_PATH = Path(__file__).with_name("macro_events.json")


def _load_macro_events(path: Path | None = None) -> list[tuple[datetime, str, float, float]]:
    """Load approximate UTC release windows. Override live with --macro when stale."""
    cal = path or _CALENDAR_PATH
    if not cal.exists():
        return []
    raw = json.loads(cal.read_text(encoding="utf-8"))
    events: list[tuple[datetime, str, float, float]] = []
    for row in raw:
        when = datetime.fromisoformat(row["utc"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        events.append(
            (
                when.astimezone(timezone.utc),
                str(row["name"]),
                float(row.get("hours_before", 6)),
                float(row.get("hours_after", 2)),
            )
        )
    return events


_MACRO_EVENTS: list[tuple[datetime, str, float, float]] = _load_macro_events()


def _nearest_event(now: datetime) -> tuple[datetime, str, float, float] | None:
    upcoming = [e for e in _MACRO_EVENTS if e[0] > now - timedelta(hours=e[3])]
    if not upcoming:
        return None
    upcoming.sort(key=lambda e: e[0])
    return upcoming[0]


def extract_catalyst(
    override: MacroMode = MacroMode.AUTO,
    now: datetime | None = None,
    force: bool = False,
) -> CatalystFeatures:
    now = now or datetime.now(timezone.utc)

    if override != MacroMode.AUTO:
        force_no = override in (MacroMode.ELEVATED, MacroMode.EVENT_BULL, MacroMode.EVENT_BEAR) and not force
        # event_bull / event_bear still block unless --force; bias points only if forced or low
        if override == MacroMode.LOW:
            return CatalystFeatures(
                mode=override,
                risk_label="LOW",
                force_no_trade=False,
                bullish_bias=False,
                bearish_bias=False,
                next_event="(override)",
                hours_to_event=None,
                detail="Macro override: LOW",
            )
        if override == MacroMode.ELEVATED:
            return CatalystFeatures(
                mode=override,
                risk_label="ELEVATED",
                force_no_trade=force_no,
                bullish_bias=False,
                bearish_bias=False,
                next_event="(override)",
                hours_to_event=None,
                detail="Macro override: ELEVATED — prefer NO TRADE",
            )
        if override == MacroMode.EVENT_BULL:
            return CatalystFeatures(
                mode=override,
                risk_label="EVENT_BULL",
                force_no_trade=force_no,
                bullish_bias=True,
                bearish_bias=False,
                next_event="(override)",
                hours_to_event=None,
                detail="Macro override: EVENT_BULL",
            )
        return CatalystFeatures(
            mode=override,
            risk_label="EVENT_BEAR",
            force_no_trade=force_no,
            bullish_bias=False,
            bearish_bias=True,
            next_event="(override)",
            hours_to_event=None,
            detail="Macro override: EVENT_BEAR",
        )

    ev = _nearest_event(now)
    if ev is None:
        return CatalystFeatures(
            mode=MacroMode.AUTO,
            risk_label="LOW",
            force_no_trade=False,
            bullish_bias=False,
            bearish_bias=False,
            next_event="none scheduled",
            hours_to_event=None,
            detail="No known macro event in calendar",
        )

    when, name, hrs_before, hrs_after = ev
    hours_to = (when - now).total_seconds() / 3600.0
    in_window = -hrs_after <= hours_to <= hrs_before

    if in_window:
        return CatalystFeatures(
            mode=MacroMode.AUTO,
            risk_label="ELEVATED",
            force_no_trade=not force,
            bullish_bias=False,
            bearish_bias=False,
            next_event=name,
            hours_to_event=hours_to,
            detail=f"{name} in {hours_to:+.1f}h — don't-trade window",
        )

    return CatalystFeatures(
        mode=MacroMode.AUTO,
        risk_label="LOW",
        force_no_trade=False,
        bullish_bias=False,
        bearish_bias=False,
        next_event=name,
        hours_to_event=hours_to,
        detail=f"Next: {name} in {hours_to:.1f}h",
    )
