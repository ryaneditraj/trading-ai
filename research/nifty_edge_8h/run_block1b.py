#!/usr/bin/env python3
"""
Block 1b — deep refine on Block-1 winners + new variants.

Focus:
  - Supertrend ATR trail basket (mult grid + nifty gate on/off)
  - EMA ribbon basket
  - ATR expansion Donchian basket
  - Breadth-thrust gated Donchian on Nifty
  - NR7 thrust on index (price-only)
  - Hybrid: ADX Donchian + supertrend exit
  - Compare to buy&hold risk-adjusted

Writes strategies/nifty_edge_best.py + pinescript when beaten.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "strategies"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from india_edge_engine import (  # noqa: E402
    add_structure_features,
    compute_stats,
    fetch_daily,
    run_signal_backtest,
    time_split,
)
from hypotheses_b1 import (  # noqa: E402
    b1_05_atr_expansion,
    b1_06_nr7_thrust,
    b1_08_zscore_mr,
    b1_15_keltner,
    b1_16_supertrend,
    b1_24_breadth_thrust,
    b1_26_ema_ribbon,
)
from run_block1 import (  # noqa: E402
    LEADERBOARD,
    LOG,
    RESULTS,
    RT,
    RT_STRESS,
    TRAIN_FRAC,
    UNIVERSE,
    align_nifty,
    attach_rs_and_breadth,
    basket_signal_adx_donchian,
    buy_hold_stats,
    eval_single,
    log,
    prepare_symbol,
    run_portfolio,
    score_row,
    write_leaderboard,
)

OUT_STRAT = ROOT / "strategies"
OUT_PINE = ROOT / "pinescript"


def supertrend_bands(df: pd.DataFrame, mult: float) -> pd.Series:
    atr = df["atr"]
    hl2 = (df["High"] + df["Low"]) / 2.0
    basic_lb = hl2 - mult * atr
    final_lb = basic_lb.copy()
    close = df["Close"].values
    lb = basic_lb.values.copy()
    out = np.full(len(df), np.nan)
    for i in range(len(df)):
        if not np.isfinite(lb[i]):
            continue
        if i == 0 or not np.isfinite(out[i - 1]):
            out[i] = lb[i]
        elif close[i - 1] > out[i - 1]:
            out[i] = max(lb[i], out[i - 1])
        else:
            out[i] = lb[i]
    return pd.Series(out, index=df.index)


def sig_supertrend(df, p):
    mult = float(p.get("mult", 3.0))
    use_nifty = bool(p.get("use_nifty", True))
    use_ema = bool(p.get("use_ema200", True))
    final_lb = supertrend_bands(df, mult)
    regime = pd.Series(True, index=df.index)
    if use_ema:
        regime &= df["Close"] > df["ema200"]
    if use_nifty and "nifty_bull" in df.columns:
        regime &= df["nifty_bull"].fillna(False)
    e = (df["Close"] > final_lb) & (df["Close"].shift(1) <= final_lb.shift(1)) & regime
    x = df["Close"] < final_lb
    return e.fillna(False), x.fillna(False), 1


def sig_ema_ribbon(df, p):
    e, x, side = b1_26_ema_ribbon(df, p)
    if bool(p.get("use_nifty", True)) and "nifty_bull" in df.columns:
        e = e & df["nifty_bull"].fillna(False)
    if bool(p.get("adx_min", 0)):
        e = e & (df["adx"] >= float(p["adx_min"])) & df["adx_rising"].fillna(False)
    return e, x, side


def sig_atr_exp(df, p):
    e, x, side = b1_05_atr_expansion(df, p)
    if bool(p.get("use_nifty", True)) and "nifty_bull" in df.columns:
        e = e & df["nifty_bull"].fillna(False)
    return e, x, side


def sig_hybrid_adx_st(df, p):
    """Entry: ADX Donchian; Exit: supertrend OR Donchian low."""
    entry_n = int(p.get("entry_n", 70))
    exit_n = int(p.get("exit_n", 25))
    adx_min = float(p.get("adx_min", 18))
    mult = float(p.get("mult", 3.0))
    ema = df["Close"].ewm(span=200, adjust=False).mean()
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    regime = (df["Close"] > ema) & (df["adx"] >= adx_min) & df["adx_rising"].fillna(False)
    if "nifty_bull" in df.columns:
        regime = regime & df["nifty_bull"].fillna(False)
    e = (df["Close"] > hh) & regime
    st = supertrend_bands(df, mult)
    x = (df["Close"] < ll) | (df["Close"] < st)
    return e.fillna(False), x.fillna(False), 1


def sig_breadth_donchian(df, p):
    """Nifty-only: Donchian when breadth thrust recently fired."""
    entry_n = int(p.get("entry_n", 55))
    exit_n = int(p.get("exit_n", 20))
    thr = float(p.get("breadth_min", 0.65))
    if "breadth50" not in df.columns:
        z = pd.Series(False, index=df.index)
        return z, z, 1
    thrust = (df["breadth50"] >= thr).rolling(10).max().astype(bool)
    e = thrust & (df["Close"] > df["High"].rolling(entry_n).max().shift(1)) & (df["Close"] > df["ema200"])
    x = df["Close"] < df["Low"].rolling(exit_n).min().shift(1)
    return e.fillna(False), x.fillna(False), 1


def sig_keltner_adx(df, p):
    e, x, side = b1_15_keltner(df, p)
    adx_min = float(p.get("adx_min", 18))
    e = e & (df["adx"] >= adx_min) & df["adx_rising"].fillna(False)
    if "nifty_bull" in df.columns and bool(p.get("use_nifty", True)):
        e = e & df["nifty_bull"].fillna(False)
    return e, x, side


def portfolio_eval(name, data, fn, params, oos_start) -> dict:
    is_s = run_portfolio(data, fn, params, end_date=oos_start - pd.Timedelta(days=1))
    oos_s = run_portfolio(data, fn, params, start_date=oos_start)
    oos_st = run_portfolio(data, fn, params, start_date=oos_start, rt_cost=RT_STRESS)
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_portfolio(data, fn, params, start_date=dates[i], end_date=dates[i + 1])
        wf.append({"period": f"{dates[i].date()}→{dates[i+1].date()}", **st})
    return {
        "name": name,
        "params": params,
        "IS": is_s,
        "OOS": oos_s,
        "OOS_stress": oos_st,
        "wf": wf,
        "wf_pos": int(sum(1 for w in wf if w["expectancy"] > 0)),
        "wf_n": 3,
        "symbol": "BASKET20",
    }


def rank_key(r):
    o = r["OOS"]
    # Prefer PF, then WF+, then stress PF, then expectancy; penalize tiny n
    n_pen = 0 if o["n_trades"] >= 40 else -1.0
    return (
        n_pen,
        o["profit_factor"],
        r.get("wf_pos", 0),
        r["OOS_stress"]["profit_factor"],
        o["expectancy"],
        o["total_return"],
    )


def write_best_strategy(best: dict) -> None:
    """Persist Python + Pine for current #1."""
    params = best["params"]
    name = best["name"]
    oos = best["OOS"]
    py = f'''"""
Nifty Edge Best (Block 1 campaign)
==================================
Candidate: {name}
Params: {json.dumps(params)}

OOS (0.08% RT): n={oos["n_trades"]} PF={oos["profit_factor"]:.2f}
  exp={oos["expectancy"]*100:.2f}% tot={oos["total_return"]*100:.1f}%
  MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f}
Stress 0.15% RT PF={best["OOS_stress"]["profit_factor"]:.2f}
WF+={best.get("wf_pos")}/{best.get("wf_n")}

Honesty notes:
  - Next-open entry after signal close; exit on signal close (basket engine).
  - 2024-09→2026 chunk may still be fragile — check wf in results JSON.
  - Buy&hold ^NSEI OOS often beats total return; compare Sharpe/MDD.

Usage:
  python strategies/nifty_edge_best.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))

from run_block1 import (  # noqa: E402
    RESULTS,
    TRAIN_FRAC,
    UNIVERSE,
    align_nifty,
    log,
    prepare_symbol,
    run_portfolio,
    time_split,
)
from run_block1b import sig_supertrend, sig_ema_ribbon, sig_hybrid_adx_st, sig_atr_exp, sig_keltner_adx  # noqa: E402

PARAMS = {json.dumps(params, indent=4)}
NAME = {json.dumps(name)}

FN_MAP = {{
    "supertrend": sig_supertrend,
    "ema_ribbon": sig_ema_ribbon,
    "hybrid": sig_hybrid_adx_st,
    "atr_exp": sig_atr_exp,
    "keltner_adx": sig_keltner_adx,
}}


def pick_fn(name: str):
    n = name.lower()
    if "hybrid" in n:
        return sig_hybrid_adx_st
    if "ribbon" in n:
        return sig_ema_ribbon
    if "atr_exp" in n or "expansion" in n:
        return sig_atr_exp
    if "keltner" in n:
        return sig_keltner_adx
    return sig_supertrend


def main():
    nifty = prepare_symbol("^NSEI")
    stocks = {{s: align_nifty(prepare_symbol(s), nifty) for s in UNIVERSE}}
    _, oos_ref = time_split(stocks["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    fn = pick_fn(NAME)
    oos = run_portfolio(stocks, fn, PARAMS, start_date=oos_start)
    stress = run_portfolio(stocks, fn, PARAMS, start_date=oos_start, rt_cost=0.0015)
    print(json.dumps({{"name": NAME, "params": PARAMS, "OOS": oos, "OOS_stress": stress}}, indent=2, default=str))


if __name__ == "__main__":
    main()
'''
    (OUT_STRAT / "nifty_edge_best.py").write_text(py)

    # Pine — Supertrend-style or Donchian hybrid; default to supertrend long
    mult = float(params.get("mult", 3.0))
    pine = f'''//@version=5
strategy("Nifty Edge Best (Block1)", overlay=true, initial_capital=100000,
     commission_type=strategy.commission.percent, commission_value=0.04,
     slippage=2, process_orders_on_close=false)

// Research candidate: {name}
// Params: {json.dumps(params)}
// Python basket OOS PF≈{oos["profit_factor"]:.2f} — single-symbol Pine will NOT match basket.

atrLen = input.int(14, "ATR Length")
mult = input.float({mult}, "ATR Mult", step=0.1)
useEma = input.bool(true, "Require Close > EMA200")
emaLen = input.int(200, "EMA Length")

atr = ta.atr(atrLen)
hl2 = (high + low) / 2.0
var float finalLB = na
basicLB = hl2 - mult * atr
if na(finalLB)
    finalLB := basicLB
else if close[1] > finalLB[1]
    finalLB := math.max(basicLB, finalLB[1])
else
    finalLB := basicLB

ema = ta.ema(close, emaLen)
regime = not useEma or close > ema
longCond = ta.crossover(close, finalLB) and regime
exitCond = close < finalLB

if longCond
    strategy.entry("L", strategy.long)
if exitCond
    strategy.close("L")

plot(finalLB, "ST Lower", color=color.teal)
plot(ema, "EMA", color=color.orange)
'''
    (OUT_PINE / "nifty_edge_best.pine").write_text(pine)
    log(f"Wrote {OUT_STRAT / 'nifty_edge_best.py'} and {OUT_PINE / 'nifty_edge_best.pine'}")


