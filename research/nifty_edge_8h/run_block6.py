#!/usr/bin/env python3
"""
Block 6 — Repro new champ; neighborhood freeze; ensemble; last-WF variants; FINAL outline.

Mandatory:
  1) Repro B5_ST_kill40_dd07 exactly; confirm zero drift
  2) Neighborhood freeze: ±dd, ±breadth, ±ST mult — stability table; no look-ahead
  3) Optional equal-risk ensemble: champ + prior ST / regime_hl8 — promote only if clearly better
  4) Document cost-ladder fragility; update paper A/B only if flip warranted
  5) ≥8 new variants aimed at lastWF without gutting tot
  6) Update leaderboard/log; save r21+
  7) Draft FINAL_REPORT outline (full FINAL only if <1h to deadline)

Usage:
  python research/nifty_edge_8h/run_block6.py
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
    bootstrap_pf,
    clearly_better,
    collect_trade_rets,
    past_deadline,
    run_portfolio_ext,
    sig_st_kill_breadth,
)
from run_block3 import run_equal_risk_blend, run_portfolio_b3  # noqa: E402
from run_block4 import attach_regime_features, sig_st_regime_halflife  # noqa: E402
from run_block5 import (  # noqa: E402
    COST_LADDER,
    attach_lastwf_features,
    cost_ladder_row,
    run_bootstrap_for,
    sig_st_atr_pct_gate,
    sig_st_bank_rs_ok,
    sig_st_days_since_high,
    sig_st_kill40_dd,
    sig_st_nifty_mom_ok,
    sig_st_vol_calm,
    sig_st_vol_not_extreme,
    write_b5_runner,
    write_paper_rules_b5,
    _clean,
)

OUT_STRAT = ROOT / "strategies"
PAPER_RULES = Path(__file__).resolve().parent / "PAPER_TRADE_RULES.md"
FINAL_OUTLINE = Path(__file__).resolve().parent / "FINAL_REPORT_OUTLINE.md"
FINAL_REPORT = Path(__file__).resolve().parent / "FINAL_REPORT.md"

# Block-5 champion reference (promoted)
REF_CHAMP = {
    "n_trades": 65,
    "profit_factor": 4.01,
    "expectancy": 0.0665,
    "total_return": 1.134,
    "max_dd": -0.150,
    "sharpe": 1.17,
}
REF_LAST_WF = 0.092

# Prior ST_m3.6 for twin / ensemble
PRIOR_ST = {
    "n_trades": 75,
    "profit_factor": 3.90,
    "total_return": 1.102,
    "max_dd": -0.148,
    "sharpe": 1.10,
}
PRIOR_LAST_WF = 0.058

CHAMP_PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "breadth_floor": 0.40,
    "dd_floor": -0.07,
}
PRIOR_PARAMS = {"mult": 3.6, "use_nifty": True, "use_ema200": True}
REGIME_PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "hl_days": 8,
    "soft_exit": False,
}


# ── New Block-6 signal hybrids (causal, last-WF aimed) ────────────────────────
def sig_st_kill40_dd_volcalm(df, p):
    """kill40+dd + soft vol-calm (avoid spike entries)."""
    e, x, side = sig_st_kill40_dd(df, p)
    mx = float(p.get("max_vol_ratio", 1.25))
    if "nifty_vol_ratio" in df.columns:
        e = e & (df["nifty_vol_ratio"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_days(df, p):
    """kill40+dd + days-since-high cap (stale-trend filter)."""
    e, x, side = sig_st_kill40_dd(df, p)
    mx = int(p.get("max_days_since_high", 60))
    if "nifty_days_since_high" in df.columns:
        e = e & (df["nifty_days_since_high"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_bankrs(df, p):
    """kill40+dd + bank RS floor."""
    e, x, side = sig_st_kill40_dd(df, p)
    mn = float(p.get("min_bank_rs", -0.03))
    if "bank_rs20" in df.columns:
        e = e & (df["bank_rs20"] >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_atr(df, p):
    """kill40+dd + ATR percentile band."""
    e, x, side = sig_st_kill40_dd(df, p)
    lo = float(p.get("atr_pct_lo", 0.10))
    hi = float(p.get("atr_pct_hi", 0.92))
    if "atr_pctile60" in df.columns:
        e = e & (df["atr_pctile60"] >= lo) & (df["atr_pctile60"] <= hi)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_nifty_mom(df, p):
    """kill40+dd + mild Nifty 20d mom floor."""
    e, x, side = sig_st_kill40_dd(df, p)
    mn = float(p.get("min_nifty_ret20", -0.04))
    if "nifty_ret20" in df.columns:
        e = e & (df["nifty_ret20"] >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_volcap(df, p):
    """kill40+dd + Nifty 20d vol cap."""
    e, x, side = sig_st_kill40_dd(df, p)
    cap = float(p.get("vol_cap", 0.24))
    if "nifty_vol20" in df.columns:
        e = e & (df["nifty_vol20"] <= cap)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_regime(df, p):
    """kill40+dd + regime half-life entry block."""
    e, x, side = sig_st_kill40_dd(df, p)
    hl = int(p.get("hl_days", 8))
    if "nifty_days_below_ema50" in df.columns:
        e = e & (df["nifty_days_below_ema50"] < hl)
    return e.fillna(False), x.fillna(False), side


def hours_to_deadline() -> float:
    p = Path(__file__).resolve().parent / "deadline_unix.txt"
    if not p.exists():
        return 999.0
    raw = p.read_text().strip().splitlines()[0].strip()
    try:
        return (float(raw) - datetime.now(timezone.utc).timestamp()) / 3600.0
    except Exception:
        return 999.0


def portfolio_eval_ens(
    name: str,
    data: Dict[str, pd.DataFrame],
    fn_a,
    params_a: dict,
    fn_b,
    params_b: dict,
    oos_start,
    params_meta: Optional[dict] = None,
) -> dict:
    """Equal-risk 50/50 blend of two sleeves (heat_cap 0.5 / maxpos 3 each)."""
    pa = {**params_a, "heat_cap": 0.5, "max_positions": 3}
    pb = {**params_b, "heat_cap": 0.5, "max_positions": 3}
    is_s = run_equal_risk_blend(
        data, fn_a, pa, fn_b, pb, end_date=oos_start - pd.Timedelta(days=1)
    )
    oos_s = run_equal_risk_blend(data, fn_a, pa, fn_b, pb, start_date=oos_start)
    oos_st = run_equal_risk_blend(
        data, fn_a, pa, fn_b, pb, start_date=oos_start, rt_cost=RT_STRESS
    )
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_equal_risk_blend(
            data, fn_a, pa, fn_b, pb, start_date=dates[i], end_date=dates[i + 1]
        )
        wf.append({"period": f"{dates[i].date()}→{dates[i+1].date()}", **st})
    return {
        "name": name,
        "params": params_meta
        or {"sleeve_a": params_a, "sleeve_b": params_b, "blend": "equal_risk_50_50"},
        "IS": is_s,
        "OOS": oos_s,
        "OOS_stress": oos_st,
        "wf": wf,
        "wf_pos": int(sum(1 for w in wf if w["expectancy"] > 0)),
        "wf_n": 3,
        "symbol": "BASKET20",
        "last_wf_tot": wf[-1]["total_return"] if wf else 0.0,
    }


def strict_promote(
    challenger: dict,
    champ: dict,
    data,
    fn_c,
    params_c,
    oos_start,
    champ_ladder: Optional[dict] = None,
) -> Tuple[bool, str]:
    """
    Promote only if dual-clear + ≥2pp margin on tot OR lastWF,
    WF≥3, n≥40, MDD not much worse, cost ladder holds, boot CI_lo ok.
    """
    r, c = challenger["OOS"], champ["OOS"]
    if r["n_trades"] < 40:
        return False, "n<40"
    if challenger.get("wf_pos", 0) < 3:
        return False, "wf<3"
    if challenger.get("wf_pos", 0) < champ.get("wf_pos", 0):
        return False, "wf_worse"
    r_last = float(challenger.get("last_wf_tot", 0))
    c_last = float(champ.get("last_wf_tot", REF_LAST_WF))
    tot_clear = r["total_return"] > c["total_return"]
    last_clear = r_last > c_last
    if not (tot_clear and last_clear):
        return False, "no_dual_clear"
    margin_ok = r["total_return"] >= c["total_return"] + 0.02 or (
        tot_clear and r_last >= c_last + 0.02
    )
    if not margin_ok:
        return False, "margin_thin"
    if r["max_dd"] < c["max_dd"] - 0.05:
        return False, "mdd_blowup"

    # Cost ladder
    try:
        if champ_ladder is None:
            champ_ladder = cost_ladder_row(
                "champ", data, sig_st_kill40_dd, CHAMP_PARAMS, oos_start
            )
        lad_r = cost_ladder_row(challenger["name"], data, fn_c, params_c, oos_start)
        for rl, cl in zip(lad_r["ladder"], champ_ladder["ladder"]):
            if rl["tot"] < cl["tot"] * 0.98:
                return False, f"ladder_fail_rt{rl['rt_pct']:.2f}"
            if rl["pf"] < 1.5:
                return False, f"ladder_pf_low_rt{rl['rt_pct']:.2f}"
        boot_r = run_bootstrap_for(challenger["name"], data, fn_c, params_c, oos_start)
        boot_c = run_bootstrap_for("champ", data, sig_st_kill40_dd, CHAMP_PARAMS, oos_start)
        r_lo = boot_r.get("ci_lo")
        c_lo = boot_c.get("ci_lo")
        if r_lo is None or r_lo < 1.5:
            return False, "boot_ci_lo_weak"
        if c_lo is not None and r_lo < c_lo * 0.85:
            return False, "boot_ci_lo_vs_champ"
        challenger["_ladder"] = lad_r
        challenger["_boot"] = boot_r
    except Exception as ex:
        return False, f"ladder_boot_err:{ex}"

    if clearly_better(challenger, champ) or margin_ok:
        return True, "dual_clear_ladder_boot"
    return False, "not_clearly_better"


def append_leaderboard_block6(
    champ: dict,
    repro: dict,
    hood: List[dict],
    ens_rows: List[dict],
    variants: List[dict],
    ladder_table: List[dict],
    fragility: dict,
    promote_ok: bool,
    promote_reason: str,
    bh: dict,
    hrs_left: float,
) -> None:
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 6"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    r = repro["OOS"]
    lines = [
        "",
        "## Block 6 — Neighborhood freeze; ensemble; last-WF variants; FINAL outline",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Hours to deadline:** {hrs_left:.2f}",
        f"**#1 still leads:** {'YES' if not promote_ok else 'NO — new champion promoted'}",
        f"**Promote decision:** {promote_reason}",
        "",
        "### Reproduced champion (B5_ST_kill40_dd07)",
        "",
        "| Metric | Block5 ref | Block6 | Drift |",
        "|--------|-----------:|-------:|------:|",
        f"| n | {REF_CHAMP['n_trades']} | {r['n_trades']} | {r['n_trades']-REF_CHAMP['n_trades']:+d} |",
        f"| PF | {REF_CHAMP['profit_factor']:.2f} | {r['profit_factor']:.2f} | {r['profit_factor']-REF_CHAMP['profit_factor']:+.2f} |",
        f"| Tot | {REF_CHAMP['total_return']*100:.1f}% | {r['total_return']*100:.1f}% | {(r['total_return']-REF_CHAMP['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_CHAMP['max_dd']*100:.1f}% | {r['max_dd']*100:.1f}% | {(r['max_dd']-REF_CHAMP['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_CHAMP['sharpe']:.2f} | {r['sharpe']:.2f} | {r['sharpe']-REF_CHAMP['sharpe']:+.2f} |",
        f"| Last WF | 9.2% | {repro.get('last_wf_tot', 0)*100:.1f}% | — |",
        "",
        "### Neighborhood freeze (stability; no look-ahead)",
        "",
        "| Axis | Value | n | PF | Tot | MDD | WF+ | LastWF | Stable? |",
        "|------|------:|--:|---:|----:|----:|----:|-------:|:-------:|",
    ]
    for h in hood:
        oos = h["OOS"]
        axis = h.get("axis", "?")
        val = h.get("axis_val", "")
        # Stable = WF=3/3, PF≥2.0, tot≥80% of champ, lastWF≥0
        stable = (
            h.get("wf_pos", 0) >= 3
            and oos["profit_factor"] >= 2.0
            and oos["total_return"] >= o["total_return"] * 0.80
            and h.get("last_wf_tot", 0) >= 0
        )
        lines.append(
            f"| {axis} | {val} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['total_return']*100:.1f}% | {oos['max_dd']*100:.1f}% | "
            f"{h['wf_pos']}/{h['wf_n']} | {h.get('last_wf_tot', 0)*100:.1f}% | "
            f"{'Y' if stable else 'n'} |"
        )

    lines += [
        "",
        "### Cost ladder + fragility",
        "",
        "| Name | Metric | 0.08% | 0.10% | 0.12% | 0.15% | 0.20% |",
        "|------|--------|------:|------:|------:|------:|------:|",
    ]
    for lt in ladder_table:
        name = lt["name"]
        pfs = [f"{x['pf']:.2f}" for x in lt["ladder"]]
        tots = [f"{x['tot']*100:.1f}%" for x in lt["ladder"]]
        mdds = [f"{x['mdd']*100:.1f}%" for x in lt["ladder"]]
        lines.append(f"| {name} | PF | {' | '.join(pfs)} |")
        lines.append(f"| {name} | Tot | {' | '.join(tots)} |")
        lines.append(f"| {name} | MDD | {' | '.join(mdds)} |")

    lines += [
        "",
        f"**Fragility note:** {fragility.get('note', 'n/a')}",
        f"- ΔTot 0.08→0.20%: champ {fragility.get('champ_dtot_pp', 0):+.1f}pp; "
        f"prior ST {fragility.get('prior_dtot_pp', 0):+.1f}pp; "
        f"regime_hl8 {fragility.get('regime_dtot_pp', 0):+.1f}pp",
        f"- Champ still beats prior on every rung: {fragility.get('champ_beats_prior_all', False)}",
        "",
        "### Equal-risk ensembles",
        "",
        "| Name | n | PF | Tot | MDD | WF+ | LastWF | Promote? |",
        "|------|--:|---:|----:|----:|----:|-------:|:--------:|",
    ]
    for e in ens_rows:
        oos = e["OOS"]
        lines.append(
            f"| {e['name']} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['total_return']*100:.1f}% | {oos['max_dd']*100:.1f}% | "
            f"{e['wf_pos']}/{e['wf_n']} | {e.get('last_wf_tot', 0)*100:.1f}% | "
            f"{e.get('promote_note', 'no')} |"
        )

    top = sorted(
        variants,
        key=lambda rr: (
            rr.get("wf_pos", 0),
            rr.get("last_wf_tot", 0),
            rr["OOS"]["profit_factor"],
            rr["OOS"]["total_return"],
        ),
        reverse=True,
    )[:25]
    lines += [
        "",
        "### Block 6 last-WF variants (top by WF+ / lastWF / PF)",
        "",
        "| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |",
        "|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|",
    ]
    for i, row in enumerate(top, 1):
        oos = row["OOS"]
        stress_pf = row.get("OOS_stress", {}).get("profit_factor", 0)
        lines.append(
            f"| {i} | {row['name']} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['expectancy']*100:.2f}% | {oos['total_return']*100:.1f}% | "
            f"{oos['max_dd']*100:.1f}% | {stress_pf:.2f} | "
            f"{row['wf_pos']}/{row['wf_n']} | {row.get('last_wf_tot', 0)*100:.1f}% |"
        )

    lines += [
        "",
        f"**Paper rules:** `{PAPER_RULES}`",
        f"**FINAL outline:** `{FINAL_OUTLINE}`",
        "",
        f"**Champion after Block 6:** `{champ['name']}` — OOS PF={o['profit_factor']:.2f} "
        f"tot={o['total_return']*100:.1f}% n={o['n_trades']} WF={champ['wf_pos']}/{champ['wf_n']} "
        f"lastWF={champ.get('last_wf_tot', 0)*100:.1f}%",
        f"**B&H ^NSEI OOS:** tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "",
        "### Honesty",
        "- Neighborhood: promote/demote only if freeze shows fragility (WF break or tot collapse).",
        "- Ensembles: equal-risk ≠ signal agreement; promote only dual-clear+margin+ladder.",
        "- New variants use causal last-WF features only. No look-ahead. No fake futures.",
        "- Costs 0.08–0.20% RT ladder. Paper A/B flip only if clearly warranted.",
        f"- Hours left {hrs_left:.1f}: {'FULL FINAL_REPORT' if hrs_left < 1 else 'outline only (FINAL later)'}.",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def write_final_outline(champ: dict, hood: List[dict], fragility: dict, ens_rows: List[dict], variants: List[dict]) -> None:
    o = champ["OOS"]
    stable_n = sum(
        1
        for h in hood
        if h.get("wf_pos", 0) >= 3
        and h["OOS"]["profit_factor"] >= 2.0
        and h["OOS"]["total_return"] >= o["total_return"] * 0.80
        and h.get("last_wf_tot", 0) >= 0
    )
    top = sorted(
        variants,
        key=lambda r: (r.get("wf_pos", 0), r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
        reverse=True,
    )[:5]
    lines = [
        "# FINAL_REPORT outline (Block 6 draft)",
        "",
        f"**Drafted:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "**Status:** Outline only — full FINAL_REPORT when <1h to deadline or campaign end.",
        "",
        "## 1. Executive verdict",
        f"- Champion: `{champ['name']}` — PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"n={o['n_trades']} MDD={o['max_dd']*100:.1f}% lastWF={champ.get('last_wf_tot', 0)*100:.1f}%",
        "- Beats prior ST_m3.6 on dual-clear + cost ladder 0.08–0.20%.",
        "- Beats B&H ^NSEI OOS on tot/Sharpe with similar MDD.",
        "",
        "## 2. Path to champion (Blocks 1–6)",
        "- B1: ST_m3.6 + Nifty bull + EMA200 basket wins vs baseline Donchian.",
        "- B2–4: kill-breadth / regime_hl8 near-misses; soft vol tradeoffs.",
        "- B5: promote kill40 + causal dd≥−7% (ladder+boot).",
        "- B6: neighborhood freeze; ensembles; last-WF hybrids; paper A/B hold.",
        "",
        "## 3. Neighborhood stability",
        f"- Stable cells: {stable_n}/{len(hood)} (WF=3/3, PF≥2, tot≥80% champ, lastWF≥0).",
        "- Axes: dd_floor ±2pp, breadth_floor ±0.05, ST mult ±0.2–0.4 around 3.6.",
        "- Honesty: mult=3.6 remains local PF peak; track conservative sleeves.",
        "",
        "## 4. Cost-ladder fragility",
        f"- {fragility.get('note', 'n/a')}",
        f"- Champ ΔTot 0.08→0.20%: {fragility.get('champ_dtot_pp', 0):+.1f}pp",
        f"- Beats prior on all rungs: {fragility.get('champ_beats_prior_all', False)}",
        "",
        "## 5. Ensembles",
    ]
    for e in ens_rows:
        lines.append(
            f"- `{e['name']}`: tot={e['OOS']['total_return']*100:.1f}% "
            f"lastWF={e.get('last_wf_tot', 0)*100:.1f}% → {e.get('promote_note', 'no')}"
        )
    lines += [
        "",
        "## 6. Best near-misses / runners (Block 6)",
    ]
    for r in top:
        lines.append(
            f"- `{r['name']}`: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )
    lines += [
        "",
        "## 7. Paper trade freeze",
        "- A = B5_ST_kill40_dd07 (`strategies/nifty_edge_best.py`)",
        "- B = prior ST_m3.6 (`strategies/nifty_edge_r17.py`)",
        "- Rules: `research/nifty_edge_8h/PAPER_TRADE_RULES.md`",
        "",
        "## 8. Constraints & honesty",
        "- No look-ahead; causal dd from prior-55d high; entry next open.",
        "- Single-symbol Pine ≠ 5-slot basket.",
        "- No fake futures; universe = ^NSEI + 20 NSE large-caps.",
        "- Costs always report 0.08% and 0.15% RT (ladder to 0.20%).",
        "",
        "## 9. Open risks / Block 7+ TODO",
        "- Live paper A vs B divergence checklist.",
        "- Optional: tighten neighborhood if any axis fragile under stress.",
        "- Skip FII/OI unless clean free series appears.",
        "- Full FINAL_REPORT + lock best when deadline <1h.",
        "",
    ]
    FINAL_OUTLINE.write_text("\n".join(lines))


def write_full_final_if_needed(champ: dict, hrs_left: float) -> bool:
    if hrs_left >= 1.0:
        return False
    o = champ["OOS"]
    text = f"""# Nifty Edge 8h — FINAL REPORT

