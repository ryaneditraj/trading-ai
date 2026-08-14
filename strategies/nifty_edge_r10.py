"""
Runner-up r10: B3_ST_kill40_vol15_m3.6
Params: {"mult": 3.6, "use_nifty": true, "use_ema200": true, "breadth_floor": 0.4, "vol_target": 0.15}
OOS n=65 PF=3.94 tot=68.7%
MDD=-9.5% Sharpe=1.10 WF+=3/3
lastWF=10.9%
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
from run_block3 import run_portfolio_b3, portfolio_eval_blend
from run_block2 import sig_st_kill_breadth
FN = sig_st_kill_breadth

PARAMS = {
  "mult": 3.6,
  "use_nifty": true,
  "use_ema200": true,
  "breadth_floor": 0.4,
  "vol_target": 0.15
}
NAME = "B3_ST_kill40_vol15_m3.6"

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    if NAME.startswith("B3_ENS_equal_risk"):
        row = portfolio_eval_blend(NAME, data, oos_start, PARAMS)
        print(json.dumps({"name": NAME, "OOS": row["OOS"], "last_wf_tot": row.get("last_wf_tot")}, indent=2, default=str))
        return
    oos = run_portfolio_b3(data, FN, PARAMS, start_date=oos_start)
    print(json.dumps({"name": NAME, "OOS": oos}, indent=2, default=str))

if __name__ == "__main__":
    main()