def write_runner_up(path: Path, name: str, params: dict, fn_name: str, stats: dict) -> None:
    code = f'''"""
Runner-up: {name}
Params: {params}
OOS PF={stats["OOS"]["profit_factor"]:.2f} tot={stats["OOS"]["total_return"]*100:.1f}%
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from run_block1 import UNIVERSE, TRAIN_FRAC, align_nifty, prepare_symbol, run_portfolio, time_split
from run_block1b import {fn_name}

PARAMS = {json.dumps(params)}

def main():
    nifty = prepare_symbol("^NSEI")
    stocks = {{s: align_nifty(prepare_symbol(s), nifty) for s in UNIVERSE}}
    _, oos_ref = time_split(stocks["RELIANCE.NS"], TRAIN_FRAC)
    oos = run_portfolio(stocks, {fn_name}, PARAMS, start_date=oos_ref.index[0])
    print(json.dumps({{"name": {json.dumps(name)}, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
    path.write_text(code)


def main():
    log("=== Block 1b deep refine start ===")
    nifty_raw = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty_raw, bank, stocks_raw)
    stock_data = {s: align_nifty(df, nifty) for s, df in stocks_raw.items()}
    _, oos_ref = time_split(stock_data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    _, nifty_oos = time_split(nifty, TRAIN_FRAC)
    bh = buy_hold_stats(nifty_oos, "OOS")

    results = []

    # Supertrend grid
    for mult in (2.0, 2.5, 3.0, 3.5, 3.6, 4.0, 4.5, 5.0):
        for use_nifty in (True, False):
            for use_ema in (True, False):
                p = {"mult": mult, "use_nifty": use_nifty, "use_ema200": use_ema}
                name = f"ST_m{mult}_n{int(use_nifty)}_e{int(use_ema)}"
                r = portfolio_eval(name, stock_data, sig_supertrend, p, oos_start)
                results.append(r)
                log(f"  {name}: OOS n={r['OOS']['n_trades']} PF={r['OOS']['profit_factor']:.2f} "
                    f"tot={r['OOS']['total_return']*100:.1f}% WF+={r['wf_pos']}/3 "
                    f"stress={r['OOS_stress']['profit_factor']:.2f}")

    # EMA ribbon variants
    for adx_min in (0, 15, 18, 22):
        for use_nifty in (True, False):
            p = {"use_nifty": use_nifty, "adx_min": adx_min}
            name = f"RIBBON_adx{adx_min}_n{int(use_nifty)}"
            r = portfolio_eval(name, stock_data, sig_ema_ribbon, p, oos_start)
            results.append(r)
            log(f"  {name}: OOS n={r['OOS']['n_trades']} PF={r['OOS']['profit_factor']:.2f} "
                f"tot={r['OOS']['total_return']*100:.1f}% WF+={r['wf_pos']}/3")

    # ATR expansion grid
    for n in (15, 20, 25, 40):
        for rank_max in (0.2, 0.3, 0.4):
            p = {"n": n, "rank_max": rank_max, "use_nifty": True}
            name = f"ATREXP_n{n}_r{rank_max}"
            r = portfolio_eval(name, stock_data, sig_atr_exp, p, oos_start)
            results.append(r)
            log(f"  {name}: OOS n={r['OOS']['n_trades']} PF={r['OOS']['profit_factor']:.2f} "
                f"tot={r['OOS']['total_return']*100:.1f}% WF+={r['wf_pos']}/3")

    # Hybrid ADX entry + ST exit
    for entry_n, exit_n, mult, adx_min in [
        (70, 25, 3.0, 18),
        (70, 25, 3.6, 18),
        (55, 20, 3.0, 18),
        (80, 30, 3.5, 20),
        (70, 25, 4.0, 15),
    ]:
        p = {"entry_n": entry_n, "exit_n": exit_n, "mult": mult, "adx_min": adx_min}
        name = f"HYBRID_{entry_n}_{exit_n}_m{mult}_a{adx_min}"
        r = portfolio_eval(name, stock_data, sig_hybrid_adx_st, p, oos_start)
        results.append(r)
        log(f"  {name}: OOS n={r['OOS']['n_trades']} PF={r['OOS']['profit_factor']:.2f} "
            f"tot={r['OOS']['total_return']*100:.1f}% WF+={r['wf_pos']}/3")

    # Keltner + ADX
    for mult in (1.5, 2.0, 2.5):
        for adx_min in (15, 18, 22):
            p = {"n": 20, "mult": mult, "adx_min": adx_min, "use_nifty": True}
            name = f"KELT_m{mult}_a{adx_min}"
            r = portfolio_eval(name, stock_data, sig_keltner_adx, p, oos_start)
            results.append(r)
            log(f"  {name}: OOS n={r['OOS']['n_trades']} PF={r['OOS']['profit_factor']:.2f} "
                f"tot={r['OOS']['total_return']*100:.1f}% WF+={r['wf_pos']}/3")

    # Index-only candidates
    index_rows = []
    for label, fn, params, mh in [
        ("IDX_breadth_donchian", sig_breadth_donchian, {"entry_n": 55, "exit_n": 20, "breadth_min": 0.65}, 80),
        ("IDX_breadth_donchian_70", sig_breadth_donchian, {"entry_n": 70, "exit_n": 25, "breadth_min": 0.60}, 100),
        ("IDX_nr7", b1_06_nr7_thrust, {}, 15),
        ("IDX_zscore", b1_08_zscore_mr, {"z": -2.0}, 10),
        ("IDX_zscore_25", b1_08_zscore_mr, {"z": -2.5}, 10),
        ("IDX_keltner", b1_15_keltner, {"n": 20, "mult": 1.5}, 40),
        ("IDX_st_3.6", b1_16_supertrend, {"mult": 3.6}, 80),
    ]:
        r = eval_single(label, nifty, fn, params, mh)
        r["symbol"] = "^NSEI"
        r["family"] = "index"
        # attach stress already in eval
        index_rows.append(r)
        o = r["OOS"]
        log(f"  {label}: OOS n={o['n_trades']} PF={o['profit_factor']:.2f} "
            f"tot={o['total_return']*100:.1f}% WF={r['wf_pos']}/{r['wf_n']}")

    # Baseline reference
    base = portfolio_eval("BASELINE_ADX_DON_70_25", stock_data, basket_signal_adx_donchian,
                          {"entry_n": 70, "exit_n": 25, "adx_min": 18}, oos_start)
    results.append(base)

    (RESULTS / "block1b_refine.json").write_text(json.dumps({"basket": results, "index": index_rows}, indent=2, default=str))

    ranked = sorted(results, key=rank_key, reverse=True)
    log("--- Top 10 basket ---")
    for r in ranked[:10]:
        o = r["OOS"]
        log(f"  {r['name']}: PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
            f"n={o['n_trades']} MDD={o['max_dd']*100:.1f}% WF+={r['wf_pos']}/3 "
            f"stressPF={r['OOS_stress']['profit_factor']:.2f}")

    best = ranked[0]
    # Require beats baseline PF or clearly better WF, and n>=40 preferred
    if best["OOS"]["n_trades"] < 35:
        for r in ranked:
            if r["OOS"]["n_trades"] >= 40 and r["OOS"]["profit_factor"] >= 1.3:
                best = r
                break

    log(f"Selected #1: {best['name']} PF={best['OOS']['profit_factor']:.2f} n={best['OOS']['n_trades']}")
    for w in best["wf"]:
        log(f"  WF {w['period']}: exp={w['expectancy']*100:.2f}% tot={w['total_return']*100:.1f}% n={w['n_trades']}")

    write_best_strategy(best)

    # Runner-ups
    runners = []
    for r in ranked[1:]:
        if r["OOS"]["profit_factor"] >= 1.4 and r["OOS"]["n_trades"] >= 40 and r["name"] != best["name"]:
            runners.append(r)
        if len(runners) >= 3:
            break
    fn_guess = {
        "ST_": ("sig_supertrend", "nifty_edge_r1.py"),
        "RIBBON": ("sig_ema_ribbon", "nifty_edge_r2.py"),
        "ATREXP": ("sig_atr_exp", "nifty_edge_r3.py"),
        "HYBRID": ("sig_hybrid_adx_st", "nifty_edge_r1.py"),
        "KELT": ("sig_keltner_adx", "nifty_edge_r2.py"),
        "BASELINE": ("basket_signal_adx_donchian", "nifty_edge_r3.py"),
    }
    used = set()
    for i, r in enumerate(runners):
        for prefix, (fn, fname) in fn_guess.items():
            if r["name"].startswith(prefix) and fname not in used:
                write_runner_up(OUT_STRAT / fname, r["name"], r["params"], fn, r)
                used.add(fname)
                log(f"Runner-up saved {fname}: {r['name']}")
                break

    # Update leaderboard appendix
    lb = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    extra = [
        "",
        "## Block 1b deep refine — top basket",
        "",
        "| Rank | Name | OOS n | PF | Exp | Tot | MDD | Stress PF | WF+ |",
        "|-----:|------|------:|---:|----:|----:|----:|----------:|----:|",
    ]
    for i, r in enumerate(ranked[:15], 1):
        o = r["OOS"]
        extra.append(
            f"| {i} | {r['name']} | {o['n_trades']} | {o['profit_factor']:.2f} | "
            f"{o['expectancy']*100:.2f}% | {o['total_return']*100:.1f}% | {o['max_dd']*100:.1f}% | "
            f"{r['OOS_stress']['profit_factor']:.2f} | {r['wf_pos']}/3 |"
        )
    extra += [
        "",
        f"**Buy&hold ^NSEI OOS:** tot={bh['total_return']*100:.1f}% MDD={bh['max_dd']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        f"**Block1 #1:** `{best['name']}` — see `strategies/nifty_edge_best.py`",
        "",
        "### Honesty vs buy&hold",
        f"- B&H total return ({bh['total_return']*100:.1f}%) often exceeds active tot; edge claim is on **PF/expectancy/MDD control**, not raw CAGR dominance.",
        f"- Baseline last WF chunk 2024-09→2026 still a known failure mode — any #1 must show WF detail.",
        "",
    ]
    LEADERBOARD.write_text(lb + "\n".join(extra))

    summary = {
        "best": best,
        "top10": ranked[:10],
        "buy_hold": bh,
        "index_top": sorted(index_rows, key=score_row, reverse=True)[:5],
    }
    (RESULTS / "block1b_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log("=== Block 1b complete ===")
    return summary


if __name__ == "__main__":
    main()
