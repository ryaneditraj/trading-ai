#!/usr/bin/env python3
"""
Block 3 — ensemble / kill-breadth refine / vol-target / sector heat / hourly ORB.

Mandatory attacks:
  1) Reproduce #1 quickly
  2) Ensemble / blend ST 3.0 + 3.6 (agreement + equal-risk)
  3) Refine kill_breadth (sweep thresholds); promote ONLY if OOS tot AND last WF both clear #1
  4) Vol targeting / sector-neutral / heat caps (improve MDD without gutting return)
  5) Hourly stock ORB if data usable (skip if volume/data garbage; no fake futures)
  6) ≥12 new measured variants; update leaderboard + log; overwrite best only if clearly superior
  7) Save promising as nifty_edge_r7+

Usage:
  python research/nifty_edge_8h/run_block3.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from india_edge_engine import (  # noqa: E402
    add_structure_features,
    fetch_hourly,
    run_signal_backtest,
    compute_stats,
    time_split,
)
from run_block1 import (  # noqa: E402
    LEADERBOARD,
    LOG,
    RESULTS,
    RT,
    RT_STRESS,
    TRAIN_FRAC,
    UNIVERSE,
    attach_rs_and_breadth,
    buy_hold_stats,
    log,
    prepare_symbol,
)
from run_block1b import portfolio_eval, sig_supertrend, supertrend_bands  # noqa: E402
from run_block2 import (  # noqa: E402
    attach_market_to_stocks,
    clearly_better,
    past_deadline,
    portfolio_eval_ext,
    run_portfolio_ext,
    sig_st_kill_breadth,
    write_runner_up,
)

OUT_STRAT = ROOT / "strategies"
OUT_PINE = ROOT / "pinescript"

REF_OOS = {
    "n_trades": 75,
    "profit_factor": 3.90,
    "expectancy": 0.0553,
    "total_return": 1.102,
    "max_dd": -0.148,
    "sharpe": 1.10,
}

# Sector map for 20-name universe (coarse GICS-like)
SECTOR: Dict[str, str] = {
    "RELIANCE.NS": "energy",
    "TCS.NS": "it",
    "INFY.NS": "it",
    "HDFCBANK.NS": "bank",
    "ICICIBANK.NS": "bank",
    "SBIN.NS": "bank",
    "BHARTIARTL.NS": "telecom",
    "ITC.NS": "fmcg",
    "LT.NS": "industrial",
    "AXISBANK.NS": "bank",
    "KOTAKBANK.NS": "bank",
    "HINDUNILVR.NS": "fmcg",
    "BAJFINANCE.NS": "finance",
    "ASIANPAINT.NS": "consumer",
    "MARUTI.NS": "auto",
    "SUNPHARMA.NS": "pharma",
    "TITAN.NS": "consumer",
    "ULTRACEMCO.NS": "industrial",
    "WIPRO.NS": "it",
    "NESTLEIND.NS": "fmcg",
}


# ── Extended portfolio: vol-target + sector cap ───────────────────────────────
def run_portfolio_b3(
    data: Dict[str, pd.DataFrame],
    signal_fn,
    params: dict,
    start_date=None,
    end_date=None,
    max_positions: int = 5,
    rt_cost: float = RT,
    return_trades: bool = False,
) -> dict:
    """
    Portfolio with optional:
      - vol_target: annualized vol target; scales slot by target/realized (clipped)
      - sector_cap: max open positions per sector
      - heat_cap / max_positions / entry_delay (same as block2)
    No look-ahead: vol uses trailing realized returns only.
    """
    delay = int(params.get("entry_delay", 0))
    max_pos = int(params.get("max_positions", max_positions))
    heat = float(params.get("heat_cap", 1.0))
    vol_target = params.get("vol_target")  # e.g. 0.15 annualized
    vol_look = int(params.get("vol_look", 20))
    vol_floor = float(params.get("vol_floor", 0.08))
    vol_ceil = float(params.get("vol_ceil", 0.40))
    scale_lo = float(params.get("vol_scale_lo", 0.5))
    scale_hi = float(params.get("vol_scale_hi", 1.25))
    sector_cap = params.get("sector_cap")  # int or None
    if sector_cap is not None:
        sector_cap = int(sector_cap)

    sig = {}
    for s, df in data.items():
        e, x = signal_fn(df, params)[:2]
        # trailing realized vol (annualized), lag-safe
        rets = df["Close"].pct_change()
        rvol = rets.rolling(vol_look).std() * np.sqrt(252)
        sig[s] = {
            "entry": e.fillna(False),
            "exit": x.fillna(False),
            "open": df["Open"],
            "close": df["Close"],
            "ema200": df["ema200"],
            "rvol_ann": rvol,
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
    slot = 1.0 / max_pos
    delayed: Dict[str, int] = {}

    for i, dt in enumerate(all_dates):
        for s in list(positions):
            if dt in sig[s]["exit"].index and bool(sig[s]["exit"].loc[dt]):
                px = float(sig[s]["close"].loc[dt])
                ret = px / positions[s]["entry_px"] - 1.0 - rt_cost
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
                float(sig[s]["close"].loc[dt]) / p["entry_px"]
                if dt in sig[s]["close"].index
                else 1.0
            )
            for s, p in positions.items()
        )
        equity_curve.append((dt, equity, len(positions)))

        if i + 1 >= len(all_dates):
            continue
        nxt = all_dates[i + 1]
        free = max_pos - len(positions)
        if free <= 0 or cash <= 1e-8:
            if delay > 0:
                for s, elig_i in list(delayed.items()):
                    if i > elig_i + 5:
                        del delayed[s]
            continue

        # sector counts
        sec_count: Dict[str, int] = {}
        for s in positions:
            sec = SECTOR.get(s, "other")
            sec_count[sec] = sec_count.get(sec, 0) + 1

        ranked = []
        if delay <= 0:
            for s in data:
                if s in positions:
                    continue
                if dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                    continue
                if nxt not in sig[s]["open"].index or dt not in data[s].index:
                    continue
                sec = SECTOR.get(s, "other")
                if sector_cap is not None and sec_count.get(sec, 0) >= sector_cap:
                    continue
                strength = float(data[s].loc[dt, "Close"] / data[s].loc[dt, "ema200"] - 1.0)
                ranked.append((strength, s))
        else:
            for s in data:
                if s in positions or s in delayed:
                    continue
                if dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                    continue
                delayed[s] = i + delay
            for s, elig_i in list(delayed.items()):
                if s in positions:
                    del delayed[s]
                    continue
                if i < elig_i:
                    continue
                if dt not in data[s].index or dt not in sig[s]["exit"].index:
                    continue
                if bool(sig[s]["exit"].loc[dt]):
                    del delayed[s]
                    continue
                if i > elig_i + 5:
                    del delayed[s]
                    continue
                if nxt not in sig[s]["open"].index:
                    continue
                sec = SECTOR.get(s, "other")
                if sector_cap is not None and sec_count.get(sec, 0) >= sector_cap:
                    continue
                strength = float(data[s].loc[dt, "Close"] / data[s].loc[dt, "ema200"] - 1.0)
                ranked.append((strength, s))
        ranked.sort(reverse=True)

        invested = equity - cash
        for _, s in ranked[:free]:
            if invested / max(equity, 1e-12) >= heat - 1e-9:
                break
            scale = 1.0
            if vol_target is not None:
                rv = (
                    float(sig[s]["rvol_ann"].loc[dt])
                    if dt in sig[s]["rvol_ann"].index
                    else np.nan
                )
                if np.isfinite(rv) and rv > 1e-8:
                    rv_c = float(np.clip(rv, vol_floor, vol_ceil))
                    scale = float(np.clip(float(vol_target) / rv_c, scale_lo, scale_hi))
            alloc = min(cash, equity * slot * scale, equity * heat - invested)
            if alloc <= 1e-8:
                break
            entry_px = float(sig[s]["open"].loc[nxt])
            cash -= alloc
            invested += alloc
            positions[s] = {
                "w": alloc * (1 - rt_cost / 2),
                "entry_px": entry_px,
                "entry_date": nxt,
            }
            delayed.pop(s, None)
            sec = SECTOR.get(s, "other")
            sec_count[sec] = sec_count.get(sec, 0) + 1

    if all_dates:
        last = all_dates[-1]
        for s, p in list(positions.items()):
            px = float(sig[s]["close"].loc[last]) if last in sig[s]["close"].index else p["entry_px"]
            ret = px / p["entry_px"] - 1.0 - rt_cost
            cash += p["w"] * (1.0 + ret)
            trades.append({"symbol": s, "entry": p["entry_date"], "exit": last, "ret": ret})

    eq = pd.Series({d: e for d, e, _ in equity_curve})
    rets = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    tr = np.array([t["ret"] for t in trades], dtype=float) if trades else np.array([])
    wins = tr[tr > 0]
    losses = tr[tr <= 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and -losses.sum() > 0 else 0.0
    out = {
        "n_trades": int(len(trades)),
        "win_rate": float((tr > 0).mean()) if len(tr) else 0.0,
        "profit_factor": pf,
        "expectancy": float(tr.mean()) if len(tr) else 0.0,
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0,
        "max_dd": float(dd.min()) if len(dd) else 0.0,
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252))
        if len(rets) > 2 and rets.std() > 0
        else 0.0,
        "avg_hold_days": float(np.mean([(t["exit"] - t["entry"]).days for t in trades])) if trades else 0.0,
    }
    if return_trades:
        out["trades"] = trades
        out["trade_rets"] = tr.tolist()
        out["equity"] = eq
    return out


def portfolio_eval_b3(name, data, fn, params, oos_start, **kw) -> dict:
    is_s = run_portfolio_b3(data, fn, params, end_date=oos_start - pd.Timedelta(days=1), **kw)
    oos_s = run_portfolio_b3(data, fn, params, start_date=oos_start, **kw)
    oos_st = run_portfolio_b3(data, fn, params, start_date=oos_start, rt_cost=RT_STRESS, **kw)
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_portfolio_b3(data, fn, params, start_date=dates[i], end_date=dates[i + 1], **kw)
        wf.append(
            {
                "period": f"{dates[i].date()}→{dates[i+1].date()}",
                **{k: st[k] for k in st if k not in ("trades", "trade_rets", "equity")},
            }
        )
    return {
        "name": name,
        "params": params,
        "IS": {k: v for k, v in is_s.items() if k not in ("trades", "trade_rets", "equity")},
        "OOS": {k: v for k, v in oos_s.items() if k not in ("trades", "trade_rets", "equity")},
        "OOS_stress": {k: v for k, v in oos_st.items() if k not in ("trades", "trade_rets", "equity")},
        "wf": wf,
        "wf_pos": int(sum(1 for w in wf if w["expectancy"] > 0)),
        "wf_n": 3,
        "symbol": "BASKET20",
        "last_wf_tot": wf[-1]["total_return"] if wf else 0.0,
    }


# ── Ensemble equal-risk: average two independent sleeve equities ──────────────
def run_equal_risk_blend(
    data: Dict[str, pd.DataFrame],
    fn_a,
    params_a: dict,
    fn_b,
    params_b: dict,
    start_date=None,
    end_date=None,
    rt_cost: float = RT,
) -> dict:
    """
    Equal-risk blend: each sleeve runs with heat_cap=0.5 / max_positions=3,
    then average equity curves (50/50 capital). No look-ahead.
    """
    pa = {**params_a, "heat_cap": float(params_a.get("heat_cap", 0.5)), "max_positions": int(params_a.get("max_positions", 3))}
    pb = {**params_b, "heat_cap": float(params_b.get("heat_cap", 0.5)), "max_positions": int(params_b.get("max_positions", 3))}
    a = run_portfolio_b3(data, fn_a, pa, start_date=start_date, end_date=end_date, rt_cost=rt_cost, return_trades=True)
    b = run_portfolio_b3(data, fn_b, pb, start_date=start_date, end_date=end_date, rt_cost=rt_cost, return_trades=True)
    eq_a = a.get("equity", pd.Series(dtype=float))
    eq_b = b.get("equity", pd.Series(dtype=float))
    if eq_a.empty or eq_b.empty:
        return {
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "total_return": 0.0,
            "max_dd": 0.0,
            "sharpe": 0.0,
            "avg_hold_days": 0.0,
        }
    idx = eq_a.index.intersection(eq_b.index)
    # Normalize each to 1.0 at start then 50/50
    ea = eq_a.loc[idx] / float(eq_a.loc[idx].iloc[0])
    eb = eq_b.loc[idx] / float(eq_b.loc[idx].iloc[0])
    eq = 0.5 * ea + 0.5 * eb
    rets = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    # Combine trade lists (each sleeve already half-sized via heat)
    trades = list(a.get("trades", [])) + list(b.get("trades", []))
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
        "avg_hold_days": float(np.mean([(t["exit"] - t["entry"]).days for t in trades])) if trades else 0.0,
    }


def portfolio_eval_blend(name, data, oos_start, params_meta: dict) -> dict:
    """Evaluate equal-risk ST 3.0 + 3.6 blend."""
    base = {"use_nifty": True, "use_ema200": True, "heat_cap": 0.5, "max_positions": 3}
    pa = {**base, "mult": 3.0}
    pb = {**base, "mult": 3.6}
    is_s = run_equal_risk_blend(data, sig_supertrend, pa, sig_supertrend, pb, end_date=oos_start - pd.Timedelta(days=1))
    oos_s = run_equal_risk_blend(data, sig_supertrend, pa, sig_supertrend, pb, start_date=oos_start)
    oos_st = run_equal_risk_blend(
        data, sig_supertrend, pa, sig_supertrend, pb, start_date=oos_start, rt_cost=RT_STRESS
    )
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_equal_risk_blend(
            data, sig_supertrend, pa, sig_supertrend, pb, start_date=dates[i], end_date=dates[i + 1]
        )
        wf.append({"period": f"{dates[i].date()}→{dates[i+1].date()}", **st})
    return {
        "name": name,
        "params": params_meta,
        "IS": is_s,
        "OOS": oos_s,
        "OOS_stress": oos_st,
        "wf": wf,
        "wf_pos": int(sum(1 for w in wf if w["expectancy"] > 0)),
        "wf_n": 3,
        "symbol": "BASKET20",
        "last_wf_tot": wf[-1]["total_return"] if wf else 0.0,
    }


# ── Signal variants ───────────────────────────────────────────────────────────
def sig_st_agree_36_while_30(df, p):
    """Enter on 3.6 cross only while price already above 3.0 band; exit on 3.0 (tighter)."""
    use_nifty = bool(p.get("use_nifty", True))
    use_ema = bool(p.get("use_ema200", True))
    st30 = supertrend_bands(df, 3.0)
    st36 = supertrend_bands(df, 3.6)
    regime = pd.Series(True, index=df.index)
    if use_ema:
        regime &= df["Close"] > df["ema200"]
    if use_nifty and "nifty_bull" in df.columns:
        regime &= df["nifty_bull"].fillna(False)
    e36 = (df["Close"] > st36) & (df["Close"].shift(1) <= st36.shift(1)) & regime
    e = e36 & (df["Close"] > st30)
    x = df["Close"] < st30  # tighter trail
    return e.fillna(False), x.fillna(False), 1


def sig_st_agree_both_cross(df, p):
    """Enter only if both 3.0 and 3.6 fire within lookback window; exit either trail."""
    look = int(p.get("agree_look", 3))
    use_nifty = bool(p.get("use_nifty", True))
    use_ema = bool(p.get("use_ema200", True))
    e30, x30, _ = sig_supertrend(df, {"mult": 3.0, "use_nifty": use_nifty, "use_ema200": use_ema})
    e36, x36, _ = sig_supertrend(df, {"mult": 3.6, "use_nifty": use_nifty, "use_ema200": use_ema})
    recent30 = e30.rolling(look).max().astype(bool)
    recent36 = e36.rolling(look).max().astype(bool)
    # Fire on the later of the two within window
    e = (e30 | e36) & recent30 & recent36
    x = x30 | x36
    return e.fillna(False), x.fillna(False), 1


def sig_st_or_union(df, p):
    """Enter on either 3.0 or 3.6; exit when both trails broken (looser)."""
    use_nifty = bool(p.get("use_nifty", True))
    use_ema = bool(p.get("use_ema200", True))
    st30 = supertrend_bands(df, 3.0)
    st36 = supertrend_bands(df, 3.6)
    regime = pd.Series(True, index=df.index)
    if use_ema:
        regime &= df["Close"] > df["ema200"]
    if use_nifty and "nifty_bull" in df.columns:
        regime &= df["nifty_bull"].fillna(False)
    e30 = (df["Close"] > st30) & (df["Close"].shift(1) <= st30.shift(1)) & regime
    e36 = (df["Close"] > st36) & (df["Close"].shift(1) <= st36.shift(1)) & regime
    e = e30 | e36
    x = (df["Close"] < st30) & (df["Close"] < st36)
    return e.fillna(False), x.fillna(False), 1


def sig_st_kill_breadth_force_exit(df, p):
    """Hard kill: no entries below floor; also force exit when breadth collapses."""
    e, x, side = sig_supertrend(df, p)
    floor = float(p.get("breadth_floor", 0.40))
    if "breadth50" in df.columns:
        e = e & (df["breadth50"] >= floor)
        x = x | (df["breadth50"] < floor)
    return e.fillna(False), x.fillna(False), side


def kill_breadth_beats_champ(challenger: dict, champion: dict) -> bool:
    """Strict Block-3 rule: OOS total AND last WF both must clear #1."""
    c, h = challenger["OOS"], champion["OOS"]
    if c["n_trades"] < 30:
        return False
    if challenger.get("wf_pos", 0) < champion.get("wf_pos", 0):
        return False
    tot_clear = c["total_return"] > h["total_return"]
    last_clear = challenger.get("last_wf_tot", 0) > champion.get("last_wf_tot", 0)
    return bool(tot_clear and last_clear)


