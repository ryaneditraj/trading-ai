"""
Nifty Edge Paper A — teach + daily scan
=======================================
Explains the locked champion and prints today's gates / signals.

Usage:
  python strategies/nifty_edge_teach.py
  python strategies/nifty_edge_teach.py --scan-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))

from india_edge_engine import time_split  # noqa: E402
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth  # noqa: E402
from run_block1b import supertrend_bands  # noqa: E402
from run_block2 import attach_market_to_stocks, run_portfolio_ext as RUN  # noqa: E402
from run_block4 import attach_regime_features  # noqa: E402
from run_block5 import attach_lastwf_features  # noqa: E402
from run_block6 import sig_st_kill40_dd_nifty_mom as FN  # noqa: E402

PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "breadth_floor": 0.4,
    "dd_floor": -0.07,
    "min_nifty_ret20": -0.04,
}
MAX_SLOTS = 5

LESSON = """
╔══════════════════════════════════════════════════════════════════╗
║  THE STRATEGY (Paper A) — what actually beat everything else    ║
╚══════════════════════════════════════════════════════════════════╝

Name:  B6_ST_kill40_dd_nifty_mom_m04
File:  strategies/nifty_edge_paper.py
OOS:   64 trades · PF 4.73 · +124% · MDD −13% · Sharpe 1.24
vs BH: Nifty +70%, equal-weight basket +99%  →  Paper A wins both

ONE-SENTENCE THESIS
  Ride large-cap uptrends with a wide Supertrend trail, but ONLY open
  new longs when the whole market is healthy (breadth + shallow DD +
  not in a sharp Nifty slide).

WHY THIS — NOT YOUTUBE SUPPLY/DEMAND
  ICT FVG taps look sexy on shorts; they failed OOS on Nifty/BTC as
  a mechanical system. Trend + regime filters survived 11 research
  blocks, walk-forward, cost ladder, and anti-overfit checks.

══════════════════════════════════════════════════════════════════
LAYER 1 — THE TRADE (per stock)
══════════════════════════════════════════════════════════════════
  Supertrend lower band = HL2 − 3.6 × ATR(14), ratcheted up while
  prior close was above the band (classic ATR trail).

  ENTRY  (signal on daily CLOSE):
    Close crosses ABOVE the Supertrend lower band
    AND Close > stock EMA200
    AND Nifty is "bull":
         Nifty Close > Nifty EMA200
         OR Nifty Close > prior 55-day high

  EXIT   (same bar CLOSE):
    Close < Supertrend lower band
    (gates never force you out — only the trail does)

  FILL:
    Buy next session OPEN after entry signal
    Sell on the exit signal bar CLOSE
    Cost assumption: 0.08% round-trip (shadow book 0.15%)

══════════════════════════════════════════════════════════════════
LAYER 2 — THE GATES (entry-only; skip new trades if any fail)
══════════════════════════════════════════════════════════════════
  1. Breadth50 ≥ 0.40
     = fraction of the 20-name universe with Close > EMA50
     → don't buy when most large-caps are already broken

  2. Nifty drawdown from prior 55d high ≥ −7%
     → skip entries in deep index selloffs

  3. Nifty 20-day return ≥ −4%
     → skip when the index just dumped hard

  Research twin (monitor only) also wants days-since-55d-high ≤ 60.
  Paper A drops that — thin skip sample, same late OOS.

══════════════════════════════════════════════════════════════════
LAYER 3 — THE PORTFOLIO
══════════════════════════════════════════════════════════════════
  • Universe: 20 frozen NSE large-caps (see UNIVERSE_FREEZE.md)
  • Max 5 equal-risk slots (each ~20% of equity when full)
  • Rank candidates by strength = Close/EMA200 − 1 (strongest first)
  • Long only · daily bars · no look-ahead

══════════════════════════════════════════════════════════════════
HOW TO RUN IT LIVE (paper first)
══════════════════════════════════════════════════════════════════
  Every day after NSE close:
    1) Update prices for 20 stocks + Nifty
    2) Recompute ST band, EMA200, gates
    3) Exit any open name whose Close < ST band
    4) If slots free AND all gates green: enter next-day open on
       strongest new crosses (up to 5 total)
    5) Log P&L at 0.08% RT; keep a 0.15% shadow book

  DO NOT: retune mult mid-paper, add gates, drop WIPRO casually,
  or trust TradingView single-symbol Pine as the basket P&L.

══════════════════════════════════════════════════════════════════
HARD RULES FROM RESEARCH
══════════════════════════════════════════════════════════════════
  • mult=3.6 is a local peak — 3.5 was FRAGILE (lastWF −3.5%). Don't "improve" it.
  • Prefer fewer gates when lastWF ties → Paper A beats Research A for trading.
  • This is a research paper sleeve, not a promise of live profit.
