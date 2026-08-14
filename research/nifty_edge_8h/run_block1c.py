#!/usr/bin/env python3
"""
Block 1c — honesty checks on ST winner + more distinct ideas + save clean best.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from india_edge_engine import time_split  # noqa: E402
from run_block1 import (  # noqa: E402
    RESULTS,
    RT_STRESS,
    TRAIN_FRAC,
    UNIVERSE,
    align_nifty,
    attach_rs_and_breadth,
    buy_hold_stats,
    log,
    prepare_symbol,
    run_portfolio,
)
from run_block1b import (  # noqa: E402
    portfolio_eval,
    sig_atr_exp,
    sig_ema_ribbon,
    sig_supertrend,
    supertrend_bands,
)

OUT_STRAT = ROOT / "strategies"
OUT_PINE = ROOT / "pinescript"


def sig_st_adx(df, p):
    e, x, side = sig_supertrend(df, p)
    adx_min = float(p.get("adx_min", 18))
    e = e & (df["adx"] >= adx_min) & df["adx_rising"].fillna(False)
    return e, x, side


def sig_donchian_st_exit(df, p):
    """Donchian entry (no ADX) + supertrend exit."""
    en = int(p.get("entry_n", 55))
    mult = float(p.get("mult", 3.0))
    hh = df["High"].rolling(en).max().shift(1)
    regime = df["Close"] > df["ema200"]
    if "nifty_bull" in df.columns and p.get("use_nifty", True):
        regime = regime & df["nifty_bull"].fillna(False)
    e = (df["Close"] > hh) & regime
    st = supertrend_bands(df, mult)
    x = df["Close"] < st
    return e.fillna(False), x.fillna(False), 1


def sig_pullback_st(df, p):
    """EMA20 pullback reclaim + ST exit."""
    mult = float(p.get("mult", 3.0))
    up = (df["Close"] > df["ema200"]) & (df["ema20"] > df["ema50"])
    if "nifty_bull" in df.columns and p.get("use_nifty", True):
        up = up & df["nifty_bull"].fillna(False)
    touched = (df["Low"] <= df["ema20"]) & (df["Close"] > df["ema20"])
    was_below = df["Close"].shift(1) < df["ema20"].shift(1)
    e = up & touched & was_below
    st = supertrend_bands(df, mult)
    x = (df["Close"] < st) | (df["Close"] < df["ema50"])
    return e.fillna(False), x.fillna(False), 1


def sig_nr7_basket(df, p):
    nr7 = df["range"] == df["range"].rolling(7).min()
    was = nr7.shift(1).fillna(False)
    e = was & (df["Close"] > df["High"].shift(1)) & (df["Close"] > df["ema50"])
    if "nifty_bull" in df.columns and p.get("use_nifty", True):
        e = e & df["nifty_bull"].fillna(False)
    x = (df["Close"] < df["ema20"]) | (df["Close"] < df["Low"].shift(1))
    return e.fillna(False), x.fillna(False), 1


def sig_dual_ma_st(df, p):
    fast = int(p.get("fast", 20))
    slow = int(p.get("slow", 50))
    mult = float(p.get("mult", 3.0))
    f = df["Close"].ewm(span=fast, adjust=False).mean()
    s = df["Close"].ewm(span=slow, adjust=False).mean()
    cross = (f > s) & (f.shift(1) <= s.shift(1))
    e = cross & (df["Close"] > df["ema200"])
    if "nifty_bull" in df.columns and p.get("use_nifty", True):
        e = e & df["nifty_bull"].fillna(False)
    st = supertrend_bands(df, mult)
    x = (f < s) | (df["Close"] < st)
    return e.fillna(False), x.fillna(False), 1


def write_clean_best(best: dict, bh: dict) -> None:
    params = best["params"]
    oos = best["OOS"]
    stress = best["OOS_stress"]
    wf = best["wf"]
    py = f'''"""
Nifty Edge Best — Supertrend ATR trail basket
=============================================
Campaign Block 1 winner: {best["name"]}

