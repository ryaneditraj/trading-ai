#!/usr/bin/env python3
"""
Pass 3: portfolio-pooled evaluation + index price-structure (no index volume)
+ stock hourly VWAP MR. Goal: n>=80 OOS or honest closest.
"""
from __future__ import annotations

import json
from typing import Callable, List, Tuple

import numpy as np
import pandas as pd

from india_edge_engine import (
    DEFAULT_RT_COST,
    RESULTS_DIR,
    Trade,
    add_structure_features,
    compute_stats,
    fetch_daily,
    fetch_hourly,
    param_perturb,
    run_signal_backtest,
    time_split,
    walk_forward_folds,
)

RT = 0.0008
STOCKS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
INDICES = ["^NSEI", "^NSEBANK"]
ETFS = ["NIFTYBEES.NS", "BANKBEES.NS"]  # volume usable if cleaned


def clean_daily(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    gap = o["Open"] / o["Close"].shift(1) - 1.0
    ret = o["Close"].pct_change()
    mask = ((gap.abs() < 0.08) | gap.isna()) & ((ret.abs() < 0.12) | ret.isna())
    o = o.loc[mask].copy()
    return add_structure_features(o)


def clean_hourly(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    return add_structure_features(o)


def fmt(s):
    return (
        f"n={s.n_trades:4d} WR={s.win_rate:5.1%} PF={s.profit_factor:5.2f} "
        f"E={s.expectancy*100:6.3f}% Tot={s.total_return*100:7.1f}% "
        f"MDD={s.max_dd*100:6.1f}% Sh={s.sharpe:5.2f}"
    )


def pool_backtest(
    data: dict,
    builder: Callable,
    params: dict,
    rt_cost: float = RT,
    max_hold: int = 20,
    train_frac: float = 0.7,
):
    """Run per-symbol non-overlapping backtests; pool trades by entry time for IS/OOS."""
    is_trades: List[Trade] = []
    oos_trades: List[Trade] = []
    wf_trades: List[Trade] = []
    for sym, df in data.items():
        train, test = time_split(df, train_frac)
        e, x, side = builder(train, params)
        is_trades.extend(run_signal_backtest(train, e, x, side=side, rt_cost=rt_cost, max_hold=max_hold))
        e, x, side = builder(test, params)
        oos_trades.extend(run_signal_backtest(test, e, x, side=side, rt_cost=rt_cost, max_hold=max_hold))
        for _, te in walk_forward_folds(df, n_folds=5, train_bars=756, test_bars=252):
            e, x, side = builder(te, params)
            wf_trades.extend(run_signal_backtest(te, e, x, side=side, rt_cost=rt_cost, max_hold=max_hold))
    # sort by entry
    is_trades.sort(key=lambda t: t.entry_time)
    oos_trades.sort(key=lambda t: t.entry_time)
    wf_trades.sort(key=lambda t: t.entry_time)
    return is_trades, oos_trades, wf_trades


# ── Strategies ───────────────────────────────────────────────────────────────

def s_gap_fade_uptrend_novol(df, p):
    """Gap-down fade in EMA200 uptrend; close reclaim (price structure only)."""
    gap_min = float(p.get("gap_min", 0.005))
    entries = (
        (df["gap"] <= -gap_min)
        & (df["Close"] > df["ema200"])
        & (df["Close"] > df["Open"])
        & (df["Close"] > df["ema20"])
    )
    exits = (df["High"] >= df["prior_close"]) | (df["Close"] < df["Low"].rolling(3).min().shift(1))
    return entries, exits, 1


def s_gap_fade_uptrend_rvol(df, p):
    gap_min = float(p.get("gap_min", 0.005))
    rvol_max = float(p.get("rvol_max", 1.2))
    entries = (
        (df["gap"] <= -gap_min)
        & (df["Close"] > df["ema200"])
        & (df["Close"] > df["Open"])
        & (df["rvol"] <= rvol_max)
    )
    exits = (df["High"] >= df["prior_close"]) | (df["Close"] < df["ema20"])
    return entries, exits, 1


def s_donchian_index(df, p):
    n = int(p.get("n", 20))
    exit_n = int(p.get("exit_n", 10))
    hh = df["High"].rolling(n).max().shift(1)
    entries = (df["Close"] > hh) & (df["Close"] > df["ema200"])
    exits = df["Close"] < df["Low"].rolling(exit_n).min().shift(1)
    return entries, exits, 1


def s_nr7_break_novol(df, p):
    nr7 = df["range"] == df["range"].rolling(7).min()
    was = nr7.shift(1).fillna(False)
    nr7_high = df["High"].where(nr7).ffill().shift(1)
    entries = was & (df["Close"] > nr7_high) & (df["Close"] > df["ema50"])
    exits = df["Close"] < df["ema20"]
    return entries, exits, 1


def s_two_day_reversal(df, p):
    """2 down days + bullish engulf/reclaim in uptrend."""
    d1 = df["Close"].shift(1) < df["Close"].shift(2)
    d2 = df["Close"] < df["Close"].shift(1)
    # Actually signal on reversal day: prior 2 down, today up and closes above prior high
    two_down = (df["Close"].shift(1) < df["Close"].shift(2)) & (
        df["Close"].shift(2) < df["Close"].shift(3)
    )
    entries = (
        two_down
        & (df["Close"] > df["Open"])
        & (df["Close"] > df["prior_high"])
        & (df["Close"] > df["ema200"])
    )
    exits = (df["Close"] < df["ema20"]) | (df["Low"] < df["Low"].rolling(5).min().shift(1))
    return entries, exits, 1


def s_inside_break_novol(df, p):
    was_inside = df["inside"].shift(1).fillna(False)
    mother_high = df["High"].shift(1)
    entries = was_inside & (df["Close"] > mother_high) & (df["Close"] > df["ema50"])
    exits = df["Close"] < df["ema20"]
    return entries, exits, 1


def s_hourly_vwap_mr(df, p):
    """Hourly: 2 consecutive down bars, close < vwap20, trend ema50 rising → long; exit VWAP reclaim or weak."""
    rvol_min = float(p.get("rvol_min", 0.8))  # allow normal volume
    down2 = (df["Close"] < df["Close"].shift(1)) & (df["Close"].shift(1) < df["Close"].shift(2))
    entries = (
        down2
        & (df["Close"] < df["vwap20"])
        & (df["ema20"] > df["ema50"])
        & (df["rvol"] >= rvol_min)
        & (df["Close"] > df["Open"])  # reversal hour
    )
    # Session filter: not first bar
    tod = df.index.hour * 60 + df.index.minute
    entries = entries & (tod >= 615) & (tod <= 870)
    exits = (df["Close"] > df["vwap20"]) | (tod >= 930) | (df["Close"] < df["ema50"])
    return entries, exits, 1


def s_hourly_orb_stock(df, p):
    rvol_min = float(p.get("rvol_min", 1.15))
    o = df
    date = pd.to_datetime(o.index.date)
    tod = o.index.hour * 60 + o.index.minute
    tmp = o.copy()
    tmp["date"] = date
    first = tmp.groupby("date").head(1)
    or_high = first.set_index("date")["High"]
    or_low = first.set_index("date")["Low"]
    orh = pd.Series(date.map(or_high), index=o.index)
    orl = pd.Series(date.map(or_low), index=o.index)
    after = (tod >= 615) & (tod <= 870)
    entries = after & (o["Close"] > orh) & (o["rvol"] >= rvol_min) & (o["Close"] > o["ema50"])
    entries = entries & ~(o["Close"].shift(1) > orh.shift(1))
    exits = (o["Close"] < orl) | (tod >= 930) | (o["Close"] < o["ema20"])
    return entries, exits, 1


def s_pullback_50_novol(df, p):
    stacked = (df["Close"] > df["ema200"]) & (df["ema20"] > df["ema50"])
    touch = df["Low"] <= df["ema50"]
    reclaim = (df["Close"] > df["ema50"]) & (df["Close"] > df["Open"])
    entries = stacked & touch & reclaim
    exits = df["Close"] < df["ema50"]
    return entries, exits, 1


def robustness_pool(data, builder, params, max_hold):
    train_frac = 0.7
    # perturb on pooled OOS
    keys = [k for k, v in params.items() if isinstance(v, (int, float))]
    fracs = []
    for vp in param_perturb(params, keys, 0.2):
        _, oos, _ = pool_backtest(data, builder, vp, max_hold=max_hold, train_frac=train_frac)
        st = compute_stats(oos, "", "", "OOS", vp)
        if st.n_trades >= 20:
            fracs.append(st.expectancy > 0)
    return float(np.mean(fracs)) if fracs else 0.0


def main():
    print(f"RT cost={RT*100:.2f}%")
    daily_stocks = {s: clean_daily(fetch_daily(s)) for s in STOCKS}
    daily_idx = {s: clean_daily(fetch_daily(s)) for s in INDICES}
    daily_etf = {s: clean_daily(fetch_daily(s)) for s in ETFS}
    daily_all = {**daily_stocks, **daily_idx, **daily_etf}
    daily_liq = {**daily_stocks, **daily_etf}  # volume-reliable

    hourly_stocks = {s: clean_hourly(fetch_hourly(s)) for s in STOCKS}

    experiments = []

    def run_exp(tag, data, builder, grid, max_hold):
        for params in grid:
            is_tr, oos_tr, wf_tr = pool_backtest(data, builder, params, max_hold=max_hold)
            is_s = compute_stats(is_tr, tag, "POOL", "IS", params)
            oos = compute_stats(oos_tr, tag, "POOL", "OOS", params)
            wf = compute_stats(wf_tr, tag, "POOL", "WF", params)
            pert = robustness_pool(data, builder, params, max_hold)
            row = {
                "tag": tag,
                "params": json.dumps(params),
                "universe": ",".join(data.keys()),
                "n_syms": len(data),
                "is_n": is_s.n_trades,
                "is_exp": is_s.expectancy,
                "is_pf": is_s.profit_factor,
                "oos_n": oos.n_trades,
                "oos_exp": oos.expectancy,
                "oos_pf": oos.profit_factor,
                "oos_wr": oos.win_rate,
                "oos_mdd": oos.max_dd,
                "oos_sharpe": oos.sharpe,
                "oos_tot": oos.total_return,
                "oos_hold": oos.avg_hold,
                "wf_n": wf.n_trades,
                "wf_exp": wf.expectancy,
                "wf_pf": wf.profit_factor,
                "wf_mdd": wf.max_dd,
                "wf_sharpe": wf.sharpe,
                "pert_frac": pert,
            }
            experiments.append(row)
            flag = ""
            if oos.expectancy > 0 and wf.expectancy > 0 and oos.n_trades >= 80 and pert >= 0.5:
                flag = " *** EDGE CANDIDATE ***"
            elif oos.expectancy > 0 and wf.expectancy > 0 and oos.n_trades >= 40:
                flag = " * partial *"
            print(
                f"{tag} {params} | OOS {fmt(oos)} | WF n={wf.n_trades} E={wf.expectancy*100:.3f}% "
                f"pert+={pert:.0%}{flag}"
            )

    print("\n=== Pooled daily strategies ===")
    run_exp(
        "P_gap_fade_up_novol_all",
        daily_all,
        s_gap_fade_uptrend_novol,
        [{"gap_min": 0.004}, {"gap_min": 0.005}, {"gap_min": 0.006}, {"gap_min": 0.008}],
        max_hold=8,
    )
    run_exp(
        "P_gap_fade_up_rvol_liq",
        daily_liq,
        s_gap_fade_uptrend_rvol,
        [
            {"gap_min": 0.005, "rvol_max": 1.3},
            {"gap_min": 0.006, "rvol_max": 1.1},
            {"gap_min": 0.008, "rvol_max": 1.2},
        ],
        max_hold=8,
    )
    run_exp(
        "P_donchian_idx",
        daily_idx,
        s_donchian_index,
        [{"n": 20, "exit_n": 10}, {"n": 20, "exit_n": 20}, {"n": 55, "exit_n": 20}],
        max_hold=80,
    )
    run_exp(
        "P_donchian_stocks",
        daily_stocks,
        s_donchian_index,
        [{"n": 20, "exit_n": 10}, {"n": 55, "exit_n": 20}],
        max_hold=80,
    )
    run_exp(
        "P_nr7_all",
        daily_all,
        s_nr7_break_novol,
        [{}],
        max_hold=15,
    )
    run_exp(
        "P_two_day_rev",
        daily_all,
        s_two_day_reversal,
        [{}],
        max_hold=10,
    )
    run_exp(
        "P_inside_break",
        daily_all,
        s_inside_break_novol,
        [{}],
        max_hold=15,
    )
    run_exp(
        "P_pullback50",
        daily_all,
        s_pullback_50_novol,
        [{}],
        max_hold=25,
    )

    print("\n=== Pooled hourly stock strategies ===")
    # Adjust WF for hourly: more bars
    def pool_hourly(data, builder, params, max_hold=10):
        is_trades, oos_trades, wf_trades = [], [], []
        for sym, df in data.items():
            train, test = time_split(df, 0.7)
            e, x, side = builder(train, params)
            is_trades.extend(run_signal_backtest(train, e, x, side=side, rt_cost=RT, max_hold=max_hold))
            e, x, side = builder(test, params)
            oos_trades.extend(run_signal_backtest(test, e, x, side=side, rt_cost=RT, max_hold=max_hold))
            # hourly WF: ~504 train (~3m), 168 test (~1m) — use larger
            folds = walk_forward_folds(df, n_folds=4, train_bars=1500, test_bars=500)
            for _, te in folds:
                e, x, side = builder(te, params)
                wf_trades.extend(run_signal_backtest(te, e, x, side=side, rt_cost=RT, max_hold=max_hold))
        is_trades.sort(key=lambda t: t.entry_time)
        oos_trades.sort(key=lambda t: t.entry_time)
        wf_trades.sort(key=lambda t: t.entry_time)
        return is_trades, oos_trades, wf_trades

    for tag, builder, grid, mh in [
        (
            "H_vwap_mr",
            s_hourly_vwap_mr,
            [{"rvol_min": 0.8}, {"rvol_min": 1.0}, {"rvol_min": 1.2}],
            8,
        ),
        (
            "H_orb",
            s_hourly_orb_stock,
            [{"rvol_min": 1.1}, {"rvol_min": 1.25}, {"rvol_min": 1.5}],
            10,
        ),
    ]:
        for params in grid:
            is_tr, oos_tr, wf_tr = pool_hourly(hourly_stocks, builder, params, max_hold=mh)
            is_s = compute_stats(is_tr, tag, "POOL", "IS", params)
            oos = compute_stats(oos_tr, tag, "POOL", "OOS", params)
            wf = compute_stats(wf_tr, tag, "POOL", "WF", params)
            # quick pert
            keys = [k for k, v in params.items() if isinstance(v, (int, float))]
            pert_flags = []
            for vp in param_perturb(params, keys, 0.2):
                _, ot, _ = pool_hourly(hourly_stocks, builder, vp, max_hold=mh)
                st = compute_stats(ot, tag, "POOL", "OOS", vp)
                if st.n_trades >= 20:
                    pert_flags.append(st.expectancy > 0)
            pert = float(np.mean(pert_flags)) if pert_flags else 0.0
            row = {
                "tag": tag,
                "params": json.dumps(params),
                "universe": "STOCKS_1H",
                "n_syms": len(hourly_stocks),
                "is_n": is_s.n_trades,
                "is_exp": is_s.expectancy,
                "is_pf": is_s.profit_factor,
                "oos_n": oos.n_trades,
                "oos_exp": oos.expectancy,
                "oos_pf": oos.profit_factor,
                "oos_wr": oos.win_rate,
                "oos_mdd": oos.max_dd,
                "oos_sharpe": oos.sharpe,
                "oos_tot": oos.total_return,
                "oos_hold": oos.avg_hold,
                "wf_n": wf.n_trades,
                "wf_exp": wf.expectancy,
                "wf_pf": wf.profit_factor,
                "wf_mdd": wf.max_dd,
                "wf_sharpe": wf.sharpe,
                "pert_frac": pert,
            }
            experiments.append(row)
            flag = ""
            if oos.expectancy > 0 and wf.expectancy > 0 and oos.n_trades >= 80 and pert >= 0.5:
                flag = " *** EDGE CANDIDATE ***"
            elif oos.expectancy > 0 and wf.expectancy > 0 and oos.n_trades >= 40:
                flag = " * partial *"
            print(
                f"{tag} {params} | OOS {fmt(oos)} | WF n={wf.n_trades} E={wf.expectancy*100:.3f}% "
                f"pert+={pert:.0%}{flag}"
            )

    # Cost sensitivity on best looking
    out = pd.DataFrame(experiments).sort_values(
        by=["oos_exp", "wf_exp", "oos_n"], ascending=False
    )
    out.to_csv(RESULTS_DIR / "pass3_pool.csv", index=False)

    print("\n=== STRICT FILTER ===")
    strict = out[
        (out["oos_exp"] > 0)
        & (out["wf_exp"] > 0)
        & (out["oos_n"] >= 80)
        & (out["pert_frac"] >= 0.5)
        & (out["oos_pf"] > 1.05)
    ]
    print(strict.to_string(index=False) if len(strict) else "NONE meeting full edge definition")

    print("\n=== PARTIAL (OOS+WF>0, n>=50) ===")
    part = out[(out["oos_exp"] > 0) & (out["wf_exp"] > 0) & (out["oos_n"] >= 50)]
    print(
        part[
            ["tag", "params", "oos_n", "oos_exp", "oos_pf", "oos_mdd", "wf_n", "wf_exp", "pert_frac"]
        ].head(20).to_string(index=False)
        if len(part)
        else "none"
    )

    # Cost stress on top partial/strict
    focus = strict if len(strict) else part
    if len(focus):
        print("\n=== Cost stress on top candidate ===")
        top = focus.iloc[0]
        tag = top["tag"]
        params = json.loads(top["params"])
        # map tag to builder/data
        mapping = {
            "P_gap_fade_up_novol_all": (daily_all, s_gap_fade_uptrend_novol, 8),
            "P_gap_fade_up_rvol_liq": (daily_liq, s_gap_fade_uptrend_rvol, 8),
            "P_donchian_idx": (daily_idx, s_donchian_index, 80),
            "P_donchian_stocks": (daily_stocks, s_donchian_index, 80),
            "P_nr7_all": (daily_all, s_nr7_break_novol, 15),
            "P_two_day_rev": (daily_all, s_two_day_reversal, 10),
            "P_inside_break": (daily_all, s_inside_break_novol, 15),
            "P_pullback50": (daily_all, s_pullback_50_novol, 25),
            "H_vwap_mr": (hourly_stocks, s_hourly_vwap_mr, 8),
            "H_orb": (hourly_stocks, s_hourly_orb_stock, 10),
        }
        data, builder, mh = mapping[tag]
        for cost in [0.0003, 0.0008, 0.0010, 0.0015]:
            if tag.startswith("H_"):
                # manual
                is_tr, oos_tr = [], []
                for sym, df in data.items():
                    train, test = time_split(df, 0.7)
                    e, x, side = builder(test, params)
                    oos_tr.extend(run_signal_backtest(test, e, x, side=side, rt_cost=cost, max_hold=mh))
                oos = compute_stats(oos_tr, tag, "POOL", "OOS", params)
            else:
                _, oos_tr, _ = pool_backtest(data, builder, params, rt_cost=cost, max_hold=mh)
                oos = compute_stats(oos_tr, tag, "POOL", "OOS", params)
            print(f"  cost={cost*100:.2f}% RT → OOS n={oos.n_trades} E={oos.expectancy*100:.3f}% PF={oos.profit_factor:.2f}")

        meta = {
            "tag": tag,
            "params": params,
            "oos_n": int(top["oos_n"]),
            "oos_exp": float(top["oos_exp"]),
            "oos_pf": float(top["oos_pf"]),
            "oos_mdd": float(top["oos_mdd"]),
            "oos_wr": float(top["oos_wr"]),
            "wf_n": int(top["wf_n"]),
            "wf_exp": float(top["wf_exp"]),
            "pert_frac": float(top["pert_frac"]),
            "strict_edge": len(strict) > 0,
        }
        (RESULTS_DIR / "pass3_winner.json").write_text(json.dumps(meta, indent=2))
        print("\nSELECTED:", json.dumps(meta, indent=2))
    else:
        # closest overall
        close = out[(out["oos_exp"] > 0) & (out["wf_exp"] > 0)].sort_values("oos_n", ascending=False)
        print("\nClosest by trade count among positive OOS+WF:")
        print(close.head(10).to_string(index=False) if len(close) else out.head(10).to_string(index=False))
        if len(close):
            top = close.iloc[0]
            meta = {
                "tag": top["tag"],
                "params": json.loads(top["params"]),
                "oos_n": int(top["oos_n"]),
                "oos_exp": float(top["oos_exp"]),
                "oos_pf": float(top["oos_pf"]),
                "wf_n": int(top["wf_n"]),
                "wf_exp": float(top["wf_exp"]),
                "pert_frac": float(top["pert_frac"]),
                "strict_edge": False,
            }
            (RESULTS_DIR / "pass3_winner.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
