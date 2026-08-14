"""
Runner-up r18: B5_ST_dd_gate_m8
Params: {"mult": 3.6, "use_nifty": true, "use_ema200": true, "dd_floor": -0.08}
OOS n=75 PF=3.56 tot=101.6%
MDD=-14.2% Sharpe=1.05 WF+=3/3
lastWF=6.9%
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks
from run_block4 import attach_regime_features
from run_block5 import attach_lastwf_features
from run_block2 import run_portfolio_ext
from run_block5 import sig_st_dd_gate as FN

PARAMS = {
  "mult": 3.6,
  "use_nifty": True,
  "use_ema200": True,
  "dd_floor": -0.08
}
NAME = "B5_ST_dd_gate_m8"

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    data = attach_lastwf_features(data, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    oos = run_portfolio_ext(data, FN, PARAMS, start_date=oos_start)
    print(json.dumps({"name": NAME, "OOS": oos}, indent=2, default=str))

if __name__ == "__main__":
    main()
