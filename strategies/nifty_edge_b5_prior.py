"""
Paper B twin — demoted Block-5 champion (Block 7 flip)
======================================================
B5_ST_kill40_dd07
Params: {"mult": 3.6, "use_nifty": true, "use_ema200": true, "breadth_floor": 0.4, "dd_floor": -0.07}

OOS: n=65 PF=4.01 tot=113.4%
MDD=-15.0% Sharpe=1.17 stressPF=3.93
WF=3/3 lastWF=9.2%

Demoted in Block 7: r21 nifty_mom cleared robust risk-adj + ladder + boot
(same lastWF, +tot/+Sharpe/better MDD). Still the paper twin for divergence logs.

Usage:
  python strategies/nifty_edge_b5_prior.py
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
from run_block5 import sig_st_kill40_dd as FN

PARAMS = {
  "mult": 3.6,
  "use_nifty": True,
  "use_ema200": True,
  "breadth_floor": 0.4,
  "dd_floor": -0.07
}
NAME = "B5_ST_kill40_dd07"

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
    print(json.dumps({"name": NAME, "OOS": oos}, indent=2, default=str))

if __name__ == "__main__":
    main()
