"""
India Failed-Breakdown Fade (secondary sleeve)
==============================================
Mean-reversion complement to the Nifty+ADX Donchian trend sleeve.

Thesis: After a close below the prior N-day low, a reclaim close back above
that level (failed breakdown) while above EMA50 is a structure short-squeeze
long. Exit on close back below the channel or a short trailing low.

Research OOS (n=20): n=61, PF≈1.59, E≈+0.97%, Tot≈+11%, MDD≈−7.5%.
Lower absolute return than the trend sleeve; better DD. Do NOT merge into
one hybrid exit engine (hybrid tests destroyed both edges).

Usage:
  python strategies/india_failed_breakdown_fade_v2.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "strategies"))

from india_edge_engine import RESULTS_DIR, fetch_daily, time_split  # noqa: E402
from india_nifty_adx_donchian_v2 import (  # noqa: E402
    RT_COST,
    TRAIN_FRAC,
    UNIVERSE,
    add_adx,
    align_nifty,
    clean,
)
from run_india_edge_round2 import fmt, r2_failed_bo_fade, run_portfolio, strip  # noqa: E402

CHANNEL_N = 20


def main():
    print(f"Fetching {len(UNIVERSE)} symbols...")
    nifty = add_adx(clean(fetch_daily("^NSEI")))
    data = {s: align_nifty(add_adx(clean(fetch_daily(s))), nifty) for s in UNIVERSE}
    ref = data["RELIANCE.NS"]
    _, oos_ref = time_split(ref, TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    params = {"entry_n": CHANNEL_N, "max_hold": 5}

    is_s = run_portfolio(
        data,
        r2_failed_bo_fade,
        params,
        end_date=oos_start - pd.Timedelta(days=1),
        rt_cost=RT_COST,
    )
    oos_s = run_portfolio(
        data, r2_failed_bo_fade, params, start_date=oos_start, rt_cost=RT_COST
    )
    stress = run_portfolio(
        data, r2_failed_bo_fade, params, start_date=oos_start, rt_cost=0.0015
    )

    print("\n=== IS ===")
    print(fmt(strip(is_s)))
    print("\n=== OOS ===")
    print(fmt(strip(oos_s)))
    print("\n=== OOS stress 0.15% ===")
    print(fmt(strip(stress)))
    print("\nRules: Failed breakdown reclaim (n=20) + EMA50; exit channel/trail.")
    print("Run as SEPARATE sleeve from Nifty+ADX Donchian — do not merge exits.")

    out = {
        "params": params,
        "IS": strip(is_s),
        "OOS": strip(oos_s),
        "OOS_stress_0.15": strip(stress),
        "oos_start": str(oos_start.date()),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "india_failed_breakdown_fade_v2_stats.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