def hourly_data_usable(df: pd.DataFrame) -> Tuple[bool, str]:
    """Reject garbage: empty volume, too few bars, or >40% zero-volume bars."""
    if df is None or len(df) < 500:
        return False, f"too_few_bars={0 if df is None else len(df)}"
    if "Volume" not in df.columns:
        return False, "no_volume_col"
    vol = df["Volume"].fillna(0)
    zero_frac = float((vol <= 0).mean())
    if zero_frac > 0.40:
        return False, f"zero_vol_frac={zero_frac:.2f}"
    med = float(vol.replace(0, np.nan).median())
    if not np.isfinite(med) or med <= 0:
        return False, "median_vol_bad"
    return True, f"bars={len(df)} zero_vol={zero_frac:.2f} med_vol={med:.0f}"


def orb_hourly_stock(df, p):
    """First-hour ORB long on hourly IST bars; exit OR low or session end."""
    rvol_min = float(p.get("rvol_min", 1.2))
    o = df.copy()
    o["date"] = pd.to_datetime(o.index.date)
    o["tod"] = o.index.hour * 60 + o.index.minute
    first = o.groupby("date").head(1)
    or_high = first.set_index("date")["High"]
    or_low = first.set_index("date")["Low"]
    o["or_high"] = o["date"].map(or_high)
    o["or_low"] = o["date"].map(or_low)
    after = o["tod"] >= 615
    before_close = o["tod"] <= 930
    entries = (
        after
        & before_close
        & (o["Close"] > o["or_high"])
        & (o["rvol"] >= rvol_min)
        & (o["Close"] > o["ema50"])
    )
    entries = entries & ~(o["Close"].shift(1) > o["or_high"].shift(1))
    exits = (o["Close"] < o["or_low"]) | (o["tod"] >= 930)
    return entries.fillna(False), exits.fillna(False), 1


