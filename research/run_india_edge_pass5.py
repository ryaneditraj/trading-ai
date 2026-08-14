#!/usr/bin/env python3
"""Pass 5: gap-and-go, ORB EOD, overnight, futures-cost index trend."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from india_edge_engine import (
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

STOCKS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
IDX = ["^NSEI", "^NSEBANK"]


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
        f"E={s.expectancy*100:6.3f}% MDD={s.max_dd*100:6.1f}% Sh={s.sharpe:5.2f} hold={s.avg_hold:.1f}"
    )


def pool(data, builder, params, max_hold, rt, wf_train=756, wf_test=252, n_folds=5):
    is_tr, oos_tr, wf_tr = [], [], []
    for df in data.values():
        train, test = time_split(df, 0.7)
        e, x, side = builder(train, params)
        is_tr += run_signal_backtest(train, e, x, side=side, rt_cost=rt, max_hold=max_hold)
        e, x, side = builder(test, params)
        oos_tr += run_signal_backtest(test, e, x, side=side, rt_cost=rt, max_hold=max_hold)
        for _, te in walk_forward_folds(df, n_folds=n_folds, train_bars=wf_train, test_bars=wf_test):
            e, x, side = builder(te, params)
            wf_tr += run_signal_backtest(te, e, x, side=side, rt_cost=rt, max_hold=max_hold)
    is_tr.sort(key=lambda t: t.entry_time)
    oos_tr.sort(key=lambda t: t.entry_time)
    wf_tr.sort(key=lambda t: t.entry_time)
    return is_tr, oos_tr, wf_tr


def gap_and_go(df, p):
    gap_min = float(p.get("gap_min", 0.005))
    rvol_min = float(p.get("rvol_min", 1.2))
    entries = (
        (df["gap"] >= gap_min)
        & (df["Close"] > df["Open"])
        & (df["Close"] > df["ema200"])
        & (df["rvol"] >= rvol_min)
        & (df["Close"] > df["prior_high"])
    )
    exits = (df["Close"] < df["ema20"]) | (df["Close"] < df["prior_low"])
    return entries, exits, 1


def overnight_uptrend(df, p):
    """Signal at close: buy next open, exit next close (max_hold=1)."""
    entries = (df["Close"] > df["ema200"]) & (df["Close"] > df["ema20"]) & (
        df["Close"] > df["Open"]
    )
    # Always exit next bar via max_hold=1; provide dummy exit never true except safety
    exits = pd.Series(False, index=df.index)
    return entries, exits, 1


def overnight_after_down(df, p):
    """Buy overnight only after down day in uptrend (mean-reversion overnight)."""
    entries = (
        (df["Close"] > df["ema200"])
        & (df["Close"] < df["Open"])
        & (df["Close"] < df["prior_close"])
    )
    exits = pd.Series(False, index=df.index)
    return entries, exits, 1


def intraday_long_bias(df, p):
    """Buy open sell close when prior close > EMA200 (open-to-close)."""
    # Signal on prior day; entry next open; exit same day close → max_hold=1
    entries = (df["Close"] > df["ema200"]) & (df["ema20"] > df["ema50"])
    exits = pd.Series(False, index=df.index)
    return entries, exits, 1


def donchian(df, p):
    n = int(p.get("n", 55))
    exit_n = int(p.get("exit_n", 20))
    hh = df["High"].rolling(n).max().shift(1)
    entries = (df["Close"] > hh) & (df["Close"] > df["ema200"])
    exits = df["Close"] < df["Low"].rolling(exit_n).min().shift(1)
    return entries, exits, 1


def orb_eod(df, p):
    rvol_min = float(p.get("rvol_min", 1.15))
    date = pd.to_datetime(df.index.date)
    tod = df.index.hour * 60 + df.index.minute
    tmp = df.copy()
    tmp["date"] = date
    first = tmp.groupby("date").head(1)
    orh = date.map(first.set_index("date")["High"])
    orl = date.map(first.set_index("date")["Low"])
    orh = pd.Series(orh, index=df.index)
    orl = pd.Series(orl, index=df.index)
    after = (tod >= 615) & (tod <= 840)
    entries = after & (df["Close"] > orh) & (df["rvol"] >= rvol_min) & (df["Close"] > df["ema20"])
    entries = entries & ~(df["Close"].shift(1) > orh.shift(1))
    # Exit EOD or OR low break
    exits = (df["Close"] < orl) | (tod >= 900)
    return entries, exits, 1


def orb_fade(df, p):
    """Fade failed ORB: break OR high then close back below by early afternoon."""
    rvol_min = float(p.get("rvol_min", 1.1))
    date = pd.to_datetime(df.index.date)
    tod = df.index.hour * 60 + df.index.minute
    tmp = df.copy()
    tmp["date"] = date
    first = tmp.groupby("date").head(1)
    orh = pd.Series(date.map(first.set_index("date")["High"]), index=df.index)
    orl = pd.Series(date.map(first.set_index("date")["Low"]), index=df.index)
    broke = (df["High"] > orh) & (tod >= 615)
    failed = broke.groupby(date).transform("max").astype(bool)  # any break so far — lookahead risk
    # safer: prior bar broke
    prior_broke = (df["High"].shift(1) > orh.shift(1)) & (tod.shift(1) >= 615)
    entries = (
        prior_broke
        & (df["Close"] < orh)
        & (tod >= 675)
        & (tod <= 840)
        & (df["rvol"] >= rvol_min)
        & (df["Close"] < df["ema20"])
    )
    exits = (df["Close"] > orh) | (tod >= 900)
    return entries, exits, -1


def main():
    daily_stocks = {s: clean(fetch_daily(s)) for s in STOCKS}
    daily_idx = {s: clean(fetch_daily(s)) for s in IDX}
    hourly_stocks = {s: add_structure_features(fetch_hourly(s)) for s in STOCKS}

    rows = []

    def run(tag, data, builder, grid, max_hold, rt, **wf):
        for params in grid:
            is_tr, oos_tr, wf_tr = pool(data, builder, params, max_hold, rt, **wf)
            is_s = compute_stats(is_tr, tag, "POOL", "IS", params)
            oos = compute_stats(oos_tr, tag, "POOL", "OOS", params)
            wfs = compute_stats(wf_tr, tag, "POOL", "WF", params)
            keys = [k for k, v in params.items() if isinstance(v, (int, float))]
            pert = []
            for vp in param_perturb(params, keys, 0.2) if keys else [params]:
                _, ot, _ = pool(data, builder, vp, max_hold, rt, **wf)
                st = compute_stats(ot, tag, "POOL", "P", vp)
                if st.n_trades >= 30:
                    pert.append(st.expectancy > 0)
            pfrac = float(np.mean(pert)) if pert else float("nan")
            row = dict(
                tag=tag,
                params=json.dumps(params),
                rt=rt,
                is_n=is_s.n_trades,
                is_exp=is_s.expectancy,
                oos_n=oos.n_trades,
                oos_exp=oos.expectancy,
                oos_pf=oos.profit_factor,
                oos_wr=oos.win_rate,
                oos_mdd=oos.max_dd,
                oos_sharpe=oos.sharpe,
                oos_hold=oos.avg_hold,
                wf_n=wfs.n_trades,
                wf_exp=wfs.expectancy,
                wf_pf=wfs.profit_factor,
                wf_mdd=wfs.max_dd,
                pert_frac=pfrac if pfrac == pfrac else 0.0,
            )
            rows.append(row)
            mark = ""
            if (
                oos.expectancy > 0
                and wfs.expectancy > 0
                and oos.n_trades >= 80
                and (pfrac == pfrac and pfrac >= 0.5)
                and oos.max_dd > -0.35
                and oos.profit_factor > 1.1
            ):
                mark = " *** EDGE ***"
            elif oos.expectancy > 0 and wfs.expectancy > 0 and oos.n_trades >= 50:
                mark = " *partial*"
            print(
                f"{tag} rt={rt*100:.2f}% {params} | OOS {fmt(oos)} | "
                f"WF n={wfs.n_trades} E={wfs.expectancy*100:.3f}% pert+={pfrac if pfrac==pfrac else 0:.0%}{mark}"
            )

    print("=== Gap and go (stocks) ===")
    run(
        "gap_and_go",
        daily_stocks,
        gap_and_go,
        [
            {"gap_min": 0.005, "rvol_min": 1.2},
            {"gap_min": 0.006, "rvol_min": 1.4},
            {"gap_min": 0.008, "rvol_min": 1.3},
        ],
        max_hold=8,
        rt=0.0008,
    )

    print("\n=== Overnight / open-close ===")
    run("overnight_up", daily_idx, overnight_uptrend, [{}], max_hold=1, rt=0.0003)
    run("overnight_up", daily_idx, overnight_uptrend, [{}], max_hold=1, rt=0.0008)
    run("overnight_up_stocks", daily_stocks, overnight_uptrend, [{}], max_hold=1, rt=0.0008)
    run("overnight_after_down", daily_idx, overnight_after_down, [{}], max_hold=1, rt=0.0003)
    run("overnight_after_down", daily_idx, overnight_after_down, [{}], max_hold=1, rt=0.0008)
    run("open_to_close_idx", daily_idx, intraday_long_bias, [{}], max_hold=1, rt=0.0003)
    run("open_to_close_idx", daily_idx, intraday_long_bias, [{}], max_hold=1, rt=0.0008)

    print("\n=== Index Donchian cost variants ===")
    for rt in [0.0003, 0.0005, 0.0008]:
        run(
            "donch_idx",
            daily_idx,
            donchian,
            [{"n": 20, "exit_n": 10}, {"n": 55, "exit_n": 20}],
            max_hold=80,
            rt=rt,
        )

    print("\n=== Stock Donchian 55/20 cost variants ===")
    for rt in [0.0003, 0.0008, 0.001]:
        run(
            "donch_stocks",
            daily_stocks,
            donchian,
            [{"n": 55, "exit_n": 20}],
            max_hold=80,
            rt=rt,
        )

    print("\n=== Hourly ORB / fade ===")
    run(
        "orb_eod",
        hourly_stocks,
        orb_eod,
        [{"rvol_min": 1.1}, {"rvol_min": 1.25}, {"rvol_min": 1.4}],
        max_hold=8,
        rt=0.0008,
        wf_train=1500,
        wf_test=500,
        n_folds=4,
    )
    run(
        "orb_fade",
        hourly_stocks,
        orb_fade,
        [{"rvol_min": 1.0}, {"rvol_min": 1.2}],
        max_hold=8,
        rt=0.0008,
        wf_train=1500,
        wf_test=500,
        n_folds=4,
    )

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "pass5.csv", index=False)

    print("\n=== BEST positive OOS+WF ===")
    pos = df[(df["oos_exp"] > 0) & (df["wf_exp"] > 0)].sort_values(
        by=["oos_n", "oos_exp"], ascending=False
    )
    cols = [
        "tag",
        "rt",
        "params",
        "oos_n",
        "oos_exp",
        "oos_pf",
        "oos_mdd",
        "wf_n",
        "wf_exp",
        "pert_frac",
    ]
    print(pos[cols].head(25).to_string(index=False) if len(pos) else "none")

    strict = df[
        (df["oos_exp"] > 0)
        & (df["wf_exp"] > 0)
        & (df["oos_n"] >= 80)
        & (df["pert_frac"] >= 0.5)
        & (df["oos_pf"] > 1.1)
        & (df["oos_mdd"] > -0.35)
    ]
    print("\nSTRICT EDGE:", "YES" if len(strict) else "NO")
    if len(strict):
        print(strict[cols].to_string(index=False))
        w = strict.sort_values("oos_exp", ascending=False).iloc[0]
    elif len(pos):
        # prefer more trades and better DD
        pos2 = pos.copy()
        pos2["rank"] = (
            pos2["oos_exp"] * 500
            + pos2["wf_exp"] * 500
            + np.minimum(pos2["oos_n"], 150) / 50
            + pos2["oos_mdd"].clip(-0.5, 0) * 2
            + pos2["pert_frac"]
        )
        w = pos2.sort_values("rank", ascending=False).iloc[0]
    else:
        w = df.sort_values("oos_exp", ascending=False).iloc[0]

    meta = {
        "tag": w["tag"],
        "params": json.loads(w["params"]),
        "rt": float(w["rt"]),
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
    (RESULTS_DIR / "pass5_winner.json").write_text(json.dumps(meta, indent=2))
    print("\nSELECTED:", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
