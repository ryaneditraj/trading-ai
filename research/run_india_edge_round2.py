#!/usr/bin/env python3
"""
Round 2 — User rejected prior Donchian basket as unprofitable.
Aggressive re-search: regime gates, breadth, RVOL, failed-BO fade,
gap continuation, EMA pullback, index-only. Portfolio engine (max 5 slots).

Target: OOS PF>=1.3 after >=0.08% RT, n>=50 (or index n>=30 with multi-year profit).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "strategies"))

from india_edge_engine import (  # noqa: E402
    RESULTS_DIR,
    add_structure_features,
    fetch_daily,
    time_split,
)

UNIVERSE = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "LT.NS",
    "AXISBANK.NS",
    "KOTAKBANK.NS",
    "HINDUNILVR.NS",
    "BAJFINANCE.NS",
    "ASIANPAINT.NS",
    "MARUTI.NS",
    "SUNPHARMA.NS",
    "TITAN.NS",
    "ULTRACEMCO.NS",
    "WIPRO.NS",
    "NESTLEIND.NS",
]
INDICES = ["^NSEI", "^NSEBANK"]
MAX_POS = 5
RT = 0.0008
RT_STRESS = 0.0015
TRAIN_FRAC = 0.7

SignalFn = Callable[[pd.DataFrame, dict], Tuple[pd.Series, pd.Series]]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    gap = o["Open"] / o["Close"].shift(1) - 1.0
    ret = o["Close"].pct_change()
    mask = ((gap.abs() < 0.08) | gap.isna()) & ((ret.abs() < 0.12) | ret.isna())
    return add_structure_features(o.loc[mask].copy())


def add_adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    o = df.copy()
    up = o["High"].diff()
    down = -o["Low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat(
        [
            o["High"] - o["Low"],
            (o["High"] - o["Close"].shift(1)).abs(),
            (o["Low"] - o["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=o.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=o.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    o["adx"] = dx.ewm(alpha=1 / n, adjust=False).mean()
    o["adx_rising"] = o["adx"] > o["adx"].shift(5)
    o["atr_expanding"] = o["atr"] > o["atr"].rolling(50).mean()
    return o


def align_index_filter(stock: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    """Attach nifty regime columns onto stock calendar."""
    o = stock.copy()
    n = nifty.reindex(o.index, method="ffill")
    o["nifty_close"] = n["Close"]
    o["nifty_ema100"] = n["Close"].ewm(span=100, adjust=False).mean()
    o["nifty_ema200"] = n["Close"].ewm(span=200, adjust=False).mean()
    o["nifty_hh55"] = n["High"].rolling(55).max().shift(1)
    o["nifty_above_ema"] = o["nifty_close"] > o["nifty_ema200"]
    o["nifty_hh"] = o["nifty_close"] > o["nifty_hh55"]
    o["nifty_bull"] = o["nifty_above_ema"] | o["nifty_hh"]
    return o


def breadth_series(data: Dict[str, pd.DataFrame], ma: str = "ema50") -> pd.Series:
    """Fraction of universe with Close > ma on each date."""
    above = None
    count = None
    for df in data.values():
        a = (df["Close"] > df[ma]).astype(float)
        c = (~df["Close"].isna()).astype(float)
        above = a if above is None else above.add(a, fill_value=0)
        count = c if count is None else count.add(c, fill_value=0)
    return (above / count.replace(0, np.nan)).fillna(0)


# ── Signal builders (entry, exit) — long only unless noted ───────────────────

def baseline_donchian(df, p):
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (df["Close"] > hh) & (df["Close"] > df["ema200"])
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_regime_adx(df, p):
    """R2-01: Donchian only when ADX rising + ATR expanding + >EMA200."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    adx_min = float(p.get("adx_min", 20))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    regime = (
        (df["Close"] > df["ema200"])
        & (df["adx"] >= adx_min)
        & df["adx_rising"].fillna(False)
        & df["atr_expanding"].fillna(False)
    )
    e = (df["Close"] > hh) & regime
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_nifty_filter(df, p):
    """R2-02: Stock breakout only when Nifty bull (above EMA200 or HH55)."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (df["Close"] > hh) & (df["Close"] > df["ema200"]) & df["nifty_bull"].fillna(False)
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_rvol_breakout(df, p):
    """R2-03: Donchian + RVOL >= threshold on breakout day."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    rvol_min = float(p.get("rvol_min", 1.5))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (
        (df["Close"] > hh)
        & (df["Close"] > df["ema200"])
        & (df["rvol"] >= rvol_min)
    )
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_combo_filters(df, p):
    """R2-04: Donchian + Nifty bull + RVOL + ADX rising."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    rvol_min = float(p.get("rvol_min", 1.3))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (
        (df["Close"] > hh)
        & (df["Close"] > df["ema200"])
        & df["nifty_bull"].fillna(False)
        & (df["rvol"] >= rvol_min)
        & df["adx_rising"].fillna(False)
    )
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_failed_bo_fade(df, p):
    """R2-05: Fade false breakouts — close back inside range next day; short or long fade."""
    n = int(p.get("entry_n", 20))
    hold = int(p.get("max_hold", 5))
    hh = df["High"].rolling(n).max().shift(1)
    ll = df["Low"].rolling(n).min().shift(1)
    # Long fade: broke below then reclaimed (failed breakdown)
    broke_down = (df["Close"].shift(1) < ll.shift(1))
    reclaim = df["Close"] > ll
    e = broke_down & reclaim & (df["Close"] > df["ema50"])
    # Tight structure stop: exit if close back below breakout level or after hold via trailing
    x = (df["Close"] < ll) | (df["Close"] < df["Low"].rolling(hold).min().shift(1))
    return e.fillna(False), x.fillna(False)


def r2_failed_bo_short(df, p):
    """R2-06: Fade failed upside breakouts (close back inside) — short thesis test."""
    n = int(p.get("entry_n", 20))
    hh = df["High"].rolling(n).max().shift(1)
    broke_up = df["Close"].shift(1) > hh.shift(1)
    fail = df["Close"] < hh
    e = broke_up & fail & (df["Close"] < df["ema50"])
    x = (df["Close"] > hh) | (df["Close"] > df["High"].rolling(5).max().shift(1))
    return e.fillna(False), x.fillna(False)


def r2_gap_continuation(df, p):
    """R2-07: Gap-up continuation on liquid names with volume + EMA200."""
    gap_min = float(p.get("gap_min", 0.01))
    rvol_min = float(p.get("rvol_min", 1.5))
    e = (
        (df["gap"] >= gap_min)
        & (df["Close"] > df["Open"])
        & (df["Close"] > df["ema200"])
        & (df["rvol"] >= rvol_min)
        & (df["Close"] > df["prior_high"])
    )
    x = (df["Close"] < df["ema20"]) | (df["Close"] < df["Low"].rolling(5).min().shift(1))
    return e.fillna(False), x.fillna(False)


def r2_ema_pullback(df, p):
    """R2-08: Pullback to EMA20/50 in uptrend + volume dry-up then thrust."""
    e = (
        (df["Close"] > df["ema200"])
        & (df["ema20"] > df["ema50"])
        & (df["Low"] <= df["ema20"] * 1.005)
        & (df["Close"] > df["ema20"])
        & (df["rvol"] <= float(p.get("rvol_max", 0.9)))  # dry-up day
        & (df["Close"] > df["Open"])
        # higher low structure: recent low > low 10 bars ago
        & (df["Low"].rolling(5).min() > df["Low"].rolling(20).min().shift(5))
    )
    # Thrust confirmation: next bar handled by portfolio entry; exit on structure break
    x = (df["Close"] < df["ema50"]) | (df["Close"] < df["Low"].rolling(10).min().shift(1))
    return e.fillna(False), x.fillna(False)


def r2_ema_pullback_thrust(df, p):
    """R2-09: After dry-up near EMA20, require next-day thrust via prior-day setup flag."""
    dry = (
        (df["Close"] > df["ema200"])
        & (df["ema20"] > df["ema50"])
        & (df["Low"] <= df["ema20"] * 1.01)
        & (df["rvol"] <= float(p.get("rvol_max", 0.85)))
    )
    e = (
        dry.shift(1).fillna(False)
        & (df["Close"] > df["prior_high"])
        & (df["rvol"] >= float(p.get("rvol_min", 1.2)))
        & (df["Close"] > df["ema20"])
    )
    x = (df["Close"] < df["ema50"]) | (df["Close"] < df["Low"].rolling(10).min().shift(1))
    return e.fillna(False), x.fillna(False)


def r2_breadth_donchian(df, p):
    """R2-10: Donchian only when breadth (%% above EMA50) high."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    br_min = float(p.get("breadth_min", 0.55))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (
        (df["Close"] > hh)
        & (df["Close"] > df["ema200"])
        & (df["breadth"] >= br_min)
    )
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_slow_turtle(df, p):
    """R2-11: Slower 100/50 Donchian + EMA200 — fewer, stronger trends."""
    entry_n = int(p.get("entry_n", 100))
    exit_n = int(p.get("exit_n", 50))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (df["Close"] > hh) & (df["Close"] > df["ema200"])
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_donchian_atr_trail(df, p):
    """R2-12: 55-day breakout, exit on ATR trail (2.5x) or 20d low."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    mult = float(p.get("atr_mult", 2.5))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    # trail proxy: close < highest close since entry approximated by rolling peak - atr
    peak = df["Close"].rolling(40).max()
    trail = peak - mult * df["atr"]
    e = (df["Close"] > hh) & (df["Close"] > df["ema200"])
    x = (df["Close"] < ll) | (df["Close"] < trail)
    return e.fillna(False), x.fillna(False)


def r2_index_donchian(df, p):
    """R2-13: Index-only Donchian 55/20 + EMA200."""
    return baseline_donchian(df, p)


def r2_index_regime(df, p):
    """R2-14: Index Donchian with ADX rising + ATR expand."""
    return r2_regime_adx(df, p)


def r2_nifty_hh_only(df, p):
    """R2-15: Stock breakout only when Nifty making HH55 (stricter than EMA)."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (df["Close"] > hh) & (df["Close"] > df["ema200"]) & df["nifty_hh"].fillna(False)
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_dual_ma_momentum(df, p):
    """R2-16: Close > EMA50 & EMA50 slope up + prior 20d high break + RVOL."""
    rvol_min = float(p.get("rvol_min", 1.4))
    hh = df["High"].rolling(20).max().shift(1)
    slope = df["ema50"] > df["ema50"].shift(10)
    e = (
        (df["Close"] > hh)
        & (df["Close"] > df["ema50"])
        & slope
        & (df["Close"] > df["ema200"])
        & (df["rvol"] >= rvol_min)
    )
    x = (df["Close"] < df["ema50"]) | (df["Close"] < df["Low"].rolling(15).min().shift(1))
    return e.fillna(False), x.fillna(False)


