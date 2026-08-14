"""
GIFT / Overnight Nifty — PAPER sleeve
=====================================
ON_mom_trend_0.008

Thesis
  After a strong India *cash-session* day in the direction of the EMA200 trend,
  hold that risk overnight (GIFT Session II / into next open). You monetize the
  open gap. Do NOT blindly trade the next cash day off the overnight cue —
  OOS prediction of open→close is ~coin-flip.

Rules (long/short)
  Signal at India CLOSE of day t-1:
    day_ret = Close/Open - 1 that day
    If Close > EMA200 and day_ret >= +0.8%  → LONG overnight
    If Close < EMA200 and day_ret <= -0.8%  → SHORT overnight
    Else flat
  Exit / realize at next session OPEN (gap capture).
  Cost: 0.08% RT primary; stress 0.15% still PF≈1.30 OOS.

OOS (proxy = NSE open gap, 2015→2026 holdout):
  n=66  WR=57.6%  PF=1.74  E=+0.134%/trade  Tot=+8.9%  MDD=-3.8%  WF=3/3
  Stress 0.15%: PF=1.30  Tot=+4.0%

Live trading notes
  - Ideal venue: GIFT Nifty futures (Session II → next morning).
  - Proxy backtest uses ^NSEI open gap (basis ≠ futures; size smaller live).
  - Drop real GIFT OHLC to research/gift_overnight_edge/data/gift_nifty.csv
    and re-run research/gift_overnight_edge/run_research.py.

Usage:
  python strategies/gift_overnight_paper.py
  python strategies/gift_overnight_paper.py --scan
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "gift_overnight_edge"))

from run_research import (  # noqa: E402
    RT,
    RT_STRESS,
    build_frame,
    eval_signal,
    fmt,
    sig_overnight_mom_trend,
)

PARAMS = {"thr": 0.008}
NAME = "ON_mom_trend_0.008"


def scan(df: pd.DataFrame):
    """What to do at today's close for tonight's overnight hold."""
    row = df.iloc[-1]
    day = float(row["day"])
    above = bool(row["Close"] > row["ema200"])
    thr = PARAMS["thr"]
    print(f"\n── Overnight scan @ {df.index[-1].date()} close ──")
    print(f"  Nifty close:   {row['Close']:.1f}")
    print(f"  EMA200:        {row['ema200']:.1f}  ({'ABOVE' if above else 'BELOW'})")
    print(f"  Cash day ret:  {day*100:+.2f}%  (need |day|≥{thr*100:.1f}% + trend align)")
    if above and day >= thr:
        action = "LONG overnight (GIFT / hold into next open)"
    elif (not above) and day <= -thr:
        action = "SHORT overnight (GIFT / hold into next open)"
    else:
        action = "FLAT — no overnight trade"
    print(f"  → {action}")
    # Show last gap for context
    if len(df) >= 2:
        print(f"  Last overnight gap: {float(df.iloc[-1]['gap'])*100:+.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="Tonight's overnight decision")
    args = ap.parse_args()

    df = build_frame()
    side = sig_overnight_mom_trend(df, PARAMS)
    primary = eval_signal(df, side, "gap", NAME, rt=RT)
    stress = eval_signal(df, side, "gap", NAME, rt=RT_STRESS)

    out = {
        "name": NAME,
        "role": "PAPER_OVERNIGHT",
        "params": PARAMS,
        "venue": "GIFT Nifty (preferred) / NSE open-gap proxy in backtest",
        "OOS": primary["OOS"],
        "OOS_stress_0.15": stress["OOS"],
        "wf_pos": primary["wf_pos"],
        "last_wf_tot": primary["last_wf_tot"],
        "rules": {
            "entry": "India close: |day|>=0.8% with EMA200 alignment",
            "exit": "Next open (gap)",
            "side": "long if uptrend+up day; short if downtrend+down day",
        },
    }
    print(json.dumps({k: v for k, v in out.items() if k != "rules"}, indent=2, default=str))
    print(f"\nOOS primary: {fmt(primary['OOS'])}")
    print(f"OOS stress:  {fmt(stress['OOS'])}")
    print(f"WF: {primary['wf_pos']}/3  lastWF={primary['last_wf_tot']*100:+.1f}%")

    path = ROOT / "research" / "results" / "gift_overnight_paper_stats.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {path}")

    if args.scan:
        scan(df)


if __name__ == "__main__":
    main()