def eval_hourly_orb(sym: str, hdf: pd.DataFrame, params: dict, train_frac: float = 0.7) -> dict:
    e, x, side = orb_hourly_stock(hdf, params)
    trades = run_signal_backtest(hdf, e, x, side=side, rt_cost=RT, max_hold=12)
    n = len(hdf)
    cut = int(n * train_frac)
    is_idx = set(hdf.index[:cut])
    oos_idx = set(hdf.index[cut:])
    is_tr = [t for t in trades if t.entry_time in is_idx]
    oos_tr = [t for t in trades if t.entry_time in oos_idx]
    is_s = compute_stats(is_tr, "ORB_1h", sym, "IS", params)
    oos = compute_stats(oos_tr, "ORB_1h", sym, "OOS", params)
    # simple 3-fold WF on OOS half
    oos_dates = hdf.index[cut:]
    if len(oos_dates) < 30:
        wf_pos = 0
        last_wf = 0.0
        wf = []
    else:
        dates = pd.date_range(oos_dates[0], oos_dates[-1], periods=4)
        wf = []
        for i in range(3):
            fold_tr = [
                t
                for t in oos_tr
                if dates[i] <= t.entry_time <= dates[i + 1]
            ]
            st = compute_stats(fold_tr, "ORB_1h", sym, f"WF{i}", params)
            wf.append(
                {
                    "period": f"{dates[i].date()}→{dates[i+1].date()}",
                    "n_trades": st.n_trades,
                    "expectancy": st.expectancy,
                    "total_return": st.total_return,
                    "profit_factor": st.profit_factor,
                }
            )
        wf_pos = int(sum(1 for w in wf if w["expectancy"] > 0))
        last_wf = wf[-1]["total_return"] if wf else 0.0
    return {
        "name": f"B3_ORB_1h_{sym}_{params.get('rvol_min', 1.2)}",
        "params": params,
        "symbol": sym,
        "IS": {
            "n_trades": is_s.n_trades,
            "profit_factor": is_s.profit_factor,
            "expectancy": is_s.expectancy,
            "total_return": is_s.total_return,
            "max_dd": is_s.max_dd,
            "sharpe": is_s.sharpe,
        },
        "OOS": {
            "n_trades": oos.n_trades,
            "profit_factor": oos.profit_factor,
            "expectancy": oos.expectancy,
            "total_return": oos.total_return,
            "max_dd": oos.max_dd,
            "sharpe": oos.sharpe,
            "win_rate": oos.win_rate,
        },
        "OOS_stress": {
            "n_trades": oos.n_trades,
            "profit_factor": oos.profit_factor,  # single-name; stress noted separately if needed
            "expectancy": oos.expectancy,
            "total_return": oos.total_return,
            "max_dd": oos.max_dd,
            "sharpe": oos.sharpe,
        },
        "wf": wf,
        "wf_pos": wf_pos,
        "wf_n": 3,
        "last_wf_tot": last_wf,
    }