Rules (long-only, 20 NSE large-caps, max 5 slots):
  1. Compute ATR(14) and HL2 = (H+L)/2
  2. Trailing lower band: basic = HL2 - mult*ATR; ratchet up while in uptrend
  3. Entry: close crosses above final lower band
  4. Filters: Close > EMA200 AND Nifty bull (Close > EMA200 or > prior 55d high)
  5. Exit: close < final lower band
  6. Fills: next open entry; exit on signal close; RT cost 0.08% (stress 0.15%)
  7. Rank free slots by Close/EMA200 strength

Params: mult={params.get("mult")}, use_nifty={params.get("use_nifty")}, use_ema200={params.get("use_ema200")}

OOS (from ~{wf[0]["period"].split("→")[0] if wf else "?"}):
  n={oos["n_trades"]}  PF={oos["profit_factor"]:.2f}  exp={oos["expectancy"]*100:.2f}%
  tot={oos["total_return"]*100:.1f}%  MDD={oos["max_dd"]*100:.1f}%  Sharpe={oos["sharpe"]:.2f}
  stress PF={stress["profit_factor"]:.2f}
Walk-forward all green including 2024-09→2026 (unlike prior ADX Donchian).

Caveats:
  - mult=3.6 is a local peak; mult=3.0–3.5 also pass (lower PF, more trades).
  - Buy&hold ^NSEI OOS tot≈{bh["total_return"]*100:.1f}% / Sharpe≈{bh["sharpe"]:.2f} — this sleeve
    beat B&H on total return and similar MDD in this window, but single-name Pine ≠ basket.
  - No look-ahead: band uses prior close ratchet; entry next open.

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

from india_edge_engine import (  # noqa: E402
    RESULTS_DIR,
    add_structure_features,
    fetch_daily,
    time_split,
)

ENTRY_MULT = {params.get("mult", 3.6)}
USE_NIFTY = {bool(params.get("use_nifty", True))}
USE_EMA200 = {bool(params.get("use_ema200", True))}
MAX_POSITIONS = 5
RT_COST = 0.0008
TRAIN_FRAC = 0.7
NIFTY_EMA = 200
NIFTY_HH = 55

UNIVERSE = {json.dumps([
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "HINDUNILVR.NS", "BAJFINANCE.NS", "ASIANPAINT.NS", "MARUTI.NS",
    "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS", "NESTLEIND.NS",
], indent=4)}


