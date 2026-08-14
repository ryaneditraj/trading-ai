#!/usr/bin/env python3
"""
Block 10 — Operationalize Paper A (B6); Research A = monitor-only; no new gates.

Mandatory:
  1) Repro Research A (B7) and Paper A (B6) side by side
  2) Operationalize Paper A: PAPER_TRADE_RULES / CHECKLIST; nifty_edge_paper.py;
     label pine (paper vs research) — do NOT silently demote research files
  3) Allowed sensitivity on Paper A ONLY:
       - execution realism (next-open vs same-bar close entry)
       - cost ladder refresh 0.08–0.20%
       - universe drop 1–2 names
       - max-slots 4 vs 5
       - ST mult neighborhood
  4) NO new gate stacking
  5) Expand FINAL_REPORT_DRAFT; full lock only if <1h
  6) Leaderboard/log: Paper vs Research distinction prominent

Usage:
  python research/nifty_edge_8h/run_block10.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from india_edge_engine import time_split  # noqa: E402
from run_block1 import (  # noqa: E402
    LEADERBOARD,
    LOG,
    RESULTS,
    RT,
    TRAIN_FRAC,
    UNIVERSE,
    buy_hold_stats,
    log,
    prepare_symbol,
)
from run_block1b import portfolio_eval  # noqa: E402
from run_block2 import (  # noqa: E402
    attach_market_to_stocks,
    past_deadline,
    portfolio_eval_ext,
    run_portfolio_ext,
)
from run_block4 import attach_regime_features  # noqa: E402
from run_block5 import (  # noqa: E402
    COST_LADDER,
    attach_lastwf_features,
    cost_ladder_row,
    sig_st_kill40_dd,
)
from run_block6 import (  # noqa: E402
    hours_to_deadline,
    sig_st_kill40_dd_nifty_mom,
    write_full_final_if_needed,
)
from run_block7 import sig_st_kill40_dd_mom_days  # noqa: E402

OUT_STRAT = ROOT / "strategies"
OUT_PINE_DIR = ROOT / "pinescript"
CHECKLIST = Path(__file__).resolve().parent / "CHECKLIST.md"
PAPER_RULES = Path(__file__).resolve().parent / "PAPER_TRADE_RULES.md"
FINAL_OUTLINE = Path(__file__).resolve().parent / "FINAL_REPORT_OUTLINE.md"
FINAL_DRAFT = Path(__file__).resolve().parent / "FINAL_REPORT_DRAFT.md"
FINAL_REPORT = Path(__file__).resolve().parent / "FINAL_REPORT.md"

REF_RESEARCH = {
    "n_trades": 63,
    "profit_factor": 5.17,
    "total_return": 1.294,
    "max_dd": -0.110,
    "sharpe": 1.28,
}
REF_PAPER = {
    "n_trades": 64,
    "profit_factor": 4.73,
    "total_return": 1.243,
    "max_dd": -0.130,
    "sharpe": 1.24,
}

RESEARCH_PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "breadth_floor": 0.40,
    "dd_floor": -0.07,
    "min_nifty_ret20": -0.04,
    "max_days_since_high": 60,
}
PAPER_PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "breadth_floor": 0.40,
    "dd_floor": -0.07,
    "min_nifty_ret20": -0.04,
}
B5_PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "breadth_floor": 0.40,
    "dd_floor": -0.07,
}

# Drop candidates for universe sensitivity (Paper A only)
DROP_SETS = [
    ("drop_WIPRO", ["WIPRO.NS"]),
    ("drop_WIPRO_BAJFINANCE", ["WIPRO.NS", "BAJFINANCE.NS"]),
]


def drift_ok(o: dict, ref: dict) -> bool:
    return (
        abs(o["n_trades"] - ref["n_trades"]) <= 1
        and abs(o["profit_factor"] - ref["profit_factor"]) < 0.05
        and abs(o["total_return"] - ref["total_return"]) < 0.02
        and abs(o["max_dd"] - ref["max_dd"]) < 0.01
    )


def fmt_oos(row: dict) -> str:
    o = row["OOS"]
    lw = row.get("last_wf_tot", 0.0)
    return (
        f"n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} "
        f"WF={row.get('wf_pos', '?')}/{row.get('wf_n', 3)} lastWF={lw*100:.1f}%"
    )


# ── Execution realism: same-bar close entry (vs baseline next-open) ───────────
def run_portfolio_close_entry(
    data: Dict[str, pd.DataFrame],
    signal_fn,
    params: dict,
    start_date=None,
    end_date=None,
    max_positions: int = 5,
    rt_cost: float = RT,
) -> dict:
    """
    Optimistic / alternate fill: enter at signal-bar CLOSE (not next open).
    Exit still at signal-bar close. Used ONLY as realism stress on Paper A.
    """
    max_pos = int(params.get("max_positions", max_positions))
    sig = {}
    for s, df in data.items():
        e, x = signal_fn(df, params)[:2]
        sig[s] = {
            "entry": e.fillna(False),
            "exit": x.fillna(False),
            "close": df["Close"],
            "ema200": df["ema200"],
        }
    all_dates = sorted(set().union(*[set(df.index) for df in data.values()]))
    all_dates = [
        d
        for d in all_dates
        if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)
    ]
    cash = 1.0
    positions: dict = {}
    equity_curve = []
    trades = []
    slot = 1.0 / max_pos

    for i, dt in enumerate(all_dates):
        for s in list(positions):
            if dt in sig[s]["exit"].index and bool(sig[s]["exit"].loc[dt]):
                # Skip same-bar enter+exit
                if positions[s]["entry_date"] == dt:
                    continue
                px = float(sig[s]["close"].loc[dt])
                ret = px / positions[s]["entry_px"] - 1.0 - rt_cost
                cash += positions[s]["w"] * (1.0 + ret)
                trades.append(
                    {
                        "symbol": s,
                        "entry": positions[s]["entry_date"],
                        "exit": dt,
                        "ret": ret,
                    }
                )
                del positions[s]

        equity = cash + sum(
            p["w"]
            * (
                float(sig[s]["close"].loc[dt]) / p["entry_px"]
                if dt in sig[s]["close"].index
                else 1.0
            )
            for s, p in positions.items()
        )
        equity_curve.append((dt, equity, len(positions)))

        free = max_pos - len(positions)
        if free <= 0 or cash <= 1e-8:
            continue
        ranked = []
        for s in data:
            if s in positions:
                continue
            if dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                continue
            if dt not in sig[s]["close"].index:
                continue
            # Don't enter if same-bar exit also fires
            if bool(sig[s]["exit"].loc[dt]):
                continue
            strength = float(data[s].loc[dt, "Close"] / data[s].loc[dt, "ema200"] - 1.0)
            ranked.append((strength, s))
        ranked.sort(reverse=True)
        for _, s in ranked[:free]:
            alloc = min(cash, equity * slot)
            if alloc <= 1e-8:
                break
            entry_px = float(sig[s]["close"].loc[dt])
            cash -= alloc
            positions[s] = {
                "w": alloc * (1 - rt_cost / 2),
                "entry_px": entry_px,
                "entry_date": dt,
            }

    if all_dates:
        last = all_dates[-1]
        for s, p in list(positions.items()):
            px = float(sig[s]["close"].loc[last]) if last in sig[s]["close"].index else p["entry_px"]
            ret = px / p["entry_px"] - 1.0 - rt_cost
            cash += p["w"] * (1.0 + ret)
            trades.append({"symbol": s, "entry": p["entry_date"], "exit": last, "ret": ret})

    eq = pd.Series({d: e for d, e, _ in equity_curve})
    rets = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    tr = np.array([t["ret"] for t in trades], dtype=float) if trades else np.array([])
    wins = tr[tr > 0]
    losses = tr[tr <= 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and -losses.sum() > 0 else 0.0
    return {
        "n_trades": int(len(trades)),
        "win_rate": float((tr > 0).mean()) if len(tr) else 0.0,
        "profit_factor": pf,
        "expectancy": float(tr.mean()) if len(tr) else 0.0,
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0,
        "max_dd": float(dd.min()) if len(dd) else 0.0,
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252))
        if len(rets) > 2 and rets.std() > 0
        else 0.0,
        "avg_hold_days": float(np.mean([(t["exit"] - t["entry"]).days for t in trades]))
        if trades
        else 0.0,
    }


def write_paper_strategy(paper: dict) -> Path:
    o = paper["OOS"]
    path = OUT_STRAT / "nifty_edge_paper.py"
    text = f'''"""
