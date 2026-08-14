"""
Nifty Edge PAPER A — Block 10 operational sleeve
================================================
B6_ST_kill40_dd_nifty_mom_m04  << PAPER PRIMARY (complexity; drop thin days60)

Params: {"mult": 3.6, "use_nifty": true, "use_ema200": true, "breadth_floor": 0.4, "dd_floor": -0.07, "min_nifty_ret20": -0.04}

OOS: n=64 PF=4.73 tot=124.3%
MDD=-13.0% Sharpe=1.24
WF=3/3 lastWF=9.2%

GATES (entry-only, causal):
  - Breadth50 >= 0.40
  - Nifty dd from prior-55d high >= -0.07
  - Nifty ret20 >= -0.04
  - NO days-since-high gate (that is Research A only)

RESEARCH A (monitor-only, do not paper-trade as primary):
  strategies/nifty_edge_best.py / r29.py = B7_ST_kill40_dd_mom_days60

Also: strategies/nifty_edge_b6_prior.py / r21.py (same sleeve, legacy twin path)

Usage:
  python strategies/nifty_edge_paper.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks, run_portfolio_ext as RUN
from run_block4 import attach_regime_features
from run_block5 import attach_lastwf_features
from run_block6 import sig_st_kill40_dd_nifty_mom as FN

PARAMS = {
  "mult": 3.6,
  "use_nifty": True,
  "use_ema200": True,
  "breadth_floor": 0.4,
  "dd_floor": -0.07,
  "min_nifty_ret20": -0.04
}
NAME = "B6_ST_kill40_dd_nifty_mom_m04"

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    data = attach_lastwf_features(data, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos = RUN(data, FN, PARAMS, start_date=oos_ref.index[0])
    print(json.dumps({"name": NAME, "role": "PAPER_A", "OOS": oos}, indent=2, default=str))

if __name__ == "__main__":
    main()
