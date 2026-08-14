#!/usr/bin/env python3
"""
Pass 4: harden Donchian; washout MR; index-filtered breakouts; ATR stops.
"""
from __future__ import annotations

import json
from typing import Dict, List

import numpy as np
import pandas as pd

from india_edge_engine import (
    DEFAULT_RT_COST,
    RESULTS_DIR,
    Trade,
    add_structure_features,
    compute_stats,
    fetch_daily,
    param_perturb,
    run_signal_backtest,
    time_split,
    walk_forward_folds,
)

RT = DEFAULT_RT_COST
STOCKS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
ALL = STOCKS + ["^NSEI", "^NSEBANK", "NIFTYBEES.NS", "BANKBEES.NS"]


def clean(df):
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    gap = o["Open"] / o["Close"].shift(1) - 1.0
    ret = o["Close"].pct_change()
    mask = ((gap.abs() < 0.08) | gap.isna()) & ((ret.abs() < 0.12) | ret.isna())
    return add_structure_features(o.loc[mask].copy())


def fmt(s):
    return (
        f"n={s.n_trades:4d} WR={s.win_rate:5.1%} PF={s.profit_factor:5.2f} "
        f"E={s.expectancy*100:6.3f}% MDD={s.max_dd*100:6.1f}% Sh={s.sharpe:5.2f}"
    )


def pool(data, builder, params, max_hold=40, rt=RT):
    is_tr, oos_tr, wf_tr = [], [], []
    for df in data.values():
        train, test = time_split(df, 0.7)
        e, x, side = builder(train, params)
        is_tr += run_signal_backtest(train, e, x, side=side, rt_cost=rt, max_hold=max_hold)
        e, x, side = builder(test, params)
        oos_tr += run_signal_backtest(test, e, x, side=side, rt_cost=rt, max_hold=max_hold)
        for _, te in walk_forward_folds(df, n_folds=5, train_bars=756, test_bars=252):
            e, x, side = builder(te, params)
            wf_tr += run_signal_backtest(te, e, x, side=side, rt_cost=rt, max_hold=max_hold)
    is_tr.sort(key=lambda t: t.entry_time)
    oos_tr.sort(key=lambda t: t.entry_time)
    wf_tr.sort(key=lambda t: t.entry_time)
    return is_tr, oos_tr, wf_tr


def with_index_filter(stock_df, nifty_df):
    """Align Nifty EMA200 regime onto stock calendar."""
    d = stock_df.copy()
    n = nifty_df[["ema200", "Close"]].copy()
    n["nifty_up"] = n["Close"] > n["ema200"]
    # asof join on date
    d2 = d.copy()
    d2["dt"] = pd.to_datetime(d2.index.date)
    n2 = n.copy()
    n2["dt"] = pd.to_datetime(n2.index.date)
    m = d2.merge(n2[["dt", "nifty_up"]], on="dt", how="left")
    m.index = d.index
    m["nifty_up"] = m["nifty_up"].ffill().fillna(False)
    return m


# ── Builders ─────────────────────────────────────────────────────────────────

def donchian_atr_stop(df, p):
    """Enter Donchian break; exit on ATR stop from entry OR opposite channel (approx via EMA/LL)."""
    n = int(p.get("n", 55))
    exit_n = int(p.get("exit_n", 20))
    atr_mult = float(p.get("atr_mult", 3.0))
    hh = df["High"].rolling(n).max().shift(1)
    trend = df["Close"] > df["ema200"]
    vol_ok = True
    if "rvol_min" in p:
        vol_ok = df["rvol"] >= float(p["rvol_min"])
    entries = (df["Close"] > hh) & trend & vol_ok
    # Exit: close below entry-ish trail using rolling max - atr, OR exit channel
    # Approximate trail: Close < HH_since - atr_mult*atr → use Close < ema20 as soft + LL exit_n
    trail = df["Close"].rolling(10).max() - atr_mult * df["atr"]
    exits = (df["Close"] < df["Low"].rolling(exit_n).min().shift(1)) | (df["Close"] < trail)
    if "nifty_up" in df.columns and p.get("use_nifty", False):
        entries = entries & df["nifty_up"]
    return entries, exits, 1


