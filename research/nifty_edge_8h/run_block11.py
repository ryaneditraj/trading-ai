#!/usr/bin/env python3
"""
Block 11 — Paper shadow P&L hygiene; days60-skip live log; no new gates.

Mandatory:
  1) Repro Paper A (B6) + Research A (B7)
  2) Shadow P&L: 0.08% + 0.15% RT; weekly equity table; SHADOW.md / CHECKLIST
  3) Structure live days60-skip log template (until n≥20)
  4) No new gates / no mid-paper param tweaks
       Allowed: pine conceptual compile check; doc/code mismatch fixes;
       universe listing freeze; FINAL_REPORT_DRAFT → publishable
  5) Optional: Paper A vs ^NSEI BH vs EW basket BH (same OOS) — one table
  6) Update log/leaderboard; full FINAL lock only if <1h

Usage:
  python research/nifty_edge_8h/run_block11.py
"""
from __future__ import annotations

import json
import re
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
    RT_STRESS,
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
    run_portfolio_ext,
)
from run_block4 import attach_regime_features  # noqa: E402
from run_block5 import attach_lastwf_features  # noqa: E402
from run_block6 import hours_to_deadline, write_full_final_if_needed  # noqa: E402
from run_block6 import sig_st_kill40_dd_nifty_mom  # noqa: E402
from run_block7 import sig_st_kill40_dd_mom_days  # noqa: E402
from run_block8 import weekly_equity_delta  # noqa: E402
from run_block9 import analyze_days60_skips, verify_pine_vs_python  # noqa: E402

HERE = Path(__file__).resolve().parent
CHECKLIST = HERE / "CHECKLIST.md"
PAPER_RULES = HERE / "PAPER_TRADE_RULES.md"
FINAL_OUTLINE = HERE / "FINAL_REPORT_OUTLINE.md"
FINAL_DRAFT = HERE / "FINAL_REPORT_DRAFT.md"
FINAL_REPORT = HERE / "FINAL_REPORT.md"
SHADOW = HERE / "SHADOW.md"
DAYS60_LOG = HERE / "DAYS60_SKIP_LOG.md"
UNIVERSE_FREEZE = HERE / "UNIVERSE_FREEZE.md"
OUT_PINE_PAPER = ROOT / "pinescript" / "nifty_edge_paper.pine"
OUT_PINE_BEST = ROOT / "pinescript" / "nifty_edge_best.pine"

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

FROZEN_UNIVERSE = list(UNIVERSE)


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


def weekly_equity_table(eq: pd.Series, label: str) -> dict:
    """Friday-close weekly equity levels + week returns for shadow book."""
    if eq is None or len(eq) < 5:
        return {"label": label, "n_weeks": 0, "error": "thin equity", "weeks": []}
    w = eq.resample("W-FRI").last().dropna()
    if len(w) < 2:
        return {"label": label, "n_weeks": len(w), "error": "need ≥2 weeks", "weeks": []}
    rets = w.pct_change()
    weeks = []
    for i, dt in enumerate(w.index):
        weeks.append(
            {
                "week": str(dt.date()),
                "equity": float(w.iloc[i]),
                "week_ret": float(rets.iloc[i]) if i > 0 and not np.isnan(rets.iloc[i]) else None,
            }
        )
    r = rets.dropna()
    return {
        "label": label,
        "n_weeks": int(len(r)),
        "start_eq": float(w.iloc[0]),
        "end_eq": float(w.iloc[-1]),
        "tot_from_weekly": float(w.iloc[-1] / w.iloc[0] - 1.0),
        "mean_week_pp": float(r.mean() * 100) if len(r) else None,
        "median_week_pp": float(r.median() * 100) if len(r) else None,
        "worst_week_pp": float(r.min() * 100) if len(r) else None,
        "best_week_pp": float(r.max() * 100) if len(r) else None,
        "weeks": weeks,  # full hist for SHADOW.md (trimmed in display)
    }