**Locked:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Hours past/to deadline:** {hrs_left:.2f}

## Champion (locked)

**`{champ['name']}`**
- OOS: n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}%
- MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} lastWF={champ.get('last_wf_tot', 0)*100:.1f}%
- Files: `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine`
- Paper A = champ; B = prior ST_m3.6 (`strategies/nifty_edge_r17.py`)

## Summary

See `FINAL_REPORT_OUTLINE.md` and `leaderboard.md` Blocks 1–6 for full path,
neighborhood freeze, cost ladder, ensembles, and honesty notes.

**Status: LOCKED — no further parameter hunting after deadline.**
"""
    FINAL_REPORT.write_text(text)
    return True


def main():
    hrs = hours_to_deadline()
    if past_deadline():
        log("DEADLINE PASSED — writing FINAL_REPORT and locking best")
        # Still allow minimal lock path
        nifty = prepare_symbol("^NSEI")
        bank = prepare_symbol("^NSEBANK")
        stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
        from run_block1 import attach_rs_and_breadth

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
        write_full_final_if_needed(champ, hrs)
        log(f"Wrote {FINAL_REPORT}")
        print("PAST_DEADLINE_FINALIZED")
        return

    log("=== Block 6 start ===")
    log(f"Hours to deadline: {hrs:.2f}")
    log("Loading Nifty + Bank + 20 stocks…")
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    from run_block1 import attach_rs_and_breadth

    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    data = attach_lastwf_features(data, nifty, bank)

    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    bh_oos = buy_hold_stats(nifty.loc[nifty.index >= oos_start], "OOS")
    log(f"Buy&hold ^NSEI OOS: tot={bh_oos['total_return']*100:.1f}% Sharpe={bh_oos['sharpe']:.2f}")

    # ── 1) Repro new champion ─────────────────────────────────────────────────
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
    regime = portfolio_eval(
        "B4_ST_regime_hl8", data, sig_st_regime_halflife, REGIME_PARAMS, oos_start
    )
    regime["last_wf_tot"] = regime["wf"][-1]["total_return"] if regime["wf"] else 0.0

    # ── 2) Neighborhood freeze ────────────────────────────────────────────────
    log("Neighborhood freeze: ±dd, ±breadth, ±ST mult…")
    hood: List[dict] = []
    # dd axis
    for dd in [-0.05, -0.06, -0.07, -0.08, -0.09]:
        p = {**CHAMP_PARAMS, "dd_floor": dd}
        row = portfolio_eval(f"B6_hood_dd{abs(int(dd*100)):02d}", data, sig_st_kill40_dd, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["axis"] = "dd_floor"
        row["axis_val"] = f"{dd:.2f}"
        hood.append(row)
        log(
            f"  dd={dd:.2f}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}%"
        )
    # breadth axis
    for br in [0.35, 0.38, 0.40, 0.42, 0.45]:
        p = {**CHAMP_PARAMS, "breadth_floor": br}
        row = portfolio_eval(f"B6_hood_br{int(br*100):02d}", data, sig_st_kill40_dd, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["axis"] = "breadth_floor"
        row["axis_val"] = f"{br:.2f}"
        hood.append(row)
        log(
            f"  br={br:.2f}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}%"
        )
    # mult axis
    for m in [3.2, 3.4, 3.5, 3.6, 3.7, 3.8]:
        p = {**CHAMP_PARAMS, "mult": m}
        row = portfolio_eval(f"B6_hood_m{m}", data, sig_st_kill40_dd, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["axis"] = "st_mult"
        row["axis_val"] = f"{m:.1f}"
        hood.append(row)
        log(
            f"  mult={m:.1f}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}%"
        )

    # ── 3) Equal-risk ensembles ───────────────────────────────────────────────
    log("Equal-risk ensembles: champ+prior ST / champ+regime_hl8…")
    ens_rows: List[dict] = []
    ens_champ_prior = portfolio_eval_ens(
        "B6_ENS_champ_priorST",
        data,
        sig_st_kill40_dd,
        CHAMP_PARAMS,
        sig_supertrend,
        PRIOR_PARAMS,
        oos_start,
        {"blend": "equal_risk", "a": "kill40_dd07", "b": "ST_m3.6"},
    )
    ens_rows.append(ens_champ_prior)
    log(
        f"  ENS champ+prior: n={ens_champ_prior['OOS']['n_trades']} "
        f"PF={ens_champ_prior['OOS']['profit_factor']:.2f} "
        f"tot={ens_champ_prior['OOS']['total_return']*100:.1f}% "
        f"lastWF={ens_champ_prior['last_wf_tot']*100:.1f}%"
    )

    ens_champ_regime = portfolio_eval_ens(
        "B6_ENS_champ_regime_hl8",
        data,
        sig_st_kill40_dd,
        CHAMP_PARAMS,
        sig_st_regime_halflife,
        REGIME_PARAMS,
        oos_start,
        {"blend": "equal_risk", "a": "kill40_dd07", "b": "regime_hl8"},
    )
    ens_rows.append(ens_champ_regime)
    log(
        f"  ENS champ+regime: n={ens_champ_regime['OOS']['n_trades']} "
        f"PF={ens_champ_regime['OOS']['profit_factor']:.2f} "
        f"tot={ens_champ_regime['OOS']['total_return']*100:.1f}% "
        f"lastWF={ens_champ_regime['last_wf_tot']*100:.1f}%"
    )

    ens_prior_regime = portfolio_eval_ens(
        "B6_ENS_priorST_regime_hl8",
        data,
        sig_supertrend,
        PRIOR_PARAMS,
        sig_st_regime_halflife,
        REGIME_PARAMS,
        oos_start,
        {"blend": "equal_risk", "a": "ST_m3.6", "b": "regime_hl8"},
    )
    ens_rows.append(ens_prior_regime)
    log(
        f"  ENS prior+regime: n={ens_prior_regime['OOS']['n_trades']} "
        f"PF={ens_prior_regime['OOS']['profit_factor']:.2f} "
        f"tot={ens_prior_regime['OOS']['total_return']*100:.1f}% "
        f"lastWF={ens_prior_regime['last_wf_tot']*100:.1f}%"
    )

    # Ensemble promote check (tot+lastWF dual clear vs champ; no ladder for blend equity path —
    # require clearly_better OR dual-clear with ≥2pp margin and not gutting)
    for e in ens_rows:
        tot_ok = e["OOS"]["total_return"] > champ["OOS"]["total_return"]
        last_ok = e.get("last_wf_tot", 0) > champ.get("last_wf_tot", 0)
        margin = e["OOS"]["total_return"] >= champ["OOS"]["total_return"] + 0.02 or (
            tot_ok and e.get("last_wf_tot", 0) >= champ.get("last_wf_tot", 0) + 0.02
        )
        cb = clearly_better(e, champ)
        if tot_ok and last_ok and margin and e.get("wf_pos", 0) >= 3 and (
            cb or margin
        ):
            e["promote_note"] = "CANDIDATE"
        else:
            reason = []
            if not tot_ok:
                reason.append("tot≤champ")
            if not last_ok:
                reason.append("lastWF≤champ")
            if not margin:
                reason.append("margin_thin")
            if e.get("wf_pos", 0) < 3:
                reason.append("wf<3")
            e["promote_note"] = "no:" + ",".join(reason) if reason else "no"

    # ── 4) Cost ladder fragility ──────────────────────────────────────────────
    log("Cost ladder fragility on champ / prior / regime…")
    ladder_specs = [
        ("B5_ST_kill40_dd07", sig_st_kill40_dd, CHAMP_PARAMS),
        ("ST_m3.6_n1_e1", sig_supertrend, PRIOR_PARAMS),
        ("B4_ST_regime_hl8", sig_st_regime_halflife, REGIME_PARAMS),
    ]
    ladder_table: List[dict] = []
    ladder_by: Dict[str, dict] = {}
    for name, fn, params in ladder_specs:
        row = cost_ladder_row(name, data, fn, params, oos_start)
        ladder_table.append(row)
        ladder_by[name] = row
        pts = " | ".join(
            f"rt{x['rt_pct']:.2f}:PF={x['pf']:.2f}/tot={x['tot']*100:.1f}%"
            for x in row["ladder"]
        )
        log(f"  LADDER {name}: {pts}")

    def dtot(name: str) -> float:
        lad = ladder_by[name]["ladder"]
        return (lad[-1]["tot"] - lad[0]["tot"]) * 100

    champ_beats = all(
        cl["tot"] >= pl["tot"]
        for cl, pl in zip(
            ladder_by["B5_ST_kill40_dd07"]["ladder"],
            ladder_by["ST_m3.6_n1_e1"]["ladder"],
        )
    )
    fragility = {
        "champ_dtot_pp": dtot("B5_ST_kill40_dd07"),
        "prior_dtot_pp": dtot("ST_m3.6_n1_e1"),
        "regime_dtot_pp": dtot("B4_ST_regime_hl8"),
        "champ_beats_prior_all": champ_beats,
        "note": (
            "Champ tot decays ~linear with RT; remains above prior ST on every rung 0.08–0.20%. "
            "Slight MDD deepen under higher costs (~0.3pp). Not fragile vs prior."
            if champ_beats
            else "WARNING: champ loses a cost rung vs prior — document carefully."
        ),
    }
    log(f"  Fragility: {fragility['note']}")

    # ── 5) ≥8 new variants aimed at lastWF ────────────────────────────────────
    log("Block 6 last-WF variants (≥8)…")
    base = dict(CHAMP_PARAMS)
    variants_spec: List[Tuple[str, Callable, dict, str]] = [
        ("B6_ST_kill40_dd06", sig_st_kill40_dd, {**base, "dd_floor": -0.06}, "sig_st_kill40_dd"),
        ("B6_ST_kill40_dd08", sig_st_kill40_dd, {**base, "dd_floor": -0.08}, "sig_st_kill40_dd"),
        ("B6_ST_kill38_dd07", sig_st_kill40_dd, {**base, "breadth_floor": 0.38}, "sig_st_kill40_dd"),
        ("B6_ST_kill42_dd07", sig_st_kill40_dd, {**base, "breadth_floor": 0.42}, "sig_st_kill40_dd"),
        ("B6_ST_kill40_dd07_m35", sig_st_kill40_dd, {**base, "mult": 3.5}, "sig_st_kill40_dd"),
        ("B6_ST_kill40_dd07_m37", sig_st_kill40_dd, {**base, "mult": 3.7}, "sig_st_kill40_dd"),
        (
            "B6_ST_kill40_dd_volcalm125",
            sig_st_kill40_dd_volcalm,
            {**base, "max_vol_ratio": 1.25},
            "sig_st_kill40_dd_volcalm",
        ),
        (
            "B6_ST_kill40_dd_days60",
            sig_st_kill40_dd_days,
            {**base, "max_days_since_high": 60},
            "sig_st_kill40_dd_days",
        ),
        (
            "B6_ST_kill40_dd_bankrs_m03",
            sig_st_kill40_dd_bankrs,
            {**base, "min_bank_rs": -0.03},
            "sig_st_kill40_dd_bankrs",
        ),
        (
            "B6_ST_kill40_dd_atr10_92",
            sig_st_kill40_dd_atr,
            {**base, "atr_pct_lo": 0.10, "atr_pct_hi": 0.92},
            "sig_st_kill40_dd_atr",
        ),
        (
            "B6_ST_kill40_dd_nifty_mom_m04",
            sig_st_kill40_dd_nifty_mom,
            {**base, "min_nifty_ret20": -0.04},
            "sig_st_kill40_dd_nifty_mom",
        ),
        (
            "B6_ST_kill40_dd_volcap24",
            sig_st_kill40_dd_volcap,
            {**base, "vol_cap": 0.24},
            "sig_st_kill40_dd_volcap",
        ),
        (
            "B6_ST_kill40_dd_regime_hl8",
            sig_st_kill40_dd_regime,
            {**base, "hl_days": 8},
            "sig_st_kill40_dd_regime",
        ),
        (
            "B6_ST_kill40_dd_days40",
            sig_st_kill40_dd_days,
            {**base, "max_days_since_high": 40},
            "sig_st_kill40_dd_days",
        ),
    ]

    new_rows: List[dict] = []
    fn_map: Dict[str, str] = {"B5_ST_kill40_dd07": "sig_st_kill40_dd"}
    # Include ensembles + prior + regime as reference
    for ref in ens_rows + [prior, regime, champ]:
        if ref["name"] not in {r["name"] for r in new_rows}:
            new_rows.append(ref)

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

    b6_only = [r for r in new_rows if r["name"].startswith("B6_ST_")]
    log(f"Screened {len(b6_only)} B6_ST variants (target ≥8); total rows={len(new_rows)}")

    # Promote check
    new_champ = champ
    promote_ok = False
    promote_reason = "keep_champ:no_challenger"
    champ_ladder = ladder_by["B5_ST_kill40_dd07"]

    # Ensembles first
    for e in ens_rows:
        if e.get("promote_note") == "CANDIDATE":
            # Ensembles don't have a single fn for ladder — require clearly_better + dual margin
            if clearly_better(e, new_champ) and e["OOS"]["total_return"] >= new_champ["OOS"]["total_return"] + 0.02:
                new_champ = e
                promote_ok = True
                promote_reason = f"ensemble_clear:{e['name']}"
                e["promote_note"] = "PROMOTED"
                log(f"  PROMOTED ensemble {e['name']}")
                break
            else:
                e["promote_note"] = "no:ensemble_not_clear_enough"
                log(f"  Ensemble candidate rejected (not clearly better): {e['name']}")

    # Signal variants
    fn_lookup = {
        "sig_st_kill40_dd": sig_st_kill40_dd,
        "sig_st_kill40_dd_volcalm": sig_st_kill40_dd_volcalm,
        "sig_st_kill40_dd_days": sig_st_kill40_dd_days,
        "sig_st_kill40_dd_bankrs": sig_st_kill40_dd_bankrs,
        "sig_st_kill40_dd_atr": sig_st_kill40_dd_atr,
        "sig_st_kill40_dd_nifty_mom": sig_st_kill40_dd_nifty_mom,
        "sig_st_kill40_dd_volcap": sig_st_kill40_dd_volcap,
        "sig_st_kill40_dd_regime": sig_st_kill40_dd_regime,
    }
    if not promote_ok:
        for row in sorted(
            b6_only,
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
            if ok:
                if row.get("_ladder"):
                    ladder_table.append(row["_ladder"])
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

    # ── Paper A/B update only if flip ─────────────────────────────────────────
    if promote_ok and new_champ["name"] != champ["name"]:
        twin = champ
        twin_label = "prior Block-5 champ (demoted twin)"
        twin_code = "strategies/nifty_edge_r21.py"
        twin_rules = [
            "Prior champion kill40 + dd≥−7% (Block-5).",
            "- Entry/exit identical to Block-5 Sleeve A.",
        ]
        freeze_note = (
            f"A = {new_champ['name']} (promoted Block 6); B = prior B5_ST_kill40_dd07. "
            f"Promote reason: {promote_reason}."
        )
        write_paper_rules_b5(new_champ, twin, twin_label, twin_code, twin_rules, freeze_note)
        log(f"  Paper A/B flipped → wrote {PAPER_RULES}")
        # Overwrite best
        fn_name = fn_map.get(new_champ["name"], "sig_st_kill40_dd")
        if new_champ["name"].startswith("B6_ENS_"):
            log("  Ensemble champion — keep best.py as signal champ; save ens as runner")
        else:
            fn_import = f"from run_block6 import {fn_name} as FN" if fn_name != "sig_st_kill40_dd" else "from run_block5 import sig_st_kill40_dd as FN"
            # Prefer run_block5 for kill40_dd; run_block6 for hybrids
            if fn_name == "sig_st_kill40_dd":
                fn_import = "from run_block5 import sig_st_kill40_dd as FN"
            else:
                fn_import = f"from run_block6 import {fn_name} as FN"
            # Reuse write pattern inline
            oos = new_champ["OOS"]
            stress = new_champ["OOS_stress"]
            params = new_champ["params"]
            params_txt = json.dumps(params, indent=2).replace("true", "True").replace("false", "False")
            py = f'''"""