Nifty Edge PAPER A — Block 10 operational sleeve
================================================
B6_ST_kill40_dd_nifty_mom_m04  << PAPER PRIMARY (complexity; drop thin days60)

Params: {json.dumps(PAPER_PARAMS)}

OOS: n={o["n_trades"]} PF={o["profit_factor"]:.2f} tot={o["total_return"]*100:.1f}%
MDD={o["max_dd"]*100:.1f}% Sharpe={o["sharpe"]:.2f}
WF={paper.get("wf_pos")}/{paper.get("wf_n")} lastWF={paper.get("last_wf_tot", 0)*100:.1f}%

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

PARAMS = {{
  "mult": 3.6,
  "use_nifty": True,
  "use_ema200": True,
  "breadth_floor": 0.4,
  "dd_floor": -0.07,
  "min_nifty_ret20": -0.04
}}
NAME = "B6_ST_kill40_dd_nifty_mom_m04"

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    data = attach_lastwf_features(data, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos = RUN(data, FN, PARAMS, start_date=oos_ref.index[0])
    print(json.dumps({{"name": NAME, "role": "PAPER_A", "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
    path.write_text(text)
    return path


def write_paper_pine() -> Path:
    path = OUT_PINE_DIR / "nifty_edge_paper.pine"
    text = '''//@version=5
strategy("Nifty Edge PAPER A ST Proxy", overlay=true, initial_capital=100000,
     commission_type=strategy.commission.percent, commission_value=0.04,
     slippage=2, process_orders_on_close=false)

// PAPER A = B6_ST_kill40_dd_nifty_mom_m04 (Block 10 operational sleeve)
// SINGLE SYMBOL proxy — research edge is a 5-slot basket.
// OOS ref ~PF 4.73, tot 124.3%, lastWF 9.2%
// Basket also requires breadth50>=0.4 (not in single-symbol Pine)
// Basket also requires Nifty dd_from_prior55d_high>=-0.07 (not in Pine)
// Basket also requires Nifty ret20>=-0.04 (not in single-symbol Pine)
// NO days-since-high gate on Paper A (that gate is Research A only)
//
// RESEARCH A (monitor): pinescript/nifty_edge_best.pine = B7 + days60
// Do not confuse: best.pine = research; this file = paper.

atrLen = input.int(14, "ATR Length")
mult = input.float(3.6, "ATR Mult", step=0.1)
emaLen = input.int(200, "EMA Length")
useEma = input.bool(true, "Require Close > EMA")

atr = ta.atr(atrLen)
hl2 = (high + low) / 2.0
basicLB = hl2 - mult * atr
var float finalLB = na
if na(finalLB)
    finalLB := basicLB
else if close[1] > finalLB[1]
    finalLB := math.max(basicLB, finalLB[1])
else
    finalLB := basicLB

ema = ta.ema(close, emaLen)
regime = not useEma or close > ema
longCond = ta.crossover(close, finalLB) and regime
exitCond = close < finalLB

if longCond
    strategy.entry("Long", strategy.long)
if exitCond
    strategy.close("Long")

plot(finalLB, "ST Lower", color=color.new(color.teal, 0), linewidth=2)
plot(ema, "EMA200", color=color.orange)
bgcolor(longCond ? color.new(color.green, 85) : na)
'''
    path.write_text(text)
    return path


def annotate_research_best_header() -> None:
    """Ensure best.py header states RESEARCH A monitor-only (do not silently change logic)."""
    path = OUT_STRAT / "nifty_edge_best.py"
    if not path.exists():
        return
    text = path.read_text()
    if "RESEARCH A" in text and "monitor-only" in text:
        return
    # Rewrite header only; keep body
    if '"""' in text:
        rest = text.split('"""', 2)
        if len(rest) >= 3:
            body = rest[2]
            new = f'''"""
Nifty Edge RESEARCH A — Block 8/9 stacked champ (MONITOR-ONLY)
==============================================================
B7_ST_kill40_dd_mom_days60

Params: {json.dumps(RESEARCH_PARAMS)}

OOS: n=63 PF=5.17 tot=129.4%
MDD=-11.0% Sharpe=1.28
WF=3/3 lastWF=9.2%

ROLE: Research / monitor twin for days60-skip divergence.
PAPER A (trade this): strategies/nifty_edge_paper.py = B6 (no days60)
Do NOT silently swap paper to this sleeve without labeling.

Usage:
  python strategies/nifty_edge_best.py
"""{body}'''
            path.write_text(new)


def annotate_research_pine() -> None:
    path = OUT_PINE_DIR / "nifty_edge_best.pine"
    if not path.exists():
        return
    text = path.read_text()
    if "RESEARCH A" in text and "monitor-only" in text.lower().replace(" ", "") or (
        "RESEARCH A" in text and "MONITOR" in text
    ):
        # still refresh header for clarity
        pass
    lines = text.splitlines()
    # Replace strategy title / first comment block if present
    new_header = [
        "//@version=5",
        'strategy("Nifty Edge RESEARCH A ST Proxy", overlay=true, initial_capital=100000,',
        "     commission_type=strategy.commission.percent, commission_value=0.04,",
        "     slippage=2, process_orders_on_close=false)",
        "",
        "// RESEARCH A = B7_ST_kill40_dd_mom_days60 (MONITOR-ONLY — Block 10)",
        "// SINGLE SYMBOL proxy. Research edge is a 5-slot basket.",
        "// OOS ~PF 5.17, tot 129.4%, lastWF 9.2%",
        "// Basket also requires breadth50>=0.4 (not in single-symbol Pine)",
        "// Basket also requires Nifty dd_from_prior55d_high>=-0.07 (not in Pine)",
        "// Basket also requires Nifty ret20>=-0.04 (not in single-symbol Pine)",
        "// Basket also requires Nifty days_since_high<=60 (not in single-symbol Pine)",
        "//",
        "// PAPER A (operational): pinescript/nifty_edge_paper.pine = B6 (no days60)",
        "// Do not paper-trade this file as primary without reading PAPER_TRADE_RULES.md",
        "",
    ]
    # Find first non-header code line (atrLen = ...)
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("atrLen"):
            body_start = i
            break
    else:
        return
    path.write_text("\n".join(new_header + lines[body_start:]) + "\n")


def write_paper_rules(paper: dict, research: dict, hrs: float, sens: dict) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    po, ro = paper["OOS"], research["OOS"]
    text = f"""# Paper Trade Rules — Nifty Edge 8h

**Written:** Block 5; flipped B7–8; anti-overfit B9; **operationalized Block 10** {now}
**Status:** Research paper sleeves — not live capital. No look-ahead.
**Hours to deadline:** {hrs:.2f}

---

## ★ PAPER vs RESEARCH (Block 10 — read this first)

| Role | ID | Code | Gates | OOS ref |
|------|----|------|-------|---------|
| **PAPER A (trade this)** | `B6_ST_kill40_dd_nifty_mom_m04` | `strategies/nifty_edge_paper.py` (+ `b6_prior.py` / `r21.py`) | kill40 + dd−7% + mom−4% | n={po['n_trades']} PF={po['profit_factor']:.2f} tot={po['total_return']*100:.1f}% lastWF={paper.get('last_wf_tot',0)*100:.1f}% |
| **RESEARCH A (monitor only)** | `B7_ST_kill40_dd_mom_days60` | `strategies/nifty_edge_best.py` / `r29.py` | Paper A **+ days≤60** | n={ro['n_trades']} PF={ro['profit_factor']:.2f} tot={ro['total_return']*100:.1f}% lastWF={research.get('last_wf_tot',0)*100:.1f}% |
| Tertiary | `B5_ST_kill40_dd07` | `strategies/nifty_edge_b5_prior.py` | kill40 + dd only | tot=113.4% lastWF=9.2% |

**Pine labeling**
- `pinescript/nifty_edge_paper.pine` → **PAPER A** (B6; no days60 in basket rules)
- `pinescript/nifty_edge_best.pine` → **RESEARCH A** (B7; monitor; days60 in basket rules)
- Both are single-symbol ST+EMA proxies — basket gates are NOT in Pine.

**Why Paper ≠ Research:** Block 9 complexity + thin days60-skip (n=1) + identical held-out late OOS (12.7%). Overfit MIXED. No new gate stacking.

---

## Universe & execution

| Item | Rule |
|------|------|
| Universe | 20 NSE large-caps (`UNIVERSE` in `run_block1.py`) |
| Index filter | ^NSEI daily |
| Max positions | **5** equal-risk slots (Block 10: slots=4 stress-tested; keep 5) |
| Rank | Free slots by Close/EMA200 − 1 |
| Entry fill | Next session **open** after signal bar close (**primary**) |
| Exit fill | Signal bar **close** |
| Costs | **0.08% RT** primary; **0.15%** stress; ladder 0.08–0.20 |
| Side | Long-only |
| Cadence | Daily bars |

### Universe tickers

```
RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, ICICIBANK.NS, SBIN.NS, BHARTIARTL.NS, ITC.NS, LT.NS, AXISBANK.NS, KOTAKBANK.NS, HINDUNILVR.NS, BAJFINANCE.NS, ASIANPAINT.NS, MARUTI.NS, SUNPHARMA.NS, TITAN.NS, ULTRACEMCO.NS, WIPRO.NS, NESTLEIND.NS
```

---

## Sleeve PAPER A — operational primary (FROZEN Block 10)

**ID:** `B6_ST_kill40_dd_nifty_mom_m04`  
**Code:** `strategies/nifty_edge_paper.py`  
**Also:** `strategies/nifty_edge_b6_prior.py`, `r21.py`  
**Pine:** `pinescript/nifty_edge_paper.pine` (illustrative)

### Exact entry

1. ATR(14), HL2; Supertrend lower band mult=**3.6**; ratchet on prior close.
2. Signal (bar close): Close crosses above final lower band AND Close > stock EMA200
   AND Nifty bull (Close_Nifty > EMA200_Nifty OR Close_Nifty > prior 55d Nifty high).
3. **Breadth gate (entry-only):** Breadth50 ≥ **0.40**.
4. **Drawdown gate (entry-only, causal):** Nifty Close / prior-55d-High − 1 ≥ **−0.07**.
5. **Nifty mom gate (entry-only, causal):** Nifty 20d return ≥ **−0.04**.
6. **No days60 gate** on Paper A.
7. Fill: next open. Size: min(cash, equity × 1/5).

### Exact exit

Close < final Supertrend lower band → exit that bar close. No force-exit on gates.

---

## Sleeve RESEARCH A — monitor only (NOT paper primary)

**ID:** `B7_ST_kill40_dd_mom_days60`  
**Code:** `strategies/nifty_edge_best.py`, `r29.py`  
**Pine:** `pinescript/nifty_edge_best.pine`

Same as Paper A **plus** days-since-high ≤ 60. Use for live divergence / skip log only.

---

## Block 10 sensitivity (Paper A only — no new gates)

{sens.get("summary_md", "(see results/block10_summary.json)")}

---

## Daily checklist

1. Update OHLCV for universe + ^NSEI.
2. Recompute ST trail, EMA200, Nifty bull, breadth50, dd, mom20.
3. Research twin: also compute days-since-high (monitor skips).
4. Exits first, then entries (rank + slots).
5. Log fills @ 0.08% RT (shadow 0.15% weekly).
6. Weekly: Paper A vs Research A equity / last-chunk; see `CHECKLIST.md`.

## Honesty

- Consecutive risk-adj promotes (B7+B8) with tied lastWF=9.2% — stacking smell.
- Days60-skip hist n=1; mom-skip n=2 — provisional.
- Placebo PASS but held-out late identical for B5/B6/B7 — prefer simpler Paper A.
- mult=3.6 local peak; avoid mult≈3.5 (fragile lastWF). Track 3.0 as conservative core elsewhere.
- No look-ahead. No new gate stacking in Block 10+.
"""
    PAPER_RULES.write_text(text)


def write_checklist(paper: dict, research: dict, hrs: float, sens: dict) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    po, ro = paper["OOS"], research["OOS"]
    text = f"""# Paper A vs Research A — Live Divergence Checklist

**Updated:** {now} (Block 10 — Paper A operationalized)
**Hours to deadline:** {hrs:.2f}
**Status:** Monitoring — research paper sleeves. No look-ahead. No live capital.

| Role | ID | Code |
|------|----|------|
| **PAPER A (primary)** | `B6_ST_kill40_dd_nifty_mom_m04` | `strategies/nifty_edge_paper.py` |
| **RESEARCH A (monitor)** | `B7_ST_kill40_dd_mom_days60` | `strategies/nifty_edge_best.py` / `r29.py` |
| Tertiary | `B5_ST_kill40_dd07` | `strategies/nifty_edge_b5_prior.py` |

**Rules:** `PAPER_TRADE_RULES.md`  
**Pine:** `nifty_edge_paper.pine` = Paper A; `nifty_edge_best.pine` = Research A (monitor)

OOS: Paper n={po['n_trades']} PF={po['profit_factor']:.2f} tot={po['total_return']*100:.1f}% lastWF={paper.get('last_wf_tot',0)*100:.1f}%  
vs Research n={ro['n_trades']} PF={ro['profit_factor']:.2f} tot={ro['total_return']*100:.1f}% lastWF={research.get('last_wf_tot',0)*100:.1f}%

---

## What should differ

| Gate | Paper A | Research A |
|------|:-------:|:----------:|
| Breadth50 ≥ 0.40 | YES | YES |
| Nifty dd ≥ −7% | YES | YES |
| Nifty ret20 ≥ −0.04 | YES | YES |
| Days-since-high ≤ 60 | **NO** | YES |
| ST 3.6 + Nifty bull + EMA200 | YES | YES |

---

## Block 10 Paper A sensitivity (no new gates)

{sens.get("summary_md", "")}

---

## Days60-skip (Research-only vs Paper) — thin-n honesty

Hist OOS: n=1 save-rate=100% — **provisional until n≥20**. See Block 8/9.

## Daily divergence log

| Date | Paper entries | Research entries | Research-only skips | Notes |
|------|-------------:|-----------------:|---------------------|-------|
| YYYY-MM-DD | | | days60 / — | |

## Weekly review

1. If Research lags Paper by >2pp for 3 weeks — expected if days60 over-filters; do not auto-promote Research to paper.
2. Days60-skip save-rate target ≥50% once n≥20.
3. **No new gate stacking.** No mid-paper param tweak.
4. Promote Research→Paper only if dual-clear lastWF **strictly >** Paper lastWF OR held-out clear win + ladder + boot.

## Honesty (Block 10)

- Paper A preferred via complexity (drop thin days60). Research files kept labeled.
- Overfit MIXED (placebo PASS, stacking smell, identical late held-out).
- Block 10 work = operationalize + execution/cost/universe/slots/mult stress on Paper A only.
"""
    CHECKLIST.write_text(text)


def expand_final_draft(
    paper: dict,
    research: dict,
    hrs: float,
    sens: dict,
    drift_paper: bool,
    drift_research: bool,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    po, ro = paper["OOS"], research["OOS"]
    draft = f"""# Nifty Edge 8h — FINAL REPORT (DRAFT — Block 10)

**Drafted:** {now}
**Hours to deadline:** {hrs:.2f}
**Status:** DRAFT — not locked. Lock when <1h via `FINAL_REPORT.md`.

## Executive verdict

| Role | Sleeve | Tot | LastWF | Use |
|------|--------|----:|-------:|-----|
| **PAPER A** | `B6_ST_kill40_dd_nifty_mom_m04` | {po['total_return']*100:.1f}% | {paper.get('last_wf_tot',0)*100:.1f}% | **Trade / paper this** |
| **RESEARCH A** | `B7_ST_kill40_dd_mom_days60` | {ro['total_return']*100:.1f}% | {research.get('last_wf_tot',0)*100:.1f}% | Monitor only (days60 stacked) |
| Tertiary | `B5_ST_kill40_dd07` | 113.4% | 9.2% | Fallback |
| Core | `ST_m3.6_n1_e1` | 110.2% | 5.8% | Trail baseline |

**Files**
- Paper: `strategies/nifty_edge_paper.py`, `pinescript/nifty_edge_paper.pine`
- Research: `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine`, `r29.py`
- Rules: `PAPER_TRADE_RULES.md` · Checklist: `CHECKLIST.md`

## Block 10 repro

- Research A drift_ok={drift_research}: {fmt_oos(research)}
- Paper A drift_ok={drift_paper}: {fmt_oos(paper)}

## Overfit assessment (unchanged honesty from B9)

MIXED: placebo calendars PASS for all four gates, but consecutive risk-adj promotes with
tied lastWF=9.2% + identical held-out late tot=12.7% for B5/B6/B7 + thin skip n
(days60=1, mom=2) still smell like filter stacking on early/mid OOS.
**Paper A = B6 (drop days60). Research A kept. NO new stacking in Block 10.**

## Path (Blocks 1–10)

1. B1–4: ST_m3.6 + Nifty + EMA200 core; kill-breadth near-miss.
2. B5: promote kill40+dd (dual-clear lastWF 9.2%).
3. B6: neighborhood freeze; nifty_mom near-miss (risk-adj later).
4. B7–8: consecutive **risk-adj** promotes (mom → days60) with **tied lastWF**.
5. B9: anti-overfit → complexity prefers Paper A = B6.
6. **B10: operationalize Paper A; sensitivity (exec/cost/universe/slots/mult) — no new gates.**

## Block 10 Paper A sensitivity

{sens.get("summary_md", "")}

### Interpretation
- Primary fill remains **next-open entry / close exit**.
- Close-entry is a realism stress only — do not retune gates on it.
- Cost ladder should remain roughly linear; document if a rung fails PF≥1.3.
- Universe drop / slots=4: robustness check — keep 20-name / 5-slot default unless collapse.
- ST mult neighborhood: avoid fragile mult≈3.5; keep 3.6 as Paper A default.

## What not to do

- Do not stack more gates without dual-clear lastWF strictly > Paper A lastWF.
- Do not treat days60/mom skip save-rates as confirmatory while n<20.
- Do not silently make `nifty_edge_best.py` the paper sleeve without labeling.

## Lock criteria

When hours_left < 1.0 → write `FINAL_REPORT.md` and freeze params.
Until then this draft + outline are the publishable body.

## Buy & hold reference

^NSEI OOS ~tot 70.5% Sharpe ~0.76 (see leaderboard).
"""
    FINAL_DRAFT.write_text(draft)

    outline = f"""# FINAL_REPORT outline (Block 10 — Paper A operationalized)

**Drafted:** {now}
**Hours to deadline:** {hrs:.2f}
**Status:** Expanded draft — full FINAL_REPORT lock when <1h.

## 1. Executive verdict
- **PAPER A:** `B6_ST_kill40_dd_nifty_mom_m04` — tot={po['total_return']*100:.1f}% lastWF={paper.get('last_wf_tot',0)*100:.1f}%
- **RESEARCH A (monitor):** `B7_ST_kill40_dd_mom_days60` — tot={ro['total_return']*100:.1f}% lastWF={research.get('last_wf_tot',0)*100:.1f}%
- Overfit MIXED; no new stacking.

## 2. Path B1–B10
- See FINAL_REPORT_DRAFT.md § Path.

## 3. Anti-overfit (B9) + ops (B10)
- Placebo/ablation/complexity → Paper A = B6.
- B10: repro + paper files + sensitivity on Paper A only.

## 4. Paper freeze
- `nifty_edge_paper.py` / `nifty_edge_paper.pine` = PAPER A
- `nifty_edge_best.py` / `nifty_edge_best.pine` = RESEARCH A monitor

## 5. Open / Block 11 or FINAL
- Live days60-skip log until n≥20.
- Full FINAL lock when <1h.
- Block 11 (if time): paper shadow P&L hygiene only; still no stacking.
"""
    FINAL_OUTLINE.write_text(outline)


def append_leaderboard(
    paper: dict,
    research: dict,
    hrs: float,
    sens: dict,
    drift_paper: bool,
    drift_research: bool,
    bh_oos: dict,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    po, ro = paper["OOS"], research["OOS"]
    block = f"""
## Block 10 — Paper A operationalize; Research A monitor; no new gates

**Updated:** {now}
**Hours to deadline:** {hrs:.2f}

### ★ PAPER vs RESEARCH (prominent)

| Role | Name | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | Files |
|------|------|--:|---:|----:|----:|-------:|----:|-------:|-------|
| **PAPER A** | B6_ST_kill40_dd_nifty_mom_m04 | {po['n_trades']} | {po['profit_factor']:.2f} | {po['total_return']*100:.1f}% | {po['max_dd']*100:.1f}% | {po['sharpe']:.2f} | {paper.get('wf_pos')}/{paper.get('wf_n')} | {paper.get('last_wf_tot',0)*100:.1f}% | `nifty_edge_paper.py` / `nifty_edge_paper.pine` |
| **RESEARCH A** | B7_ST_kill40_dd_mom_days60 | {ro['n_trades']} | {ro['profit_factor']:.2f} | {ro['total_return']*100:.1f}% | {ro['max_dd']*100:.1f}% | {ro['sharpe']:.2f} | {research.get('wf_pos')}/{research.get('wf_n')} | {research.get('last_wf_tot',0)*100:.1f}% | `nifty_edge_best.py` / `nifty_edge_best.pine` (monitor) |

**Repro:** paper drift_ok={drift_paper}; research drift_ok={drift_research}

### Paper A sensitivity (no new gates)

{sens.get("summary_md", "")}

**Buy&hold ^NSEI OOS:** tot={bh_oos['total_return']*100:.1f}% Sharpe={bh_oos['sharpe']:.2f}

### Honesty
- Paper A = complexity-preferred B6; Research A = stacked B7 monitor-only.
- Block 10 forbids new gate stacking; sensitivity only (exec/cost/universe/slots/mult).
- Overfit MIXED (B9). Days60-skip n=1 thin.
"""
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 10 —"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"
    # Keep Block 1 header but prepend Block 10 near top after intro? Append at end is fine;
    # also inject a short banner after the title block.
    banner = (
        "\n> **Block 10 freeze:** PAPER A = `B6_ST_kill40_dd_nifty_mom_m04` "
        "(`nifty_edge_paper.py`); RESEARCH A = `B7_…days60` (`nifty_edge_best.py`, monitor). "
        "See § Block 10 below.\n"
    )
    if "**Block 10 freeze:**" not in prev:
        # Insert after first heading block
        lines = prev.splitlines(True)
        insert_at = 0
        for i, ln in enumerate(lines):
            if ln.startswith("**Updated:**") or ln.startswith("**Costs:**"):
                insert_at = i + 1
                break
        if insert_at == 0:
            insert_at = min(5, len(lines))
        lines.insert(insert_at, banner)
        prev = "".join(lines)
    else:
        # refresh banner line
        import re

        prev = re.sub(
            r"> \*\*Block 10 freeze:\*\*.*\n",
            banner.lstrip("\n"),
            prev,
            count=1,
        )
    LEADERBOARD.write_text(prev.rstrip() + "\n" + block)


def main():
    hrs = hours_to_deadline()
    if past_deadline() or hrs < 1.0:
        log("DEADLINE/<1h — writing FINAL_REPORT and locking")
        from run_block1 import attach_rs_and_breadth

        nifty = prepare_symbol("^NSEI")
        bank = prepare_symbol("^NSEBANK")
        stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
        nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
        data = attach_market_to_stocks(stocks_raw, nifty, bank)
        data = attach_regime_features(data, nifty)
        data = attach_lastwf_features(data, nifty, bank)
        _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
        oos_start = oos_ref.index[0]
        # Lock with Paper A as operational champ narrative
        paper = portfolio_eval(
            "B6_ST_kill40_dd_nifty_mom_m04",
            data,
            sig_st_kill40_dd_nifty_mom,
            PAPER_PARAMS,
            oos_start,
        )
        paper["last_wf_tot"] = paper["wf"][-1]["total_return"] if paper["wf"] else 0.0
        write_full_final_if_needed(paper, hrs if hrs < 1.0 else -0.01)
        # Enrich FINAL with paper/research distinction
        if FINAL_REPORT.exists():
            extra = (
                "\n## Paper vs Research (locked)\n\n"
                "- **PAPER A:** B6_ST_kill40_dd_nifty_mom_m04 — `strategies/nifty_edge_paper.py`\n"
                "- **RESEARCH A (monitor):** B7_ST_kill40_dd_mom_days60 — `strategies/nifty_edge_best.py`\n"
                "- No new gate stacking after lock.\n"
            )
            FINAL_REPORT.write_text(FINAL_REPORT.read_text() + extra)
        log(f"Wrote {FINAL_REPORT}")
        print("FINALIZED_NEAR_DEADLINE")
        return

    log("=== Block 10 start ===")
    log(f"Hours to deadline: {hrs:.2f}")
    log("Loading Nifty + Bank + 20 stocks…")
    from run_block1 import attach_rs_and_breadth

    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    data = attach_lastwf_features(data, nifty, bank)

    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    bh_oos = buy_hold_stats(nifty.loc[nifty.index >= oos_start], "OOS")
    log(f"Buy&hold ^NSEI OOS: tot={bh_oos['total_return']*100:.1f}% Sharpe={bh_oos['sharpe']:.2f}")

    # ── 1) Side-by-side repro ─────────────────────────────────────────────────
    log("Repro RESEARCH A (B7) vs PAPER A (B6) side by side…")
    research = portfolio_eval(
        "B7_ST_kill40_dd_mom_days60",
        data,
        sig_st_kill40_dd_mom_days,
        RESEARCH_PARAMS,
        oos_start,
    )
    research["last_wf_tot"] = research["wf"][-1]["total_return"] if research["wf"] else 0.0
    paper = portfolio_eval(
        "B6_ST_kill40_dd_nifty_mom_m04",
        data,
        sig_st_kill40_dd_nifty_mom,
        PAPER_PARAMS,
        oos_start,
    )
    paper["last_wf_tot"] = paper["wf"][-1]["total_return"] if paper["wf"] else 0.0

    d_r = drift_ok(research["OOS"], REF_RESEARCH)
    d_p = drift_ok(paper["OOS"], REF_PAPER)
    log(f"  RESEARCH A: {fmt_oos(research)} drift_ok={d_r}")
    log(f"  PAPER A:    {fmt_oos(paper)} drift_ok={d_p}")

    b5 = portfolio_eval(
        "B5_ST_kill40_dd07", data, sig_st_kill40_dd, B5_PARAMS, oos_start
    )
    b5["last_wf_tot"] = b5["wf"][-1]["total_return"] if b5["wf"] else 0.0
    log(f"  Tertiary B5: {fmt_oos(b5)}")

    # ── 2) Operationalize Paper A files ───────────────────────────────────────
    log("Writing Paper A strategy + pine; annotating Research A labels…")
    p_py = write_paper_strategy(paper)
    p_pine = write_paper_pine()
    annotate_research_best_header()
    annotate_research_pine()
    log(f"  Wrote {p_py}")
    log(f"  Wrote {p_pine}")
    log("  Annotated nifty_edge_best.py / nifty_edge_best.pine as RESEARCH A monitor")

    # ── 3) Paper A sensitivity (no new gates) ─────────────────────────────────
    sens_rows: List[dict] = []
    log("Paper A sensitivity — execution realism (next-open vs close entry)…")
    base_oos = run_portfolio_ext(
        data, sig_st_kill40_dd_nifty_mom, PAPER_PARAMS, start_date=oos_start
    )
    close_oos = run_portfolio_close_entry(
        data, sig_st_kill40_dd_nifty_mom, PAPER_PARAMS, start_date=oos_start
    )
    sens_rows.append(
        {
            "check": "exec_next_open",
            "n": base_oos["n_trades"],
            "pf": base_oos["profit_factor"],
            "tot": base_oos["total_return"],
            "mdd": base_oos["max_dd"],
            "sharpe": base_oos["sharpe"],
            "note": "PRIMARY fill",
        }
    )
    sens_rows.append(
        {
            "check": "exec_close_entry",
            "n": close_oos["n_trades"],
            "pf": close_oos["profit_factor"],
            "tot": close_oos["total_return"],
            "mdd": close_oos["max_dd"],
            "sharpe": close_oos["sharpe"],
            "note": "stress only — same-bar close fill",
        }
    )
    log(
        f"  EXEC next-open: n={base_oos['n_trades']} PF={base_oos['profit_factor']:.2f} "
        f"tot={base_oos['total_return']*100:.1f}%"
    )
    log(
        f"  EXEC close-entry: n={close_oos['n_trades']} PF={close_oos['profit_factor']:.2f} "
        f"tot={close_oos['total_return']*100:.1f}% "
        f"(Δtot={(close_oos['total_return']-base_oos['total_return'])*100:+.1f}pp)"
    )

    log("Paper A cost ladder refresh 0.08–0.20%…")
    ladder = cost_ladder_row(
        "PAPER_A_B6", data, sig_st_kill40_dd_nifty_mom, PAPER_PARAMS, oos_start
    )
    for rung in ladder["ladder"]:
        log(
            f"  LADDER rt={rung['rt_pct']:.2f}%: PF={rung['pf']:.2f} "
            f"tot={rung['tot']*100:.1f}% MDD={rung['mdd']*100:.1f}%"
        )
        sens_rows.append(
            {
                "check": f"cost_rt_{rung['rt_pct']:.2f}",
                "n": rung["n"],
                "pf": rung["pf"],
                "tot": rung["tot"],
                "mdd": rung["mdd"],
                "sharpe": rung["sharpe"],
                "note": "cost ladder",
            }
        )
    tot_08 = ladder["ladder"][0]["tot"]
    tot_20 = ladder["ladder"][-1]["tot"]
    ladder_ok = all(r["pf"] >= 1.3 for r in ladder["ladder"])

    log("Paper A max-slots 4 vs 5…")
    for slots in (5, 4):
        row = portfolio_eval_ext(
            f"PAPER_slots{slots}",
            data,
            sig_st_kill40_dd_nifty_mom,
            {**PAPER_PARAMS, "max_positions": slots},
            oos_start,
        )
        row["last_wf_tot"] = row.get("last_wf_tot") or (
            row["wf"][-1]["total_return"] if row["wf"] else 0.0
        )
        log(f"  SLOTS={slots}: {fmt_oos(row)}")
        sens_rows.append(
            {
                "check": f"slots_{slots}",
                "n": row["OOS"]["n_trades"],
                "pf": row["OOS"]["profit_factor"],
                "tot": row["OOS"]["total_return"],
                "mdd": row["OOS"]["max_dd"],
                "sharpe": row["OOS"]["sharpe"],
                "last_wf": row["last_wf_tot"],
                "note": "max_positions",
            }
        )

    log("Paper A ST mult neighborhood…")
    mult_rows = []
    for m in (3.4, 3.5, 3.6, 3.7, 3.8):
        row = portfolio_eval(
            f"PAPER_m{m}",
            data,
            sig_st_kill40_dd_nifty_mom,
            {**PAPER_PARAMS, "mult": m},
            oos_start,
        )
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        fragile = row["last_wf_tot"] < 0 or row.get("wf_pos", 0) < 3
        log(
            f"  MULT={m}: {fmt_oos(row)}"
            + (" ⚠ FRAGILE" if fragile else "")
        )
        mult_rows.append(
            {
                "mult": m,
                "n": row["OOS"]["n_trades"],
                "pf": row["OOS"]["profit_factor"],
                "tot": row["OOS"]["total_return"],
                "mdd": row["OOS"]["max_dd"],
                "last_wf": row["last_wf_tot"],
                "wf_pos": row.get("wf_pos"),
                "fragile": fragile,
            }
        )
        sens_rows.append(
            {
                "check": f"mult_{m}",
                "n": row["OOS"]["n_trades"],
                "pf": row["OOS"]["profit_factor"],
                "tot": row["OOS"]["total_return"],
                "mdd": row["OOS"]["max_dd"],
                "last_wf": row["last_wf_tot"],
                "note": "fragile" if fragile else "ok",
            }
        )

    log("Paper A universe sensitivity (drop 1–2 names)…")
    univ_rows = []
    for label, drops in DROP_SETS:
        sub = {k: v for k, v in data.items() if k not in drops}
        row = portfolio_eval(
            f"PAPER_{label}",
            sub,
            sig_st_kill40_dd_nifty_mom,
            PAPER_PARAMS,
            oos_start,
        )
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        d_tot = (row["OOS"]["total_return"] - paper["OOS"]["total_return"]) * 100
        log(f"  UNIV {label}: {fmt_oos(row)} Δtot={d_tot:+.1f}pp")
        univ_rows.append(
            {
                "label": label,
                "dropped": drops,
                "n": row["OOS"]["n_trades"],
                "pf": row["OOS"]["profit_factor"],
                "tot": row["OOS"]["total_return"],
                "mdd": row["OOS"]["max_dd"],
                "last_wf": row["last_wf_tot"],
                "d_tot_pp": d_tot,
            }
        )
        sens_rows.append(
            {
                "check": label,
                "n": row["OOS"]["n_trades"],
                "pf": row["OOS"]["profit_factor"],
                "tot": row["OOS"]["total_return"],
                "mdd": row["OOS"]["max_dd"],
                "last_wf": row["last_wf_tot"],
                "note": f"drop {','.join(drops)}",
            }
        )

    # Build sensitivity markdown summary
    md_lines = [
        "| Check | n | PF | Tot | MDD | LastWF / note |",
        "|-------|--:|---:|----:|----:|---------------|",
        f"| exec next-open (PRIMARY) | {base_oos['n_trades']} | {base_oos['profit_factor']:.2f} | {base_oos['total_return']*100:.1f}% | {base_oos['max_dd']*100:.1f}% | primary fill |",
        f"| exec close-entry (stress) | {close_oos['n_trades']} | {close_oos['profit_factor']:.2f} | {close_oos['total_return']*100:.1f}% | {close_oos['max_dd']*100:.1f}% | Δtot={(close_oos['total_return']-base_oos['total_return'])*100:+.1f}pp |",
    ]
    for r in ladder["ladder"]:
        md_lines.append(
            f"| cost {r['rt_pct']:.2f}% RT | {r['n']} | {r['pf']:.2f} | {r['tot']*100:.1f}% | {r['mdd']*100:.1f}% | ladder_ok={ladder_ok} |"
        )
    for slots in (5, 4):
        hit = next(s for s in sens_rows if s["check"] == f"slots_{slots}")
        md_lines.append(
            f"| max_slots={slots} | {hit['n']} | {hit['pf']:.2f} | {hit['tot']*100:.1f}% | {hit['mdd']*100:.1f}% | lastWF={hit.get('last_wf',0)*100:.1f}% |"
        )
    for m in mult_rows:
        flag = " FRAGILE" if m["fragile"] else ""
        md_lines.append(
            f"| ST mult={m['mult']} | {m['n']} | {m['pf']:.2f} | {m['tot']*100:.1f}% | {m['mdd']*100:.1f}% | lastWF={m['last_wf']*100:.1f}%{flag} |"
        )
    for u in univ_rows:
        md_lines.append(
            f"| univ {u['label']} | {u['n']} | {u['pf']:.2f} | {u['tot']*100:.1f}% | {u['mdd']*100:.1f}% | Δtot={u['d_tot_pp']:+.1f}pp lastWF={u['last_wf']*100:.1f}% |"
        )
    md_lines.append("")
    md_lines.append(
        f"- Cost ΔTot 0.08→0.20% = {(tot_20-tot_08)*100:.1f}pp; all rungs PF≥1.3: **{ladder_ok}**"
    )
    md_lines.append(
        f"- Close-entry ΔTot vs next-open = {(close_oos['total_return']-base_oos['total_return'])*100:+.1f}pp "
        "(stress only; keep next-open as paper fill)."
    )
    fragile_mults = [m["mult"] for m in mult_rows if m["fragile"]]
    md_lines.append(
        f"- Fragile ST mults: {fragile_mults or 'none'}; keep Paper A mult=**3.6**."
    )
    md_lines.append("- Default universe 20 names / max_slots=5 unchanged.")

    sens = {
        "summary_md": "\n".join(md_lines),
        "rows": sens_rows,
        "ladder": ladder,
        "mult": mult_rows,
        "universe": univ_rows,
        "exec": {
            "next_open": base_oos,
            "close_entry": close_oos,
            "d_tot_pp": (close_oos["total_return"] - base_oos["total_return"]) * 100,
        },
        "ladder_ok": ladder_ok,
        "cost_delta_08_20_pp": (tot_20 - tot_08) * 100,
    }

    # ── 4) Docs / board / draft ───────────────────────────────────────────────
    log("Updating PAPER_TRADE_RULES / CHECKLIST / FINAL draft / leaderboard…")
    write_paper_rules(paper, research, hrs, sens)
    write_checklist(paper, research, hrs, sens)
    expand_final_draft(paper, research, hrs, sens, d_p, d_r)
    append_leaderboard(paper, research, hrs, sens, d_p, d_r, bh_oos)
    log(f"Wrote {PAPER_RULES}")
    log(f"Wrote {CHECKLIST}")
    log(f"Wrote {FINAL_DRAFT}")
    log(f"Wrote {FINAL_OUTLINE}")
    log(f"Updated {LEADERBOARD}")

    if hrs < 1.0:
        write_full_final_if_needed(paper, hrs)
        log("FULL FINAL written (<1h)")
    else:
        log(f"FINAL draft only ({hrs:.1f}h left; full lock later)")

    summary = {
        "block": 10,
        "hours_left": hrs,
        "paper_a": {
            "name": paper["name"],
            "n": paper["OOS"]["n_trades"],
            "pf": paper["OOS"]["profit_factor"],
            "tot": paper["OOS"]["total_return"],
            "mdd": paper["OOS"]["max_dd"],
            "sharpe": paper["OOS"]["sharpe"],
            "last_wf": paper["last_wf_tot"],
            "drift_ok": d_p,
            "files": [
                "strategies/nifty_edge_paper.py",
                "pinescript/nifty_edge_paper.pine",
            ],
        },
        "research_a": {
            "name": research["name"],
            "n": research["OOS"]["n_trades"],
            "pf": research["OOS"]["profit_factor"],
            "tot": research["OOS"]["total_return"],
            "mdd": research["OOS"]["max_dd"],
            "sharpe": research["OOS"]["sharpe"],
            "last_wf": research["last_wf_tot"],
            "drift_ok": d_r,
            "files": [
                "strategies/nifty_edge_best.py",
                "pinescript/nifty_edge_best.pine",
                "strategies/nifty_edge_r29.py",
            ],
            "role": "monitor_only",
        },
        "recommendation": (
            "PAPER A = B6_ST_kill40_dd_nifty_mom_m04 (nifty_edge_paper.py); "
            "RESEARCH A = B7_ST_kill40_dd_mom_days60 (nifty_edge_best.py, monitor). "
            "No new gate stacking. Overfit MIXED."
        ),
        "sensitivity": {
            "ladder_ok": ladder_ok,
            "cost_delta_08_20_pp": sens["cost_delta_08_20_pp"],
            "exec_close_d_tot_pp": sens["exec"]["d_tot_pp"],
            "fragile_mults": fragile_mults,
            "mult": mult_rows,
            "universe": univ_rows,
            "rows": sens_rows,
        },
        "buy_hold_oos": {"tot": bh_oos["total_return"], "sharpe": bh_oos["sharpe"]},
        "no_new_gates": True,
    }
    out_path = RESULTS / "block10_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    log(f"Wrote {out_path}")

    log("--- Block 10 Paper vs Research ---")
    log(f"  PAPER A:    {paper['name']} tot={paper['OOS']['total_return']*100:.1f}% lastWF={paper['last_wf_tot']*100:.1f}%")
    log(f"  RESEARCH A: {research['name']} tot={research['OOS']['total_return']*100:.1f}% lastWF={research['last_wf_tot']*100:.1f}% (monitor)")
    log(
        f"=== Block 10 complete === paper={paper['name']} research={research['name']} "
        f"drift_p={d_p} drift_r={d_r} ladder_ok={ladder_ok} hrs_left={hrs:.2f}"
    )
    log(
        "Next Block 11: paper shadow hygiene / live skip log; still no stacking; "
        "FINAL lock when <1h."
    )
    print(
        json.dumps(
            {
                "paper_a": paper["name"],
                "research_a": research["name"],
                "drift_paper": d_p,
                "drift_research": d_r,
                "ladder_ok": ladder_ok,
                "exec_close_d_tot_pp": sens["exec"]["d_tot_pp"],
                "fragile_mults": fragile_mults,
                "hrs_left": hrs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
