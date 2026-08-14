"""Price structure features: VWAP, PDH/PDL, session H/L, EMA trend."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def session_vwap(df: pd.DataFrame) -> float:
    """UTC-day session VWAP from typical price * volume."""
    if df.empty:
        return float("nan")
    last_day = df["open_time"].dt.floor("D").iloc[-1]
    day = df[df["open_time"].dt.floor("D") == last_day].copy()
    if day.empty:
        day = df.tail(min(len(df), 48)).copy()
    tp = (day["high"] + day["low"] + day["close"]) / 3.0
    vol = day["volume"].replace(0, np.nan)
    if vol.isna().all() or float(vol.sum()) == 0:
        return float(day["close"].iloc[-1])
    return float((tp * day["volume"]).sum() / day["volume"].sum())


@dataclass
class StructureFeatures:
    price: float
    vwap: float
    above_vwap: bool
    pdh: float
    pdl: float
    session_high: float
    session_low: float
    ema20_5m: float
    ema50_5m: float
    ema20_15m: float
    ema50_15m: float
    trend_bullish: bool
    trend_bearish: bool
    near_support: bool
    near_resistance: bool
    label: str  # bullish / bearish / mixed


def extract_structure(snapshot: dict) -> StructureFeatures:
    k5: pd.DataFrame = snapshot["k5"]
    k15: pd.DataFrame = snapshot["k15"]
    k1d: pd.DataFrame = snapshot["k1d"]
    if k5 is None or k5.empty or k15 is None or k15.empty:
        raise ValueError("Need non-empty 5m and 15m klines to score structure")
    price = float(snapshot["premium"]["markPrice"])

    vwap = session_vwap(k5)
    above_vwap = price > vwap

    # Previous day high/low (yesterday's completed daily candle)
    if len(k1d) >= 2:
        prev = k1d.iloc[-2]
        pdh, pdl = float(prev["high"]), float(prev["low"])
    else:
        pdh = float(k5["high"].max())
        pdl = float(k5["low"].min())

    last_day = k5["open_time"].dt.floor("D").iloc[-1]
    sess = k5[k5["open_time"].dt.floor("D") == last_day]
    if sess.empty:
        sess = k5.tail(48)
    session_high = float(sess["high"].max())
    session_low = float(sess["low"].min())

    e20_5 = float(_ema(k5["close"], 20).iloc[-1])
    e50_5 = float(_ema(k5["close"], 50).iloc[-1])
    e20_15 = float(_ema(k15["close"], 20).iloc[-1])
    e50_15 = float(_ema(k15["close"], 50).iloc[-1])

    bull_5 = price > e20_5 > e50_5
    bear_5 = price < e20_5 < e50_5
    bull_15 = price > e20_15 > e50_15
    bear_15 = price < e20_15 < e50_15

    trend_bullish = bull_5 and bull_15
    trend_bearish = bear_5 and bear_15

    # Proximity to major levels (within 0.35%)
    thr = price * 0.0035
    near_support = min(abs(price - pdl), abs(price - session_low)) <= thr
    near_resistance = min(abs(price - pdh), abs(price - session_high)) <= thr

    if trend_bullish and above_vwap:
        label = "bullish"
    elif trend_bearish and not above_vwap:
        label = "bearish"
    else:
        label = "mixed"

    return StructureFeatures(
        price=price,
        vwap=vwap,
        above_vwap=above_vwap,
        pdh=pdh,
        pdl=pdl,
        session_high=session_high,
        session_low=session_low,
        ema20_5m=e20_5,
        ema50_5m=e50_5,
        ema20_15m=e20_15,
        ema50_15m=e50_15,
        trend_bullish=trend_bullish,
        trend_bearish=trend_bearish,
        near_support=near_support,
        near_resistance=near_resistance,
        label=label,
    )
