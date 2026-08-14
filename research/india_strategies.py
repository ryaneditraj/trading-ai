"""
Price / volume / market-structure signal builders for India edge search.
Each returns (entries, exits, side) where side is +1 long or -1 short.
"""
from __future__ import annotations

from typing import Callable, Dict, Tuple

import numpy as np
import pandas as pd

SignalBuilder = Callable[[pd.DataFrame, dict], Tuple[pd.Series, pd.Series, int]]


def _exit_opposite_or_ma(df: pd.DataFrame, side: int, ma_col: str = "ema20") -> pd.Series:
    if side == 1:
        return df["Close"] < df[ma_col]
    return df["Close"] > df[ma_col]


# ── H1: Donchian breakout + relative volume ──────────────────────────────────
def h1_donchian_rvol(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    n = int(p.get("n", 20))
    rvol_min = float(p.get("rvol_min", 1.3))
    hh = df["High"].rolling(n).max().shift(1)
    ll = df["Low"].rolling(n).min().shift(1)
    long_e = (df["Close"] > hh) & (df["rvol"] >= rvol_min) & (df["Close"] > df["ema200"])
    short_e = (df["Close"] < ll) & (df["rvol"] >= rvol_min) & (df["Close"] < df["ema200"])
    # Combined: prefer long signals; for simplicity long-only first via side param
    side = int(p.get("side", 1))
    entries = long_e if side == 1 else short_e
    exits = _exit_opposite_or_ma(df, side, "ema20")
    # Also exit on opposite channel
    if side == 1:
        exits = exits | (df["Close"] < df["Low"].rolling(10).min().shift(1))
    else:
        exits = exits | (df["Close"] > df["High"].rolling(10).max().shift(1))
    return entries, exits, side


# ── H2: NR7 expansion breakout ───────────────────────────────────────────────
def h2_nr7_breakout(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_min = float(p.get("rvol_min", 1.2))
    nr7 = df["range"] == df["range"].rolling(7).min()
    # Signal day after NR7: break prior high of NR7 day
    nr7_high = df["High"].where(nr7).ffill()
    nr7_low = df["Low"].where(nr7).ffill()
    was_nr7 = nr7.shift(1).fillna(False)
    side = int(p.get("side", 1))
    if side == 1:
        entries = was_nr7 & (df["Close"] > nr7_high.shift(1)) & (df["rvol"] >= rvol_min) & (
            df["Close"] > df["ema50"]
        )
    else:
        entries = was_nr7 & (df["Close"] < nr7_low.shift(1)) & (df["rvol"] >= rvol_min) & (
            df["Close"] < df["ema50"]
        )
    exits = _exit_opposite_or_ma(df, side, "ema20")
    return entries, exits, side


# ── H3: Gap fade (mean reversion) with weak volume ───────────────────────────
def h3_gap_fade(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    gap_min = float(p.get("gap_min", 0.008))
    rvol_max = float(p.get("rvol_max", 1.0))
    # Fade gap-up: short; fade gap-down: long. Use side=+1 for gap-down longs.
    side = int(p.get("side", 1))
    if side == 1:
        entries = (df["gap"] <= -gap_min) & (df["rvol"] <= rvol_max) & (df["Close"] > df["Open"])
        # Exit when gap filled (close back to prior close) or EMA20
        exits = (df["Close"] >= df["prior_close"]) | (df["Close"] > df["ema20"])
    else:
        entries = (df["gap"] >= gap_min) & (df["rvol"] <= rvol_max) & (df["Close"] < df["Open"])
        exits = (df["Close"] <= df["prior_close"]) | (df["Close"] < df["ema20"])
    return entries, exits, side


# ── H4: Break of structure + volume confirmation ─────────────────────────────
def h4_bos_volume(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_min = float(p.get("rvol_min", 1.4))
    side = int(p.get("side", 1))
    # Bullish BOS: close above last swing high with volume, above EMA50
    # Bearish BOS: close below last swing low with volume
    if side == 1:
        entries = (
            (df["Close"] > df["last_swing_high"])
            & (df["rvol"] >= rvol_min)
            & (df["Close"] > df["ema50"])
            & (df["Close"].shift(1) <= df["last_swing_high"].shift(1))
        )
        exits = df["Close"] < df["last_swing_low"]
    else:
        entries = (
            (df["Close"] < df["last_swing_low"])
            & (df["rvol"] >= rvol_min)
            & (df["Close"] < df["ema50"])
            & (df["Close"].shift(1) >= df["last_swing_low"].shift(1))
        )
        exits = df["Close"] > df["last_swing_high"]
    return entries, exits, side


# ── H5: Inside-bar breakout + RVOL ───────────────────────────────────────────
def h5_inside_bar(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_min = float(p.get("rvol_min", 1.25))
    side = int(p.get("side", 1))
    mother_high = df["High"].shift(1)
    mother_low = df["Low"].shift(1)
    was_inside = df["inside"].shift(1).fillna(False)
    if side == 1:
        entries = was_inside & (df["Close"] > mother_high) & (df["rvol"] >= rvol_min) & (
            df["Close"] > df["ema50"]
        )
        exits = df["Close"] < df["ema20"]
    else:
        entries = was_inside & (df["Close"] < mother_low) & (df["rvol"] >= rvol_min) & (
            df["Close"] < df["ema50"]
        )
        exits = df["Close"] > df["ema20"]
    return entries, exits, side


# ── H6: ATR squeeze breakout ─────────────────────────────────────────────────
def h6_atr_squeeze(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    n = int(p.get("n", 20))
    squeeze_max = float(p.get("squeeze_max", 0.25))
    rvol_min = float(p.get("rvol_min", 1.2))
    side = int(p.get("side", 1))
    hh = df["High"].rolling(n).max().shift(1)
    ll = df["Low"].rolling(n).min().shift(1)
    squeezed = df["atr_rank"] <= squeeze_max
    if side == 1:
        entries = squeezed & (df["Close"] > hh) & (df["rvol"] >= rvol_min) & (df["Close"] > df["ema50"])
        exits = df["Close"] < df["Low"].rolling(10).min().shift(1)
    else:
        entries = squeezed & (df["Close"] < ll) & (df["rvol"] >= rvol_min) & (df["Close"] < df["ema50"])
        exits = df["Close"] > df["High"].rolling(10).max().shift(1)
    return entries, exits, side


# ── H7: Prior-day high break + RVOL (momentum continuation) ──────────────────
def h7_pdh_rvol(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_min = float(p.get("rvol_min", 1.5))
    side = int(p.get("side", 1))
    if side == 1:
        entries = (
            (df["Close"] > df["prior_high"])
            & (df["rvol"] >= rvol_min)
            & (df["Close"] > df["ema20"])
            & (df["ema20"] > df["ema50"])
        )
        exits = (df["Close"] < df["ema20"]) | (df["Close"] < df["prior_low"])
    else:
        entries = (
            (df["Close"] < df["prior_low"])
            & (df["rvol"] >= rvol_min)
            & (df["Close"] < df["ema20"])
            & (df["ema20"] < df["ema50"])
        )
        exits = (df["Close"] > df["ema20"]) | (df["Close"] > df["prior_high"])
    return entries, exits, side


# ── H8: Trend pullback to EMA20 with volume dry-up then reclaim ──────────────
def h8_pullback_reclaim(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_entry = float(p.get("rvol_min", 1.1))
    side = int(p.get("side", 1))
    # Touched EMA20 recently while in uptrend, then close back above EMA20 with volume
    touched = (df["Low"] <= df["ema20"]) & (df["Low"] >= df["ema20"] - 0.5 * df["atr"])
    if side == 1:
        uptrend = (df["Close"] > df["ema200"]) & (df["ema20"] > df["ema50"])
        near = touched.rolling(3).max().astype(bool)
        entries = near & (df["Close"] > df["ema20"]) & (df["rvol"] >= rvol_entry) & uptrend
        # Prefer days that were below EMA20 recently
        was_below = (df["Close"].shift(1) < df["ema20"].shift(1)) | (
            df["Close"].shift(2) < df["ema20"].shift(2)
        )
        entries = entries & was_below
        exits = df["Close"] < df["ema50"]
    else:
        downtrend = (df["Close"] < df["ema200"]) & (df["ema20"] < df["ema50"])
        near = ((df["High"] >= df["ema20"]) & (df["High"] <= df["ema20"] + 0.5 * df["atr"])).rolling(
            3
        ).max().astype(bool)
        was_above = (df["Close"].shift(1) > df["ema20"].shift(1)) | (
            df["Close"].shift(2) > df["ema20"].shift(2)
        )
        entries = near & (df["Close"] < df["ema20"]) & (df["rvol"] >= rvol_entry) & downtrend & was_above
        exits = df["Close"] > df["ema50"]
    return entries, exits, side


# ── H9: Volume climax reversal (wide range exhaustion) ───────────────────────
def h9_climax_reversal(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_min = float(p.get("rvol_min", 2.0))
    range_mult = float(p.get("range_mult", 1.8))
    side = int(p.get("side", 1))
    wide = df["range"] > range_mult * df["atr"]
    # Climax down day → long next (signal today); climax up → short
    if side == 1:
        entries = wide & (df["Close"] < df["Open"]) & (df["rvol"] >= rvol_min) & (
            df["Close"] > df["ema200"]
        )  # selloff in uptrend
        exits = (df["Close"] >= df["High"].rolling(5).max().shift(1)) | (df["Close"] < df["ema50"])
    else:
        entries = wide & (df["Close"] > df["Open"]) & (df["rvol"] >= rvol_min) & (
            df["Close"] < df["ema200"]
        )
        exits = (df["Close"] <= df["Low"].rolling(5).min().shift(1)) | (df["Close"] > df["ema50"])
    return entries, exits, side


# ── H10: VWAP20 reclaim after acceptance below ───────────────────────────────
def h10_vwap_reclaim(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_min = float(p.get("rvol_min", 1.2))
    side = int(p.get("side", 1))
    below = df["Close"] < df["vwap20"]
    above = df["Close"] > df["vwap20"]
    if side == 1:
        accepted_below = below.rolling(3).sum() >= 2
        reclaim = above & below.shift(1)
        entries = accepted_below.shift(1).fillna(False) & reclaim & (df["rvol"] >= rvol_min) & (
            df["Close"] > df["ema50"]
        )
        exits = df["Close"] < df["vwap20"]
    else:
        accepted_above = above.rolling(3).sum() >= 2
        reject = below & above.shift(1)
        entries = accepted_above.shift(1).fillna(False) & reject & (df["rvol"] >= rvol_min) & (
            df["Close"] < df["ema50"]
        )
        exits = df["Close"] > df["vwap20"]
    return entries, exits, side


# ── H11: Dual-timeframe structure — daily trend + hourly BOS (hourly df) ─────
def h11_hourly_bos_daily_trend(
    h1: pd.DataFrame, daily_trend_long: bool, p: dict
) -> Tuple[pd.Series, pd.Series, int]:
    """Built separately in runner for hourly data."""
    rvol_min = float(p.get("rvol_min", 1.5))
    side = 1 if daily_trend_long else -1
    if side == 1:
        entries = (
            (h1["Close"] > h1["last_swing_high"])
            & (h1["rvol"] >= rvol_min)
            & (h1["Close"] > h1["ema50"])
            & (h1["Close"].shift(1) <= h1["last_swing_high"].shift(1))
        )
        exits = h1["Close"] < h1["ema20"]
    else:
        entries = (
            (h1["Close"] < h1["last_swing_low"])
            & (h1["rvol"] >= rvol_min)
            & (h1["Close"] < h1["ema50"])
            & (h1["Close"].shift(1) >= h1["last_swing_low"].shift(1))
        )
        exits = h1["Close"] > h1["ema20"]
    return entries, exits, side


# ── H12: Range contraction (3-day) then directional volume thrust ────────────
def h12_contraction_thrust(df: pd.DataFrame, p: dict) -> Tuple[pd.Series, pd.Series, int]:
    rvol_min = float(p.get("rvol_min", 1.4))
    side = int(p.get("side", 1))
    avg3 = df["range"].rolling(3).mean()
    avg20 = df["range"].rolling(20).mean()
    contracted = avg3 < 0.55 * avg20
    if side == 1:
        entries = (
            contracted.shift(1).fillna(False)
            & (df["Close"] > df["hh10"])
            & (df["rvol"] >= rvol_min)
            & (df["Close"] > df["ema50"])
        )
        exits = df["Close"] < df["ema20"]
    else:
        entries = (
            contracted.shift(1).fillna(False)
            & (df["Close"] < df["ll10"])
            & (df["rvol"] >= rvol_min)
            & (df["Close"] < df["ema50"])
        )
        exits = df["Close"] > df["ema20"]
    return entries, exits, side


STRATEGIES: Dict[str, SignalBuilder] = {
    "H1_donchian_rvol": h1_donchian_rvol,
    "H2_nr7_breakout": h2_nr7_breakout,
    "H3_gap_fade": h3_gap_fade,
    "H4_bos_volume": h4_bos_volume,
    "H5_inside_bar": h5_inside_bar,
    "H6_atr_squeeze": h6_atr_squeeze,
    "H7_pdh_rvol": h7_pdh_rvol,
    "H8_pullback_reclaim": h8_pullback_reclaim,
    "H9_climax_reversal": h9_climax_reversal,
    "H10_vwap_reclaim": h10_vwap_reclaim,
    "H12_contraction_thrust": h12_contraction_thrust,
}

# Default param grids (coarse) — first pass
DEFAULT_PARAMS = {
    "H1_donchian_rvol": [
        {"n": 20, "rvol_min": 1.3, "side": 1},
        {"n": 55, "rvol_min": 1.2, "side": 1},
        {"n": 20, "rvol_min": 1.5, "side": -1},
    ],
    "H2_nr7_breakout": [
        {"rvol_min": 1.2, "side": 1},
        {"rvol_min": 1.5, "side": 1},
        {"rvol_min": 1.2, "side": -1},
    ],
    "H3_gap_fade": [
        {"gap_min": 0.008, "rvol_max": 1.0, "side": 1},
        {"gap_min": 0.012, "rvol_max": 0.9, "side": 1},
        {"gap_min": 0.008, "rvol_max": 1.0, "side": -1},
    ],
    "H4_bos_volume": [
        {"rvol_min": 1.4, "side": 1},
        {"rvol_min": 1.8, "side": 1},
        {"rvol_min": 1.4, "side": -1},
    ],
    "H5_inside_bar": [
        {"rvol_min": 1.25, "side": 1},
        {"rvol_min": 1.5, "side": 1},
        {"rvol_min": 1.25, "side": -1},
    ],
    "H6_atr_squeeze": [
        {"n": 20, "squeeze_max": 0.25, "rvol_min": 1.2, "side": 1},
        {"n": 20, "squeeze_max": 0.35, "rvol_min": 1.3, "side": 1},
        {"n": 20, "squeeze_max": 0.25, "rvol_min": 1.2, "side": -1},
    ],
    "H7_pdh_rvol": [
        {"rvol_min": 1.5, "side": 1},
        {"rvol_min": 1.8, "side": 1},
        {"rvol_min": 1.5, "side": -1},
    ],
    "H8_pullback_reclaim": [
        {"rvol_min": 1.1, "side": 1},
        {"rvol_min": 1.3, "side": 1},
        {"rvol_min": 1.1, "side": -1},
    ],
    "H9_climax_reversal": [
        {"rvol_min": 2.0, "range_mult": 1.8, "side": 1},
        {"rvol_min": 2.5, "range_mult": 2.0, "side": 1},
        {"rvol_min": 2.0, "range_mult": 1.8, "side": -1},
    ],
    "H10_vwap_reclaim": [
        {"rvol_min": 1.2, "side": 1},
        {"rvol_min": 1.5, "side": 1},
        {"rvol_min": 1.2, "side": -1},
    ],
    "H12_contraction_thrust": [
        {"rvol_min": 1.4, "side": 1},
        {"rvol_min": 1.6, "side": 1},
        {"rvol_min": 1.4, "side": -1},
    ],
}
