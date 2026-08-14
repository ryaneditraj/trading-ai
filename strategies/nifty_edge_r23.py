"""
Runner-up r23: B6_ENS_champ_priorST
Params: {"blend": "equal_risk", "a": "kill40_dd07", "b": "ST_m3.6"}
OOS n=78 PF=3.02 tot=49.0%
MDD=-10.9% Sharpe=0.75 WF+=3/3
lastWF=2.2%
Equal-risk 50/50 blend — see run_block6.portfolio_eval_ens
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
from run_block1b import sig_supertrend
from run_block4 import sig_st_regime_halflife
from run_block5 import sig_st_kill40_dd
from run_block6 import portfolio_eval_ens, CHAMP_PARAMS, PRIOR_PARAMS, REGIME_PARAMS

NAME = "B6_ENS_champ_priorST"

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
    if "priorST" in NAME and "champ" in NAME:
        row = portfolio_eval_ens(NAME, data, sig_st_kill40_dd, CHAMP_PARAMS, sig_supertrend, PRIOR_PARAMS, oos_start)
    elif "regime" in NAME and "champ" in NAME:
        row = portfolio_eval_ens(NAME, data, sig_st_kill40_dd, CHAMP_PARAMS, sig_st_regime_halflife, REGIME_PARAMS, oos_start)
    else:
        row = portfolio_eval_ens(NAME, data, sig_supertrend, PRIOR_PARAMS, sig_st_regime_halflife, REGIME_PARAMS, oos_start)
    print(json.dumps({"name": NAME, "OOS": row["OOS"], "last_wf_tot": row.get("last_wf_tot")}, indent=2, default=str))

if __name__ == "__main__":
    main()