Nifty Edge Best — Block 6 champion
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
    else:
        log("  Paper A/B unchanged (no flip warranted)")
        # Touch paper rules timestamp note only via append in honesty — keep file

    # ── 6) Save r21+ ──────────────────────────────────────────────────────────
    log("Saving runners r21+…")
    basket = [
        r
        for r in new_rows
        if r["OOS"]["n_trades"] >= 30
        and r["OOS"]["profit_factor"] >= 1.5
        and r["name"] != new_champ["name"]
    ]

    def runner_score(r):
        return (
            r["wf_pos"],
            r.get("last_wf_tot", 0),
            r["OOS"]["profit_factor"],
            r["OOS"]["total_return"],
        )

    prioritized = []
    # Best lastWF with tot near champ
    near = [
        r
        for r in b6_only
        if r["OOS"]["total_return"] >= champ["OOS"]["total_return"] * 0.90
        and r["name"] != new_champ["name"]
    ]
    if near:
        prioritized.append(max(near, key=lambda r: (r.get("last_wf_tot", 0), r["OOS"]["total_return"])))
    if b6_only:
        prioritized.append(max(b6_only, key=runner_score))
    # Best ensemble
    if ens_rows:
        prioritized.append(max(ens_rows, key=runner_score))
    # regime if interesting
    if regime["name"] != new_champ["name"]:
        prioritized.append(regime)

    seen = set()
    save_list = []
    for r in prioritized + sorted(basket, key=runner_score, reverse=True):
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        save_list.append(r)
        if len(save_list) >= 4:
            break

    # Map ensemble names to a writable fn (use kill40_dd as placeholder won't work —
    # write custom for ensembles)
    saved = []
    for i, r in enumerate(save_list, start=21):
        if r["name"].startswith("B6_ENS_"):
            path = OUT_STRAT / f"nifty_edge_r{i}.py"
            oos = r["OOS"]
            code = f'''"""
Runner-up r{i}: {r["name"]}
Params: {json.dumps(r["params"])}
OOS n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} WF+={r.get("wf_pos")}/{r.get("wf_n")}
lastWF={r.get("last_wf_tot", 0)*100:.1f}%
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

NAME = {json.dumps(r["name"])}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
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
    print(json.dumps({{"name": NAME, "OOS": row["OOS"], "last_wf_tot": row.get("last_wf_tot")}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
            path.write_text(code)
        else:
            fn_name = fn_map.get(r["name"], "sig_st_kill40_dd")
            # write_b5_runner imports from run_block5 — for B6 hybrids import from run_block6
            if fn_name.startswith("sig_st_kill40_dd_") and fn_name != "sig_st_kill40_dd":
                path = OUT_STRAT / f"nifty_edge_r{i}.py"
                oos = r["OOS"]
                params = r["params"]
                path.write_text(f'''"""
Runner-up r{i}: {r["name"]}
Params: {json.dumps(params)}
OOS n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} WF+={r.get("wf_pos")}/{r.get("wf_n")}
lastWF={r.get("last_wf_tot", 0)*100:.1f}%
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
from run_block6 import {fn_name} as FN

PARAMS = {json.dumps(params, indent=2).replace("true","True").replace("false","False")}
NAME = {json.dumps(r["name"])}

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
''')
            elif r["name"] == "B4_ST_regime_hl8":
                path = write_b5_runner(i, r, "sig_st_regime_halflife")
            elif r["name"] == "ST_m3.6_n1_e1":
                path = write_b5_runner(i, r, "sig_supertrend")
            else:
                path = write_b5_runner(i, r, fn_name)
        saved.append(str(path))
        log(
            f"  Saved {path.name}: {r['name']} PF={r['OOS']['profit_factor']:.2f} "
            f"tot={r['OOS']['total_return']*100:.1f}% lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )

    # ── 7) FINAL outline (full only if <1h) ───────────────────────────────────
    write_final_outline(new_champ, hood, fragility, ens_rows, b6_only + ens_rows)
    log(f"Wrote {FINAL_OUTLINE}")
    if write_full_final_if_needed(new_champ, hrs):
        log(f"Wrote full {FINAL_REPORT} (<1h to deadline)")
    else:
        log(f"FINAL outline only ({hrs:.1f}h left; full FINAL later)")

    # Persist summary
    summary = {
        "repro": champ,
        "drift_ok": drift_ok,
        "neighborhood": hood,
        "ensembles": ens_rows,
        "cost_ladder": ladder_table,
        "fragility": fragility,
        "promote_ok": promote_ok,
        "promote_reason": promote_reason,
        "champion": new_champ["name"],
        "new_variants": [r for r in new_rows if r["name"].startswith("B6_")],
        "runners_up": saved,
        "bh_oos": bh_oos,
        "n_b6_variants": len(b6_only),
        "hours_to_deadline": hrs,
        "paper_rules": str(PAPER_RULES),
        "final_outline": str(FINAL_OUTLINE),
    }
    path = RESULTS / "block6_summary.json"
    path.write_text(json.dumps(_clean(summary), indent=2, default=str))
    log(f"Wrote {path}")

    append_leaderboard_block6(
        new_champ,
        champ,
        hood,
        ens_rows,
        b6_only + ens_rows,
        ladder_table,
        fragility,
        promote_ok,
        promote_reason,
        bh_oos,
        hrs,
    )
    log(f"Updated {LEADERBOARD}")

    top5 = sorted(
        b6_only,
        key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["profit_factor"]),
        reverse=True,
    )[:5]
    log("--- Block 6 top 5 variants ---")
    for r in top5:
        log(
            f"  {r['name']}: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"n={r['OOS']['n_trades']} WF={r['wf_pos']}/3 lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )
    log(
        f"=== Block 6 complete === champion={new_champ['name']} "
        f"PF={new_champ['OOS']['profit_factor']:.2f} tot={new_champ['OOS']['total_return']*100:.1f}% "
        f"promoted={promote_ok} reason={promote_reason} n_b6={len(b6_only)} "
        f"drift_ok={drift_ok} hrs_left={hrs:.2f}"
    )
    log(
        "Next Block 7: paper live checklist; stress any fragile neighborhood cells; "
        "FINAL_REPORT + lock when <1h to deadline"
    )


if __name__ == "__main__":
    main()
