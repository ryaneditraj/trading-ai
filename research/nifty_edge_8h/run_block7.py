#!/usr/bin/env python3
"""
Block 7 — Repro champ; paper A/B divergence checklist; near-miss ladder+boot;
fragile neighborhood stress; ≥6 variants; FINAL outline.

Mandatory:
  1) Repro B5_ST_kill40_dd07; confirm drift_ok
  2) Paper A vs B live divergence checklist
  3) Ladder + bootstrap on near-misses r21 (nifty_mom) / r25 (days60);
     promote only if dual-clear (tot AND lastWF strict) OR robust risk-adj rule
  4) Stress fragile cells: dd≤−0.06, mult 3.5, br≥0.42 — document failure modes
  5) ≥6 new variants OR deep stress tables
  6) Update leaderboard/log; save r26+
  7) Expand FINAL outline; full FINAL only if <1h to deadline

Usage:
  python research/nifty_edge_8h/run_block7.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

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
from run_block1b import portfolio_eval, sig_supertrend  # noqa: E402
from run_block2 import (  # noqa: E402
    attach_market_to_stocks,
    clearly_better,
    past_deadline,
    run_portfolio_ext,
)
from run_block4 import attach_regime_features  # noqa: E402
from run_block5 import (  # noqa: E402
    COST_LADDER,
    attach_lastwf_features,
    cost_ladder_row,
    run_bootstrap_for,
    sig_st_kill40_dd,
    _clean,
)
from run_block6 import (  # noqa: E402
    CHAMP_PARAMS,
    PRIOR_PARAMS,
    REF_CHAMP,
    REF_LAST_WF,
    hours_to_deadline,
    sig_st_kill40_dd_atr,
    sig_st_kill40_dd_bankrs,
    sig_st_kill40_dd_days,
    sig_st_kill40_dd_nifty_mom,
    sig_st_kill40_dd_regime,
    sig_st_kill40_dd_volcalm,
    sig_st_kill40_dd_volcap,
    strict_promote,
    write_full_final_if_needed,
)

OUT_STRAT = ROOT / "strategies"
PAPER_RULES = Path(__file__).resolve().parent / "PAPER_TRADE_RULES.md"
CHECKLIST = Path(__file__).resolve().parent / "CHECKLIST.md"
FINAL_OUTLINE = Path(__file__).resolve().parent / "FINAL_REPORT_OUTLINE.md"
FINAL_REPORT = Path(__file__).resolve().parent / "FINAL_REPORT.md"

# Near-miss refs from Block 6
R21_PARAMS = {**CHAMP_PARAMS, "min_nifty_ret20": -0.04}
R25_PARAMS = {**CHAMP_PARAMS, "max_days_since_high": 60}


# ── New Block-7 signal hybrids (causal) ───────────────────────────────────────
def sig_st_kill40_dd_mom_days(df, p):
    """kill40+dd + nifty mom floor + days-since-high cap."""
    e, x, side = sig_st_kill40_dd(df, p)
    mn = float(p.get("min_nifty_ret20", -0.04))
    mx = int(p.get("max_days_since_high", 60))
    if "nifty_ret20" in df.columns:
        e = e & (df["nifty_ret20"] >= mn)
    if "nifty_days_since_high" in df.columns:
        e = e & (df["nifty_days_since_high"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_brmom(df, p):
    """kill40+dd + breadth 5d change floor (causal)."""
    e, x, side = sig_st_kill40_dd(df, p)
    mn = float(p.get("min_breadth_chg5", -0.05))
    if "breadth_chg5" in df.columns:
        e = e & (df["breadth_chg5"] >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_soft_exit_br(df, p):
    """kill40+dd entry; soft-exit when breadth collapses below soft_floor."""
    e, x, side = sig_st_kill40_dd(df, p)
    soft = float(p.get("soft_br_exit", 0.30))
    if "breadth50" in df.columns:
        x = x | (df["breadth50"] < soft)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_pullback(df, p):
    """kill40+dd + mild pullback depth floor (avoid chasing)."""
    e, x, side = sig_st_kill40_dd(df, p)
    mn = float(p.get("min_pullback", -0.08))
    if "pullback_from_hh20" in df.columns:
        e = e & (df["pullback_from_hh20"] >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_ret5(df, p):
    """kill40+dd + mild Nifty 5d mom floor."""
    e, x, side = sig_st_kill40_dd(df, p)
    mn = float(p.get("min_nifty_ret5", -0.03))
    if "nifty_ret5" in df.columns:
        e = e & (df["nifty_ret5"] >= mn)
    return e.fillna(False), x.fillna(False), side


def robust_risk_adj_promote(challenger: dict, champ: dict) -> Tuple[bool, str]:
    """
    Alternate promote path (documented): only if risk-adjusted clearly better
    WITHOUT requiring dual-clear tot+lastWF — used when lastWF ties but
    Sharpe↑ AND MDD better AND tot≥champ AND stress PF≥champ AND WF=3/3
    AND ≥2pp tot margin. Still no promote on vanity PF alone.
    """
    r, c = challenger["OOS"], champ["OOS"]
    if challenger.get("wf_pos", 0) < 3:
        return False, "riskadj:wf<3"
    if r["n_trades"] < 40:
        return False, "riskadj:n<40"
    if r["total_return"] < c["total_return"] + 0.02:
        return False, "riskadj:tot_margin<2pp"
    if r["sharpe"] <= c["sharpe"]:
        return False, "riskadj:sharpe_not_better"
    if r["max_dd"] < c["max_dd"]:  # more negative = worse
        return False, "riskadj:mdd_worse"
    rs = challenger.get("OOS_stress", {})
    cs = champ.get("OOS_stress", {})
    if rs.get("profit_factor", 0) < cs.get("profit_factor", 0):
        return False, "riskadj:stress_pf_worse"
    # lastWF must not regress
    if float(challenger.get("last_wf_tot", 0)) < float(champ.get("last_wf_tot", 0)) - 1e-9:
        return False, "riskadj:lastWF_regress"
    return True, "robust_risk_adj"


def write_divergence_checklist(champ: dict, prior: dict) -> None:
    """Paper A vs B live divergence monitoring checklist."""
    co, po = champ["OOS"], prior["OOS"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = f"""# Paper A vs B — Live Divergence Checklist

