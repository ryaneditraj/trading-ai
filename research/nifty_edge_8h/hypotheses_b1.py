"""
Block-1 Nifty edge hypothesis factory (≥20 NEW distinct ideas).

Each builder returns (entries, exits, side) on a feature-rich daily frame.
No look-ahead: entries use shifted highs/lows; fills = next open in engine.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

SignalBuilder = Callable[[pd.DataFrame, dict], Tuple[pd.Series, pd.Series, int]]


def _ll(df: pd.DataFrame, n: int) -> pd.Series:
    return df["Low"].rolling(n).min().shift(1)


def _hh(df: pd.DataFrame, n: int) -> pd.Series:
    return df["High"].rolling(n).max().shift(1)


# ── B1-01: Classic Donchian on Nifty (index-only baseline) ───────────────────
def b1_01_donchian(df, p):
    en, xn = int(p.get("entry_n", 55)), int(p.get("exit_n", 20))
    e = (df["Close"] > _hh(df, en)) & (df["Close"] > df["ema200"])
    x = df["Close"] < _ll(df, xn)
    return e.fillna(False), x.fillna(False), 1


# ── B1-02: Slow Turtle 100/50 on Nifty ───────────────────────────────────────
def b1_02_turtle_slow(df, p):
    en, xn = int(p.get("entry_n", 100)), int(p.get("exit_n", 50))
    e = (df["Close"] > _hh(df, en)) & (df["Close"] > df["ema200"])
    x = df["Close"] < _ll(df, xn)
    return e.fillna(False), x.fillna(False), 1


# ── B1-03: ADX-gated Donchian (index) ────────────────────────────────────────
def b1_03_adx_donchian(df, p):
    en, xn = int(p.get("entry_n", 70)), int(p.get("exit_n", 25))
    adx_min = float(p.get("adx_min", 18))
    regime = (df["Close"] > df["ema200"]) & (df["adx"] >= adx_min) & df["adx_rising"].fillna(False)
    e = (df["Close"] > _hh(df, en)) & regime
    x = df["Close"] < _ll(df, xn)
    return e.fillna(False), x.fillna(False), 1


# ── B1-04: MA pullback reclaim (EMA20 in EMA50/200 uptrend) ──────────────────
def b1_04_ma_pullback(df, p):
    atr_buf = float(p.get("atr_buf", 0.5))
    up = (df["Close"] > df["ema200"]) & (df["ema20"] > df["ema50"]) & (df["ema50"] > df["ema200"])
    touched = (df["Low"] <= df["ema20"] + atr_buf * df["atr"]) & (df["Low"] >= df["ema20"] - atr_buf * df["atr"])
    near = touched.rolling(5).max().astype(bool)
    was_below = df["Close"].shift(1) < df["ema20"].shift(1)
    e = up & near & was_below & (df["Close"] > df["ema20"])
    x = (df["Close"] < df["ema50"]) | (df["Close"] < _ll(df, 10))
    return e.fillna(False), x.fillna(False), 1


# ── B1-05: ATR expansion breakout after compression ──────────────────────────
def b1_05_atr_expansion(df, p):
    n = int(p.get("n", 20))
    rank_max = float(p.get("rank_max", 0.3))
    squeezed = df["atr_rank"] <= rank_max
    e = squeezed & (df["Close"] > _hh(df, n)) & (df["Close"] > df["ema50"])
    x = df["Close"] < _ll(df, 10)
    return e.fillna(False), x.fillna(False), 1


# ── B1-06: NR7 → next-day thrust (price-only, no RVOL on index) ──────────────
def b1_06_nr7_thrust(df, p):
    nr7 = df["range"] == df["range"].rolling(7).min()
    was = nr7.shift(1).fillna(False)
    e = was & (df["Close"] > df["High"].shift(1)) & (df["Close"] > df["ema50"])
    x = (df["Close"] < df["ema20"]) | (df["Close"] < df["Low"].shift(1))
    return e.fillna(False), x.fillna(False), 1


# ── B1-07: RSI extremes mean-reversion (long RSI≤30 in bull) ─────────────────
def b1_07_rsi_mr(df, p):
    lo = float(p.get("rsi_lo", 30))
    hi = float(p.get("rsi_exit", 55))
    bull = df["Close"] > df["ema200"]
    e = bull & (df["rsi14"] <= lo)
    x = (df["rsi14"] >= hi) | (df["Close"] < df["ema50"])
    return e.fillna(False), x.fillna(False), 1


# ── B1-08: Return z-score fade (2σ down day in uptrend) ───────────────────────
def b1_08_zscore_mr(df, p):
    z = float(p.get("z", -2.0))
    e = (df["Close"] > df["ema200"]) & (df["ret_z20"] <= z)
    # Exit when recovered above prior close or EMA20, or structure stop
    x = (df["Close"] >= df["prior_close"]) | (df["Close"] > df["ema20"]) | (df["Close"] < _ll(df, 5))
    return e.fillna(False), x.fillna(False), 1


# ── B1-09: Gap continuation (gap-up + close > open in bull) ──────────────────
def b1_09_gap_cont(df, p):
    gmin = float(p.get("gap_min", 0.005))
    e = (df["gap"] >= gmin) & (df["Close"] > df["Open"]) & (df["Close"] > df["ema50"])
    x = (df["Close"] < df["ema20"]) | (df["Close"] < _ll(df, 5))
    return e.fillna(False), x.fillna(False), 1


# ── B1-10: Gap fade (gap-down reclaim in bull) ───────────────────────────────
def b1_10_gap_fade(df, p):
    gmin = float(p.get("gap_min", 0.008))
    e = (df["gap"] <= -gmin) & (df["Close"] > df["Open"]) & (df["Close"] > df["ema200"])
    x = (df["Close"] >= df["prior_close"]) | (df["Close"] > df["ema20"])
    return e.fillna(False), x.fillna(False), 1


# ── B1-11: Day-of-week seasonality (Mon long / Fri exit) ─────────────────────
def b1_11_dow_long(df, p):
    # Enter Mon close if bull; exit Fri or stop
    dow = df.index.dayofweek
    bull = df["Close"] > df["ema50"]
    e = (dow == 0) & bull  # Monday
    x = (dow == 4) | (df["Close"] < _ll(df, 3))  # Friday or 3d low
    return pd.Series(e, index=df.index).fillna(False), pd.Series(x, index=df.index).fillna(False), 1


# ── B1-12: Month-turn (last 2 / first 3 trading days) ────────────────────────
def b1_12_month_turn(df, p):
    # Approximate: day-of-month <= 3 or >= 28
    dom = df.index.day
    bull = df["Close"] > df["ema200"]
    e = bull & ((dom <= 3) | (dom >= 28))
    # Hold ~5 bars via exit when leaving window and after 5d high failure
    x = (dom > 5) & (dom < 25) & (df["Close"] < df["ema20"])
    return e.fillna(False), x.fillna(False), 1


# ── B1-13: Dual MA cross + vol filter (ATR rising) ───────────────────────────
def b1_13_ma_cross_vol(df, p):
    fast, slow = int(p.get("fast", 20)), int(p.get("slow", 50))
    f = df["Close"].ewm(span=fast, adjust=False).mean()
    s = df["Close"].ewm(span=slow, adjust=False).mean()
    cross = (f > s) & (f.shift(1) <= s.shift(1))
    vol_ok = df["atr"] > df["atr"].rolling(50).mean()
    e = cross & vol_ok & (df["Close"] > df["ema200"])
    x = (f < s) | (df["Close"] < _ll(df, 15))
    return e.fillna(False), x.fillna(False), 1


# ── B1-14: Bollinger walk (close above upper band, ride until mid) ───────────
def b1_14_bb_walk(df, p):
    n = int(p.get("n", 20))
    k = float(p.get("k", 2.0))
    mid = df["Close"].rolling(n).mean()
    sd = df["Close"].rolling(n).std()
    upper = mid + k * sd
    e = (df["Close"] > upper) & (df["Close"] > df["ema200"]) & (df["Close"].shift(1) <= upper.shift(1))
    x = df["Close"] < mid
    return e.fillna(False), x.fillna(False), 1


# ── B1-15: Keltner breakout ──────────────────────────────────────────────────
def b1_15_keltner(df, p):
    n = int(p.get("n", 20))
    mult = float(p.get("mult", 1.5))
    mid = df["Close"].ewm(span=n, adjust=False).mean()
    upper = mid + mult * df["atr"]
    lower = mid - mult * df["atr"]
    e = (df["Close"] > upper) & (df["Close"] > df["ema200"])
    x = df["Close"] < mid
    return e.fillna(False), x.fillna(False), 1


# ── B1-16: Supertrend-like ATR trail (long-only flip) ────────────────────────
def b1_16_supertrend(df, p):
    mult = float(p.get("mult", 3.0))
    atr = df["atr"]
    hl2 = (df["High"] + df["Low"]) / 2.0
    basic_ub = hl2 + mult * atr
    basic_lb = hl2 - mult * atr
    # Simplified: enter when close crosses above trailing lower band that was below
    # Use rolling final band proxy
    final_lb = basic_lb.copy()
    for i in range(1, len(df)):
        prev = final_lb.iloc[i - 1]
        cur = basic_lb.iloc[i]
        if np.isfinite(prev) and np.isfinite(cur):
            if df["Close"].iloc[i - 1] > prev:
                final_lb.iloc[i] = max(cur, prev)
            else:
                final_lb.iloc[i] = cur
    e = (df["Close"] > final_lb) & (df["Close"].shift(1) <= final_lb.shift(1)) & (df["Close"] > df["ema50"])
    x = df["Close"] < final_lb
    return e.fillna(False), x.fillna(False), 1


# ── B1-17: Failed breakout fade (break HH then close back inside) ────────────
def b1_17_failed_bo_fade(df, p):
    n = int(p.get("n", 20))
    hh = _hh(df, n)
    broke = df["High"] > hh
    failed = broke & (df["Close"] < hh) & (df["Close"] < df["Open"])
    # Fade = short would be natural; long fade of failed breakdown instead
    ll = _ll(df, n)
    broke_dn = df["Low"] < ll
    fail_bd = broke_dn & (df["Close"] > ll) & (df["Close"] > df["Open"]) & (df["Close"] > df["ema200"])
    e = fail_bd
    x = (df["Close"] > _hh(df, 10)) | (df["Close"] < _ll(df, 5))
    return e.fillna(False), x.fillna(False), 1


# ── B1-18: Time-stop + structure hybrid (Donchian 40/15, max_hold via exit) ──
def b1_18_time_structure(df, p):
    en, xn = int(p.get("entry_n", 40)), int(p.get("exit_n", 15))
    e = (df["Close"] > _hh(df, en)) & (df["Close"] > df["ema100"])
    # Structure exit OR close below EMA20 (proxy for time+structure hybrid)
    x = (df["Close"] < _ll(df, xn)) | (df["Close"] < df["ema20"])
    return e.fillna(False), x.fillna(False), 1


# ── B1-19: Volatility breakout — close range > N×ATR with direction ─────────
def b1_19_vol_bo(df, p):
    mult = float(p.get("mult", 1.5))
    wide = df["range"] > mult * df["atr"]
    e = wide & (df["Close"] > df["Open"]) & (df["Close"] > df["ema50"]) & (df["Close"] > _hh(df, 10))
    x = (df["Close"] < df["ema20"]) | (df["Close"] < _ll(df, 5))
    return e.fillna(False), x.fillna(False), 1


# ── B1-20: Consecutive down-days reversal in bull ───────────────────────────
def b1_20_downstreak_rev(df, p):
    n = int(p.get("n", 3))
    downs = (df["Close"] < df["Close"].shift(1)).astype(int)
    streak = downs.rolling(n).sum() == n
    e = streak & (df["Close"] > df["ema200"]) & (df["Close"] > df["Open"])
    x = (df["Close"] > df["ema20"]) | (df["Close"] < _ll(df, 5))
    return e.fillna(False), x.fillna(False), 1


# ── B1-21: High-close location breakout (close in top decile of range) ───────
def b1_21_close_loc(df, p):
    loc = (df["Close"] - df["Low"]) / (df["range"].replace(0, np.nan))
    e = (loc >= 0.9) & (df["Close"] > _hh(df, 20)) & (df["Close"] > df["ema200"])
    x = (df["Close"] < df["ema20"]) | (df["Close"] < _ll(df, 10))
    return e.fillna(False), x.fillna(False), 1


# ── B1-22: ADX rising + DI+ > DI− momentum ───────────────────────────────────
def b1_22_di_momentum(df, p):
    adx_min = float(p.get("adx_min", 20))
    e = (
        (df["adx"] >= adx_min)
        & df["adx_rising"].fillna(False)
        & (df["plus_di"] > df["minus_di"])
        & (df["Close"] > df["ema50"])
        & (df["Close"] > _hh(df, 20))
    )
    x = (df["plus_di"] < df["minus_di"]) | (df["Close"] < _ll(df, 10))
    return e.fillna(False), x.fillna(False), 1


# ── B1-23: BankNifty relative strength (Nifty long when Nifty>Bank RS) ───────
# Needs columns nifty_rs / bank attached by runner
def b1_23_rs_nifty(df, p):
    if "rs_nifty_bank" not in df.columns:
        z = pd.Series(False, index=df.index)
        return z, z, 1
    e = (
        (df["rs_nifty_bank"] > 0)
        & (df["rs_nifty_bank"] > df["rs_nifty_bank"].shift(5))
        & (df["Close"] > df["ema50"])
        & (df["Close"] > _hh(df, 20))
    )
    x = (df["rs_nifty_bank"] < 0) | (df["Close"] < _ll(df, 10))
    return e.fillna(False), x.fillna(False), 1


# ── B1-24: Breadth thrust proxy (need breadth col) ───────────────────────────
def b1_24_breadth_thrust(df, p):
    thr = float(p.get("breadth_min", 0.65))
    if "breadth50" not in df.columns:
        z = pd.Series(False, index=df.index)
        return z, z, 1
    e = (df["breadth50"] >= thr) & (df["breadth50"].shift(1) < thr) & (df["Close"] > df["ema50"])
    x = (df["breadth50"] < 0.45) | (df["Close"] < _ll(df, 15))
    return e.fillna(False), x.fillna(False), 1


# ── B1-25: Opening range proxy — gap + first-day range expansion ─────────────
def b1_25_orb_daily(df, p):
    # Daily proxy of ORB: open in top half of prior range + close > prior high
    prior_mid = (df["prior_high"] + df["prior_low"]) / 2.0
    e = (df["Open"] > prior_mid) & (df["Close"] > df["prior_high"]) & (df["Close"] > df["ema50"])
    x = (df["Close"] < df["ema20"]) | (df["Close"] < _ll(df, 5))
    return e.fillna(False), x.fillna(False), 1


# ── B1-26: EMA ribbon stack ignition ─────────────────────────────────────────
def b1_26_ema_ribbon(df, p):
    e8 = df["Close"].ewm(span=8, adjust=False).mean()
    e21 = df["Close"].ewm(span=21, adjust=False).mean()
    e55 = df["Close"].ewm(span=55, adjust=False).mean()
    stack = (e8 > e21) & (e21 > e55) & (e55 > df["ema200"])
    ignite = stack & (~stack.shift(1).fillna(False))
    e = ignite
    x = (e8 < e21) | (df["Close"] < _ll(df, 15))
    return e.fillna(False), x.fillna(False), 1


HYPOTHESES: Dict[str, dict] = {
    "B1-01_donchian_55_20": {"fn": b1_01_donchian, "params": {"entry_n": 55, "exit_n": 20}, "family": "donchian", "max_hold": 80},
    "B1-02_turtle_100_50": {"fn": b1_02_turtle_slow, "params": {"entry_n": 100, "exit_n": 50}, "family": "donchian", "max_hold": 120},
    "B1-03_adx_donchian_70_25": {"fn": b1_03_adx_donchian, "params": {"entry_n": 70, "exit_n": 25, "adx_min": 18}, "family": "trend_adx", "max_hold": 100},
    "B1-04_ma_pullback": {"fn": b1_04_ma_pullback, "params": {"atr_buf": 0.5}, "family": "ma_pullback", "max_hold": 40},
    "B1-05_atr_expansion": {"fn": b1_05_atr_expansion, "params": {"n": 20, "rank_max": 0.3}, "family": "vol_bo", "max_hold": 40},
    "B1-06_nr7_thrust": {"fn": b1_06_nr7_thrust, "params": {}, "family": "vol_bo", "max_hold": 15},
    "B1-07_rsi_mr": {"fn": b1_07_rsi_mr, "params": {"rsi_lo": 30, "rsi_exit": 55}, "family": "mean_rev", "max_hold": 20},
    "B1-08_zscore_mr": {"fn": b1_08_zscore_mr, "params": {"z": -2.0}, "family": "mean_rev", "max_hold": 10},
    "B1-09_gap_cont": {"fn": b1_09_gap_cont, "params": {"gap_min": 0.005}, "family": "gap", "max_hold": 10},
    "B1-10_gap_fade": {"fn": b1_10_gap_fade, "params": {"gap_min": 0.008}, "family": "gap", "max_hold": 10},
    "B1-11_dow_monday": {"fn": b1_11_dow_long, "params": {}, "family": "calendar", "max_hold": 5},
    "B1-12_month_turn": {"fn": b1_12_month_turn, "params": {}, "family": "calendar", "max_hold": 8},
    "B1-13_ma_cross_vol": {"fn": b1_13_ma_cross_vol, "params": {"fast": 20, "slow": 50}, "family": "ma_cross", "max_hold": 60},
    "B1-14_bb_walk": {"fn": b1_14_bb_walk, "params": {"n": 20, "k": 2.0}, "family": "bollinger", "max_hold": 40},
    "B1-15_keltner": {"fn": b1_15_keltner, "params": {"n": 20, "mult": 1.5}, "family": "keltner", "max_hold": 40},
    "B1-16_supertrend": {"fn": b1_16_supertrend, "params": {"mult": 3.0}, "family": "atr_trail", "max_hold": 80},
    "B1-17_failed_bd_fade": {"fn": b1_17_failed_bo_fade, "params": {"n": 20}, "family": "failed_bo", "max_hold": 15},
    "B1-18_time_structure": {"fn": b1_18_time_structure, "params": {"entry_n": 40, "exit_n": 15}, "family": "hybrid", "max_hold": 25},
    "B1-19_vol_bo": {"fn": b1_19_vol_bo, "params": {"mult": 1.5}, "family": "vol_bo", "max_hold": 15},
    "B1-20_downstreak_rev": {"fn": b1_20_downstreak_rev, "params": {"n": 3}, "family": "mean_rev", "max_hold": 10},
    "B1-21_close_loc": {"fn": b1_21_close_loc, "params": {}, "family": "structure", "max_hold": 30},
    "B1-22_di_momentum": {"fn": b1_22_di_momentum, "params": {"adx_min": 20}, "family": "trend_adx", "max_hold": 40},
    "B1-23_rs_nifty_bank": {"fn": b1_23_rs_nifty, "params": {}, "family": "pairs_rs", "max_hold": 40},
    "B1-24_breadth_thrust": {"fn": b1_24_breadth_thrust, "params": {"breadth_min": 0.65}, "family": "breadth", "max_hold": 40},
    "B1-25_orb_daily": {"fn": b1_25_orb_daily, "params": {}, "family": "opening_range", "max_hold": 10},
    "B1-26_ema_ribbon": {"fn": b1_26_ema_ribbon, "params": {}, "family": "ma_cross", "max_hold": 60},
}


def list_hypotheses() -> List[str]:
    return list(HYPOTHESES.keys())