def donchian_adxish(df, p):
    """Use |ema20-ema50|/atr as trend strength proxy (no classic ADX needed)."""
    n = int(p.get("n", 55))
    exit_n = int(p.get("exit_n", 20))
    strength = (df["ema20"] - df["ema50"]).abs() / (df["atr"] + 1e-12)
    min_s = float(p.get("min_strength", 0.8))
    hh = df["High"].rolling(n).max().shift(1)
    entries = (df["Close"] > hh) & (df["Close"] > df["ema200"]) & (strength >= min_s)
    if "nifty_up" in df.columns and p.get("use_nifty", False):
        entries = entries & df["nifty_up"]
    exits = df["Close"] < df["Low"].rolling(exit_n).min().shift(1)
    return entries, exits, 1


def washout_mr(df, p):
    """Close below N-day low (or near) but still above EMA200 → long mean reversion."""
    n = int(p.get("n", 10))
    ll = df["Low"].rolling(n).min().shift(1)
    # washout: close in bottom of range and near LL, bullish close
    loc = (df["Close"] - df["Low"]) / (df["High"] - df["Low"] + 1e-12)
    entries = (
        (df["Low"] <= ll * 1.002)
        & (df["Close"] > df["ema200"])
        & (df["Close"] > df["Open"])
        & (loc > 0.5)
    )
    if "rvol_min" in p:
        entries = entries & (df["rvol"] >= float(p["rvol_min"]))
    exits = (df["Close"] > df["ema20"]) | (df["Close"] < df["ema50"])
    return entries, exits, 1


def atr_band_fade(df, p):
    """Fade close below lower ATR band in uptrend (structure: stretch from EMA)."""
    k = float(p.get("k", 2.0))
    lower = df["ema20"] - k * df["atr"]
    entries = (df["Close"] < lower) & (df["Close"] > df["ema200"]) & (df["Close"] > df["Open"])
    exits = (df["Close"] >= df["ema20"]) | (df["Close"] < df["ema50"])
    return entries, exits, 1


def expansion_breakout(df, p):
    """Break HH20 only if today's range > 1.2*ATR (expansion) and close strong."""
    n = int(p.get("n", 20))
    hh = df["High"].rolling(n).max().shift(1)
    expand = df["range"] > float(p.get("exp", 1.2)) * df["atr"]
    strong = (df["Close"] - df["Low"]) / (df["High"] - df["Low"] + 1e-12) > 0.66
    entries = (df["Close"] > hh) & expand & strong & (df["Close"] > df["ema200"])
    if "rvol_min" in p:
        entries = entries & (df["rvol"] >= float(p["rvol_min"]))
    if "nifty_up" in df.columns and p.get("use_nifty", False):
        entries = entries & df["nifty_up"]
    exits = df["Close"] < df["Low"].rolling(int(p.get("exit_n", 10))).min().shift(1)
    return entries, exits, 1


def rsi_proxy_mr(df, p):
    """% of closes up over 14 days low → oversold proxy without RSI lib."""
    window = int(p.get("window", 14))
    thr = float(p.get("thr", 0.30))
    up_frac = (df["Close"] > df["Close"].shift(1)).rolling(window).mean()
    entries = (up_frac <= thr) & (df["Close"] > df["ema200"]) & (df["Close"] > df["Open"])
    exits = (up_frac >= 0.5) | (df["Close"] < df["ema50"])
    return entries, exits, 1


def relative_breakout(df, p, rel_series=None):
    """Stock making HH20 while outperforming Nifty 20d."""
    n = int(p.get("n", 20))
    hh = df["High"].rolling(n).max().shift(1)
    entries = (df["Close"] > hh) & (df["Close"] > df["ema200"])
    if "rel_ok" in df.columns:
        entries = entries & df["rel_ok"]
    exits = df["Close"] < df["Low"].rolling(int(p.get("exit_n", 10))).min().shift(1)
    return entries, exits, 1


