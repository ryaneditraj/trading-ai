"""
Runner-up r6: B2_ST_delay1_m3.6
Params: {"mult": 3.6, "use_nifty": true, "use_ema200": true, "entry_delay": 1}
OOS n=82 PF=2.90 tot=94.3%
MDD=-14.2% Sharpe=0.99 WF+=3/3
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks, run_portfolio_ext, sig_st_delay_base

PARAMS = {
  "mult": 3.6,
  "use_nifty": true,
  "use_ema200": true,
  "entry_delay": 1
}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    oos = run_portfolio_ext(data, sig_st_delay_base, PARAMS, start_date=oos_start)
    print(json.dumps({"name": "B2_ST_delay1_m3.6", "OOS": oos}, indent=2, default=str))

if __name__ == "__main__":
    main()