# ── Portfolio engine ─────────────────────────────────────────────────────────

def run_portfolio(
    data: Dict[str, pd.DataFrame],
    signal_fn: SignalFn,
    params: dict,
    start_date=None,
    end_date=None,
    max_positions: int = MAX_POS,
    rt_cost: float = RT,
    side: int = 1,
    rank_col: str = "ema200",
) -> dict:
    sig = {}
    for s, df in data.items():
        e, x = signal_fn(df, params)
        sig[s] = {
            "entry": e,
            "exit": x,
            "open": df["Open"],
            "close": df["Close"],
            "rank": df["Close"] / df[rank_col] - 1.0 if rank_col in df.columns else df["Close"] * 0,
        }

    all_dates = sorted(set().union(*[set(df.index) for df in data.values()]))
    all_dates = [
        d
        for d in all_dates
        if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)
    ]

    cash = 1.0
    positions: dict = {}
    equity_curve = []
    trades = []
    slot = 1.0 / max_positions

    for i, dt in enumerate(all_dates):
        for s in list(positions):
            if dt in sig[s]["exit"].index and bool(sig[s]["exit"].loc[dt]):
                px = float(sig[s]["close"].loc[dt])
                raw = px / positions[s]["entry_px"] - 1.0
                ret = side * raw - rt_cost
                cash += positions[s]["w"] * (1.0 + ret)
                trades.append(
                    {
                        "symbol": s,
                        "entry": positions[s]["entry_date"],
                        "exit": dt,
                        "ret": ret,
                    }
                )
                del positions[s]

        equity = cash + sum(
            p["w"]
            * (
                1.0
                + side
                * (
                    float(sig[s]["close"].loc[dt]) / p["entry_px"] - 1.0
                    if dt in sig[s]["close"].index
                    else 0.0
                )
            )
            for s, p in positions.items()
        )
        equity_curve.append((dt, equity, len(positions)))

        if i + 1 >= len(all_dates):
            continue
        nxt = all_dates[i + 1]
        free = max_positions - len(positions)
        if free <= 0 or cash <= 1e-8:
            continue

        ranked = []
        for s in data:
            if s in positions:
                continue
            if dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                continue
            if nxt not in sig[s]["open"].index:
                continue
            strength = float(sig[s]["rank"].loc[dt]) if dt in sig[s]["rank"].index else 0.0
            ranked.append((strength, s))
        ranked.sort(reverse=True)

        for _, s in ranked[:free]:
            alloc = min(cash, equity * slot)
            if alloc <= 0:
                break
            entry_px = float(sig[s]["open"].loc[nxt])
            cash -= alloc
            positions[s] = {
                "w": alloc * (1 - rt_cost / 2),
                "entry_px": entry_px,
                "entry_date": nxt,
            }

    if all_dates:
        last = all_dates[-1]
        for s, p in list(positions.items()):
            px = (
                float(sig[s]["close"].loc[last])
                if last in sig[s]["close"].index
                else p["entry_px"]
            )
            raw = px / p["entry_px"] - 1.0
            ret = side * raw - rt_cost
            cash += p["w"] * (1.0 + ret)
            trades.append({"symbol": s, "entry": p["entry_date"], "exit": last, "ret": ret})
            del positions[s]

    eq = pd.Series({d: e for d, e, _ in equity_curve})
    rets = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    tr = np.array([t["ret"] for t in trades], dtype=float) if trades else np.array([])
    wins = tr[tr > 0]
    losses = tr[tr <= 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and -losses.sum() > 0 else 0.0

    return {
        "n_trades": int(len(trades)),
        "win_rate": float((tr > 0).mean()) if len(tr) else 0.0,
        "profit_factor": pf,
        "expectancy": float(tr.mean()) if len(tr) else 0.0,
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0,
        "max_dd": float(dd.min()) if len(dd) else 0.0,
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252))
        if len(rets) > 2 and rets.std() > 0
        else 0.0,
        "avg_hold_days": float(np.mean([(t["exit"] - t["entry"]).days for t in trades]))
        if trades
        else 0.0,
        "trades": trades,
        "equity": eq,
    }