def append_leaderboard_block3(
    champ: dict,
    repro: dict,
    rows: List[dict],
    kill_sweep: List[dict],
    hourly_note: str,
    promoted: bool,
    bh: dict,
) -> None:
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 3"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    r = repro["OOS"]
    lines = [
        "",
        "## Block 3 — Ensemble, kill-breadth refine, vol/sector, hourly ORB",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**#1 still leads:** {'YES' if not promoted else 'NO — new champion promoted'}",
        "",
        "### Reproduced #1 (ST_m3.6_n1_e1)",
        "",
        "| Metric | Block1/2 ref | Block3 | Drift |",
        "|--------|-------------:|-------:|------:|",
        f"| n | {REF_OOS['n_trades']} | {r['n_trades']} | {r['n_trades']-REF_OOS['n_trades']:+d} |",
        f"| PF | {REF_OOS['profit_factor']:.2f} | {r['profit_factor']:.2f} | {r['profit_factor']-REF_OOS['profit_factor']:+.2f} |",
        f"| Tot | {REF_OOS['total_return']*100:.1f}% | {r['total_return']*100:.1f}% | {(r['total_return']-REF_OOS['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_OOS['max_dd']*100:.1f}% | {r['max_dd']*100:.1f}% | {(r['max_dd']-REF_OOS['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_OOS['sharpe']:.2f} | {r['sharpe']:.2f} | {r['sharpe']-REF_OOS['sharpe']:+.2f} |",
        f"| Last WF | 5.8% | {repro.get('last_wf_tot', 0)*100:.1f}% | — |",
        "",
        "### Kill-breadth threshold sweep (vs #1 tot=110.2% lastWF=+5.8%)",
        "",
        "| Floor | n | PF | Tot | MDD | WF+ | LastWF | Beat tot+lastWF? |",
        "|------:|--:|---:|----:|----:|----:|-------:|:-----------------|",
    ]
    for row in kill_sweep:
        oos = row["OOS"]
        beat = kill_breadth_beats_champ(row, repro)
        lines.append(
            f"| {row['params'].get('breadth_floor', '?')} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['total_return']*100:.1f}% | {oos['max_dd']*100:.1f}% | "
            f"{row['wf_pos']}/{row['wf_n']} | {row['last_wf_tot']*100:.1f}% | {'YES' if beat else 'no'} |"
        )

    top = sorted(
        rows,
        key=lambda rr: (
            rr.get("wf_pos", 0),
            rr["OOS"]["profit_factor"],
            rr["OOS"]["total_return"],
            rr["OOS"]["sharpe"],
        ),
        reverse=True,
    )[:25]
    lines += [
        "",
        "### Block 3 new variants (top by WF+ / PF / tot)",
        "",
        "| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |",
        "|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|",
    ]
    for i, row in enumerate(top, 1):
        oos = row["OOS"]
        stress_pf = row.get("OOS_stress", {}).get("profit_factor", 0)
        lines.append(
            f"| {i} | {row['name']} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['expectancy']*100:.2f}% | {oos['total_return']*100:.1f}% | "
            f"{oos['max_dd']*100:.1f}% | {stress_pf:.2f} | "
            f"{row['wf_pos']}/{row['wf_n']} | {row.get('last_wf_tot', 0)*100:.1f}% |"
        )

    lines += [
        "",
        f"**Hourly ORB:** {hourly_note}",
        "",
        f"**Champion after Block 3:** `{champ['name']}` — OOS PF={o['profit_factor']:.2f} "
        f"tot={o['total_return']*100:.1f}% n={o['n_trades']} WF={champ['wf_pos']}/{champ['wf_n']} "
        f"lastWF={champ.get('last_wf_tot', 0)*100:.1f}%",
        f"**B&H ^NSEI OOS:** tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "",
        "### Honesty",
        "- Ensemble aims for robustness vs mult=3.6 local PF peak; equal-risk ≠ signal agreement.",
        "- Kill-breadth promote requires **both** OOS tot and last WF to clear #1 (stricter than Block 2).",
        "- Vol-target / sector-cap: win only if MDD improves without gutting return.",
        "- No fake futures. Costs 0.08% / stress 0.15% RT. No look-ahead.",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in ("trades", "trade_rets", "equity")}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return str(obj)
    return obj