def equal_weight_bh(data: Dict[str, pd.DataFrame], start_date) -> dict:
    """Daily equal-weight buy-and-hold of universe on OOS window."""
    closes = {}
    for s, df in data.items():
        c = df.loc[df.index >= start_date, "Close"]
        if len(c):
            closes[s] = c
    if not closes:
        return {"n_trades": 0, "total_return": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    px = pd.DataFrame(closes).sort_index().ffill().dropna(how="all")
    rets = px.pct_change()
    port = rets.mean(axis=1).dropna()
    if len(port) < 2:
        return {"n_trades": 0, "total_return": 0.0, "max_dd": 0.0, "sharpe": 0.0}
    eq = (1.0 + port).cumprod()
    # One RT at end for fairness vs single-hold BH convention
    total = float(eq.iloc[-1] - 1.0 - RT)
    peak = eq.cummax()
    dd = float((eq / peak - 1.0).min())
    sharpe = float(port.mean() / port.std() * np.sqrt(252)) if port.std() > 0 else 0.0
    return {
        "n_trades": 1,
        "total_return": total,
        "max_dd": dd,
        "sharpe": sharpe,
        "n_names": int(px.shape[1]),
        "equity": eq,
    }


def verify_pine_pair() -> dict:
    """Conceptual compile / rule check for paper + research pine."""
    # Patch verify_pine_vs_python which reads nifty_edge_best.pine via OUT_PINE
    # We check both files explicitly here.
    checks = {}
    for label, path in (("paper", OUT_PINE_PAPER), ("research", OUT_PINE_BEST)):
        pine = path.read_text() if path.exists() else ""
        c = {
            "exists": path.exists(),
            "version5": pine.startswith("//@version=5"),
            "mult_3_6": "input.float(3.6" in pine,
            "ema200": "input.int(200" in pine,
            "crossover_entry": "ta.crossover(close, finalLB)" in pine,
            "exit_below": "close < finalLB" in pine,
            "next_open": "process_orders_on_close=false" in pine,
            "basket_disclaimer": "SINGLE SYMBOL" in pine or "single-symbol" in pine.lower(),
            "role_labeled": ("PAPER A" in pine) if label == "paper" else ("RESEARCH A" in pine),
        }
        if label == "paper":
            c["no_days60_gate"] = "NO days-since-high" in pine or "no days60" in pine.lower()
        else:
            c["days60_documented"] = "days_since_high" in pine.lower() or "days60" in pine.lower()
        c["core_ok"] = all(
            c[k]
            for k in (
                "exists",
                "version5",
                "mult_3_6",
                "ema200",
                "crossover_entry",
                "exit_below",
                "next_open",
                "basket_disclaimer",
                "role_labeled",
            )
        )
        checks[label] = c
    # Also run Block-9 helper on research pine (its OUT_PINE target)
    try:
        checks["block9_helper"] = verify_pine_vs_python()
    except Exception as e:
        checks["block9_helper"] = {"error": str(e)}
    checks["both_core_ok"] = bool(
        checks["paper"]["core_ok"] and checks["research"]["core_ok"]
    )
    return checks


def write_universe_freeze(hrs: float) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tickers = ", ".join(FROZEN_UNIVERSE)
    UNIVERSE_FREEZE.write_text(
        f"""# Universe Freeze — Paper A (Block 11)

**Frozen:** {now}
**Hours to deadline:** {hrs:.2f}
**Source of truth:** `UNIVERSE` in `research/nifty_edge_8h/run_block1.py`
**n names:** {len(FROZEN_UNIVERSE)}
**max_slots:** 5 (do not change mid-paper)

## Tickers (exact order)

```
{chr(10).join(FROZEN_UNIVERSE)}
```

One-line: `{tickers}`

## Rules
- Do **not** drop/add names mid-paper without a documented held-out dual-clear.
- Block 10 drop sensitivity (WIPRO / BAJFINANCE) was stress-only — default stays 20.
- Index filter: `^NSEI` daily. Bank reference: `^NSEBANK` (RS/breadth only).
"""
    )


def write_days60_skip_log(days60: dict, hrs: float) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n = days60.get("n_skips", 0)
    save = days60.get("save_rate")
    save_s = f"{save*100:.0f}%" if save is not None else "—"
    hist_rows = ""
    for s in days60.get("skips", [])[:20]:
        hist_rows += (
            f"| {s['sig_dt']} | {s['symbol']} | {s['days_since_high']:.0f} | "
            f"{s['entry']} | {s['exit']} | {s['ret']*100:+.2f}% | "
            f"{'W' if s['winner'] else 'L'} | hist OOS |\n"
        )
    if not hist_rows:
        hist_rows = "| — | — | — | — | — | — | — | no hist skips |\n"

    DAYS60_LOG.write_text(
        f"""# Days60-Skip Live Log — Research A vs Paper A

**Created:** {now} (Block 11)
**Hours to deadline:** {hrs:.2f}
**Purpose:** Record every signal where Paper A would enter but Research A skips
because `nifty_days_since_high > 60`. Accumulate until **n≥20** before treating
save-rate as soft evidence.

**Roles**
- Paper A (trade): `B6_ST_kill40_dd_nifty_mom_m04` — **no** days60 gate
- Research A (monitor): `B7_ST_kill40_dd_mom_days60` — days≤60 gate ON

## How to record (until n≥20)

1. After daily signal pass, list Paper A entry candidates (next-open fills).
2. For each candidate, compute causal `nifty_days_since_high` on signal bar.
3. If days > 60 → Research would skip. Log a row **even if** you still take the
   Paper A fill (you should — Paper A is primary).
4. When the Paper A trade exits, fill `exit_date`, `ret_%`, `W/L`.
5. **Save-rate** = losers among skips / n_skips. Target ≥50% once n≥20.
6. Do **not** flip Research→Paper on thin-n. Do **not** add new gates.

### Row fields
| Field | Meaning |
|-------|---------|
| date_signal | Signal bar (close) that triggered Paper entry |
| symbol | Ticker |
| days_since_high | Causal Nifty days since prior high |
| paper_entry | Next-open fill date |
| paper_exit | Exit date (or open) |
| ret_% | Paper trade return after 0.08% RT |
| W/L | Winner if ret>0 |
| notes | Optional (halt, gap, data issue) |

## Historical OOS skips (thin — provisional)

Hist n={n} save-rate={save_s} — **{days60.get('honesty', 'provisional')}**

| date_signal | symbol | days_since_high | paper_entry | paper_exit | ret_% | W/L | notes |
|-------------|--------|----------------:|-------------|------------|------:|:---:|-------|
{hist_rows}
## Live log (append below)

| date_signal | symbol | days_since_high | paper_entry | paper_exit | ret_% | W/L | notes |
|-------------|--------|----------------:|-------------|------------|------:|:---:|-------|
| YYYY-MM-DD | TICKER.NS | | | | | | |

**Running tally:** hist_n={n} + live_n=0 → combined=**{n}** (need ≥20).
**Promote Research→Paper only if:** dual-clear lastWF **strictly >** Paper lastWF
OR held-out clear win + ladder + boot — never on skip-rate alone while n<20.
"""
    )


def write_shadow_md(
    paper_08: dict,
    paper_15: dict,
    weekly_08: dict,
    weekly_15: dict,
    weekly_delta: dict,
    bench: dict,
    hrs: float,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    p08, p15 = paper_08, paper_15

    def week_md(w: dict, n_show: int = 12) -> str:
        rows = w.get("weeks", [])[-n_show:]
        if not rows:
            return "| — | — | — |\n"
        out = ""
        for r in rows:
            wr = r["week_ret"]
            wr_s = f"{wr*100:+.2f}%" if wr is not None else "—"
            out += f"| {r['week']} | {r['equity']:.4f} | {wr_s} |\n"
        return out

    delta_rows = ""
    for w in weekly_delta.get("weeks", [])[-8:]:
        delta_rows += (
            f"| {w['week']} | {w['a_ret']*100:+.2f}% | {w['b_ret']*100:+.2f}% | "
            f"{w['delta_a_minus_b']*100:+.2f}pp |\n"
        )
    if not delta_rows:
        delta_rows = "| — | — | — | — |\n"

    SHADOW.write_text(
        f"""# Paper A Shadow P&L — Block 11

**Updated:** {now}
**Hours to deadline:** {hrs:.2f}
**Sleeve:** `B6_ST_kill40_dd_nifty_mom_m04` (`strategies/nifty_edge_paper.py`)
**Status:** Simulated paper book on historical OOS — not live capital.

## Assumptions (read before comparing live)

| Assumption | Value | Notes |
|------------|-------|-------|
| Fill | Next session **open** entry; exit on signal-bar **close** | Matches engine primary |
| Costs primary | **0.08% round-trip** (`RT=0.0008`) | Applied once per completed trade |
| Costs shadow | **0.15% round-trip** (`RT_STRESS=0.0015`) | Parallel book; do not retune gates |
| Sizing | Equal-risk **1/5** equity per new slot; max 5 | Cash leftover idle |
| Universe | Frozen 20 NSE large-caps | See `UNIVERSE_FREEZE.md` |
| Side | Long-only | No shorts / hedges |
| Cadence | Daily bars | No intraday |
| Look-ahead | None | Gates use causal features only |
| Slippage model | Absorbed in RT cost | No separate tick slippage |
| Dividends / corp actions | As in Yahoo/adjusted closes | Not modeled separately |
| Starting equity | 1.0 (normalized) | Scale to paper notional offline |

**Hygiene rules**
1. Log every fill under **both** 0.08% and 0.15% books (same signals).
2. Weekly review uses Friday-close equity (table below).
3. If 0.15% weekly P&L flips ranking vs Research for 3+ weeks — flag only; no auto-flip.
4. **No mid-paper param tweaks.** Cost stress ≠ license to change mult/gates.

## OOS book summary

| Book | n | PF | Tot | MDD | Sharpe |
|------|--:|---:|----:|----:|-------:|
| Paper A @ 0.08% RT | {p08['n_trades']} | {p08['profit_factor']:.2f} | {p08['total_return']*100:.1f}% | {p08['max_dd']*100:.1f}% | {p08['sharpe']:.2f} |
| Paper A @ 0.15% RT | {p15['n_trades']} | {p15['profit_factor']:.2f} | {p15['total_return']*100:.1f}% | {p15['max_dd']*100:.1f}% | {p15['sharpe']:.2f} |
| Δ (0.15 − 0.08) | — | — | {(p15['total_return']-p08['total_return'])*100:+.1f}pp | — | — |

## Benchmarks (same OOS window)

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A @ 0.08% | {p08['total_return']*100:.1f}% | {p08['max_dd']*100:.1f}% | {p08['sharpe']:.2f} |
| Buy&hold ^NSEI | {bench['nsei']['total_return']*100:.1f}% | {bench['nsei']['max_dd']*100:.1f}% | {bench['nsei']['sharpe']:.2f} |
| EW buy-hold basket (20) | {bench['ew']['total_return']*100:.1f}% | {bench['ew']['max_dd']*100:.1f}% | {bench['ew']['sharpe']:.2f} |

Excess vs ^NSEI: **{(p08['total_return']-bench['nsei']['total_return'])*100:+.1f}pp**
Excess vs EW basket: **{(p08['total_return']-bench['ew']['total_return'])*100:+.1f}pp**

## Weekly equity — 0.08% RT (last ≤12 weeks)

| Week (Fri) | Equity | Week ret |
|------------|-------:|---------:|
{week_md(weekly_08)}
n_weeks={weekly_08.get('n_weeks')} mean={weekly_08.get('mean_week_pp')}pp worst={weekly_08.get('worst_week_pp')}pp

## Weekly equity — 0.15% RT shadow (last ≤12 weeks)

| Week (Fri) | Equity | Week ret |
|------------|-------:|---------:|
{week_md(weekly_15)}
n_weeks={weekly_15.get('n_weeks')} mean={weekly_15.get('mean_week_pp')}pp worst={weekly_15.get('worst_week_pp')}pp

## Weekly Δ (0.08 − 0.15) recent

| Week | ret_0.08 | ret_0.15 | Δ pp |
|------|---------:|---------:|-----:|
{delta_rows}
mean Δ={weekly_delta.get('mean_delta_pp')}pp · flag_3w_stress_lead={weekly_delta.get('flag_3w_b_lead')}

## Live paper template (append weekly)

| Week ending | Eq 0.08 | WeekΔ 0.08 | Eq 0.15 | WeekΔ 0.15 | Notes |
|-------------|--------:|-----------:|--------:|-----------:|-------|
| YYYY-MM-DD | | | | | |
"""
    )


def write_checklist(
    paper: dict,
    research: dict,
    hrs: float,
    weekly_08: dict,
    weekly_15: dict,
    days60: dict,
    pine: dict,
    bench: dict,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    po, ro = paper["OOS"], research["OOS"]
    CHECKLIST.write_text(
        f"""# Paper A vs Research A — Live Divergence Checklist

**Updated:** {now} (Block 11 — shadow hygiene + days60 log)
**Hours to deadline:** {hrs:.2f}
**Status:** Monitoring — research paper sleeves. No look-ahead. No live capital.

| Role | ID | Code |
|------|----|------|
| **PAPER A (primary)** | `B6_ST_kill40_dd_nifty_mom_m04` | `strategies/nifty_edge_paper.py` |
| **RESEARCH A (monitor)** | `B7_ST_kill40_dd_mom_days60` | `strategies/nifty_edge_best.py` / `r29.py` |
| Tertiary | `B5_ST_kill40_dd07` | `strategies/nifty_edge_b5_prior.py` |

**Rules:** `PAPER_TRADE_RULES.md`  
**Shadow:** `SHADOW.md` · **Days60 log:** `DAYS60_SKIP_LOG.md` · **Universe:** `UNIVERSE_FREEZE.md`  
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

## Shadow P&L hygiene (Block 11)

| Book | n | PF | Tot | MDD | Weekly mean |
|------|--:|---:|----:|----:|------------:|
| 0.08% RT (primary) | {po['n_trades']} | {po['profit_factor']:.2f} | {po['total_return']*100:.1f}% | {po['max_dd']*100:.1f}% | {weekly_08.get('mean_week_pp')}pp |
| 0.15% RT (shadow) | — | — | see SHADOW.md | — | {weekly_15.get('mean_week_pp')}pp |

Assumptions documented in `SHADOW.md` (next-open fill, equal 1/5 slots, frozen 20-name univ).

### Benchmarks same OOS

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A 0.08% | {po['total_return']*100:.1f}% | {po['max_dd']*100:.1f}% | {po['sharpe']:.2f} |
| ^NSEI BH | {bench['nsei']['total_return']*100:.1f}% | {bench['nsei']['max_dd']*100:.1f}% | {bench['nsei']['sharpe']:.2f} |
| EW basket BH | {bench['ew']['total_return']*100:.1f}% | {bench['ew']['max_dd']*100:.1f}% | {bench['ew']['sharpe']:.2f} |

---

## Days60-skip (Research-only vs Paper) — thin-n honesty

Hist OOS: n={days60.get('n_skips', 0)} save-rate={
    f"{days60['save_rate']*100:.0f}%" if days60.get('save_rate') is not None else "—"
} — **provisional until n≥20**. Live template: `DAYS60_SKIP_LOG.md`.

---

## Pine conceptual check (Block 11)

| File | core_ok |
|------|:-------:|
| `nifty_edge_paper.pine` | {pine['paper']['core_ok']} |
| `nifty_edge_best.pine` | {pine['research']['core_ok']} |

Both are single-symbol ST+EMA proxies; basket gates live in Python only.

---

## Daily divergence log

| Date | Paper entries | Research entries | Research-only skips | Notes |
|------|-------------:|-----------------:|---------------------|-------|
| YYYY-MM-DD | | | days60 / — | |

## Weekly review

1. If Research lags Paper by >2pp for 3 weeks — expected if days60 over-filters; do not auto-promote Research to paper.
2. Days60-skip save-rate target ≥50% once n≥20.
3. **No new gate stacking.** No mid-paper param tweak.
4. Promote Research→Paper only if dual-clear lastWF **strictly >** Paper lastWF OR held-out clear win + ladder + boot.
5. Shadow 0.15% book: review Friday equity in `SHADOW.md`; flag only if stress flips narrative.

## Honesty (Block 11)

- Paper A preferred via complexity (drop thin days60). Research files kept labeled.
- Shadow + skip log only this block — **no new gates**.
"""
    )


def expand_final_draft(
    paper: dict,
    research: dict,
    hrs: float,
    d_p: bool,
    d_r: bool,
    bench: dict,
    pine: dict,
    days60: dict,
    shadow_meta: dict,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    po, ro = paper["OOS"], research["OOS"]
    FINAL_DRAFT.write_text(
        f"""# Nifty Edge 8h — FINAL REPORT (DRAFT — Block 11)

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
- Rules: `PAPER_TRADE_RULES.md` · Checklist: `CHECKLIST.md` · Shadow: `SHADOW.md`
- Skip log: `DAYS60_SKIP_LOG.md` · Universe: `UNIVERSE_FREEZE.md`

## Methods

### Data & split
- Daily OHLCV for ^NSEI, ^NSEBANK, and 20 NSE large-caps (Yahoo-adjusted).
- Time split: `TRAIN_FRAC=0.70` IS / OOS on calendar index (no shuffle).
- Walk-forward: 3 equal OOS chunks; lastWF = last chunk total return.
- Features causal: breadth50, nifty_dd_hh55, nifty_ret20, nifty_days_since_high,
  Supertrend ATR(14)×3.6, stock EMA200, Nifty bull regime.

### Portfolio engine
- Long-only basket, max **5** equal-risk slots, rank by Close/EMA200 − 1.
- Entry fill: **next open** after signal close (primary).
- Exit fill: signal-bar close when Close < ST lower band.
- Costs: **0.08% RT** primary; **0.15%** stress / shadow book.
- No look-ahead; gates entry-only (exits ignore kill/dd/mom/days).

### Frozen universe ({len(FROZEN_UNIVERSE)} names)
{chr(10).join('- `' + s + '`' for s in FROZEN_UNIVERSE)}

### Promotion rules (campaign)
- Dual-clear: challenger tot **and** lastWF strictly above champ.
- Cost ladder PF≥1.3 across 0.08–0.20% RT.
- Complexity: prefer fewer gates if within ~10% tot and lastWF ≥ champ.
- **No mid-paper param tweaks.** No new gate stacking after Paper A freeze.

## Metrics (Block 11 repro)

| Sleeve | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | drift_ok |
|--------|--:|---:|----:|----:|-------:|----:|-------:|:--------:|
| Paper A | {po['n_trades']} | {po['profit_factor']:.2f} | {po['total_return']*100:.1f}% | {po['max_dd']*100:.1f}% | {po['sharpe']:.2f} | {paper.get('wf_pos')}/{paper.get('wf_n')} | {paper.get('last_wf_tot',0)*100:.1f}% | {d_p} |
| Research A | {ro['n_trades']} | {ro['profit_factor']:.2f} | {ro['total_return']*100:.1f}% | {ro['max_dd']*100:.1f}% | {ro['sharpe']:.2f} | {research.get('wf_pos')}/{research.get('wf_n')} | {research.get('last_wf_tot',0)*100:.1f}% | {d_r} |

### Benchmarks (same OOS)

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A @ 0.08% RT | {po['total_return']*100:.1f}% | {po['max_dd']*100:.1f}% | {po['sharpe']:.2f} |
| Buy&hold ^NSEI | {bench['nsei']['total_return']*100:.1f}% | {bench['nsei']['max_dd']*100:.1f}% | {bench['nsei']['sharpe']:.2f} |
| EW buy-hold basket | {bench['ew']['total_return']*100:.1f}% | {bench['ew']['max_dd']*100:.1f}% | {bench['ew']['sharpe']:.2f} |

Paper excess vs ^NSEI: **{(po['total_return']-bench['nsei']['total_return'])*100:+.1f}pp**;
vs EW basket: **{(po['total_return']-bench['ew']['total_return'])*100:+.1f}pp**.

### Shadow books
- 0.08% tot={shadow_meta['tot_08']*100:.1f}% · 0.15% tot={shadow_meta['tot_15']*100:.1f}%
  (Δ={(shadow_meta['tot_15']-shadow_meta['tot_08'])*100:+.1f}pp). See `SHADOW.md`.

### Days60-skip honesty
- Hist n={days60.get('n_skips', 0)}; save-rate provisional until n≥20.
- Live template: `DAYS60_SKIP_LOG.md`.

## Overfit assessment (unchanged honesty from B9–B10)

MIXED: placebo calendars PASS for all four gates, but consecutive risk-adj promotes with
tied lastWF=9.2% + identical held-out late tot=12.7% for B5/B6/B7 + thin skip n
(days60 hist thin) still smell like filter stacking on early/mid OOS.
**Paper A = B6 (drop days60). Research A kept. NO new stacking in Block 11.**

## Path (Blocks 1–11)

1. B1–4: ST_m3.6 + Nifty + EMA200 core; kill-breadth near-miss.
2. B5: promote kill40+dd (dual-clear lastWF 9.2%).
3. B6: neighborhood freeze; nifty_mom near-miss (risk-adj later).
4. B7–8: consecutive **risk-adj** promotes (mom → days60) with **tied lastWF**.
5. B9: anti-overfit → complexity prefers Paper A = B6.
6. B10: operationalize Paper A; sensitivity (exec/cost/universe/slots/mult) — no new gates.
7. **B11: shadow P&L hygiene (0.08/0.15); days60 live log template; BH benchmarks;
   universe freeze; publishable draft expansion — still no stacking.**

## Pine vs Python

| Check | Result |
|-------|--------|
| Paper pine core_ok | {pine['paper']['core_ok']} |
| Research pine core_ok | {pine['research']['core_ok']} |

Single-symbol Pine = ST 3.6 + EMA200 proxy only. Basket gates are Python-only
(documented in pine headers). `process_orders_on_close=false` ≈ next-open intent.

## How to run

```bash
# Repro Paper A
python strategies/nifty_edge_paper.py

# Repro Research A (monitor)
python strategies/nifty_edge_best.py

# Full Block 11 hygiene pack
python research/nifty_edge_8h/run_block11.py
```

Artifacts: `research/nifty_edge_8h/results/block11_summary.json`,
`SHADOW.md`, `DAYS60_SKIP_LOG.md`, `UNIVERSE_FREEZE.md`, this draft.

## Caveats

- OOS edge vs BH is backtest — costs, liquidity, and gap risk differ live.
- Days60 / mom skip samples are **thin**; do not confirm gates on n<20.
- Tied lastWF across B5/B6/B7 + identical late held-out → complexity favors fewer gates.
- Pine is illustrative; paper book = Python basket engine.
- No live capital in this campaign. Research paper sleeves only.
- Mult≈3.5 was fragile in B10; keep 3.6 frozen.

## What not to do

- Do not stack more gates without dual-clear lastWF strictly > Paper A lastWF.
- Do not treat days60/mom skip save-rates as confirmatory while n<20.
- Do not silently make `nifty_edge_best.py` the paper sleeve without labeling.
- Do not mid-paper tweak mult, slots, universe, or costs beyond shadow logging.
"""
    )
    FINAL_OUTLINE.write_text(
        f"""# FINAL_REPORT outline (Block 11 — shadow hygiene)

**Drafted:** {now}
**Hours to deadline:** {hrs:.2f}
**Status:** Expanded publishable draft — full FINAL_REPORT lock when <1h.

## 1. Executive verdict
- **PAPER A:** B6 — tot={po['total_return']*100:.1f}% lastWF={paper.get('last_wf_tot',0)*100:.1f}%
- **RESEARCH A (monitor):** B7 — tot={ro['total_return']*100:.1f}% lastWF={research.get('last_wf_tot',0)*100:.1f}%
- Overfit MIXED; no new stacking.

## 2. Methods / metrics / caveats / how-to-run
- See FINAL_REPORT_DRAFT.md (Block 11 expansion).

## 3. Shadow + skip log
- SHADOW.md (0.08/0.15 weekly) · DAYS60_SKIP_LOG.md until n≥20.

## 4. Benchmarks
- Paper vs ^NSEI BH vs EW basket BH (same OOS).

## 5. Open / Block 12 or FINAL
- Continue live skip + shadow weekly until deadline.
- Full FINAL lock when <1h.
- Block 12 (if time): live log maintenance only; still no stacking.
"""
    )


def append_leaderboard(
    paper: dict,
    research: dict,
    hrs: float,
    d_p: bool,
    d_r: bool,
    bench: dict,
    shadow_meta: dict,
    days60: dict,
    pine: dict,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    po, ro = paper["OOS"], research["OOS"]
    block = f"""
## Block 11 — Shadow P&L hygiene; days60 live log; no new gates

**Updated:** {now}
**Hours to deadline:** {hrs:.2f}

### ★ PAPER vs RESEARCH (locked roles)

| Role | Name | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | Files |
|------|------|--:|---:|----:|----:|-------:|----:|-------:|-------|
| **PAPER A** | B6_ST_kill40_dd_nifty_mom_m04 | {po['n_trades']} | {po['profit_factor']:.2f} | {po['total_return']*100:.1f}% | {po['max_dd']*100:.1f}% | {po['sharpe']:.2f} | {paper.get('wf_pos')}/{paper.get('wf_n')} | {paper.get('last_wf_tot',0)*100:.1f}% | `nifty_edge_paper.py` / `.pine` |
| **RESEARCH A** | B7_ST_kill40_dd_mom_days60 | {ro['n_trades']} | {ro['profit_factor']:.2f} | {ro['total_return']*100:.1f}% | {ro['max_dd']*100:.1f}% | {ro['sharpe']:.2f} | {research.get('wf_pos')}/{research.get('wf_n')} | {research.get('last_wf_tot',0)*100:.1f}% | `nifty_edge_best.py` / `.pine` (monitor) |

**Repro:** paper drift_ok={d_p}; research drift_ok={d_r}

### Benchmarks (same OOS)

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A @ 0.08% | {po['total_return']*100:.1f}% | {po['max_dd']*100:.1f}% | {po['sharpe']:.2f} |
| ^NSEI BH | {bench['nsei']['total_return']*100:.1f}% | {bench['nsei']['max_dd']*100:.1f}% | {bench['nsei']['sharpe']:.2f} |
| EW basket BH | {bench['ew']['total_return']*100:.1f}% | {bench['ew']['max_dd']*100:.1f}% | {bench['ew']['sharpe']:.2f} |

### Shadow books
| RT | Tot | note |
|---:|----:|------|
| 0.08% | {shadow_meta['tot_08']*100:.1f}% | primary |
| 0.15% | {shadow_meta['tot_15']*100:.1f}% | shadow |

Days60 hist skips n={days60.get('n_skips', 0)} (thin). Pine both_core_ok={pine.get('both_core_ok')}.
Docs: `SHADOW.md`, `DAYS60_SKIP_LOG.md`, `UNIVERSE_FREEZE.md`.

### Honesty
- No new gates. No mid-paper tweaks. Paper A remains B6; Research A monitor-only.
"""
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 11 —"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"
    banner = (
        "\n> **Block 11:** Shadow P&L + days60 live log template. "
        "PAPER A = B6 (`nifty_edge_paper.py`); RESEARCH A = B7 monitor. No stacking.\n"
    )
    if "**Block 11:**" not in prev:
        lines = prev.splitlines(True)
        insert_at = 0
        for i, ln in enumerate(lines):
            if ln.startswith("**Updated:**") or ln.startswith("**Costs:**") or "Block 10 freeze" in ln:
                insert_at = i + 1
                break
        if insert_at == 0:
            insert_at = min(8, len(lines))
        lines.insert(insert_at, banner)
        prev = "".join(lines)
    else:
        prev = re.sub(r"> \*\*Block 11:\*\*.*\n", banner.lstrip("\n"), prev, count=1)
    LEADERBOARD.write_text(prev.rstrip() + "\n" + block)


def touch_paper_rules_header(hrs: float) -> None:
    """Light header refresh — no param changes."""
    if not PAPER_RULES.exists():
        return
    text = PAPER_RULES.read_text()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = re.sub(
        r"\*\*Hours to deadline:\*\* [0-9.]+",
        f"**Hours to deadline:** {hrs:.2f}",
        text,
        count=1,
    )
    if "Block 11" not in text[:400]:
        text = text.replace(
            "**Status:** Research paper sleeves — not live capital. No look-ahead.",
            f"**Status:** Research paper sleeves — not live capital. No look-ahead.\n"
            f"**Block 11:** Shadow hygiene + days60 log — see `SHADOW.md`, `DAYS60_SKIP_LOG.md` "
            f"({now}).",
            1,
        )
    # Ensure shadow pointer in daily checklist area
    if "SHADOW.md" not in text:
        text = text.replace(
            "5. Log fills @ 0.08% RT (shadow 0.15% weekly).",
            "5. Log fills @ 0.08% RT (shadow 0.15% weekly) — see `SHADOW.md`.",
            1,
        )
    PAPER_RULES.write_text(text)


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
        paper = portfolio_eval(
            "B6_ST_kill40_dd_nifty_mom_m04",
            data,
            sig_st_kill40_dd_nifty_mom,
            PAPER_PARAMS,
            oos_start,
        )
        paper["last_wf_tot"] = paper["wf"][-1]["total_return"] if paper["wf"] else 0.0
        write_full_final_if_needed(paper, hrs if hrs < 1.0 else -0.01)
        if FINAL_REPORT.exists():
            extra = (
                "\n## Paper vs Research (locked — Block 11)\n\n"
                "- **PAPER A:** B6 — `strategies/nifty_edge_paper.py`\n"
                "- **RESEARCH A (monitor):** B7 — `strategies/nifty_edge_best.py`\n"
                "- Shadow: `SHADOW.md` · Days60: `DAYS60_SKIP_LOG.md`\n"
                "- No new gate stacking after lock.\n"
            )
            FINAL_REPORT.write_text(FINAL_REPORT.read_text() + extra)
        log(f"Wrote {FINAL_REPORT}")
        print("FINALIZED_NEAR_DEADLINE")
        return

    log("=== Block 11 start ===")
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

    # ── 1) Repro ──────────────────────────────────────────────────────────────
    log("Repro RESEARCH A (B7) vs PAPER A (B6)…")
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

    # ── 2) Shadow P&L hygiene ─────────────────────────────────────────────────
    log("Shadow paper book @ 0.08% and 0.15% RT (equity + weekly)…")
    raw_08 = run_portfolio_ext(
        data,
        sig_st_kill40_dd_nifty_mom,
        PAPER_PARAMS,
        start_date=oos_start,
        rt_cost=RT,
        return_trades=True,
    )
    raw_15 = run_portfolio_ext(
        data,
        sig_st_kill40_dd_nifty_mom,
        PAPER_PARAMS,
        start_date=oos_start,
        rt_cost=RT_STRESS,
        return_trades=True,
    )
    eq08 = raw_08.get("equity")
    eq15 = raw_15.get("equity")
    weekly_08 = weekly_equity_table(eq08, "paper_0.08")
    weekly_15 = weekly_equity_table(eq15, "paper_0.15")
    weekly_delta = weekly_equity_delta(eq08, eq15)
    log(
        f"  SHADOW 0.08%: n={raw_08['n_trades']} PF={raw_08['profit_factor']:.2f} "
        f"tot={raw_08['total_return']*100:.1f}% weeks={weekly_08.get('n_weeks')}"
    )
    log(
        f"  SHADOW 0.15%: n={raw_15['n_trades']} PF={raw_15['profit_factor']:.2f} "
        f"tot={raw_15['total_return']*100:.1f}% weeks={weekly_15.get('n_weeks')} "
        f"Δtot={(raw_15['total_return']-raw_08['total_return'])*100:+.1f}pp"
    )

    # Paper trades for days60 analysis: Paper A trades that Research would skip
    # analyze_days60_skips expects B-sleeve (simpler) trades that fail days60 —
    # historically used Paper-without-days60 trades with dsh>60.
    # Use Paper A trades (B6) as the candidate set.
    paper_trades = raw_08.get("trades", [])
    days60 = analyze_days60_skips(data, paper_trades)
    log(
        f"  DAYS60 hist skips n={days60.get('n_skips', 0)} "
        f"save_rate={days60.get('save_rate')} thin={days60.get('thin_sample')}"
    )

    # ── 3) Benchmarks ─────────────────────────────────────────────────────────
    log("Benchmarks: ^NSEI BH + EW basket BH (same OOS)…")
    bh_nsei = buy_hold_stats(nifty.loc[nifty.index >= oos_start], "OOS")
    bh_ew = equal_weight_bh(data, oos_start)
    log(
        f"  ^NSEI BH: tot={bh_nsei['total_return']*100:.1f}% "
        f"MDD={bh_nsei['max_dd']*100:.1f}% Sharpe={bh_nsei['sharpe']:.2f}"
    )
    log(
        f"  EW basket: tot={bh_ew['total_return']*100:.1f}% "
        f"MDD={bh_ew['max_dd']*100:.1f}% Sharpe={bh_ew['sharpe']:.2f}"
    )
    bench = {"nsei": bh_nsei, "ew": bh_ew}

    # ── 4) Pine / universe freeze ─────────────────────────────────────────────
    log("Pine conceptual compile check + universe freeze…")
    pine = verify_pine_pair()
    log(f"  Pine paper core_ok={pine['paper']['core_ok']} research core_ok={pine['research']['core_ok']}")
    write_universe_freeze(hrs)
    log(f"  Wrote {UNIVERSE_FREEZE}")

    # ── 5) Docs ───────────────────────────────────────────────────────────────
    log("Writing SHADOW / DAYS60 log / CHECKLIST / FINAL draft / leaderboard…")
    shadow_meta = {
        "tot_08": raw_08["total_return"],
        "tot_15": raw_15["total_return"],
        "n_08": raw_08["n_trades"],
        "n_15": raw_15["n_trades"],
        "pf_08": raw_08["profit_factor"],
        "pf_15": raw_15["profit_factor"],
    }
    write_shadow_md(raw_08, raw_15, weekly_08, weekly_15, weekly_delta, bench, hrs)
    write_days60_skip_log(days60, hrs)
    write_checklist(paper, research, hrs, weekly_08, weekly_15, days60, pine, bench)
    expand_final_draft(paper, research, hrs, d_p, d_r, bench, pine, days60, shadow_meta)
    append_leaderboard(paper, research, hrs, d_p, d_r, bench, shadow_meta, days60, pine)
    touch_paper_rules_header(hrs)
    log(f"Wrote {SHADOW}")
    log(f"Wrote {DAYS60_LOG}")
    log(f"Wrote {CHECKLIST}")
    log(f"Wrote {FINAL_DRAFT}")
    log(f"Wrote {FINAL_OUTLINE}")
    log(f"Updated {LEADERBOARD}")
    log(f"Touched {PAPER_RULES}")

    if hrs < 1.0:
        write_full_final_if_needed(paper, hrs)
        log("FULL FINAL written (<1h)")
    else:
        log(f"FINAL draft only ({hrs:.1f}h left; full lock later)")

    # Persist weekly tables (trimmed) into summary
    summary = {
        "block": 11,
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
            "role": "monitor_only",
            "files": [
                "strategies/nifty_edge_best.py",
                "pinescript/nifty_edge_best.pine",
                "strategies/nifty_edge_r29.py",
            ],
        },
        "shadow": {
            "rt_0_08": {
                "n": raw_08["n_trades"],
                "pf": raw_08["profit_factor"],
                "tot": raw_08["total_return"],
                "mdd": raw_08["max_dd"],
                "sharpe": raw_08["sharpe"],
                "weekly": {k: v for k, v in weekly_08.items() if k != "weeks"},
                "weekly_tail": weekly_08.get("weeks", [])[-12:],
            },
            "rt_0_15": {
                "n": raw_15["n_trades"],
                "pf": raw_15["profit_factor"],
                "tot": raw_15["total_return"],
                "mdd": raw_15["max_dd"],
                "sharpe": raw_15["sharpe"],
                "weekly": {k: v for k, v in weekly_15.items() if k != "weeks"},
                "weekly_tail": weekly_15.get("weeks", [])[-12:],
            },
            "weekly_delta_08_minus_15": {
                k: v for k, v in weekly_delta.items() if k != "weeks"
            },
            "assumptions_doc": "research/nifty_edge_8h/SHADOW.md",
        },
        "days60_skip": {k: v for k, v in days60.items() if k != "skips"},
        "days60_skip_sample": days60.get("skips", [])[:20],
        "days60_log": str(DAYS60_LOG.relative_to(ROOT)),
        "benchmarks": {
            "nsei_bh": {
                "tot": bh_nsei["total_return"],
                "mdd": bh_nsei["max_dd"],
                "sharpe": bh_nsei["sharpe"],
            },
            "ew_basket_bh": {
                "tot": bh_ew["total_return"],
                "mdd": bh_ew["max_dd"],
                "sharpe": bh_ew["sharpe"],
                "n_names": bh_ew.get("n_names"),
            },
            "paper_excess_vs_nsei_pp": (
                paper["OOS"]["total_return"] - bh_nsei["total_return"]
            )
            * 100,
            "paper_excess_vs_ew_pp": (
                paper["OOS"]["total_return"] - bh_ew["total_return"]
            )
            * 100,
        },
        "pine": pine,
        "universe_freeze": {
            "n": len(FROZEN_UNIVERSE),
            "tickers": FROZEN_UNIVERSE,
            "doc": str(UNIVERSE_FREEZE.relative_to(ROOT)),
        },
        "recommendation": (
            "PAPER A = B6 (nifty_edge_paper.py); RESEARCH A = B7 monitor. "
            "Shadow 0.08/0.15 hygiene done. Days60 live log until n≥20. No new gates."
        ),
        "no_new_gates": True,
        "final_locked": False,
    }

    out_path = RESULTS / "block11_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    log(f"Wrote {out_path}")

    log("--- Block 11 summary ---")
    log(
        f"  PAPER A: {paper['name']} tot={paper['OOS']['total_return']*100:.1f}% "
        f"lastWF={paper['last_wf_tot']*100:.1f}%"
    )
    log(
        f"  RESEARCH A: {research['name']} tot={research['OOS']['total_return']*100:.1f}% "
        f"(monitor)"
    )
    log(
        f"  vs ^NSEI +{(paper['OOS']['total_return']-bh_nsei['total_return'])*100:.1f}pp "
        f"vs EW +{(paper['OOS']['total_return']-bh_ew['total_return'])*100:.1f}pp"
    )
    log(
        f"=== Block 11 complete === drift_p={d_p} drift_r={d_r} "
        f"pine_ok={pine['both_core_ok']} days60_n={days60.get('n_skips', 0)} "
        f"hrs_left={hrs:.2f}"
    )
    log(
        "Next Block 12: maintain live skip + shadow weekly; still no stacking; "
        "FINAL lock when <1h."
    )
    print(
        json.dumps(
            {
                "paper_a": paper["name"],
                "research_a": research["name"],
                "drift_paper": d_p,
                "drift_research": d_r,
                "shadow_tot_08": raw_08["total_return"],
                "shadow_tot_15": raw_15["total_return"],
                "days60_n": days60.get("n_skips", 0),
                "pine_ok": pine["both_core_ok"],
                "excess_vs_nsei_pp": (paper["OOS"]["total_return"] - bh_nsei["total_return"])
                * 100,
                "excess_vs_ew_pp": (paper["OOS"]["total_return"] - bh_ew["total_return"]) * 100,
                "hrs_left": hrs,
                "final_locked": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