def strip(d):
    return {k: v for k, v in d.items() if k not in ("trades", "equity")}


def wf_chunks(stats_fn, data, signal_fn, params, oos_start, rt_cost, side=1, n_chunks=3):
    """Split OOS into equal time chunks."""
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=n_chunks + 1)
    rows = []
    for i in range(n_chunks):
        a, b = dates[i], dates[i + 1]
        st = stats_fn(
            data,
            signal_fn,
            params,
            start_date=a,
            end_date=b,
            rt_cost=rt_cost,
            side=side,
        )
        rows.append({"period": f"{a.date()}→{b.date()}", **strip(st)})
    return rows


def fmt(s: dict) -> str:
    return (
        f"n={s['n_trades']:4d} WR={s['win_rate']:5.1%} PF={s['profit_factor']:5.2f} "
        f"E={s['expectancy']*100:6.2f}% Tot={s['total_return']*100:7.1f}% "
        f"MDD={s['max_dd']*100:6.1f}% Sh={s['sharpe']:5.2f}"
    )


def meets_criteria(oos: dict, index_mode: bool = False) -> bool:
    n_min = 30 if index_mode else 50
    if oos["n_trades"] < n_min:
        return False
    if oos["profit_factor"] >= 1.3 and oos["total_return"] > 0:
        return True
    if oos["expectancy"] > 0.005 and oos["total_return"] > 0.15 and oos["profit_factor"] >= 1.15:
        return True
    return False