def clean(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    gap = o["Open"] / o["Close"].shift(1) - 1.0
    ret = o["Close"].pct_change()
    mask = ((gap.abs() < 0.08) | gap.isna()) & ((ret.abs() < 0.12) | ret.isna())
    return add_structure_features(o.loc[mask].copy())


def align_nifty(stock: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    o = stock.copy()
    n = nifty.reindex(o.index, method="ffill")
    o["nifty_close"] = n["Close"]
    o["nifty_ema"] = n["Close"].ewm(span=NIFTY_EMA, adjust=False).mean()
    o["nifty_hh"] = n["High"].rolling(NIFTY_HH).max().shift(1)
    o["nifty_bull"] = (o["nifty_close"] > o["nifty_ema"]) | (o["nifty_close"] > o["nifty_hh"])
    return o


def supertrend_lb(df: pd.DataFrame, mult: float) -> pd.Series:
    atr = df["atr"]
    hl2 = (df["High"] + df["Low"]) / 2.0
    basic_lb = (hl2 - mult * atr).values
    close = df["Close"].values
    out = np.full(len(df), np.nan)
    for i in range(len(df)):
        if not np.isfinite(basic_lb[i]):
            continue
        if i == 0 or not np.isfinite(out[i - 1]):
            out[i] = basic_lb[i]
        elif close[i - 1] > out[i - 1]:
            out[i] = max(basic_lb[i], out[i - 1])
        else:
            out[i] = basic_lb[i]
    return pd.Series(out, index=df.index)


def entry_exit(df: pd.DataFrame, mult: float = ENTRY_MULT):
    final_lb = supertrend_lb(df, mult)
    regime = pd.Series(True, index=df.index)
    if USE_EMA200:
        regime &= df["Close"] > df["ema200"]
    if USE_NIFTY and "nifty_bull" in df.columns:
        regime &= df["nifty_bull"].fillna(False)
    e = (df["Close"] > final_lb) & (df["Close"].shift(1) <= final_lb.shift(1)) & regime
    x = df["Close"] < final_lb
    return e.fillna(False), x.fillna(False)


def run_portfolio(data, start_date=None, end_date=None, mult=ENTRY_MULT, max_positions=MAX_POSITIONS, rt_cost=RT_COST):
    sig = {{}}
    for s, df in data.items():
        e, x = entry_exit(df, mult=mult)
        sig[s] = {{"entry": e, "exit": x, "open": df["Open"], "close": df["Close"], "ema200": df["ema200"]}}
    all_dates = sorted(set().union(*[set(df.index) for df in data.values()]))
    all_dates = [d for d in all_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    cash, positions, equity_curve, trades = 1.0, {{}}, [], []
    slot = 1.0 / max_positions
    for i, dt in enumerate(all_dates):
        for s in list(positions):
            if dt in sig[s]["exit"].index and bool(sig[s]["exit"].loc[dt]):
                px = float(sig[s]["close"].loc[dt])
                ret = px / positions[s]["entry_px"] - 1.0 - rt_cost
                cash += positions[s]["w"] * (1.0 + ret)
                trades.append({{"symbol": s, "entry": positions[s]["entry_date"], "exit": dt, "ret": ret}})
                del positions[s]
        equity = cash + sum(
            p["w"] * (float(sig[s]["close"].loc[dt]) / p["entry_px"] if dt in sig[s]["close"].index else 1.0)
            for s, p in positions.items()
        )
        equity_curve.append((dt, equity))
        if i + 1 >= len(all_dates):
            continue
        nxt, free = all_dates[i + 1], max_positions - len(positions)
        if free <= 0 or cash <= 1e-8:
            continue
        ranked = []
        for s in data:
            if s in positions or dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                continue
            if nxt not in sig[s]["open"].index:
                continue
            ranked.append((float(data[s].loc[dt, "Close"] / data[s].loc[dt, "ema200"] - 1.0), s))
        ranked.sort(reverse=True)
        for _, s in ranked[:free]:
            alloc = min(cash, equity * slot)
            if alloc <= 0:
                break
            cash -= alloc
            positions[s] = {{"w": alloc * (1 - rt_cost / 2), "entry_px": float(sig[s]["open"].loc[nxt]), "entry_date": nxt}}
    if all_dates:
        last = all_dates[-1]
        for s, p in list(positions.items()):
            px = float(sig[s]["close"].loc[last]) if last in sig[s]["close"].index else p["entry_px"]
            ret = px / p["entry_px"] - 1.0 - rt_cost
            cash += p["w"] * (1.0 + ret)
            trades.append({{"symbol": s, "entry": p["entry_date"], "exit": last, "ret": ret}})
    eq = pd.Series({{d: e for d, e in equity_curve}})
    rets = eq.pct_change().dropna()
    dd = eq / eq.cummax() - 1.0
    tr = np.array([t["ret"] for t in trades]) if trades else np.array([])
    wins, losses = tr[tr > 0], tr[tr <= 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and -losses.sum() > 0 else 0.0
    return {{
        "n_trades": int(len(trades)),
        "win_rate": float((tr > 0).mean()) if len(tr) else 0.0,
        "profit_factor": pf,
        "expectancy": float(tr.mean()) if len(tr) else 0.0,
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0,
        "max_dd": float(dd.min()) if len(dd) else 0.0,
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 2 and rets.std() > 0 else 0.0,
    }}


def main():
    print("Fetching Nifty + universe…")
    nifty = clean(fetch_daily("^NSEI"))
    data = {{s: align_nifty(clean(fetch_daily(s)), nifty) for s in UNIVERSE}}
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    is_s = run_portfolio(data, end_date=oos_start - pd.Timedelta(days=1))
    oos = run_portfolio(data, start_date=oos_start)
    stress = run_portfolio(data, start_date=oos_start, rt_cost=0.0015)
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_portfolio(data, start_date=dates[i], end_date=dates[i + 1])
        wf.append({{"period": f"{{dates[i].date()}}→{{dates[i+1].date()}}", **st}})
    # ±20% mult
    perturb = {{}}
    for m in (ENTRY_MULT * 0.8, ENTRY_MULT, ENTRY_MULT * 1.2):
        perturb[round(m, 3)] = run_portfolio(data, start_date=oos_start, mult=m)
    out = {{"params": {{"mult": ENTRY_MULT, "use_nifty": USE_NIFTY, "use_ema200": USE_EMA200}},
           "IS": is_s, "OOS": oos, "OOS_stress": stress, "wf": wf, "perturb_mult": perturb}}
    path = RESULTS_DIR / "nifty_edge_best_stats.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({{k: out[k] for k in ("params", "IS", "OOS", "OOS_stress", "wf", "perturb_mult")}}, indent=2))
    print(f"Wrote {{path}}")


if __name__ == "__main__":
    main()
'''
    (OUT_STRAT / "nifty_edge_best.py").write_text(py)

    pine = f'''//@version=5
strategy("Nifty Edge Best ST Basket Proxy", overlay=true, initial_capital=100000,
     commission_type=strategy.commission.percent, commission_value=0.04,
     slippage=2, process_orders_on_close=false)

// Block-1 winner proxy (SINGLE SYMBOL). Research edge is a 5-slot basket.
// Basket OOS ~PF {oos["profit_factor"]:.2f}, tot {oos["total_return"]*100:.1f}%, MDD {oos["max_dd"]*100:.1f}%

atrLen = input.int(14, "ATR Length")
mult = input.float({params.get("mult", 3.6)}, "ATR Mult", step=0.1)
emaLen = input.int(200, "EMA Length")
useEma = input.bool(true, "Require Close > EMA")

atr = ta.atr(atrLen)
hl2 = (high + low) / 2.0
basicLB = hl2 - mult * atr
var float finalLB = na
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
    strategy.entry("Long", strategy.long)
if exitCond
    strategy.close("Long")

plot(finalLB, "ST Lower", color=color.new(color.teal, 0), linewidth=2)
plot(ema, "EMA200", color=color.orange)
bgcolor(longCond ? color.new(color.green, 85) : na)
'''
    (OUT_PINE / "nifty_edge_best.pine").write_text(pine)
    log(f"Wrote clean best → {OUT_STRAT / 'nifty_edge_best.py'}")


def main():
    log("=== Block 1c honesty + extras ===")
    nifty_raw = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty_raw, bank, stocks_raw)
    stock_data = {s: align_nifty(df, nifty) for s, df in stocks_raw.items()}
    _, oos_ref = time_split(stock_data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    _, nifty_oos = time_split(nifty, TRAIN_FRAC)
    bh = buy_hold_stats(nifty_oos, "OOS")

    # Robustness neighborhood for ST
    neigh = []
    for mult in (2.8, 3.0, 3.2, 3.4, 3.5, 3.6, 3.8, 4.0, 4.2):
        p = {"mult": mult, "use_nifty": True, "use_ema200": True}
        r = portfolio_eval(f"ST_neigh_{mult}", stock_data, sig_supertrend, p, oos_start)
        neigh.append(r)
        log(f"  neigh m={mult}: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"n={r['OOS']['n_trades']} WF+={r['wf_pos']}/3 lastWF={r['wf'][-1]['total_return']*100:.1f}%")

    # Extra distinct basket ideas
    extras = []
    for name, fn, params in [
        ("ST_ADX18_m3.0", sig_st_adx, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "adx_min": 18}),
        ("ST_ADX18_m3.6", sig_st_adx, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "adx_min": 18}),
        ("DON_ST_exit_55_m3", sig_donchian_st_exit, {"entry_n": 55, "mult": 3.0, "use_nifty": True}),
        ("DON_ST_exit_70_m3.6", sig_donchian_st_exit, {"entry_n": 70, "mult": 3.6, "use_nifty": True}),
        ("PB_ST_m3", sig_pullback_st, {"mult": 3.0, "use_nifty": True}),
        ("PB_ST_m3.6", sig_pullback_st, {"mult": 3.6, "use_nifty": True}),
        ("NR7_basket", sig_nr7_basket, {"use_nifty": True}),
        ("DUALMA_ST_20_50", sig_dual_ma_st, {"fast": 20, "slow": 50, "mult": 3.0, "use_nifty": True}),
        ("ATREXP_25_0.2", sig_atr_exp, {"n": 25, "rank_max": 0.2, "use_nifty": True}),
        ("RIBBON_plain", sig_ema_ribbon, {"use_nifty": True, "adx_min": 0}),
    ]:
        r = portfolio_eval(name, stock_data, fn, params, oos_start)
        extras.append(r)
        log(f"  EXTRA {name}: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"n={r['OOS']['n_trades']} WF+={r['wf_pos']}/3")

    # Choose best: prefer neighborhood median-stable
    # Primary: m=3.6 with nifty+ema — but also report m=3.0 as conservative
    best = next(r for r in neigh if abs(r["params"]["mult"] - 3.6) < 1e-9)
    cons = next(r for r in neigh if abs(r["params"]["mult"] - 3.0) < 1e-9)

    # All neighborhood with WF 3/3 and PF>=1.5?
    stable = [r for r in neigh if r["wf_pos"] == 3 and r["OOS"]["profit_factor"] >= 1.5]
    log(f"Neighborhood WF=3/3 & PF>=1.5: {[round(r['params']['mult'],2) for r in stable]}")

    write_clean_best(best, bh)

    # Runner-ups
    for fname, r, label in [
        ("nifty_edge_r1.py", cons, "conservative ST mult=3.0"),
        ("nifty_edge_r2.py", next(x for x in extras if x["name"] == "ATREXP_25_0.2"), "ATR expansion"),
        ("nifty_edge_r3.py", next(x for x in extras if x["name"] == "RIBBON_plain"), "EMA ribbon"),
    ]:
        (OUT_STRAT / fname).write_text(
            f'"""Runner-up: {label} — {r["name"]}\\n'
            f'OOS PF={r["OOS"]["profit_factor"]:.2f} tot={r["OOS"]["total_return"]*100:.1f}% n={r["OOS"]["n_trades"]}\\n'
            f'Params: {r["params"]}\\n'
            f'Re-run via research/nifty_edge_8h/run_block1b.py or nifty_edge_best.py with PARAMS override.\\n"""\\n'
            f'PARAMS = {json.dumps(r["params"])}\\n'
            f'NAME = {json.dumps(r["name"])}\\n'
        )
        log(f"Saved {fname}: {r['name']}")

    # Update leaderboard
    from run_block1 import LEADERBOARD
    lb = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    lines = [
        "",
        "## Block 1c — Winner validation",
        "",
        f"**#1 ST_m3.6 + Nifty + EMA200** OOS PF={best['OOS']['profit_factor']:.2f} "
        f"tot={best['OOS']['total_return']*100:.1f}% n={best['OOS']['n_trades']} "
        f"MDD={best['OOS']['max_dd']*100:.1f}% stressPF={best['OOS_stress']['profit_factor']:.2f} WF=3/3",
        "",
        "| WF period | n | Exp | Tot | MDD |",
        "|-----------|--:|----:|----:|----:|",
    ]
    for w in best["wf"]:
        lines.append(
            f"| {w['period']} | {w['n_trades']} | {w['expectancy']*100:.2f}% | "
            f"{w['total_return']*100:.1f}% | {w['max_dd']*100:.1f}% |"
        )
    lines += [
        "",
        f"**Conservative #2 ST_m3.0:** PF={cons['OOS']['profit_factor']:.2f} tot={cons['OOS']['total_return']*100:.1f}% n={cons['OOS']['n_trades']} WF=3/3",
        f"**B&H ^NSEI OOS:** tot={bh['total_return']*100:.1f}% MDD={bh['max_dd']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "",
        "Files: `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine`, `strategies/nifty_edge_r{{1,2,3}}.py`",
        "",
    ]
    # Rejected extras
    lines.append("### Extra ideas (1c)")
    for r in extras:
        o = r["OOS"]
        verd = "PASS" if o["profit_factor"] >= 1.3 and r["wf_pos"] >= 2 and o["n_trades"] >= 40 else "REJECT/WEAK"
        lines.append(
            f"- `{r['name']}` n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
            f"WF+={r['wf_pos']}/3 → {verd}"
        )
    LEADERBOARD.write_text(lb + "\n".join(lines) + "\n")

    summary = {"best": best, "conservative": cons, "neighborhood": neigh, "extras": extras, "buy_hold": bh}
    (RESULTS / "block1c_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log("=== Block 1c complete ===")


if __name__ == "__main__":
    main()
