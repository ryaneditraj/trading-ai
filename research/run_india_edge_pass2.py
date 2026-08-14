#!/usr/bin/env python3
"""
Second-pass India edge research with cleaned data + refined hypotheses.
Rejects ETF garbage gaps; focuses on ^NSEI/^NSEBANK + liquid stocks.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from india_edge_engine import (
    DEFAULT_RT_COST,
    RESULTS_DIR,
    add_structure_features,
    compute_stats,
    fetch_daily,
    fetch_hourly,
    param_perturb,
    run_signal_backtest,
    time_split,
    walk_forward_folds,
)

RT = DEFAULT_RT_COST  # 0.08%
SYMBOLS = ["^NSEI", "^NSEBANK", "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    # Drop absurd gaps / returns (corporate action / bad ticks)
    gap = o["Open"] / o["Close"].shift(1) - 1.0
    ret = o["Close"].pct_change()
    o = o[(gap.abs() < 0.08) | gap.isna()]
    o = o[(ret.abs() < 0.12) | ret.isna()]
    o = o[o["Volume"] >= 0]
    return add_structure_features(o)


def fmt(s):
    return (
        f"n={s.n_trades:4d} WR={s.win_rate:5.1%} PF={s.profit_factor:5.2f} "
        f"E={s.expectancy*100:6.3f}% Tot={s.total_return*100:7.1f}% "
        f"MDD={s.max_dd*100:6.1f}% Sh={s.sharpe:5.2f} hold={s.avg_hold:4.1f}"
    )


# ── Refined signal builders ──────────────────────────────────────────────────

def gap_fade_trend(df, p):
    """H3b: Fade gap-downs ONLY in uptrend (EMA200); weak open volume."""
    gap_min = float(p.get("gap_min", 0.006))
    rvol_max = float(p.get("rvol_max", 1.1))
    side = 1
    up = df["Close"] > df["ema200"]
    entries = (
        (df["gap"] <= -gap_min)
        & (df["rvol"] <= rvol_max)
        & (df["Close"] > df["Open"])  # reclaim after weak open
        & up
    )
    # Exit: prior close filled OR EMA20 OR max via engine
    exits = (df["High"] >= df["prior_close"]) | (df["Close"] < df["ema20"])
    return entries, exits, side


def gap_fade_trend_short(df, p):
    """H3c: Fade gap-ups in downtrend."""
    gap_min = float(p.get("gap_min", 0.006))
    rvol_max = float(p.get("rvol_max", 1.1))
    down = df["Close"] < df["ema200"]
    entries = (df["gap"] >= gap_min) & (df["rvol"] <= rvol_max) & (df["Close"] < df["Open"]) & down
    exits = (df["Low"] <= df["prior_close"]) | (df["Close"] > df["ema20"])
    return entries, exits, -1


def donchian_long_hold(df, p):
    """H1b: Classic Donchian long, EMA200 filter, 10-day exit — no volume (Turtle-like)."""
    n = int(p.get("n", 20))
    hh = df["High"].rolling(n).max().shift(1)
    entries = (df["Close"] > hh) & (df["Close"] > df["ema200"])
    exits = df["Close"] < df["Low"].rolling(int(p.get("exit_n", 10))).min().shift(1)
    return entries, exits, 1


def donchian_rvol_long_hold(df, p):
    """H1c: Donchian + mild RVOL, longer exit."""
    n = int(p.get("n", 20))
    rvol_min = float(p.get("rvol_min", 1.1))
    hh = df["High"].rolling(n).max().shift(1)
    entries = (df["Close"] > hh) & (df["rvol"] >= rvol_min) & (df["Close"] > df["ema200"])
    exits = df["Close"] < df["Low"].rolling(int(p.get("exit_n", 10))).min().shift(1)
    return entries, exits, 1


def failed_breakout_fade(df, p):
    """H13: Break above 20d high then close back inside within 2 bars → short (or long opposite)."""
    n = int(p.get("n", 20))
    rvol_min = float(p.get("rvol_min", 1.2))
    hh = df["High"].rolling(n).max().shift(1)
    broke = df["High"] > hh
    # Failed: was above hh recently but closes back below hh
    failed = broke.shift(1).fillna(False) & (df["Close"] < hh) & (df["rvol"] >= rvol_min)
    # Long version: failed breakdown
    ll = df["Low"].rolling(n).min().shift(1)
    broke_dn = df["Low"] < ll
    failed_dn = broke_dn.shift(1).fillna(False) & (df["Close"] > ll) & (df["rvol"] >= rvol_min)
    side = int(p.get("side", 1))
    if side == 1:
        entries = failed_dn & (df["Close"] > df["ema50"])
        exits = (df["Close"] < df["ema20"]) | (df["Close"] < ll)
    else:
        entries = failed & (df["Close"] < df["ema50"])
        exits = (df["Close"] > df["ema20"]) | (df["Close"] > hh)
    return entries, exits, side


def orb_hourly(df, p):
    """H14: Opening range (first 1h) breakout with RVOL — hourly bars, IST session."""
    # Assumes index is naive IST-like from fetch_hourly
    rvol_min = float(p.get("rvol_min", 1.2))
    side = int(p.get("side", 1))
    o = df.copy()
    o["date"] = pd.to_datetime(o.index.date)
    o["tod"] = o.index.hour * 60 + o.index.minute
    # First bar of session ~ 9:15 → 555 minutes
    first = o.groupby("date").head(1)
    or_high = first.set_index("date")["High"]
    or_low = first.set_index("date")["Low"]
    o["or_high"] = o["date"].map(or_high)
    o["or_low"] = o["date"].map(or_low)
    # Trade only bars after first hour (tod > 555+60 = 615 → 10:15)
    after = o["tod"] >= 615
    before_close = o["tod"] <= 930  # before ~15:30
    if side == 1:
        entries = after & before_close & (o["Close"] > o["or_high"]) & (o["rvol"] >= rvol_min) & (
            o["Close"] > o["ema50"]
        )
        # one breakout per day: signal on first cross
        entries = entries & ~(o["Close"].shift(1) > o["or_high"].shift(1))
        exits = (o["Close"] < o["or_low"]) | (o["tod"] >= 930)
    else:
        entries = after & before_close & (o["Close"] < o["or_low"]) & (o["rvol"] >= rvol_min) & (
            o["Close"] < o["ema50"]
        )
        entries = entries & ~(o["Close"].shift(1) < o["or_low"].shift(1))
        exits = (o["Close"] > o["or_high"]) | (o["tod"] >= 930)
    return entries, exits, side


def consecutive_down_reversal(df, p):
    """H15: 3 down closes in uptrend + RVOL climax → long."""
    n_down = int(p.get("n_down", 3))
    rvol_min = float(p.get("rvol_min", 1.3))
    down = df["Close"] < df["Close"].shift(1)
    streak = down.rolling(n_down).sum() == n_down
    entries = streak & (df["rvol"] >= rvol_min) & (df["Close"] > df["ema200"]) & (
        df["Close"] > df["Open"]
    )  # reversal candle
    exits = (df["Close"] > df["High"].rolling(5).max().shift(1)) | (df["Close"] < df["ema50"])
    return entries, exits, 1


def volume_dryup_thrust(df, p):
    """H16: 5-day avg volume < 0.7x 20d, then close > 10d high with RVOL>1.3."""
    rvol_min = float(p.get("rvol_min", 1.3))
    dry = df["Volume"].rolling(5).mean() < 0.7 * df["vol_ma20"]
    entries = (
        dry.shift(1).fillna(False)
        & (df["Close"] > df["hh10"])
        & (df["rvol"] >= rvol_min)
        & (df["Close"] > df["ema50"])
    )
    exits = df["Close"] < df["ema20"]
    return entries, exits, 1


def ema_ribbon_pullback(df, p):
    """H17: Price > EMA50 > EMA200, pullback touches EMA50, reclaim with volume."""
    rvol_min = float(p.get("rvol_min", 1.15))
    stacked = (df["ema20"] > df["ema50"]) & (df["ema50"] > df["ema200"])
    touched = df["Low"] <= df["ema50"]
    reclaim = (df["Close"] > df["ema50"]) & (df["Close"] > df["Open"])
    entries = stacked & touched.rolling(5).max().astype(bool) & reclaim & (df["rvol"] >= rvol_min)
    # Require was below/at EMA50 recently
    entries = entries & (df["Close"].shift(1) <= df["ema50"].shift(1) * 1.005)
    exits = df["Close"] < df["ema50"]
    return entries, exits, 1


def weekly_breakout_daily(df, p):
    """H18: Proxy weekly breakout using 20-bar (=~month) with higher RVOL and trend."""
    # Use 20 as month proxy; require close strength
    n = int(p.get("n", 20))
    rvol_min = float(p.get("rvol_min", 1.25))
    hh = df["High"].rolling(n).max().shift(1)
    entries = (
        (df["Close"] > hh)
        & (df["rvol"] >= rvol_min)
        & (df["Close"] > df["ema200"])
        & ((df["Close"] - df["Low"]) / (df["High"] - df["Low"] + 1e-12) > 0.6)  # close in upper range
    )
    exits = df["Close"] < df["Low"].rolling(20).min().shift(1)
    return entries, exits, 1


STRATS = {
    "H3b_gap_fade_uptrend": gap_fade_trend,
    "H3c_gap_fade_downtrend": gap_fade_trend_short,
    "H1b_donchian_ema200": donchian_long_hold,
    "H1c_donchian_rvol_hold": donchian_rvol_long_hold,
    "H13_failed_breakout": failed_breakout_fade,
    "H15_down_streak_rev": consecutive_down_reversal,
    "H16_dryup_thrust": volume_dryup_thrust,
    "H17_ema_ribbon_pb": ema_ribbon_pullback,
    "H18_range_close_break": weekly_breakout_daily,
}

PARAM_GRID = {
    "H3b_gap_fade_uptrend": [
        {"gap_min": 0.005, "rvol_max": 1.2},
        {"gap_min": 0.006, "rvol_max": 1.0},
        {"gap_min": 0.008, "rvol_max": 1.1},
        {"gap_min": 0.010, "rvol_max": 0.9},
    ],
    "H3c_gap_fade_downtrend": [
        {"gap_min": 0.006, "rvol_max": 1.1},
        {"gap_min": 0.008, "rvol_max": 1.0},
    ],
    "H1b_donchian_ema200": [
        {"n": 20, "exit_n": 10},
        {"n": 55, "exit_n": 20},
        {"n": 20, "exit_n": 20},
    ],
    "H1c_donchian_rvol_hold": [
        {"n": 20, "exit_n": 10, "rvol_min": 1.1},
        {"n": 40, "exit_n": 15, "rvol_min": 1.2},
        {"n": 55, "exit_n": 20, "rvol_min": 1.15},
    ],
    "H13_failed_breakout": [
        {"n": 20, "rvol_min": 1.2, "side": 1},
        {"n": 20, "rvol_min": 1.5, "side": 1},
        {"n": 20, "rvol_min": 1.2, "side": -1},
    ],
    "H15_down_streak_rev": [
        {"n_down": 3, "rvol_min": 1.3},
        {"n_down": 3, "rvol_min": 1.6},
        {"n_down": 4, "rvol_min": 1.4},
    ],
    "H16_dryup_thrust": [
        {"rvol_min": 1.3},
        {"rvol_min": 1.5},
        {"rvol_min": 1.8},
    ],
    "H17_ema_ribbon_pb": [
        {"rvol_min": 1.1},
        {"rvol_min": 1.25},
        {"rvol_min": 1.4},
    ],
    "H18_range_close_break": [
        {"n": 20, "rvol_min": 1.25},
        {"n": 55, "rvol_min": 1.2},
        {"n": 20, "rvol_min": 1.5},
    ],
}


def eval_full(name, builder, df, params, max_hold=40):
    train, test = time_split(df, 0.7)
    e, x, side = builder(train, params)
    is_tr = run_signal_backtest(train, e, x, side=side, rt_cost=RT, max_hold=max_hold)
    e2, x2, side = builder(test, params)
    oos_tr = run_signal_backtest(test, e2, x2, side=side, rt_cost=RT, max_hold=max_hold)
    is_s = compute_stats(is_tr, name, "", "IS", params)
    oos = compute_stats(oos_tr, name, "", "OOS", params)

    folds = walk_forward_folds(df, n_folds=5, train_bars=756, test_bars=252)
    wf_trades = []
    for _, te in folds:
        e, x, side = builder(te, params)
        wf_trades.extend(run_signal_backtest(te, e, x, side=side, rt_cost=RT, max_hold=max_hold))
    wf = compute_stats(wf_trades, name, "", "WF", params)

    keys = [k for k in params if isinstance(params[k], (int, float)) and k != "side"]
    pert = []
    for vp in param_perturb(params, keys, 0.2):
        e, x, side = builder(test, vp)
        tr = run_signal_backtest(test, e, x, side=side, rt_cost=RT, max_hold=max_hold)
        st = compute_stats(tr, name, "", "P", vp)
        if st.n_trades >= 8:
            pert.append(st.expectancy)
    pert_frac = float(np.mean([p > 0 for p in pert])) if pert else 0.0
    return is_s, oos, wf, pert_frac, float(np.mean(pert)) if pert else 0.0


def main():
    print(f"Cost RT={RT*100:.2f}% | clean data | symbols={SYMBOLS}")
    data = {}
    for s in SYMBOLS:
        data[s] = clean(fetch_daily(s))
        print(f"  {s}: {len(data[s])} bars")

    rows = []
    print("\n=== Daily refined screen ===")
    for name, builder in STRATS.items():
        max_hold = 60 if name.startswith("H1") or name.startswith("H18") else 20
        for params in PARAM_GRID[name]:
            for sym, df in data.items():
                try:
                    is_s, oos, wf, pfrac, pmean = eval_full(name, builder, df, params, max_hold=max_hold)
                    rows.append(
                        {
                            "name": name,
                            "symbol": sym,
                            "params": json.dumps(params),
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
                            "pert_frac": pfrac,
                            "pert_mean": pmean,
                        }
                    )
                except Exception as e:
                    print("ERR", name, sym, e)

    df = pd.DataFrame(rows)
    # Rank: OOS+WF positive, trade count, robustness
    df["rank_score"] = (
        df["oos_exp"] * 800
        + df["wf_exp"] * 800
        + np.minimum(df["oos_n"], 100) / 100
        + np.minimum(df["wf_n"], 100) / 100
        + df["pert_frac"] * 2
        + np.minimum(df["oos_pf"], 3) * 0.3
        + df["oos_mdd"].clip(-0.5, 0) * 1.5
    )
    df.loc[df["oos_exp"] <= 0, "rank_score"] -= 8
    df.loc[df["wf_exp"] <= 0, "rank_score"] -= 5
    df.loc[df["oos_n"] < 25, "rank_score"] -= 3
    df = df.sort_values("rank_score", ascending=False)
    df.to_csv(RESULTS_DIR / "pass2b_refined.csv", index=False)

    print("\nTOP 30:")
    cols = [
        "name", "symbol", "params", "oos_n", "oos_exp", "oos_pf", "oos_mdd",
        "wf_n", "wf_exp", "wf_pf", "pert_frac", "rank_score",
    ]
    print(df[cols].head(30).to_string(index=False))

    print("\n=== Per-strategy best ===")
    for name in STRATS:
        sub = df[df["name"] == name]
        if sub.empty:
            continue
        b = sub.iloc[0]
        ok = b["oos_exp"] > 0 and b["wf_exp"] > 0 and b["oos_n"] >= 30 and b["pert_frac"] >= 0.5
        print(
            f"{name}: {'CANDIDATE' if ok else 'reject/weak'} "
            f"{b['symbol']} OOS n={int(b['oos_n'])} E={b['oos_exp']*100:.3f}% "
            f"WF n={int(b['wf_n'])} E={b['wf_exp']*100:.3f}% pert+={b['pert_frac']:.0%}"
        )

    # Hourly ORB
    print("\n=== Hourly ORB (H14) ===")
    hrows = []
    for sym in ["^NSEI", "^NSEBANK", "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS"]:
        hdf = clean(fetch_hourly(sym))
        for params in [{"rvol_min": 1.2, "side": 1}, {"rvol_min": 1.5, "side": 1}, {"rvol_min": 1.2, "side": -1}]:
            is_s, oos, wf, pfrac, pmean = eval_full("H14_orb", orb_hourly, hdf, params, max_hold=12)
            hrows.append(
                {
                    "name": "H14_orb",
                    "symbol": sym,
                    "params": json.dumps(params),
                    "oos_n": oos.n_trades,
                    "oos_exp": oos.expectancy,
                    "oos_pf": oos.profit_factor,
                    "oos_mdd": oos.max_dd,
                    "oos_wr": oos.win_rate,
                    "wf_n": wf.n_trades,
                    "wf_exp": wf.expectancy,
                    "wf_pf": wf.profit_factor,
                    "pert_frac": pfrac,
                }
            )
            print(f"H14 {sym} {params} | OOS {fmt(oos)} | WF n={wf.n_trades} E={wf.expectancy*100:.3f}%")
    hdf_out = pd.DataFrame(hrows).sort_values("oos_exp", ascending=False)
    hdf_out.to_csv(RESULTS_DIR / "pass2b_hourly_orb.csv", index=False)

    # Multi-symbol portfolio for top daily candidate
    print("\n=== Multi-symbol for top candidates ===")
    top_unique = []
    seen = set()
    for _, r in df.iterrows():
        key = (r["name"], r["params"])
        if key in seen:
            continue
        seen.add(key)
        top_unique.append(r)
        if len(top_unique) >= 5:
            break

    summary = []
    for r in top_unique:
        name, params = r["name"], json.loads(r["params"])
        builder = STRATS[name]
        max_hold = 60 if name.startswith("H1") or name.startswith("H18") else 20
        sym_stats = []
        for sym, d in data.items():
            _, oos, wf, pfrac, _ = eval_full(name, builder, d, params, max_hold=max_hold)
            sym_stats.append((sym, oos, wf, pfrac))
        pos = np.mean([s[1].expectancy > 0 for s in sym_stats])
        mean_e = np.mean([s[1].expectancy for s in sym_stats])
        mean_wf = np.mean([s[2].expectancy for s in sym_stats])
        total_n = sum(s[1].n_trades for s in sym_stats)
        print(
            f"{name} {params}: OOS+frac={pos:.0%} meanE={mean_e*100:.3f}% "
            f"meanWF={mean_wf*100:.3f}% totalOOS_n={total_n}"
        )
        for sym, oos, wf, pfrac in sym_stats:
            print(f"   {sym}: OOS {fmt(oos)} | WF E={wf.expectancy*100:.3f}% n={wf.n_trades} pert+={pfrac:.0%}")
        summary.append(
            {
                "name": name,
                "params": json.dumps(params),
                "oos_pos_frac": pos,
                "mean_oos_exp": mean_e,
                "mean_wf_exp": mean_wf,
                "total_oos_n": total_n,
            }
        )
    pd.DataFrame(summary).to_csv(RESULTS_DIR / "pass2b_multisymbol.csv", index=False)

    # Pick honest best
    viable = df[
        (df["oos_exp"] > 0)
        & (df["wf_exp"] > 0)
        & (df["oos_n"] >= 40)
        & (df["pert_frac"] >= 0.5)
    ]
    print("\n=== STRICT VIABLE (OOS+WF>0, n>=40, pert>=50%) ===")
    if len(viable):
        print(viable[cols].head(15).to_string(index=False))
        w = viable.iloc[0]
    else:
        print("NONE. Closest:")
        close = df[(df["oos_exp"] > 0) & (df["wf_exp"] > 0)].head(15)
        print(close[cols].to_string(index=False) if len(close) else "no positive OOS+WF")
        w = close.iloc[0] if len(close) else df.iloc[0]

    meta = {
        "winner": w["name"],
        "symbol": w["symbol"],
        "params": json.loads(w["params"]),
        "oos_n": int(w["oos_n"]),
        "oos_exp": float(w["oos_exp"]),
        "oos_pf": float(w["oos_pf"]),
        "oos_mdd": float(w["oos_mdd"]),
        "wf_n": int(w["wf_n"]),
        "wf_exp": float(w["wf_exp"]),
        "pert_frac": float(w["pert_frac"]),
        "rt_cost": RT,
    }
    (RESULTS_DIR / "pass2b_winner.json").write_text(json.dumps(meta, indent=2))
    print("\nWINNER:", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