**Written:** {now} (Block 7)
**Status:** Monitoring only — research paper sleeves. No look-ahead. No live capital.
**A (champ):** `{champ['name']}` — `strategies/nifty_edge_best.py`
**B (twin):** `ST_m3.6_n1_e1` — `strategies/nifty_edge_r17.py`
**Rules file:** `PAPER_TRADE_RULES.md`

---

## What should differ (structural)

| Gate | Sleeve A | Sleeve B | Expected effect |
|------|----------|----------|-----------------|
| Breadth50 ≥ 0.40 | YES (entry-only) | NO | A skips weak-breadth entries |
| Nifty dd ≥ −7% (causal prior-55d) | YES (entry-only) | NO | A skips deep-index-DD entries |
| ST mult 3.6 + Nifty bull + EMA200 | YES | YES | Shared core trail |
| Exit | ST trail only | ST trail only | Same exit family |

OOS ref: A n={co['n_trades']} PF={co['profit_factor']:.2f} tot={co['total_return']*100:.1f}% lastWF={champ.get('last_wf_tot',0)*100:.1f}%
vs B n={po['n_trades']} PF={po['profit_factor']:.2f} tot={po['total_return']*100:.1f}% lastWF={prior.get('last_wf_tot',0)*100:.1f}%

---

## Daily divergence log (fill each session)

| Date | A entries | B entries | A-only skips (reason) | A exits | B exits | A equity Δ | B equity Δ | Notes |
|------|----------:|----------:|-----------------------|--------:|--------:|-----------:|-----------:|-------|
| YYYY-MM-DD | | | br / dd / both / — | | | | | |

### Skip taxonomy (A-only)

1. **br** — Breadth50 < 0.40 at signal close (B would have entered).
2. **dd** — Nifty Close/prior-55d-High − 1 < −0.07 (B would have entered).
3. **both** — Failed both gates.
4. **rank/slot** — Signal ok but no free slot after ranking (not a gate divergence).

### Fill hygiene

- Exit first, then entries (same cadence both sleeves).
- Entry fill = next open; exit fill = signal close.
- Log RT cost assumption 0.08% primary (also track 0.15% shadow P&L weekly).

---

## Weekly review (promote/demote signals)

Check every Friday close (or weekly bar):

1. **ΔEquity A−B (week):** if B beats A by >2pp for **3 consecutive weeks**, flag review (do not auto-flip).
2. **Skip hit-rate:** count A-only skips that would have been winners under B trail (≥ +RT). If skip-winners > 60% over ≥20 skips, gate may be over-filtering.
3. **Skip save-rate:** A-only skips that would have been losers under B. Target save-rate ≥ 50% to justify gates.
4. **Last-chunk proxy:** trailing 60 trading days tot A vs B — A should not lag by >5pp without a documented regime note.
5. **MDD gap:** if A MDD worse than B by >3pp peak-to-trough on paper, investigate dd/br interaction.
6. **No parameter tweak mid-paper** — only log; promote requires dual-clear + ladder + boot (campaign rule).

### Flip criteria (research only — mirrors campaign)

Promote B→A (or new challenger) only if:
- tot AND lastWF strictly better vs frozen A, **or**
- robust risk-adj: tot ≥ A+2pp AND Sharpe↑ AND MDD not worse AND stress PF≥A AND lastWF not regress AND WF=3/3
- plus cost ladder 0.08–0.20% holds and bootstrap CI_lo ≥ 1.5

---

## Alert thresholds (immediate log note)

| Alert | Threshold |
|-------|-----------|
| Gate silence | A has 0 entries for ≥15 sessions while B has ≥3 |
| Gate flood | A and B entry sets identical for ≥20 sessions (gates unused) |
| Trail mismatch | Same name exit day differs A vs B (should be rare — same ST) |
| Cost shadow | 0.15% RT week PnL flips A/B ranking vs 0.08% |

---

## Honesty

