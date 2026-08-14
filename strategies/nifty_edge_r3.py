"""
Runner-up r3: EMA ribbon ignition basket (Nifty bull filter)
OOS PF≈1.45 tot≈44% n≈257 WF+=2/3 — higher trade rate, softer PF
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))

from india_edge_engine import time_split  # noqa: E402
from run_block1 import TRAIN_FRAC, UNIVERSE, align_nifty, prepare_symbol, run_portfolio  # noqa: E402
from run_block1b import sig_ema_ribbon  # noqa: E402

PARAMS = {"use_nifty": True, "adx_min": 0}


def main():
    nifty = prepare_symbol("^NSEI")
    data = {s: align_nifty(prepare_symbol(s), nifty) for s in UNIVERSE}
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos = run_portfolio(data, sig_ema_ribbon, PARAMS, start_date=oos_ref.index[0])
    stress = run_portfolio(data, sig_ema_ribbon, PARAMS, start_date=oos_ref.index[0], rt_cost=0.0015)
    print(json.dumps({"name": "RIBBON_plain", "params": PARAMS, "OOS": oos, "OOS_stress": stress}, indent=2))


if __name__ == "__main__":
    main()
