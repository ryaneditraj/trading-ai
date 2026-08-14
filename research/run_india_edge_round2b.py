#!/usr/bin/env python3
"""
Round 2b — refine top candidates from round2 with stricter honesty:
- param perturbation ±20%
- hybrid sleeves
- require not all WF damage in one chunk
- stress cost 0.15%
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from run_india_edge_round2 import (  # noqa: E402
    MAX_POS,
    RT,
    RT_STRESS,
    TRAIN_FRAC,
    UNIVERSE,
    add_adx,
    align_index_filter,
    baseline_donchian,
    breadth_series,
    clean,
    fmt,
    r2_combo_filters,
    r2_ema_pullback_thrust,
    r2_failed_bo_fade,
    r2_nifty_filter,
    r2_rvol_breakout,
    r2_slow_turtle,
    run_portfolio,
    strip,
    wf_chunks,
)
from india_edge_engine import RESULTS_DIR, fetch_daily, time_split  # noqa: E402


def r2_nifty_rvol(df, p):
    """Nifty bull + RVOL + Donchian."""
    entry_n = int(p.get("entry_n", 70))
    exit_n = int(p.get("exit_n", 25))
    rvol_min = float(p.get("rvol_min", 1.2))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (
        (df["Close"] > hh)
        & (df["Close"] > df["ema200"])
        & df["nifty_bull"].fillna(False)
        & (df["rvol"] >= rvol_min)
    )
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_nifty_adx_slow(df, p):
    entry_n = int(p.get("entry_n", 70))
    exit_n = int(p.get("exit_n", 25))
    adx_min = float(p.get("adx_min", 18))
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    e = (
        (df["Close"] > hh)
        & (df["Close"] > df["ema200"])
        & df["nifty_bull"].fillna(False)
        & (df["adx"] >= adx_min)
        & df["adx_rising"].fillna(False)
    )
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False)


def r2_failed_bd_nifty(df, p):
    """Failed breakdown fade only in Nifty bull regime."""
    e, x = r2_failed_bo_fade(df, p)
    e = e & df["nifty_bull"].fillna(False)
    return e, x


def r2_failed_bd_tight(df, p):
    """Failed BD with tighter 10d channel + EMA200."""
    n = int(p.get("entry_n", 15))
    hh = df["High"].rolling(n).max().shift(1)  # unused but keep structure
    ll = df["Low"].rolling(n).min().shift(1)
    broke_down = df["Close"].shift(1) < ll.shift(1)
    reclaim = df["Close"] > ll
    e = broke_down & reclaim & (df["Close"] > df["ema200"]) & (df["rvol"] >= float(p.get("rvol_min", 1.0)))
    x = (df["Close"] < ll) | (df["Close"] < df["Low"].rolling(3).min().shift(1))
    return e.fillna(False), x.fillna(False)


def hybrid_signals(df, p):
    """OR of slow Nifty Donchian and failed-BD fade; exit is OR of both exits when in trade.
    For portfolio engine we use combined entry; exit = either structure exit.
    """
    e1, x1 = r2_nifty_filter(df, {"entry_n": int(p.get("entry_n", 70)), "exit_n": int(p.get("exit_n", 25))})
    e2, x2 = r2_failed_bo_fade(df, {"entry_n": int(p.get("fade_n", 20))})
    # Prefer trend entries; fade only when no trend signal
    e = e1 | (e2 & ~e1)
    x = x1 | x2  # exit if either fires — may be early for fade; acceptable for research
    return e.fillna(False), x.fillna(False)


def perturb(base: dict, keys, pct=0.2):
    out = [dict(base)]
    for k in keys:
        if k not in base:
            continue
        v = base[k]
        for m in (1 - pct, 1 + pct):
            nv = dict(base)
            if isinstance(v, int):
                nv[k] = max(1, int(round(v * m)))
            else:
                nv[k] = float(v * m)
            out.append(nv)
    # dedupe
    seen, uniq = set(), []
    for p in out:
        t = tuple(sorted(p.items()))
        if t not in seen:
            seen.add(t)
            uniq.append(p)
    return uniq


def wf_positive_count(wf):
    return sum(1 for w in wf if w["expectancy"] > 0 and w["total_return"] > 0)


def evaluate(name, fn, params, stocks, oos_start, side=1, max_pos=MAX_POS):
    is_s = run_portfolio(
        stocks, fn, params, end_date=oos_start - pd.Timedelta(days=1),
        max_positions=max_pos, rt_cost=RT, side=side,
    )
    oos_s = run_portfolio(
        stocks, fn, params, start_date=oos_start,
        max_positions=max_pos, rt_cost=RT, side=side,
    )
    stress = run_portfolio(
        stocks, fn, params, start_date=oos_start,
        max_positions=max_pos, rt_cost=RT_STRESS, side=side,
    )
    wf = wf_chunks(run_portfolio, stocks, fn, params, oos_start, RT, side=side, n_chunks=3)
    # Strict: PF>=1.3, n>=50, Tot>0, stress PF>=1.2, at least 2/3 WF chunks positive expectancy
    o = strip(oos_s)
    strict = (
        o["n_trades"] >= 50
        and o["profit_factor"] >= 1.3
        and o["total_return"] > 0
        and stress["profit_factor"] >= 1.2
        and wf_positive_count(wf) >= 2
    )
    return {
        "name": name,
        "params": params,
        "IS": strip(is_s),
        "OOS": o,
        "stress": strip(stress),
        "wf": wf,
        "wf_pos": wf_positive_count(wf),
        "strict": strict,
    }


def main():
    print("=== ROUND 2b: refine + strict WF ===\n")
    nifty = add_adx(clean(fetch_daily("^NSEI")))
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
    print(f"OOS start {oos_start.date()}\n")

    specs = []

    # Grid around R2-02c Nifty+70/25
    for entry_n, exit_n in [(60, 20), (70, 25), (80, 30), (70, 20), (90, 30), (100, 40)]:
        specs.append((f"NiftyDonch {entry_n}/{exit_n}", r2_nifty_filter, {"entry_n": entry_n, "exit_n": exit_n}))

    # Nifty + RVOL grids
    for entry_n, exit_n, rv in [(70, 25, 1.2), (70, 25, 1.5), (55, 20, 1.2), (80, 30, 1.2)]:
        specs.append((f"NiftyRVOL {entry_n}/{exit_n} r{rv}", r2_nifty_rvol, {"entry_n": entry_n, "exit_n": exit_n, "rvol_min": rv}))

    # Nifty + ADX slow
    for entry_n, exit_n in [(70, 25), (80, 30)]:
        specs.append((f"NiftyADX {entry_n}/{exit_n}", r2_nifty_adx_slow, {"entry_n": entry_n, "exit_n": exit_n, "adx_min": 18}))

    # Failed BD variants
    for n in [15, 20, 25, 30]:
        specs.append((f"FailBD fade n={n}", r2_failed_bo_fade, {"entry_n": n, "max_hold": 5}))
    specs.append(("FailBD+Nifty n=20", r2_failed_bd_nifty, {"entry_n": 20, "max_hold": 5}))
    specs.append(("FailBD tight+EMA200", r2_failed_bd_tight, {"entry_n": 15, "rvol_min": 1.0}))
    specs.append(("FailBD tight RVOL1.2", r2_failed_bd_tight, {"entry_n": 15, "rvol_min": 1.2}))

    # Hybrid
    specs.append(("Hybrid Nifty70+FailBD", hybrid_signals, {"entry_n": 70, "exit_n": 25, "fade_n": 20}))
    specs.append(("Hybrid Nifty55+FailBD", hybrid_signals, {"entry_n": 55, "exit_n": 20, "fade_n": 20}))

    # Pullback thrust (stable WF earlier) with Nifty
    def pullback_nifty(df, p):
        e, x = r2_ema_pullback_thrust(df, p)
        return e & df["nifty_bull"].fillna(False), x

    specs.append(("Pullback thrust+Nifty", pullback_nifty, {"rvol_max": 0.85, "rvol_min": 1.2}))

    # Combo from R2-04 with slower
    specs.append(("Combo slow 70/25", r2_combo_filters, {"entry_n": 70, "exit_n": 25, "rvol_min": 1.2}))
    specs.append(("Slow turtle 100/50", r2_slow_turtle, {"entry_n": 100, "exit_n": 50}))
    specs.append(("Baseline 55/20", baseline_donchian, {"entry_n": 55, "exit_n": 20}))

    results = []
    for name, fn, params in specs:
        r = evaluate(name, fn, params, stocks, oos_start)
        results.append(r)
        mark = "STRICT" if r["strict"] else ("ok" if r["OOS"]["profit_factor"] >= 1.25 else "xx")
        print(f"[{mark}] {name}")
        print(f"  OOS {fmt(r['OOS'])}  stressPF={r['stress']['profit_factor']:.2f}  WF+={r['wf_pos']}/3")
        for w in r["wf"]:
            print(f"    {w['period']}: n={w['n_trades']} E={w['expectancy']*100:.2f}% Tot={w['total_return']*100:.1f}% MDD={w['max_dd']*100:.1f}%")
        print()

    # Perturb best strict / near-strict
    candidates_for_perturb = sorted(
        results,
        key=lambda r: (r["strict"], r["OOS"]["profit_factor"], r["wf_pos"], r["OOS"]["total_return"]),
        reverse=True,
    )[:5]

    print("=" * 70)
    print("PARAM PERTURBATION on top 5")
    perturb_rows = []
    for top in candidates_for_perturb:
        name, params = top["name"], top["params"]
        # find matching fn
        fn = None
        for n, f, p in specs:
            if n == name:
                fn = f
                break
        if fn is None:
            continue
        keys = [k for k in params if isinstance(params[k], (int, float))]
        print(f"\n-- {name} base {params} --")
        for pv in perturb(params, keys):
            r = evaluate(f"{name} {pv}", fn, pv, stocks, oos_start)
            perturb_rows.append({"parent": name, **{k: r[k] for k in ("params", "OOS", "stress", "wf_pos", "strict")}})
            print(
                f"  {pv}: PF={r['OOS']['profit_factor']:.2f} E={r['OOS']['expectancy']*100:.2f}% "
                f"n={r['OOS']['n_trades']} Tot={r['OOS']['total_return']*100:.1f}% "
                f"WF+={r['wf_pos']} strict={r['strict']}"
            )

    strict_passes = [r for r in results if r["strict"]]
    # Also count perturb strict
    strict_pert = [r for r in perturb_rows if r["strict"]]

    ranked = sorted(
        results,
        key=lambda r: (r["strict"], r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"]),
        reverse=True,
    )

    out = {
        "oos_start": str(oos_start.date()),
        "strict_passes": [r["name"] for r in strict_passes],
        "best": ranked[0]["name"] if ranked else None,
        "results": [
            {
                "name": r["name"],
                "params": r["params"],
                "strict": r["strict"],
                "wf_pos": r["wf_pos"],
                "IS": r["IS"],
                "OOS": r["OOS"],
                "stress": r["stress"],
                "wf": r["wf"],
            }
            for r in ranked
        ],
        "perturb_strict_count": len(strict_pert),
        "verdict": "EDGE_FOUND" if strict_passes else "NO_EDGE_FOUND",
    }
    path = RESULTS_DIR / "india_round2b_refine.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {path}")
    print(f"STRICT PASSES: {out['strict_passes']}")
    print(f"VERDICT: {out['verdict']} best={out['best']}")

    # Print honest summary of best regardless
    if ranked:
        b = ranked[0]
        print("\nBEST CANDIDATE DETAIL:")
        print(json.dumps({"name": b["name"], "params": b["params"], "OOS": b["OOS"], "stress": b["stress"], "wf": b["wf"], "strict": b["strict"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
