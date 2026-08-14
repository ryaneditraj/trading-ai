"""
Runner-up r14: B4_ST_kill40_ema50_soft
Params: {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.4, "soft_tol": 0.015, "max_days_below": 8}
OOS n=67 PF=3.26 tot=85.6%
MDD=-17.1% Sharpe=0.99 WF+=3/3
lastWF=9.2%
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
from run_block2 import run_portfolio_ext
from run_block4 import sig_st_kill40_ema50_soft as FN

PARAMS = {
  "mult": 3.6,
  "use_nifty": True,
  "use_ema200": True,
  "breadth_floor": 0.4,
  "soft_tol": 0.015,
  "max_days_below": 8
}
NAME = "B4_ST_kill40_ema50_soft"

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    oos = run_portfolio_ext(data, FN, PARAMS, start_date=oos_start)
    print(json.dumps({"name": NAME, "OOS": oos}, indent=2, default=str))

if __name__ == "__main__":
    main()
