"""
Runner-up r16: B4_ST_softvol22_shi1.0_floor0.85
Params: {"mult": 3.6, "use_nifty": True, "use_ema200": True, "vol_target": 0.22, "vol_scale_lo": 0.85, "vol_scale_hi": 1.0}
OOS n=75 PF=3.90 tot=100.7%
MDD=-13.7% Sharpe=1.10 WF+=3/3
lastWF=5.8%
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
from run_block3 import run_portfolio_b3
from run_block1b import sig_supertrend as FN

PARAMS = {
  "mult": 3.6,
  "use_nifty": True,
  "use_ema200": True,
  "vol_target": 0.22,
  "vol_scale_lo": 0.85,
  "vol_scale_hi": 1.0
}
NAME = "B4_ST_softvol22_shi1.0_floor0.85"

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    oos = run_portfolio_b3(data, FN, PARAMS, start_date=oos_start)
    print(json.dumps({"name": NAME, "OOS": oos}, indent=2, default=str))

if __name__ == "__main__":
    main()