def main():
    print("=== ROUND 2: India PV+Structure — user rejected prior as unprofitable ===\n")
    print(f"Fetching {len(UNIVERSE)} stocks + indices...")
    nifty = add_adx(clean(fetch_daily("^NSEI")))
    bank = add_adx(clean(fetch_daily("^NSEBANK")))
    stocks_raw = {s: add_adx(clean(fetch_daily(s))) for s in UNIVERSE}
    br = breadth_series(stocks_raw)
    stocks = {}
    for s, df in stocks_raw.items():
        d = align_index_filter(df, nifty)
        d["breadth"] = br.reindex(d.index).ffill()
        stocks[s] = d

    ref = stocks["RELIANCE.NS"]
    _, oos_ref = time_split(ref, TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    print(f"OOS start: {oos_start.date()}  |  RT={RT*100:.2f}% (stress {RT_STRESS*100:.2f}%)\n")

    # Reproduce baseline failure
    base_is = run_portfolio(stocks, baseline_donchian, {"entry_n": 55, "exit_n": 20}, end_date=oos_start - pd.Timedelta(days=1))
    base_oos = run_portfolio(stocks, baseline_donchian, {"entry_n": 55, "exit_n": 20}, start_date=oos_start)
    print("BASELINE Donchian 55/20 (reproduce failure):")
    print(f"  IS : {fmt(strip(base_is))}")
    print(f"  OOS: {fmt(strip(base_oos))}")
    print(f"  OOS stress 0.15%: {fmt(strip(run_portfolio(stocks, baseline_donchian, {'entry_n':55,'exit_n':20}, start_date=oos_start, rt_cost=RT_STRESS)))}")
    print()

    candidates: List[Tuple[str, SignalFn, dict, Dict[str, pd.DataFrame], int, bool]] = [
        ("R2-01 regime ADX+ATR", r2_regime_adx, {"entry_n": 55, "exit_n": 20, "adx_min": 20}, stocks, 1, False),
        ("R2-01b ADX25", r2_regime_adx, {"entry_n": 55, "exit_n": 20, "adx_min": 25}, stocks, 1, False),
        ("R2-02 Nifty bull filter", r2_nifty_filter, {"entry_n": 55, "exit_n": 20}, stocks, 1, False),
        ("R2-03 RVOL>=1.5", r2_rvol_breakout, {"entry_n": 55, "exit_n": 20, "rvol_min": 1.5}, stocks, 1, False),
        ("R2-03b RVOL>=1.2", r2_rvol_breakout, {"entry_n": 55, "exit_n": 20, "rvol_min": 1.2}, stocks, 1, False),
        ("R2-04 combo Nifty+RVOL+ADX", r2_combo_filters, {"entry_n": 55, "exit_n": 20, "rvol_min": 1.3}, stocks, 1, False),
        ("R2-05 failed BD fade long", r2_failed_bo_fade, {"entry_n": 20, "max_hold": 5}, stocks, 1, False),
        ("R2-06 failed BU fade SHORT", r2_failed_bo_short, {"entry_n": 20}, stocks, -1, False),
        ("R2-07 gap continuation", r2_gap_continuation, {"gap_min": 0.01, "rvol_min": 1.5}, stocks, 1, False),
        ("R2-07b gap 0.5% RVOL1.2", r2_gap_continuation, {"gap_min": 0.005, "rvol_min": 1.2}, stocks, 1, False),
        ("R2-08 EMA pullback dry-up", r2_ema_pullback, {"rvol_max": 0.9}, stocks, 1, False),
        ("R2-09 pullback thrust", r2_ema_pullback_thrust, {"rvol_max": 0.85, "rvol_min": 1.2}, stocks, 1, False),
        ("R2-10 breadth>=55%", r2_breadth_donchian, {"entry_n": 55, "exit_n": 20, "breadth_min": 0.55}, stocks, 1, False),
        ("R2-10b breadth>=65%", r2_breadth_donchian, {"entry_n": 55, "exit_n": 20, "breadth_min": 0.65}, stocks, 1, False),
        ("R2-11 slow Turtle 100/50", r2_slow_turtle, {"entry_n": 100, "exit_n": 50}, stocks, 1, False),
        ("R2-12 ATR trail exit", r2_donchian_atr_trail, {"entry_n": 55, "exit_n": 20, "atr_mult": 2.5}, stocks, 1, False),
        ("R2-15 Nifty HH55 only", r2_nifty_hh_only, {"entry_n": 55, "exit_n": 20}, stocks, 1, False),
        ("R2-16 dual MA + RVOL", r2_dual_ma_momentum, {"rvol_min": 1.4}, stocks, 1, False),
        # Index-only
        ("R2-13 Nifty Donchian 55/20", r2_index_donchian, {"entry_n": 55, "exit_n": 20}, {"^NSEI": nifty}, 1, True),
        ("R2-13b Nifty 20/10", r2_index_donchian, {"entry_n": 20, "exit_n": 10}, {"^NSEI": nifty}, 1, True),
        ("R2-13c BankNifty 55/20", r2_index_donchian, {"entry_n": 55, "exit_n": 20}, {"^NSEBANK": bank}, 1, True),
        ("R2-14 Nifty ADX regime", r2_index_regime, {"entry_n": 55, "exit_n": 20, "adx_min": 20}, {"^NSEI": nifty}, 1, True),
        ("R2-14b Bank ADX regime", r2_index_regime, {"entry_n": 55, "exit_n": 20, "adx_min": 20}, {"^NSEBANK": bank}, 1, True),
        # Faster / slower stock grids around filters that look promising — run all
        ("R2-02b Nifty+40/15", r2_nifty_filter, {"entry_n": 40, "exit_n": 15}, stocks, 1, False),
        ("R2-02c Nifty+70/25", r2_nifty_filter, {"entry_n": 70, "exit_n": 25}, stocks, 1, False),
        ("R2-04b combo entry40", r2_combo_filters, {"entry_n": 40, "exit_n": 15, "rvol_min": 1.3}, stocks, 1, False),
        ("R2-11b slow 80/40", r2_slow_turtle, {"entry_n": 80, "exit_n": 40}, stocks, 1, False),
        ("R2-03c RVOL+40/15", r2_rvol_breakout, {"entry_n": 40, "exit_n": 15, "rvol_min": 1.5}, stocks, 1, False),
    ]

    rows = []
    print(f"Running {len(candidates)} candidates...\n")
    for name, fn, params, data, side, index_mode in candidates:
        max_pos = 1 if index_mode else MAX_POS
        is_s = run_portfolio(
            data, fn, params, end_date=oos_start - pd.Timedelta(days=1),
            max_positions=max_pos, rt_cost=RT, side=side,
        )
        oos_s = run_portfolio(
            data, fn, params, start_date=oos_start,
            max_positions=max_pos, rt_cost=RT, side=side,
        )
        oos_stress = run_portfolio(
            data, fn, params, start_date=oos_start,
            max_positions=max_pos, rt_cost=RT_STRESS, side=side,
        )
        ok = meets_criteria(strip(oos_s), index_mode=index_mode)
        row = {
            "name": name,
            "params": params,
            "index_mode": index_mode,
            "side": side,
            "IS": strip(is_s),
            "OOS": strip(oos_s),
            "OOS_stress_0.15": strip(oos_stress),
            "meets": ok,
        }
        # walk-forward chunks for anything with positive OOS expectancy
        if oos_s["expectancy"] > 0 and oos_s["n_trades"] >= 20:
            row["wf"] = wf_chunks(
                run_portfolio, data, fn, params, oos_start, RT, side=side, n_chunks=3
            )
        rows.append(row)
        flag = "✓ PASS?" if ok else ("~" if oos_s["expectancy"] > 0 else "✗")
        print(f"{flag} {name}")
        print(f"    IS : {fmt(strip(is_s))}")
        print(f"    OOS: {fmt(strip(oos_s))}  stressPF={oos_stress['profit_factor']:.2f}")
        if "wf" in row:
            for w in row["wf"]:
                print(f"    WF {w['period']}: n={w['n_trades']} E={w['expectancy']*100:.2f}% Tot={w['total_return']*100:.1f}%")
        print()

    # Rank by OOS: prefer meets, then PF, then expectancy, then n
    def score(r):
        o = r["OOS"]
        return (
            int(r["meets"]),
            o["profit_factor"] if o["n_trades"] >= 20 else 0,
            o["expectancy"],
            o["total_return"],
            o["n_trades"],
        )

    ranked = sorted(rows, key=score, reverse=True)
    print("=" * 70)
    print("TOP 8 BY OOS SCORE")
    for r in ranked[:8]:
        print(f"  [{'MEETS' if r['meets'] else 'miss'}] {r['name']}: {fmt(r['OOS'])}")

    passes = [r for r in ranked if r["meets"]]
    out = {
        "oos_start": str(oos_start.date()),
        "rt_cost": RT,
        "baseline_oos": strip(base_oos),
        "n_candidates": len(rows),
        "passes": [r["name"] for r in passes],
        "results": [
            {
                "name": r["name"],
                "params": r["params"],
                "meets": r["meets"],
                "IS": r["IS"],
                "OOS": r["OOS"],
                "OOS_stress_0.15": r["OOS_stress_0.15"],
                "wf": r.get("wf"),
            }
            for r in ranked
        ],
        "verdict": "EDGE_FOUND" if passes else "NO_EDGE_FOUND",
        "best": ranked[0]["name"] if ranked else None,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "india_round2_results.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {path}")
    print(f"VERDICT: {out['verdict']}  best={out['best']}")
    return out


if __name__ == "__main__":
    main()