"""


def load_data():
    print("Loading universe + Nifty…")
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    data = attach_lastwf_features(data, nifty, bank)
    return data, nifty


def gate_status(sample: pd.DataFrame, dt) -> dict:
    row = sample.loc[dt]
    br = float(row.get("breadth50", np.nan))
    dd = float(row.get("nifty_dd_hh55", np.nan))
    mom = float(row.get("nifty_ret20", np.nan))
    bull = bool(row.get("nifty_bull", False))
    return {
        "date": str(pd.Timestamp(dt).date()),
        "nifty_bull": bull,
        "breadth50": br,
        "breadth_ok": br >= 0.40,
        "nifty_dd": dd,
        "dd_ok": dd >= -0.07,
        "nifty_ret20": mom,
        "mom_ok": mom >= -0.04,
        "all_gates": bull and br >= 0.40 and dd >= -0.07 and mom >= -0.04,
    }


def scan(data: dict, nifty: pd.DataFrame):
    # latest common date with features
    sample = next(iter(data.values()))
    dt = sample.index[-1]
    g = gate_status(sample, dt)

    print("\n── MARKET GATES (as of {}) ──".format(g["date"]))
    print(
        f"  Nifty bull:     {'PASS' if g['nifty_bull'] else 'FAIL'}"
    )
    print(
        f"  Breadth50:      {g['breadth50']:.2f}  "
        f"(need ≥0.40) → {'PASS' if g['breadth_ok'] else 'FAIL'}"
    )
    print(
        f"  Nifty DD 55d:   {g['nifty_dd']:+.2%}  "
        f"(need ≥−7%) → {'PASS' if g['dd_ok'] else 'FAIL'}"
    )
    print(
        f"  Nifty ret20:    {g['nifty_ret20']:+.2%}  "
        f"(need ≥−4%) → {'PASS' if g['mom_ok'] else 'FAIL'}"
    )
    print(
        f"  → New entries allowed: {'YES' if g['all_gates'] else 'NO — sit in cash / hold opens'}"
    )

    # Per-name ST cross + regime
    rows = []
    for sym, df in data.items():
        if dt not in df.index:
            continue
        st = supertrend_bands(df, PARAMS["mult"])
        c = df["Close"]
        e, x, _ = FN(df, PARAMS)
        strength = float(c.loc[dt] / df["ema200"].loc[dt] - 1.0) if np.isfinite(df["ema200"].loc[dt]) else -9
        above_st = bool(c.loc[dt] > st.loc[dt]) if np.isfinite(st.loc[dt]) else False
        above_ema = bool(c.loc[dt] > df["ema200"].loc[dt])
        rows.append(
            {
                "symbol": sym.replace(".NS", ""),
                "close": float(c.loc[dt]),
                "st": float(st.loc[dt]) if np.isfinite(st.loc[dt]) else np.nan,
                "above_st": above_st,
                "above_ema200": above_ema,
                "strength": strength,
                "entry_sig": bool(e.loc[dt]),
                "exit_sig": bool(x.loc[dt]),
            }
        )
    tab = pd.DataFrame(rows).sort_values("strength", ascending=False)

    entries = tab[tab["entry_sig"]]
    exits = tab[tab["exit_sig"]]
    held_like = tab[tab["above_st"] & tab["above_ema200"]]

    print("\n── ENTRY SIGNALS TODAY (buy next open if gates green + slot free) ──")
    if entries.empty:
        print("  (none)")
    else:
        for _, r in entries.iterrows():
            print(
                f"  BUY  {r['symbol']:12s}  close={r['close']:.1f}  "
                f"ST={r['st']:.1f}  strength={r['strength']:+.1%}"
            )

    print("\n── EXIT SIGNALS TODAY (sell on close) ──")
    if exits.empty:
        print("  (none)")
    else:
        for _, r in exits.iterrows():
            print(
                f"  SELL {r['symbol']:12s}  close={r['close']:.1f}  ST={r['st']:.1f}"
            )

    print(f"\n── TRENDING NAMES (above ST+EMA200) — top {MAX_SLOTS} by strength ──")
    top = held_like.head(MAX_SLOTS)
    if top.empty:
        print("  (none — market soft)")
    else:
        for _, r in top.iterrows():
            print(
                f"  {r['symbol']:12s}  strength={r['strength']:+.1%}  "
                f"close={r['close']:.1f}  ST={r['st']:.1f}"
            )

    return g, tab


def recent_trades(data: dict, n: int = 8):
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    raw = RUN(data, FN, PARAMS, start_date=oos_ref.index[0], return_trades=True)
    trades = raw.get("trades", [])
    if not trades:
        print("\n── Recent OOS trades: none ──")
        return
    print(f"\n── Last {n} OOS paper trades ──")
    for t in trades[-n:]:
        # trade dict shape from engine
        sym = t.get("symbol", "?")
        ret = t.get("ret", t.get("ret_net", 0.0))
        print(
            f"  {str(t.get('entry'))[:10]} → {str(t.get('exit'))[:10]}  "
            f"{str(sym).replace('.NS',''):12s}  {ret*100:+.1f}%"
        )
    oos = {k: v for k, v in raw.items() if k != "trades"}
    print(
        f"\n── Full OOS book ──  n={oos.get('n_trades')}  "
        f"PF={oos.get('profit_factor', 0):.2f}  "
        f"Tot={oos.get('total_return', 0)*100:.1f}%  "
        f"MDD={oos.get('max_dd', 0)*100:.1f}%"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan-only", action="store_true")
    args = ap.parse_args()
    if not args.scan_only:
        print(LESSON)
    data, nifty = load_data()
    scan(data, nifty)
    recent_trades(data)


if __name__ == "__main__":
    main()