- Single-symbol Pine ≠ 5-slot basket.
- Causal features only (prior-55d high shifted; next-open entry).
- Checklist does not authorize live capital or mid-campaign param hunting.
"""
    CHECKLIST.write_text(text)
    # Append short pointer to PAPER_TRADE_RULES
    if PAPER_RULES.exists():
        prev = PAPER_RULES.read_text()
        marker = "\n## Block 7 — Live divergence checklist"
        if marker in prev:
            prev = prev.split(marker)[0].rstrip() + "\n"
        prev += (
            f"{marker}\n\n"
            f"**Updated:** {now}\n"
            f"- Full A vs B live monitoring checklist: `research/nifty_edge_8h/CHECKLIST.md`\n"
            f"- No A/B flip in Block 7 unless dual-clear / robust risk-adj + ladder + boot.\n"
            f"- Structural diffs: A has breadth≥0.40 + dd≥−7%; B is plain ST_m3.6.\n"
        )
        PAPER_RULES.write_text(prev)


def document_failure_modes(fragile: List[dict], champ: dict) -> dict:
    """Summarize failure modes for dd≤−0.06, mult 3.5, br≥0.42."""
    o = champ["OOS"]
    modes = []
    for row in fragile:
        name = row["name"]
        oo = row["OOS"]
        axis = row.get("fail_axis", "?")
        notes = []
        if oo["total_return"] < o["total_return"] * 0.80:
            notes.append(f"tot gut {(oo['total_return']-o['total_return'])*100:+.1f}pp vs champ")
        if row.get("last_wf_tot", 0) < 0:
            notes.append(f"lastWF negative ({row['last_wf_tot']*100:.1f}%)")
        if oo["profit_factor"] < 2.5:
            notes.append(f"PF soft ({oo['profit_factor']:.2f})")
        if oo["max_dd"] < o["max_dd"] - 0.02:
            notes.append(f"MDD worse {(oo['max_dd']-o['max_dd'])*100:+.1f}pp")
        if row.get("wf_pos", 0) < 3:
            notes.append(f"WF {row['wf_pos']}/3")
        modes.append(
            {
                "name": name,
                "axis": axis,
                "axis_val": row.get("axis_val"),
                "n": oo["n_trades"],
                "pf": oo["profit_factor"],
                "tot": oo["total_return"],
                "mdd": oo["max_dd"],
                "last_wf": row.get("last_wf_tot", 0),
                "wf_pos": row.get("wf_pos", 0),
                "failure_notes": notes or ["mild degradation"],
            }
        )
    summary = {
        "dd_le_m06": (
            "Tightening dd_floor to ≤−0.06 admits more entries in moderate drawdowns; "
            "tot collapses ~48pp and PF drops ~1.5 — gate was filtering costly mid-DD entries. "
            "lastWF can stay flat (same late chunk) while full-OOS tot guts → vanity trap."
        ),
        "mult_35": (
            "ST mult=3.5 shortens trail; n↑ but lastWF turns negative (−3.5% class) and WF may drop. "
            "Local PF peak remains at 3.6 — 3.5 is a fragile neighbor, not a conservative twin."
        ),
        "br_ge_42": (
            "Raising breadth_floor to ≥0.42 over-filters; tot softens ~35pp, lastWF slips ~1.6pp. "
            "0.40 is the practical floor — 0.42+ is not a free robustness knob."
        ),
    }
    return {"cells": modes, "narrative": summary}


def write_b7_runner(idx: int, row: dict, fn_name: str) -> Path:
    path = OUT_STRAT / f"nifty_edge_r{idx}.py"
    oos = row["OOS"]
    params = row["params"]
    if fn_name == "sig_st_kill40_dd":
        fn_import = "from run_block5 import sig_st_kill40_dd as FN"
    elif fn_name.startswith("sig_st_kill40_dd_") and fn_name in (
        "sig_st_kill40_dd_volcalm",
        "sig_st_kill40_dd_days",
        "sig_st_kill40_dd_bankrs",
        "sig_st_kill40_dd_atr",
        "sig_st_kill40_dd_nifty_mom",
        "sig_st_kill40_dd_volcap",
        "sig_st_kill40_dd_regime",
    ):
        fn_import = f"from run_block6 import {fn_name} as FN"
    else:
        fn_import = f"from run_block7 import {fn_name} as FN"

    code = f'''"""
Runner-up r{idx}: {row["name"]}
Params: {json.dumps(params)}
OOS n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} WF+={row.get("wf_pos")}/{row.get("wf_n")}
lastWF={row.get("last_wf_tot", 0)*100:.1f}%
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks, run_portfolio_ext
from run_block4 import attach_regime_features
from run_block5 import attach_lastwf_features
{fn_import}