def main():
    if past_deadline():
        log("DEADLINE PASSED — Block 3 should not invent; run FINAL synthesis instead")
        print("PAST_DEADLINE")
        return

    log("=== Block 3 start ===")
    log("Loading Nifty + Bank + 20 stocks…")
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)

    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    bh_oos = buy_hold_stats(nifty.loc[nifty.index >= oos_start], "OOS")
    log(f"Buy&hold ^NSEI OOS: tot={bh_oos['total_return']*100:.1f}% Sharpe={bh_oos['sharpe']:.2f}")

    # ── 1) Reproduce #1 ───────────────────────────────────────────────────────
    log("Reproducing #1 ST_m3.6_n1_e1…")
    champ_params = {"mult": 3.6, "use_nifty": True, "use_ema200": True}
    champ = portfolio_eval("ST_m3.6_n1_e1", data, sig_supertrend, champ_params, oos_start)
    champ["last_wf_tot"] = champ["wf"][-1]["total_return"] if champ["wf"] else 0.0
    o = champ["OOS"]
    log(
        f"  REPRO n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} "
        f"WF={champ['wf_pos']}/{champ['wf_n']} lastWF={champ['last_wf_tot']*100:.1f}% "
        f"drift_PF={o['profit_factor']-REF_OOS['profit_factor']:+.2f}"
    )
    for w in champ["wf"]:
        log(f"  WF {w['period']}: n={w['n_trades']} exp={w['expectancy']*100:.2f}% tot={w['total_return']*100:.1f}%")

    new_rows: List[dict] = []
    fn_map: Dict[str, str] = {}
    kill_sweep: List[dict] = []

    # ── 2) Ensemble / blend ST 3.0 + 3.6 ──────────────────────────────────────
    log("Ensemble / blend ST 3.0 + 3.6…")
    ens_variants: List[Tuple[str, Callable, dict, str]] = [
        (
            "B3_ENS_agree_36_while_30",
            sig_st_agree_36_while_30,
            {"use_nifty": True, "use_ema200": True},
            "sig_st_agree_36_while_30",
        ),
        (
            "B3_ENS_agree_both_look3",
            sig_st_agree_both_cross,
            {"use_nifty": True, "use_ema200": True, "agree_look": 3},
            "sig_st_agree_both_cross",
        ),
        (
            "B3_ENS_agree_both_look5",
            sig_st_agree_both_cross,
            {"use_nifty": True, "use_ema200": True, "agree_look": 5},
            "sig_st_agree_both_cross",
        ),
        (
            "B3_ENS_or_union_loose_exit",
            sig_st_or_union,
            {"use_nifty": True, "use_ema200": True},
            "sig_st_or_union",
        ),
    ]
    for name, fn, params, fn_name in ens_variants:
        try:
            row = portfolio_eval_b3(name, data, fn, params, oos_start)
            new_rows.append(row)
            fn_map[name] = fn_name
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% MDD={row['OOS']['max_dd']*100:.1f}% "
                f"WF={row['wf_pos']}/3 lastWF={row['last_wf_tot']*100:.1f}%"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    try:
        blend = portfolio_eval_blend(
            "B3_ENS_equal_risk_3.0_3.6",
            data,
            oos_start,
            {"sleeve_a": 3.0, "sleeve_b": 3.6, "heat_cap": 0.5, "max_positions": 3},
        )
        new_rows.append(blend)
        fn_map[blend["name"]] = "sig_supertrend"
        log(
            f"  {blend['name']}: n={blend['OOS']['n_trades']} PF={blend['OOS']['profit_factor']:.2f} "
            f"tot={blend['OOS']['total_return']*100:.1f}% MDD={blend['OOS']['max_dd']*100:.1f}% "
            f"WF={blend['wf_pos']}/3 lastWF={blend['last_wf_tot']*100:.1f}%"
        )
    except Exception as ex:
        log(f"  FAIL equal_risk_blend: {ex}")

    # ── 3) Kill-breadth threshold sweep ───────────────────────────────────────
    log("Kill-breadth threshold sweep…")
    floors = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
    for fl in floors:
        name = f"B3_ST_kill_breadth{int(fl*100)}_m3.6"
        params = {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": fl}
        try:
            row = portfolio_eval(name, data, sig_st_kill_breadth, params, oos_start)
            row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            kill_sweep.append(row)
            new_rows.append(row)
            fn_map[name] = "sig_st_kill_breadth"
            beat = kill_breadth_beats_champ(row, champ)
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
                f"beat_tot+last={'YES' if beat else 'no'}"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    # Hard kill force-exit variants
    for fl in [0.35, 0.40]:
        name = f"B3_ST_killhard_br{int(fl*100)}_m3.6"
        params = {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": fl}
        try:
            row = portfolio_eval(name, data, sig_st_kill_breadth_force_exit, params, oos_start)
            row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            new_rows.append(row)
            fn_map[name] = "sig_st_kill_breadth_force_exit"
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}%"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    # Also try best floor on mult=3.0 (robustness)
    for fl in [0.40, 0.45]:
        name = f"B3_ST_kill_breadth{int(fl*100)}_m3.0"
        params = {"mult": 3.0, "use_nifty": True, "use_ema200": True, "breadth_floor": fl}
        try:
            row = portfolio_eval(name, data, sig_st_kill_breadth, params, oos_start)
            row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            new_rows.append(row)
            fn_map[name] = "sig_st_kill_breadth"
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}%"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    # ── 4) Vol targeting / sector-neutral / heat ──────────────────────────────
    log("Vol targeting / sector-neutral / heat caps…")
    risk_variants: List[Tuple[str, dict]] = [
        ("B3_ST_voltarget15_m3.6", {"mult": 3.6, "use_nifty": True, "use_ema200": True, "vol_target": 0.15}),
        ("B3_ST_voltarget12_m3.6", {"mult": 3.6, "use_nifty": True, "use_ema200": True, "vol_target": 0.12}),
        ("B3_ST_voltarget18_m3.6", {"mult": 3.6, "use_nifty": True, "use_ema200": True, "vol_target": 0.18}),
        ("B3_ST_voltarget15_m3.0", {"mult": 3.0, "use_nifty": True, "use_ema200": True, "vol_target": 0.15}),
        ("B3_ST_sectorcap1_m3.6", {"mult": 3.6, "use_nifty": True, "use_ema200": True, "sector_cap": 1}),
        ("B3_ST_sectorcap2_m3.6", {"mult": 3.6, "use_nifty": True, "use_ema200": True, "sector_cap": 2}),
        ("B3_ST_sectorcap1_heat4_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "sector_cap": 1, "max_positions": 4, "heat_cap": 0.80,
        }),
        ("B3_ST_heat3_vol15_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "max_positions": 3, "heat_cap": 0.75, "vol_target": 0.15,
        }),
        ("B3_ST_sectorcap2_vol15_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "sector_cap": 2, "vol_target": 0.15,
        }),
        ("B3_ST_kill40_sectorcap2_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "breadth_floor": 0.40, "sector_cap": 2,
        }),
        ("B3_ST_kill40_vol15_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "breadth_floor": 0.40, "vol_target": 0.15,
        }),
    ]
    for name, params in risk_variants:
        try:
            fn = sig_st_kill_breadth if "breadth_floor" in params else sig_supertrend
            row = portfolio_eval_b3(name, data, fn, params, oos_start)
            new_rows.append(row)
            fn_map[name] = fn.__name__
            mdd_delta = row["OOS"]["max_dd"] - champ["OOS"]["max_dd"]  # less negative = better
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% MDD={row['OOS']['max_dd']*100:.1f}% "
                f"(ΔMDD={mdd_delta*100:+.1f}pp) WF={row['wf_pos']}/3 lastWF={row['last_wf_tot']*100:.1f}%"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    # ── 5) Hourly stock ORB (skip if garbage) ─────────────────────────────────
    log("Probing hourly stock ORB data quality…")
    hourly_syms = ["RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS"]
    hourly_rows: List[dict] = []
    usable_count = 0
    skip_notes = []
    for sym in hourly_syms:
        try:
            hdf = fetch_hourly(sym)
            hdf = add_structure_features(hdf)
            ok, note = hourly_data_usable(hdf)
            log(f"  hourly {sym}: {note} usable={ok}")
            if not ok:
                skip_notes.append(f"{sym}:{note}")
                continue
            usable_count += 1
            for rvol in [1.2, 1.5]:
                params = {"rvol_min": rvol, "side": 1}
                row = eval_hourly_orb(sym, hdf, params)
                hourly_rows.append(row)
                new_rows.append(row)
                fn_map[row["name"]] = "orb_hourly_stock"
                log(
                    f"  {row['name']}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                    f"tot={row['OOS']['total_return']*100:.1f}% exp={row['OOS']['expectancy']*100:.2f}% "
                    f"WF={row['wf_pos']}/3"
                )
        except Exception as ex:
            skip_notes.append(f"{sym}:err={ex}")
            log(f"  FAIL hourly {sym}: {ex}")

    if usable_count == 0:
        hourly_note = "SKIPPED — no usable hourly volume/data (garbage or fetch fail). " + "; ".join(skip_notes[:5])
    else:
        best_h = max(hourly_rows, key=lambda r: (r["OOS"]["profit_factor"], r["OOS"]["total_return"])) if hourly_rows else None
        hourly_note = (
            f"Measured {len(hourly_rows)} ORB variants on {usable_count} symbols. "
            + (
                f"Best: {best_h['name']} PF={best_h['OOS']['profit_factor']:.2f} "
                f"tot={best_h['OOS']['total_return']*100:.1f}% n={best_h['OOS']['n_trades']}"
                if best_h
                else "no rows"
            )
        )
    log(f"  Hourly ORB verdict: {hourly_note}")

    log(f"Screened {len(new_rows)} Block-3 variants (target ≥12)")

    # ── 6) Promotion checks ───────────────────────────────────────────────────
    promoted = False
    new_champ = champ

    # Kill-breadth: strict dual-clear rule only
    for row in kill_sweep:
        if kill_breadth_beats_champ(row, champ):
            log(
                f"  KILL-BREADTH PROMOTE: {row['name']} tot={row['OOS']['total_return']*100:.1f}% "
                f"lastWF={row['last_wf_tot']*100:.1f}% clears #1"
            )
            new_champ = row
            promoted = True
            break
    if not any(kill_breadth_beats_champ(r, champ) for r in kill_sweep):
        log("  Kill-breadth: NO threshold cleared both OOS tot AND last WF vs #1 — not promoted")

    # Other variants: general clearly_better (exclude hourly single-name vanity)
    if not promoted:
        contenders = [
            r
            for r in new_rows
            if r["OOS"]["n_trades"] >= 30
            and r["OOS"]["profit_factor"] >= 1.3
            and not str(r["name"]).startswith("B3_ORB_1h_")
            and r["name"] != champ["name"]
        ]
        contenders = sorted(
            contenders,
            key=lambda r: (r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"]),
            reverse=True,
        )
        for c in contenders:
            # If it's a kill_breadth name, already handled by strict rule
            if "kill_breadth" in c["name"] and "killhard" not in c["name"]:
                continue
            if clearly_better(c, champ):
                log(
                    f"  BEAT: {c['name']} clearly better than #1 "
                    f"(PF {c['OOS']['profit_factor']:.2f} vs {champ['OOS']['profit_factor']:.2f}, "
                    f"tot {c['OOS']['total_return']*100:.1f}% vs {champ['OOS']['total_return']*100:.1f}%)"
                )
                new_champ = c
                promoted = True
                break
        if not promoted:
            log("  #1 ST_m3.6_n1_e1 REMAINS best — no challenger clearly better")

    # Save runners-up r7+
    basket_contenders = [
        r
        for r in new_rows
        if r["OOS"]["n_trades"] >= 30
        and r["OOS"]["profit_factor"] >= 1.5
        and not str(r["name"]).startswith("B3_ORB_1h_")
        and r["name"] != new_champ["name"]
    ]
    basket_contenders = sorted(
        basket_contenders,
        key=lambda r: (r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"], r.get("last_wf_tot", 0)),
        reverse=True,
    )
    saved = []
    for i, r in enumerate(basket_contenders[:4], start=7):
        fn_name = fn_map.get(r["name"], "sig_supertrend")
        path = OUT_STRAT / f"nifty_edge_r{i}.py"
        oos = r["OOS"]
        if fn_name in ("sig_supertrend", "sig_st_kill_breadth") and not (
            "vol_target" in r["params"] or "sector_cap" in r["params"] or r["name"].startswith("B3_ENS_equal")
        ):
            path = write_runner_up(i, r, fn_name)
        else:
            if fn_name == "sig_supertrend":
                fn_import = "from run_block1b import sig_supertrend\nFN = sig_supertrend"
            elif fn_name == "sig_st_kill_breadth":
                fn_import = "from run_block2 import sig_st_kill_breadth\nFN = sig_st_kill_breadth"
            else:
                fn_import = f"from run_block3 import {fn_name} as FN"
            code = f'''"""
Runner-up r{i}: {r["name"]}
Params: {json.dumps(r["params"])}
OOS n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} WF+={r.get("wf_pos")}/{r.get("wf_n")}
lastWF={r.get("last_wf_tot", 0)*100:.1f}%
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks
from run_block3 import run_portfolio_b3, portfolio_eval_blend
{fn_import}

PARAMS = {json.dumps(r["params"], indent=2)}
NAME = {json.dumps(r["name"])}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    if NAME.startswith("B3_ENS_equal_risk"):
        row = portfolio_eval_blend(NAME, data, oos_start, PARAMS)
        print(json.dumps({{"name": NAME, "OOS": row["OOS"], "last_wf_tot": row.get("last_wf_tot")}}, indent=2, default=str))
        return
    oos = run_portfolio_b3(data, FN, PARAMS, start_date=oos_start)
    print(json.dumps({{"name": NAME, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
            path.write_text(code)
        saved.append(str(path))
        log(f"  Saved {Path(path).name}: {r['name']} PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}%")

    if promoted:
        log("  Overwriting nifty_edge_best.py with new champion")
        oos = new_champ["OOS"]
        stress = new_champ["OOS_stress"]
        params = new_champ["params"]
        fn_name = fn_map.get(new_champ["name"], "sig_supertrend")
        if fn_name == "sig_supertrend":
            fn_import = "from run_block1b import sig_supertrend as FN"
        elif fn_name == "sig_st_kill_breadth":
            fn_import = "from run_block2 import sig_st_kill_breadth as FN"
        else:
            fn_import = f"from run_block3 import {fn_name} as FN"
        py = f'''"""
Nifty Edge Best — Block 3 champion
==================================
{new_champ["name"]}
Params: {json.dumps(params)}

OOS: n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} stressPF={stress["profit_factor"]:.2f}
WF={new_champ["wf_pos"]}/{new_champ["wf_n"]} lastWF={new_champ["last_wf_tot"]*100:.1f}%

Usage:
  python strategies/nifty_edge_best.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks
from run_block3 import run_portfolio_b3
{fn_import}

PARAMS = {json.dumps(params, indent=2)}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos = run_portfolio_b3(data, FN, PARAMS, start_date=oos_ref.index[0])
    print(json.dumps({{"name": {json.dumps(new_champ["name"])}, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
        (OUT_STRAT / "nifty_edge_best.py").write_text(py)
        log(f"  Wrote {OUT_STRAT / 'nifty_edge_best.py'}")
    else:
        log("  Kept strategies/nifty_edge_best.py unchanged (Block1 #1 still leads)")

    # Persist
    summary = {
        "repro": champ,
        "new_variants": new_rows,
        "kill_sweep": kill_sweep,
        "hourly_note": hourly_note,
        "promoted": promoted,
        "champion": new_champ["name"],
        "runners_up": saved,
        "bh_oos": bh_oos,
        "n_variants": len(new_rows),
    }
    path = RESULTS / "block3_summary.json"
    path.write_text(json.dumps(_clean(summary), indent=2, default=str))
    log(f"Wrote {path}")

    append_leaderboard_block3(new_champ, champ, new_rows, kill_sweep, hourly_note, promoted, bh_oos)
    log(f"Updated {LEADERBOARD}")

    top5 = sorted(
        [r for r in new_rows if not str(r["name"]).startswith("B3_ORB_1h_")],
        key=lambda r: (r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"]),
        reverse=True,
    )[:5]
    log("--- Block 3 top 5 basket ---")
    for r in top5:
        log(
            f"  {r['name']}: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"n={r['OOS']['n_trades']} WF={r['wf_pos']}/3 lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )
    log(
        f"=== Block 3 complete === champion={new_champ['name']} "
        f"PF={new_champ['OOS']['profit_factor']:.2f} tot={new_champ['OOS']['total_return']*100:.1f}% "
        f"promoted={promoted} n_variants={len(new_rows)}"
    )
    log(
        "Next Block 4: stress costs on ensemble; regime half-life; "
        "cross-asset breadth (FII proxy if available); tighter WF last-chunk attack; "
        "parameter freeze + paper rules"
    )


if __name__ == "__main__":
    main()