def main():
    data_raw = {s: clean(fetch_daily(s)) for s in ALL}
    nifty = data_raw["^NSEI"]
    stocks = {}
    for s in STOCKS:
        stocks[s] = with_index_filter(data_raw[s], nifty)
        # relative strength vs nifty
        stock_ret = stocks[s]["Close"].pct_change(20)
        # map nifty 20d ret
        nret = nifty["Close"].pct_change(20)
        tmp = stocks[s].copy()
        tmp["dt"] = pd.to_datetime(tmp.index.date)
        nr = nret.copy()
        nr.index = pd.to_datetime(nifty.index.date)
        # last per date
        nr = nr.groupby(level=0).last()
        tmp["nret20"] = tmp["dt"].map(nr)
        tmp["sret20"] = stock_ret.values
        tmp["rel_ok"] = tmp["sret20"] > tmp["nret20"]
        stocks[s] = tmp

    etf_idx = {
        s: data_raw[s]
        for s in ["^NSEI", "^NSEBANK", "NIFTYBEES.NS", "BANKBEES.NS"]
    }
    stock_plain = {s: data_raw[s] for s in STOCKS}
    uni_all = {s: data_raw[s] for s in ALL}

    rows = []

    def eval_tag(tag, data, builder, grid, max_hold):
        for params in grid:
            is_tr, oos_tr, wf_tr = pool(data, builder, params, max_hold=max_hold)
            is_s = compute_stats(is_tr, tag, "POOL", "IS", params)
            oos = compute_stats(oos_tr, tag, "POOL", "OOS", params)
            wf = compute_stats(wf_tr, tag, "POOL", "WF", params)
            keys = [k for k, v in params.items() if isinstance(v, (int, float))]
            pert = []
            for vp in param_perturb(params, keys, 0.2):
                _, ot, _ = pool(data, builder, vp, max_hold=max_hold)
                st = compute_stats(ot, tag, "POOL", "P", vp)
                if st.n_trades >= 25:
                    pert.append(st.expectancy > 0)
            pfrac = float(np.mean(pert)) if pert else 0.0
            row = dict(
                tag=tag,
                params=json.dumps(params),
                is_n=is_s.n_trades,
                is_exp=is_s.expectancy,
                is_pf=is_s.profit_factor,
                oos_n=oos.n_trades,
                oos_exp=oos.expectancy,
                oos_pf=oos.profit_factor,
                oos_wr=oos.win_rate,
                oos_mdd=oos.max_dd,
                oos_sharpe=oos.sharpe,
                oos_tot=oos.total_return,
                oos_hold=oos.avg_hold,
                wf_n=wf.n_trades,
                wf_exp=wf.expectancy,
                wf_pf=wf.profit_factor,
                wf_mdd=wf.max_dd,
                pert_frac=pfrac,
            )
            rows.append(row)
            mark = ""
            if (
                oos.expectancy > 0
                and wf.expectancy > 0
                and oos.n_trades >= 80
                and pfrac >= 0.5
                and oos.max_dd > -0.35
            ):
                mark = " *** EDGE ***"
            elif oos.expectancy > 0 and wf.expectancy > 0 and oos.n_trades >= 50:
                mark = " *partial*"
            print(f"{tag} {params} | OOS {fmt(oos)} | WF n={wf.n_trades} E={wf.expectancy*100:.3f}% pert+={pfrac:.0%}{mark}")

    print("=== Pass 4 ===")
    eval_tag(
        "donch_atr",
        stock_plain,
        donchian_atr_stop,
        [
            {"n": 55, "exit_n": 20, "atr_mult": 3.0},
            {"n": 55, "exit_n": 20, "atr_mult": 2.5},
            {"n": 20, "exit_n": 10, "atr_mult": 3.0},
            {"n": 55, "exit_n": 20, "atr_mult": 3.0, "rvol_min": 1.1},
        ],
        80,
    )
    eval_tag(
        "donch_niftyfilter",
        stocks,
        donchian_atr_stop,
        [
            {"n": 55, "exit_n": 20, "atr_mult": 3.0, "use_nifty": True},
            {"n": 20, "exit_n": 10, "atr_mult": 3.0, "use_nifty": True},
            {"n": 55, "exit_n": 20, "atr_mult": 2.5, "use_nifty": True, "rvol_min": 1.1},
        ],
        80,
    )
    eval_tag(
        "donch_strength",
        stock_plain,
        donchian_adxish,
        [
            {"n": 55, "exit_n": 20, "min_strength": 0.6},
            {"n": 55, "exit_n": 20, "min_strength": 1.0},
            {"n": 20, "exit_n": 10, "min_strength": 0.8},
        ],
        80,
    )
    eval_tag(
        "donch_strength_nifty",
        stocks,
        donchian_adxish,
        [
            {"n": 55, "exit_n": 20, "min_strength": 0.8, "use_nifty": True},
            {"n": 55, "exit_n": 20, "min_strength": 1.0, "use_nifty": True},
        ],
        80,
    )
    eval_tag(
        "rel_breakout",
        stocks,
        relative_breakout,
        [{"n": 20, "exit_n": 10}, {"n": 55, "exit_n": 20}],
        60,
    )
    eval_tag(
        "expansion_bo",
        stocks,
        expansion_breakout,
        [
            {"n": 20, "exit_n": 10, "exp": 1.2, "use_nifty": True},
            {"n": 20, "exit_n": 10, "exp": 1.5, "use_nifty": True, "rvol_min": 1.2},
            {"n": 55, "exit_n": 20, "exp": 1.2, "use_nifty": True},
        ],
        60,
    )
    eval_tag(
        "washout_mr",
        uni_all,
        washout_mr,
        [
            {"n": 10},
            {"n": 5},
            {"n": 10, "rvol_min": 1.3},
            {"n": 15, "rvol_min": 1.2},
        ],
        12,
    )
    eval_tag(
        "atr_band_fade",
        uni_all,
        atr_band_fade,
        [{"k": 1.5}, {"k": 2.0}, {"k": 2.5}],
        10,
    )
    eval_tag(
        "upfrac_mr",
        uni_all,
        rsi_proxy_mr,
        [{"window": 14, "thr": 0.30}, {"window": 14, "thr": 0.25}, {"window": 10, "thr": 0.30}],
        12,
    )

    df = pd.DataFrame(rows)
    df["score"] = (
        df["oos_exp"] * 1000
        + df["wf_exp"] * 800
        + np.minimum(df["oos_n"], 120) / 60
        + df["pert_frac"] * 2
        + df["oos_mdd"].clip(-0.5, 0) * 3
        + np.minimum(df["oos_pf"], 2.5)
    )
    df.loc[df["oos_exp"] <= 0, "score"] -= 10
    df.loc[df["wf_exp"] <= 0, "score"] -= 6
    df = df.sort_values("score", ascending=False)
    df.to_csv(RESULTS_DIR / "pass4.csv", index=False)

    print("\nTOP 20:")
    print(
        df[
            [
                "tag",
                "params",
                "oos_n",
                "oos_exp",
                "oos_pf",
                "oos_mdd",
                "wf_n",
                "wf_exp",
                "pert_frac",
                "score",
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    strict = df[
        (df["oos_exp"] > 0)
        & (df["wf_exp"] > 0)
        & (df["oos_n"] >= 80)
        & (df["pert_frac"] >= 0.5)
        & (df["oos_pf"] > 1.05)
        & (df["oos_mdd"] > -0.35)
    ]
    print("\nSTRICT:", "FOUND" if len(strict) else "NONE")
    if len(strict):
        print(strict.head(10).to_string(index=False))
        w = strict.iloc[0]
    else:
        part = df[(df["oos_exp"] > 0) & (df["wf_exp"] > 0) & (df["oos_n"] >= 40)]
        print("PARTIAL:")
        print(
            part[
                ["tag", "params", "oos_n", "oos_exp", "oos_pf", "oos_mdd", "wf_n", "wf_exp", "pert_frac"]
            ].head(15).to_string(index=False)
            if len(part)
            else "none"
        )
        w = part.iloc[0] if len(part) else df.iloc[0]

    meta = {
        "tag": w["tag"],
        "params": json.loads(w["params"]),
        "oos_n": int(w["oos_n"]),
        "oos_exp": float(w["oos_exp"]),
        "oos_pf": float(w["oos_pf"]),
        "oos_mdd": float(w["oos_mdd"]),
        "oos_wr": float(w["oos_wr"]),
        "wf_n": int(w["wf_n"]),
        "wf_exp": float(w["wf_exp"]),
        "pert_frac": float(w["pert_frac"]),
        "strict": len(strict) > 0,
    }
    (RESULTS_DIR / "pass4_winner.json").write_text(json.dumps(meta, indent=2))
    print("WINNER", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