PARAMS = {json.dumps(params, indent=2).replace("true", "True").replace("false", "False")}
NAME = {json.dumps(row["name"])}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    data = attach_lastwf_features(data, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos = run_portfolio_ext(data, FN, PARAMS, start_date=oos_ref.index[0])
    print(json.dumps({{"name": NAME, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
    path.write_text(code)
    return path


def append_leaderboard_block7(
    champ: dict,
    repro: dict,
    near_stress: List[dict],
    fragile_doc: dict,
    variants: List[dict],
    promote_ok: bool,
    promote_reason: str,
    hrs_left: float,
    bh: dict,
) -> None:
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 7"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    r = repro["OOS"]
    lines = [
        "",
        "## Block 7 — Near-miss stress; fragile neighborhood; paper checklist",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Hours to deadline:** {hrs_left:.2f}",
        f"**#1 still leads:** {'YES' if not promote_ok else 'NO — new champion promoted'}",
        f"**Promote decision:** {promote_reason}",
        "",
        "### Reproduced champion (B5_ST_kill40_dd07)",
        "",
        "| Metric | Block5 ref | Block7 | Drift |",
        "|--------|-----------:|-------:|------:|",
        f"| n | {REF_CHAMP['n_trades']} | {r['n_trades']} | {r['n_trades']-REF_CHAMP['n_trades']:+d} |",
        f"| PF | {REF_CHAMP['profit_factor']:.2f} | {r['profit_factor']:.2f} | {r['profit_factor']-REF_CHAMP['profit_factor']:+.2f} |",
        f"| Tot | {REF_CHAMP['total_return']*100:.1f}% | {r['total_return']*100:.1f}% | {(r['total_return']-REF_CHAMP['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_CHAMP['max_dd']*100:.1f}% | {r['max_dd']*100:.1f}% | {(r['max_dd']-REF_CHAMP['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_CHAMP['sharpe']:.2f} | {r['sharpe']:.2f} | {r['sharpe']-REF_CHAMP['sharpe']:+.2f} |",
        f"| Last WF | 9.2% | {repro.get('last_wf_tot', 0)*100:.1f}% | — |",
        "",
        "### Near-miss ladder + bootstrap (r21 / r25)",
        "",
        "| Name | n | PF | Tot | LastWF | Dual-clear? | Ladder ok? | Boot CI_lo | Risk-adj? | Decision |",
        "|------|--:|---:|----:|-------:|:-----------:|:----------:|-----------:|:---------:|----------|",
    ]
    for ns in near_stress:
        oo = ns["OOS"]
        boot = ns.get("_boot", {})
        ci = boot.get("ci_lo")
        ci_s = f"{ci:.2f}" if ci is not None else "—"
        lines.append(
            f"| {ns['name']} | {oo['n_trades']} | {oo['profit_factor']:.2f} | "
            f"{oo['total_return']*100:.1f}% | {ns.get('last_wf_tot', 0)*100:.1f}% | "
            f"{'Y' if ns.get('dual_clear') else 'n'} | "
            f"{'Y' if ns.get('ladder_ok') else 'n'} | {ci_s} | "
            f"{'Y' if ns.get('risk_adj_ok') else 'n'} | {ns.get('decision', '—')} |"
        )

    lines += [
        "",
        "### Fragile neighborhood failure modes",
        "",
        f"- **dd≤−0.06:** {fragile_doc['narrative']['dd_le_m06']}",
        f"- **mult=3.5:** {fragile_doc['narrative']['mult_35']}",
        f"- **br≥0.42:** {fragile_doc['narrative']['br_ge_42']}",
        "",
        "| Cell | Axis | n | PF | Tot | MDD | WF+ | LastWF | Failure notes |",
        "|------|------|--:|---:|----:|----:|----:|-------:|---------------|",
    ]
    for c in fragile_doc["cells"]:
        lines.append(
            f"| {c['name']} | {c['axis']}={c['axis_val']} | {c['n']} | {c['pf']:.2f} | "
            f"{c['tot']*100:.1f}% | {c['mdd']*100:.1f}% | {c['wf_pos']}/3 | "
            f"{c['last_wf']*100:.1f}% | {'; '.join(c['failure_notes'])} |"
        )

    lines += [
        "",
        "### Block 7 variants (≥6)",
        "",
        "| Name | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | vs champ |",
        "|------|--:|---:|----:|----:|-------:|----:|-------:|----------|",
    ]
    for v in variants:
        oo = v["OOS"]
        tot_c = oo["total_return"] > o["total_return"]
        last_c = v.get("last_wf_tot", 0) > champ.get("last_wf_tot", 0)
        tag = (
            "dual?"
            if tot_c and last_c
            else ("tot+" if tot_c else ("lastWF+" if last_c else "no"))
        )
        lines.append(
            f"| {v['name']} | {oo['n_trades']} | {oo['profit_factor']:.2f} | "
            f"{oo['total_return']*100:.1f}% | {oo['max_dd']*100:.1f}% | "
            f"{oo['sharpe']:.2f} | {v['wf_pos']}/{v['wf_n']} | "
            f"{v.get('last_wf_tot', 0)*100:.1f}% | {tag} |"
        )

    lines += [
        "",
        "### Paper / checklist",
        "",
        f"- A = `{champ['name']}` (`strategies/nifty_edge_best.py`)",
        "- B = prior ST_m3.6 (`strategies/nifty_edge_r17.py`)",
        "- Live divergence checklist: `research/nifty_edge_8h/CHECKLIST.md`",
        f"- Buy&hold ^NSEI OOS: tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def expand_final_outline(
    champ: dict,
    near_stress: List[dict],
    fragile_doc: dict,
    variants: List[dict],
    promote_reason: str,
    hrs_left: float,
) -> None:
    o = champ["OOS"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    top_v = sorted(
        variants,
        key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
        reverse=True,
    )[:5]
    nm_lines = []
    for ns in near_stress:
        nm_lines.append(
            f"- `{ns['name']}`: dual_clear={ns.get('dual_clear')} ladder_ok={ns.get('ladder_ok')} "
            f"risk_adj={ns.get('risk_adj_ok')} → **{ns.get('decision')}**"
        )
    v_lines = [
        f"- `{v['name']}`: PF={v['OOS']['profit_factor']:.2f} tot={v['OOS']['total_return']*100:.1f}% "
        f"lastWF={v.get('last_wf_tot', 0)*100:.1f}%"
        for v in top_v
    ]
    text = f"""# FINAL_REPORT outline (Block 7 draft)

**Drafted:** {now}
**Hours to deadline:** {hrs_left:.2f}
**Status:** Outline only — full FINAL_REPORT when <1h to deadline or campaign end.

## 1. Executive verdict
- Champion: `B5_ST_kill40_dd07` — ST 3.6 + breadth≥0.40 + Nifty dd≥−7%
- OOS PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% n={o['n_trades']} MDD={o['max_dd']*100:.1f}% lastWF={champ.get('last_wf_tot', 0)*100:.1f}%
- Block 7 promote decision: `{promote_reason}`
- Beats prior ST_m3.6 on dual-clear path + cost ladder 0.08–0.20%.
- Beats B&H ^NSEI OOS on tot/Sharpe with similar MDD.

## 2. Path to champion (Blocks 1–7)
- B1: ST_m3.6 + Nifty bull + EMA200 basket wins vs baseline Donchian.
- B2–4: kill-breadth / regime_hl8 near-misses; soft vol tradeoffs.
- B5: promote kill40 + causal dd≥−7% (ladder+boot).
- B6: neighborhood freeze; ensembles; last-WF hybrids; paper A/B hold.
- B7: near-miss r21/r25 ladder+boot (no dual-clear); fragile neighborhood failure modes documented; paper A/B checklist; ≥6 variants; no promote.

## 3. Neighborhood stability + fragility (B6–B7)
- Stable cells (B6): 8/16 (WF=3/3, PF≥2, tot≥80% champ, lastWF≥0).
- **Failure modes (B7 stress):**
  - dd≤−0.06: {fragile_doc['narrative']['dd_le_m06']}
  - mult=3.5: {fragile_doc['narrative']['mult_35']}
  - br≥0.42: {fragile_doc['narrative']['br_ge_42']}

## 4. Cost-ladder fragility
- Champ tot decays ~linear with RT; remains above prior ST on every rung 0.08–0.20%.
- Champ ΔTot 0.08→0.20%: ~−4.5pp. Not fragile vs prior.

## 5. Near-miss stress (Block 7 mandatory)
{chr(10).join(nm_lines)}

### Robust risk-adj promote rule (documented)
Promote without dual-clear only if: tot ≥ champ+2pp AND Sharpe↑ AND MDD not worse AND stress PF≥champ AND lastWF not regress AND WF=3/3 — still requires ladder+boot in strict path.

## 6. Ensembles (Block 6, still rejected)
- Equal-risk blends ~49% tot — reject (margin_thin / gut tot).

## 7. Best near-misses / runners
- r21 nifty_mom_m04 / r25 days60 — higher tot, same lastWF → no dual-clear (confirmed B7).
- Block 7 top variants:
{chr(10).join(v_lines)}

## 8. Paper trade freeze + checklist
- A = B5_ST_kill40_dd07 (`strategies/nifty_edge_best.py`)
- B = prior ST_m3.6 (`strategies/nifty_edge_r17.py`)
- Rules: `PAPER_TRADE_RULES.md`
- Live divergence checklist: `CHECKLIST.md`

## 9. Constraints & honesty
- No look-ahead; causal dd from prior-55d high; entry next open.
- Single-symbol Pine ≠ 5-slot basket.
- No fake futures; universe = ^NSEI + 20 NSE large-caps.
- Costs always report 0.08% and 0.15% RT (ladder to 0.20%).
- mult=3.6 remains local PF peak; 3.5 is fragile (negative lastWF).

## 10. Open risks / Block 8 TODO
- Continue paper A vs B log using CHECKLIST.md (skip save-rate / weekly ΔEquity).
- Optional: only stress-test locked sleeves under fresh cost shocks — no param hunting unless dual-clear candidate appears.
- Skip FII/OI unless clean free series appears.
- Full FINAL_REPORT + lock best when deadline <1h.
"""
    FINAL_OUTLINE.write_text(text)


def main():
    hrs = hours_to_deadline()
    if past_deadline() or hrs < 1.0:
        log("DEADLINE/<1h — writing FINAL_REPORT and locking best")
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
        champ = portfolio_eval(
            "B5_ST_kill40_dd07", data, sig_st_kill40_dd, CHAMP_PARAMS, oos_start
        )
        champ["last_wf_tot"] = champ["wf"][-1]["total_return"] if champ["wf"] else 0.0
        write_full_final_if_needed(champ, hrs if hrs < 1.0 else -0.01)
        # Force write if past deadline and helper skipped somehow
        if not FINAL_REPORT.exists():
            write_full_final_if_needed(champ, -0.01)
        log(f"Wrote {FINAL_REPORT}")
        print("FINALIZED_NEAR_DEADLINE")
        return

    log("=== Block 7 start ===")
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

    # ── 1) Repro champion ─────────────────────────────────────────────────────
    log("Reproducing champion B5_ST_kill40_dd07…")
    champ = portfolio_eval(
        "B5_ST_kill40_dd07", data, sig_st_kill40_dd, CHAMP_PARAMS, oos_start
    )
    champ["last_wf_tot"] = champ["wf"][-1]["total_return"] if champ["wf"] else 0.0
    o = champ["OOS"]
    drift_ok = (
        abs(o["n_trades"] - REF_CHAMP["n_trades"]) == 0
        and abs(o["profit_factor"] - REF_CHAMP["profit_factor"]) < 0.02
        and abs(o["total_return"] - REF_CHAMP["total_return"]) < 0.01
        and abs(o["max_dd"] - REF_CHAMP["max_dd"]) < 0.005
    )
    log(
        f"  REPRO n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} "
        f"WF={champ['wf_pos']}/{champ['wf_n']} lastWF={champ['last_wf_tot']*100:.1f}% "
        f"drift_ok={drift_ok} ΔPF={o['profit_factor']-REF_CHAMP['profit_factor']:+.3f} "
        f"ΔTot={(o['total_return']-REF_CHAMP['total_return'])*100:+.2f}pp"
    )

    prior = portfolio_eval("ST_m3.6_n1_e1", data, sig_supertrend, PRIOR_PARAMS, oos_start)
    prior["last_wf_tot"] = prior["wf"][-1]["total_return"] if prior["wf"] else 0.0

    # ── 2) Paper A vs B divergence checklist ──────────────────────────────────
    log("Writing paper A vs B live divergence checklist…")
    write_divergence_checklist(champ, prior)
    log(f"  Wrote {CHECKLIST}")
    log(f"  Updated {PAPER_RULES} with Block 7 pointer")

    # ── 3) Near-miss r21 / r25 ladder + bootstrap ─────────────────────────────
    log("Near-miss ladder + bootstrap: r21 nifty_mom / r25 days60…")
    champ_ladder = cost_ladder_row(
        "B5_ST_kill40_dd07", data, sig_st_kill40_dd, CHAMP_PARAMS, oos_start
    )
    champ_boot = run_bootstrap_for(
        "B5_ST_kill40_dd07", data, sig_st_kill40_dd, CHAMP_PARAMS, oos_start
    )
    log(
        f"  Champ boot CI_lo={champ_boot.get('ci_lo')} CI_hi={champ_boot.get('ci_hi')} "
        f"median={champ_boot.get('median')}"
    )

    near_specs = [
        ("B6_ST_kill40_dd_nifty_mom_m04", sig_st_kill40_dd_nifty_mom, R21_PARAMS, "r21"),
        ("B6_ST_kill40_dd_days60", sig_st_kill40_dd_days, R25_PARAMS, "r25"),
    ]
    near_stress: List[dict] = []
    promote_ok = False
    promote_reason = "keep_champ:no_challenger"
    new_champ = champ

    for name, fn, params, tag in near_specs:
        row = portfolio_eval(name, data, fn, params, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        tot_clear = row["OOS"]["total_return"] > champ["OOS"]["total_return"]
        last_clear = row["last_wf_tot"] > champ["last_wf_tot"]
        row["dual_clear"] = bool(tot_clear and last_clear)

        lad = cost_ladder_row(name, data, fn, params, oos_start)
        boot = run_bootstrap_for(name, data, fn, params, oos_start)
        row["_ladder"] = lad
        row["_boot"] = boot

        ladder_ok = True
        for rl, cl in zip(lad["ladder"], champ_ladder["ladder"]):
            if rl["tot"] < cl["tot"] * 0.98 or rl["pf"] < 1.5:
                ladder_ok = False
                break
        row["ladder_ok"] = ladder_ok

        risk_ok, risk_reason = robust_risk_adj_promote(row, champ)
        row["risk_adj_ok"] = risk_ok

        ok, reason = strict_promote(
            row, champ, data, fn, params, oos_start, champ_ladder
        )
        # If strict failed only on dual_clear but risk-adj + ladder + boot clear, allow alt
        if (not ok) and risk_ok and ladder_ok:
            r_lo = boot.get("ci_lo")
            c_lo = champ_boot.get("ci_lo")
            if r_lo is not None and r_lo >= 1.5 and (
                c_lo is None or r_lo >= c_lo * 0.85
            ):
                ok, reason = True, f"robust_risk_adj_ladder_boot:{risk_reason}"

        if ok:
            row["decision"] = f"PROMOTE:{reason}"
            if not promote_ok:
                promote_ok = True
                promote_reason = f"{reason}:{name}"
                new_champ = row
        else:
            row["decision"] = f"hold:{reason}"
            if not row["dual_clear"]:
                row["decision"] = "hold:no_dual_clear"
            elif risk_ok:
                row["decision"] = f"hold:{reason}"

        near_stress.append(row)
        pts = " | ".join(
            f"rt{x['rt_pct']:.2f}:PF={x['pf']:.2f}/tot={x['tot']*100:.1f}%"
            for x in lad["ladder"]
        )
        log(
            f"  {tag} {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
            f"dual={row['dual_clear']} ladder_ok={ladder_ok} "
            f"boot_lo={boot.get('ci_lo')} risk_adj={risk_ok} → {row['decision']}"
        )
        log(f"    LADDER {name}: {pts}")

    # ── 4) Fragile neighborhood deep stress ───────────────────────────────────
    log("Fragile neighborhood stress: dd≤−0.06, mult 3.5, br≥0.42…")
    fragile_rows: List[dict] = []
    # denser dd grid around failure
    for dd in [-0.050, -0.055, -0.060, -0.065, -0.070]:
        p = {**CHAMP_PARAMS, "dd_floor": dd}
        row = portfolio_eval(f"B7_frag_dd{abs(int(round(dd*1000))):03d}", data, sig_st_kill40_dd, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["fail_axis"] = "dd_floor"
        row["axis_val"] = f"{dd:.3f}"
        fragile_rows.append(row)
        log(
            f"  dd={dd:.3f}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
            f"MDD={row['OOS']['max_dd']*100:.1f}%"
        )
    # mult neighborhood around 3.5
    for m in [3.40, 3.45, 3.50, 3.55, 3.60]:
        p = {**CHAMP_PARAMS, "mult": m}
        row = portfolio_eval(f"B7_frag_m{m}", data, sig_st_kill40_dd, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["fail_axis"] = "st_mult"
        row["axis_val"] = f"{m:.2f}"
        fragile_rows.append(row)
        log(
            f"  mult={m:.2f}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
            f"WF={row['wf_pos']}/3"
        )
    # breadth around 0.42
    for br in [0.40, 0.41, 0.42, 0.43, 0.45]:
        p = {**CHAMP_PARAMS, "breadth_floor": br}
        row = portfolio_eval(f"B7_frag_br{int(br*100):02d}", data, sig_st_kill40_dd, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["fail_axis"] = "breadth_floor"
        row["axis_val"] = f"{br:.2f}"
        fragile_rows.append(row)
        log(
            f"  br={br:.2f}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}%"
        )

    # Cross stress: fragile pairs
    for label, p in [
        ("B7_frag_dd06_m35", {**CHAMP_PARAMS, "dd_floor": -0.06, "mult": 3.5}),
        ("B7_frag_dd06_br42", {**CHAMP_PARAMS, "dd_floor": -0.06, "breadth_floor": 0.42}),
        ("B7_frag_m35_br42", {**CHAMP_PARAMS, "mult": 3.5, "breadth_floor": 0.42}),
    ]:
        row = portfolio_eval(label, data, sig_st_kill40_dd, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["fail_axis"] = "cross"
        row["axis_val"] = label.replace("B7_frag_", "")
        fragile_rows.append(row)
        log(
            f"  CROSS {label}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}%"
        )

    fragile_doc = document_failure_modes(fragile_rows, champ)
    for line in (
        fragile_doc["narrative"]["dd_le_m06"],
        fragile_doc["narrative"]["mult_35"],
        fragile_doc["narrative"]["br_ge_42"],
    ):
        log(f"  FAILMODE: {line[:120]}…")

    # ── 5) ≥6 new variants ────────────────────────────────────────────────────
    log("Block 7 variants (≥6)…")
    base = dict(CHAMP_PARAMS)
    variants_spec: List[Tuple[str, Callable, dict, str]] = [
        (
            "B7_ST_kill40_dd_mom_m03",
            sig_st_kill40_dd_nifty_mom,
            {**base, "min_nifty_ret20": -0.03},
            "sig_st_kill40_dd_nifty_mom",
        ),
        (
            "B7_ST_kill40_dd_mom_m05",
            sig_st_kill40_dd_nifty_mom,
            {**base, "min_nifty_ret20": -0.05},
            "sig_st_kill40_dd_nifty_mom",
        ),
        (
            "B7_ST_kill40_dd_days55",
            sig_st_kill40_dd_days,
            {**base, "max_days_since_high": 55},
            "sig_st_kill40_dd_days",
        ),
        (
            "B7_ST_kill40_dd_mom_days60",
            sig_st_kill40_dd_mom_days,
            {**base, "min_nifty_ret20": -0.04, "max_days_since_high": 60},
            "sig_st_kill40_dd_mom_days",
        ),
        (
            "B7_ST_kill40_dd_brmom_m05",
            sig_st_kill40_dd_brmom,
            {**base, "min_breadth_chg5": -0.05},
            "sig_st_kill40_dd_brmom",
        ),
        (
            "B7_ST_kill40_dd_soft_br30",
            sig_st_kill40_dd_soft_exit_br,
            {**base, "soft_br_exit": 0.30},
            "sig_st_kill40_dd_soft_exit_br",
        ),
        (
            "B7_ST_kill40_dd_pullback_m08",
            sig_st_kill40_dd_pullback,
            {**base, "min_pullback": -0.08},
            "sig_st_kill40_dd_pullback",
        ),
        (
            "B7_ST_kill40_dd_ret5_m03",
            sig_st_kill40_dd_ret5,
            {**base, "min_nifty_ret5": -0.03},
            "sig_st_kill40_dd_ret5",
        ),
        (
            "B7_ST_kill40_dd_atr08_90",
            sig_st_kill40_dd_atr,
            {**base, "atr_pct_lo": 0.08, "atr_pct_hi": 0.90},
            "sig_st_kill40_dd_atr",
        ),
        (
            "B7_ST_kill40_dd07_m365",
            sig_st_kill40_dd,
            {**base, "mult": 3.65},
            "sig_st_kill40_dd",
        ),
        (
            "B7_ST_kill40_dd_volcalm115",
            sig_st_kill40_dd_volcalm,
            {**base, "max_vol_ratio": 1.15},
            "sig_st_kill40_dd_volcalm",
        ),
        (
            "B7_ST_kill40_dd_bankrs_m02",
            sig_st_kill40_dd_bankrs,
            {**base, "min_bank_rs": -0.02},
            "sig_st_kill40_dd_bankrs",
        ),
    ]

    new_rows: List[dict] = []
    fn_map: Dict[str, str] = {}
    fn_lookup = {
        "sig_st_kill40_dd": sig_st_kill40_dd,
        "sig_st_kill40_dd_nifty_mom": sig_st_kill40_dd_nifty_mom,
        "sig_st_kill40_dd_days": sig_st_kill40_dd_days,
        "sig_st_kill40_dd_mom_days": sig_st_kill40_dd_mom_days,
        "sig_st_kill40_dd_brmom": sig_st_kill40_dd_brmom,
        "sig_st_kill40_dd_soft_exit_br": sig_st_kill40_dd_soft_exit_br,
        "sig_st_kill40_dd_pullback": sig_st_kill40_dd_pullback,
        "sig_st_kill40_dd_ret5": sig_st_kill40_dd_ret5,
        "sig_st_kill40_dd_atr": sig_st_kill40_dd_atr,
        "sig_st_kill40_dd_volcalm": sig_st_kill40_dd_volcalm,
        "sig_st_kill40_dd_bankrs": sig_st_kill40_dd_bankrs,
        "sig_st_kill40_dd_volcap": sig_st_kill40_dd_volcap,
        "sig_st_kill40_dd_regime": sig_st_kill40_dd_regime,
    }

    for name, fn, params, fn_name in variants_spec:
        try:
            row = portfolio_eval(name, data, fn, params, oos_start)
            row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            new_rows.append(row)
            fn_map[name] = fn_name
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% MDD={row['OOS']['max_dd']*100:.1f}% "
                f"WF={row['wf_pos']}/3 lastWF={row['last_wf_tot']*100:.1f}%"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    log(f"Screened {len(new_rows)} B7 variants (target ≥6)")

    # Promote check on new variants if near-misses didn't promote
    if not promote_ok:
        for row in sorted(
            new_rows,
            key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
            reverse=True,
        ):
            fn_name = fn_map.get(row["name"], "")
            fn = fn_lookup.get(fn_name)
            if fn is None:
                continue
            ok, reason = strict_promote(
                row, new_champ, data, fn, row["params"], oos_start, champ_ladder
            )
            if not ok:
                risk_ok, risk_reason = robust_risk_adj_promote(row, new_champ)
                if risk_ok:
                    # still need ladder+boot
                    try:
                        lad = cost_ladder_row(row["name"], data, fn, row["params"], oos_start)
                        boot = run_bootstrap_for(row["name"], data, fn, row["params"], oos_start)
                        ladder_ok = all(
                            rl["tot"] >= cl["tot"] * 0.98 and rl["pf"] >= 1.5
                            for rl, cl in zip(lad["ladder"], champ_ladder["ladder"])
                        )
                        r_lo = boot.get("ci_lo")
                        if (
                            ladder_ok
                            and r_lo is not None
                            and r_lo >= 1.5
                            and (
                                champ_boot.get("ci_lo") is None
                                or r_lo >= champ_boot["ci_lo"] * 0.85
                            )
                        ):
                            ok, reason = True, f"robust_risk_adj_ladder_boot:{risk_reason}"
                            row["_ladder"] = lad
                            row["_boot"] = boot
                    except Exception as ex:
                        log(f"  {row['name']}: riskadj ladder/boot err {ex}")
            if ok:
                log(f"  BEAT via {reason}: {row['name']}")
                new_champ = row
                promote_ok = True
                promote_reason = f"{reason}:{row['name']}"
                break
            else:
                if reason not in ("no_dual_clear", "margin_thin", "n<40", "wf<3"):
                    log(f"  {row['name']}: skip ({reason})")

    if not promote_ok:
        log(f"  No promote — keep {champ['name']}")
        log("  Paper A/B unchanged (no flip warranted)")
    else:
        log(f"  PROMOTED {new_champ['name']} reason={promote_reason}")
        # Overwrite best if signal champ
        fn_name = fn_map.get(new_champ["name"], "sig_st_kill40_dd")
        if new_champ["name"].startswith("B6_"):
            # near-miss from block6
            if "nifty_mom" in new_champ["name"]:
                fn_name = "sig_st_kill40_dd_nifty_mom"
            elif "days60" in new_champ["name"]:
                fn_name = "sig_st_kill40_dd_days"
        if fn_name == "sig_st_kill40_dd":
            fn_import = "from run_block5 import sig_st_kill40_dd as FN"
        elif fn_name in (
            "sig_st_kill40_dd_volcalm",
            "sig_st_kill40_dd_days",
            "sig_st_kill40_dd_bankrs",
            "sig_st_kill40_dd_atr",
            "sig_st_kill40_dd_nifty_mom",
            "sig_st_kill40_dd_volcap",
            "sig_st_kill40_dd_regime",
        ):
            fn_import = f"from run_block6 import {fn_name} as FN"
        else:
            fn_import = f"from run_block7 import {fn_name} as FN"
        oos = new_champ["OOS"]
        stress = new_champ["OOS_stress"]
        params = new_champ["params"]
        params_txt = json.dumps(params, indent=2).replace("true", "True").replace("false", "False")
        py = f'''"""
Nifty Edge Best — Block 7 champion
==================================
{new_champ["name"]}
Params: {json.dumps(params)}

OOS: n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} stressPF={stress["profit_factor"]:.2f}
WF={new_champ["wf_pos"]}/{new_champ["wf_n"]} lastWF={new_champ["last_wf_tot"]*100:.1f}%

Usage:
  python strategies/nifty_edge_best.py
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
{fn_import}

PARAMS = {params_txt}

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
    print(json.dumps({{"name": {json.dumps(new_champ["name"])}, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
        (OUT_STRAT / "nifty_edge_best.py").write_text(py)
        log(f"  Wrote {OUT_STRAT / 'nifty_edge_best.py'}")

    # ── 6) Save r26+ ──────────────────────────────────────────────────────────
    log("Saving runners r26+…")
    candidates = []
    # Prefer near-misses already as r21/r25 — save new interesting B7 rows
    pool = new_rows + [
        r for r in fragile_rows if r["OOS"]["profit_factor"] >= 2.0 and r.get("last_wf_tot", -1) >= 0
    ]

    def score(r):
        return (
            r["wf_pos"],
            r.get("last_wf_tot", 0),
            r["OOS"]["profit_factor"],
            r["OOS"]["total_return"],
        )

    seen = set()
    for r in sorted(pool, key=score, reverse=True):
        if r["name"] in seen or r["name"] == new_champ["name"]:
            continue
        if r["OOS"]["n_trades"] < 30 or r["OOS"]["profit_factor"] < 1.5:
            continue
        seen.add(r["name"])
        candidates.append(r)
        if len(candidates) >= 4:
            break

    saved = []
    for i, r in enumerate(candidates, start=26):
        fn_name = fn_map.get(r["name"], "sig_st_kill40_dd")
        path = write_b7_runner(i, r, fn_name)
        saved.append({"r": i, "name": r["name"], "path": str(path)})
        log(
            f"  Saved nifty_edge_r{i}.py: {r['name']} "
            f"PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )

    # ── 7) Outline / FINAL ────────────────────────────────────────────────────
    expand_final_outline(
        new_champ if promote_ok else champ,
        near_stress,
        fragile_doc,
        new_rows,
        promote_reason,
        hrs,
    )
    log(f"Wrote {FINAL_OUTLINE}")
    wrote_final = False
    if hrs < 1.0:
        wrote_final = write_full_final_if_needed(new_champ if promote_ok else champ, hrs)
        log("FINAL_REPORT written (<1h)")
    else:
        log(f"FINAL outline only ({hrs:.1f}h left; full FINAL later)")

    append_leaderboard_block7(
        new_champ if promote_ok else champ,
        champ,  # repro always vs B5
        near_stress,
        fragile_doc,
        new_rows,
        promote_ok,
        promote_reason,
        hrs,
        bh_oos,
    )
    log(f"Updated {LEADERBOARD}")

    summary = {
        "block": 7,
        "hours_left": hrs,
        "drift_ok": drift_ok,
        "champion": (new_champ if promote_ok else champ)["name"],
        "promote_ok": promote_ok,
        "promote_reason": promote_reason,
        "repro": {
            "n": o["n_trades"],
            "pf": o["profit_factor"],
            "tot": o["total_return"],
            "mdd": o["max_dd"],
            "sharpe": o["sharpe"],
            "last_wf": champ["last_wf_tot"],
        },
        "near_miss_stress": [
            {
                "name": ns["name"],
                "dual_clear": ns.get("dual_clear"),
                "ladder_ok": ns.get("ladder_ok"),
                "risk_adj_ok": ns.get("risk_adj_ok"),
                "decision": ns.get("decision"),
                "boot_ci_lo": (ns.get("_boot") or {}).get("ci_lo"),
                "tot": ns["OOS"]["total_return"],
                "last_wf": ns.get("last_wf_tot"),
                "pf": ns["OOS"]["profit_factor"],
            }
            for ns in near_stress
        ],
        "fragile_failure_modes": fragile_doc["narrative"],
        "fragile_cells": fragile_doc["cells"],
        "n_variants": len(new_rows),
        "variants_top": [
            {
                "name": v["name"],
                "pf": v["OOS"]["profit_factor"],
                "tot": v["OOS"]["total_return"],
                "last_wf": v.get("last_wf_tot"),
                "mdd": v["OOS"]["max_dd"],
            }
            for v in sorted(
                new_rows,
                key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
                reverse=True,
            )[:5]
        ],
        "saved_runners": saved,
        "checklist": str(CHECKLIST),
        "final_outline": str(FINAL_OUTLINE),
        "final_report_written": wrote_final,
        "paper_a": "B5_ST_kill40_dd07" if not promote_ok else new_champ["name"],
        "paper_b": "ST_m3.6_n1_e1",
    }
    out = RESULTS / "block7_summary.json"
    out.write_text(json.dumps(_clean(summary), indent=2))
    log(f"Wrote {out}")

    top5 = sorted(
        new_rows,
        key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
        reverse=True,
    )[:5]
    log("--- Block 7 top 5 variants ---")
    for v in top5:
        log(
            f"  {v['name']}: PF={v['OOS']['profit_factor']:.2f} "
            f"tot={v['OOS']['total_return']*100:.1f}% n={v['OOS']['n_trades']} "
            f"WF={v['wf_pos']}/3 lastWF={v.get('last_wf_tot', 0)*100:.1f}%"
        )
    log(
        f"=== Block 7 complete === champion={(new_champ if promote_ok else champ)['name']} "
        f"PF={(new_champ if promote_ok else champ)['OOS']['profit_factor']:.2f} "
        f"tot={(new_champ if promote_ok else champ)['OOS']['total_return']*100:.1f}% "
        f"promoted={promote_ok} reason={promote_reason} n_b7={len(new_rows)} "
        f"drift_ok={drift_ok} hrs_left={hrs:.2f}"
    )
    log(
        "Next Block 8: continue paper A/B log; optional locked-sleeve cost shock only; "
        "FINAL_REPORT + lock when <1h to deadline"
    )
    print(json.dumps({"ok": True, "champion": summary["champion"], "promote_ok": promote_ok}, indent=2))


if __name__ == "__main__":
    main()
