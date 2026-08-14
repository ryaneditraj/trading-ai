#!/usr/bin/env python3
"""
Block 4 — soft vol-target, entry-only kill floors, regime half-life, paper rules.

Mandatory:
  1) Quick repro of #1
  2) Stress 0.15% RT on #1, ensembles, kill40
  3) Soft vol-target (scale_hi≈1.0) — promote only if tot+lastWF clear #1
     OR risk-adjusted win (tot within ~10% of #1 AND better MDD+lastWF)
  4) Kill-breadth entry-only floors 0.30–0.38 — promote only if tot AND lastWF clear #1
  5) Regime half-life / Nifty EMA50 soft-gate hybrids vs hard kill
  6) Write PAPER_TRADE_RULES.md for #1 and kill40 twin
  7) ≥10 new measured variants; leaderboard/log; save r11+
  8) Skip hourly ORB unless multi-name n≥40

Usage:
  python research/nifty_edge_8h/run_block4.py
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
    attach_rs_and_breadth,
    buy_hold_stats,
    log,
    prepare_symbol,
)
from run_block1b import portfolio_eval, sig_supertrend, supertrend_bands  # noqa: E402
from run_block2 import (  # noqa: E402
    attach_market_to_stocks,
    clearly_better,
    past_deadline,
    run_portfolio_ext,
    sig_st_kill_breadth,
    sig_st_kill_nifty_ema50,
    write_runner_up,
)
from run_block3 import (  # noqa: E402
    kill_breadth_beats_champ,
    portfolio_eval_b3,
    portfolio_eval_blend,
    run_portfolio_b3,
    sig_st_agree_36_while_30,
    sig_st_agree_both_cross,
    sig_st_kill_breadth_force_exit,
    sig_st_or_union,
)

OUT_STRAT = ROOT / "strategies"
PAPER_RULES = Path(__file__).resolve().parent / "PAPER_TRADE_RULES.md"

REF_OOS = {
    "n_trades": 75,
    "profit_factor": 3.90,
    "expectancy": 0.0553,
    "total_return": 1.102,
    "max_dd": -0.148,
    "sharpe": 1.10,
}
REF_LAST_WF = 0.058


# ── Soft vol-target promotion ─────────────────────────────────────────────────
def soft_vol_promote(challenger: dict, champion: dict) -> Tuple[bool, str]:
    """
    Promote soft vol-target only if:
      A) tot AND lastWF both clear #1, OR
      B) clearly better risk-adjusted: tot within ~10% of #1 AND better MDD AND better lastWF
    """
    c, h = challenger["OOS"], champion["OOS"]
    if c["n_trades"] < 30:
        return False, "n<30"
    if challenger.get("wf_pos", 0) < champion.get("wf_pos", 0):
        return False, "wf_worse"
    c_last = float(challenger.get("last_wf_tot", 0))
    h_last = float(champion.get("last_wf_tot", REF_LAST_WF))
    tot_clear = c["total_return"] > h["total_return"]
    last_clear = c_last > h_last
    if tot_clear and last_clear:
        return True, "tot+lastWF_clear"
    # Risk-adjusted path
    tot_ok = c["total_return"] >= h["total_return"] * 0.90
    mdd_better = c["max_dd"] > h["max_dd"]  # less negative
    last_better = c_last > h_last
    if tot_ok and mdd_better and last_better and challenger.get("wf_pos", 0) >= 3:
        return True, "risk_adj_within10pct_better_mdd_lastWF"
    return False, "tradeoff_only"


def attach_regime_features(
    stocks: Dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """Add Nifty EMA half-life / soft-gate features (no look-ahead)."""
    out = {}
    for s, df in stocks.items():
        o = df.copy()
        ni = nifty.reindex(o.index, method="ffill")
        # Already have nifty_ema50 / nifty_above_ema50 from attach_market_to_stocks
        # Soft distance: how far Nifty is above EMA50 (clipped), lag-safe
        ema50 = ni["Close"].ewm(span=50, adjust=False).mean()
        ema20 = ni["Close"].ewm(span=20, adjust=False).mean()
        dist50 = (ni["Close"] / ema50 - 1.0).clip(-0.08, 0.08)
        # Half-life style: exponential decay of days below EMA50 (count consecutive)
        below = (ni["Close"] < ema50).astype(float)
        # days_below: streak length while below (causal)
        streak = np.zeros(len(below))
        vals = below.values
        for i in range(len(vals)):
            if vals[i] > 0.5:
                streak[i] = (streak[i - 1] + 1) if i > 0 else 1
            else:
                streak[i] = 0
        o["nifty_ema50_dist"] = dist50.values
        o["nifty_days_below_ema50"] = streak
        o["nifty_above_ema20"] = (ni["Close"] > ema20).values
        # Soft gate weight proxy stored for signal use
        o["nifty_ema50"] = ema50.values
        out[s] = o
    return out


# ── Signal variants ───────────────────────────────────────────────────────────
def sig_st_kill_entry_only(df, p):
    """Entry-only breadth floor (same as kill_breadth; explicit alias for Block 4)."""
    return sig_st_kill_breadth(df, p)


def sig_st_ema50_soft_gate(df, p):
    """
    Soft EMA50 gate: allow entries when Nifty above EMA50 OR within soft_tol of EMA50
    and days_below < max_days. Harder than no gate, softer than hard kill.
    """
    e, x, side = sig_supertrend(df, p)
    soft_tol = float(p.get("soft_tol", 0.01))  # 1% below EMA50 still ok
    max_days = int(p.get("max_days_below", 5))
    if "nifty_close" in df.columns and "nifty_ema50" in df.columns:
        dist = df["nifty_close"] / df["nifty_ema50"] - 1.0
        days = df["nifty_days_below_ema50"] if "nifty_days_below_ema50" in df.columns else 0
        soft_ok = (dist >= -soft_tol) & (days <= max_days)
        e = e & soft_ok.fillna(False)
    elif "nifty_above_ema50" in df.columns:
        e = e & df["nifty_above_ema50"].fillna(False)
    return e.fillna(False), x.fillna(False), side


def sig_st_ema50_hard_kill(df, p):
    """Hard: no entries when Nifty below EMA50; optionally force exit."""
    e, x, side = sig_supertrend(df, p)
    force = bool(p.get("force_exit", False))
    if "nifty_above_ema50" in df.columns:
        above = df["nifty_above_ema50"].fillna(False)
        e = e & above
        if force:
            x = x | (~above)
    return e.fillna(False), x.fillna(False), side


def sig_st_regime_halflife(df, p):
    """
    Regime half-life: block entries only after Nifty has been below EMA50 for
    >= hl_days (gives short dips a pass). Optional soft exit after 2*hl_days.
    """
    e, x, side = sig_supertrend(df, p)
    hl = int(p.get("hl_days", 8))
    soft_exit = bool(p.get("soft_exit", False))
    if "nifty_days_below_ema50" in df.columns:
        days = df["nifty_days_below_ema50"]
        e = e & (days < hl)
        if soft_exit:
            x = x | (days >= 2 * hl)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_ema50_soft(df, p):
    """Hybrid: entry-only breadth floor + EMA50 soft gate."""
    e, x, side = sig_st_kill_breadth(df, p)
    soft_tol = float(p.get("soft_tol", 0.015))
    max_days = int(p.get("max_days_below", 8))
    if "nifty_close" in df.columns and "nifty_ema50" in df.columns:
        dist = df["nifty_close"] / df["nifty_ema50"] - 1.0
        days = (
            df["nifty_days_below_ema50"]
            if "nifty_days_below_ema50" in df.columns
            else pd.Series(0.0, index=df.index)
        )
        soft_ok = (dist >= -soft_tol) & (days <= max_days)
        e = e & soft_ok.fillna(False)
    return e.fillna(False), x.fillna(False), side


def sig_st_breadth_halflife(df, p):
    """Entry-only kill when breadth < floor for >= hl consecutive days."""
    e, x, side = sig_supertrend(df, p)
    floor = float(p.get("breadth_floor", 0.40))
    hl = int(p.get("hl_days", 5))
    if "breadth50" in df.columns:
        weak = (df["breadth50"] < floor).astype(float)
        streak = np.zeros(len(weak))
        vals = weak.values
        for i in range(len(vals)):
            if vals[i] > 0.5:
                streak[i] = (streak[i - 1] + 1) if i > 0 else 1
            else:
                streak[i] = 0
        days = pd.Series(streak, index=df.index)
        e = e & (days < hl)
    return e.fillna(False), x.fillna(False), side


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def stress_row(name: str, data, fn, params, oos_start, use_b3: bool = False) -> dict:
    """Run OOS at 0.08% and 0.15% RT; return compact stress dict."""
    if use_b3:
        o08 = run_portfolio_b3(data, fn, params, start_date=oos_start, rt_cost=RT)
        o15 = run_portfolio_b3(data, fn, params, start_date=oos_start, rt_cost=RT_STRESS)
    else:
        o08 = run_portfolio_ext(data, fn, params, start_date=oos_start, rt_cost=RT)
        o15 = run_portfolio_ext(data, fn, params, start_date=oos_start, rt_cost=RT_STRESS)
    return {
        "name": name,
        "n": o08["n_trades"],
        "pf_08": o08["profit_factor"],
        "tot_08": o08["total_return"],
        "mdd_08": o08["max_dd"],
        "pf_15": o15["profit_factor"],
        "tot_15": o15["total_return"],
        "mdd_15": o15["max_dd"],
        "delta_tot_pp": (o15["total_return"] - o08["total_return"]) * 100,
    }


def write_paper_trade_rules(champ: dict, kill40: dict) -> None:
    """Exact paper-trade rules for #1 and kill40 twin."""
    o = champ["OOS"]
    k = kill40["OOS"] if kill40 else {}
    lines = [
        "# Paper Trade Rules — Nifty Edge 8h",
        "",
        f"**Written:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} (Block 4)",
        "**Status:** Research paper sleeve — not live capital. No look-ahead.",
        "",
        "---",
        "",
        "## Universe & execution",
        "",
        "| Item | Rule |",
        "|------|------|",
        "| Universe | 20 NSE large-caps (same as `UNIVERSE` in `run_block1.py`) |",
        "| Index filter | ^NSEI daily (Yahoo `^NSEI`) |",
        "| Max positions | 5 equal-risk slots (slot ≈ 20% equity) |",
        "| Rank | Free slots by Close/EMA200 − 1 (highest first) |",
        "| Entry fill | Next session **open** after signal bar close |",
        "| Exit fill | Signal bar **close** |",
        "| Costs (report both) | **0.08% RT** primary; **0.15% RT** stress |",
        "| Side | Long-only |",
        "| Cadence | Daily bars only for these sleeves |",
        "",
        "### Universe tickers",
        "",
        "```",
        ", ".join(UNIVERSE),
        "```",
        "",
        "---",
        "",
        "## Sleeve A — Champion `#1` (paper primary)",
        "",
        f"**ID:** `{champ['name']}`  ",
        "**Code:** `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine`  ",
        f"**OOS ref:** n={o['n_trades']} PF={o['profit_factor']:.2f} tot={fmt_pct(o['total_return'])} "
        f"MDD={fmt_pct(o['max_dd'])} Sharpe={o['sharpe']:.2f} "
        f"WF={champ.get('wf_pos')}/{champ.get('wf_n')} lastWF={fmt_pct(champ.get('last_wf_tot', REF_LAST_WF))}",
        "",
        "### Exact entry",
        "",
        "1. Compute ATR(14), HL2 = (H+L)/2.",
        "2. Supertrend lower band: basic = HL2 − **3.6** × ATR; ratchet up while prior close > prior band.",
        "3. **Entry signal** (bar close): Close crosses **above** final lower band",
        "   AND Close > stock EMA200",
        "   AND Nifty bull: Close_Nifty > EMA200_Nifty **OR** Close_Nifty > prior 55d Nifty high.",
        "4. Fill: next open. Size: min(cash, equity × 1/5).",
        "",
        "### Exact exit",
        "",
        "1. Close < final Supertrend lower band → exit at that bar close.",
        "2. No breadth/vol kill on this sleeve — trail only.",
        "",
        "### Sizing",
        "",
        "- Equal slot; no vol-scale on #1 paper primary.",
        "- Do not pyramid. One position per name.",
        "",
        "---",
        "",
        "## Sleeve B — Kill-breadth40 twin (paper twin / near-miss)",
        "",
    ]
    if kill40:
        lines += [
            f"**ID:** `{kill40['name']}`  ",
            "**Code:** `strategies/nifty_edge_r4.py` / `r8.py` (and Block-4 r11+ if refreshed)  ",
            f"**OOS ref:** n={k['n_trades']} PF={k['profit_factor']:.2f} tot={fmt_pct(k['total_return'])} "
            f"MDD={fmt_pct(k['max_dd'])} Sharpe={k.get('sharpe', 0):.2f} "
            f"WF={kill40.get('wf_pos')}/{kill40.get('wf_n')} lastWF={fmt_pct(kill40.get('last_wf_tot', 0))}",
            "",
            "### Exact entry",
            "",
            "Same as Sleeve A **plus** entry-only filter:",
            "- Breadth50 (% of universe Close > EMA50) ≥ **0.40** on signal bar.",
            "- If breadth < 0.40: **skip new entries**; do **not** force-exit open positions.",
            "",
            "### Exact exit",
            "",
            "Same Supertrend trail as Sleeve A (no hard breadth exit).",
            "",
            "### Why twin",
            "",
            "- Slightly lower OOS tot vs #1 but stronger last WF in Blocks 2–3.",
            "- Paper both in parallel; promote twin only if live/paper last chunk + tot clear #1.",
            "",
        ]
    else:
        lines += ["*(kill40 stats missing — regenerate via Block 4 run)*", ""]

    lines += [
        "---",
        "",
        "## Daily checklist",
        "",
        "1. Update daily OHLCV for universe + ^NSEI.",
        "2. Recompute ATR trail, EMA200, Nifty bull, breadth50.",
        "3. Process exits first (trail), then entries (rank + slots).",
        "4. Log fills with RT cost assumption (0.08% primary).",
        "5. Weekly: compare sleeve A vs B equity and last-chunk PnL.",
        "",
        "## Honesty / constraints",
        "",
        "- Single-symbol Pine ≠ 5-slot basket — Pine is illustrative only.",
        "- mult=3.6 is a local PF peak; track mult=3.0 as conservative sleeve.",
        "- No look-ahead: bands use prior close ratchet; entry next open.",
        "- Costs: always report **0.08%** and **0.15%** RT when quoting results.",
        "",
    ]
    PAPER_RULES.write_text("\n".join(lines))


def append_leaderboard_block4(
    champ: dict,
    repro: dict,
    rows: List[dict],
    stress_table: List[dict],
    kill_sweep: List[dict],
    soft_vol_notes: List[str],
    promoted: bool,
    promote_reason: str,
    bh: dict,
) -> None:
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 4"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    r = repro["OOS"]
    lines = [
        "",
        "## Block 4 — Soft vol-target, entry-only kill, regime half-life, paper rules",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**#1 still leads:** {'YES' if not promoted else 'NO — new champion promoted'}",
        f"**Promote reason:** {promote_reason or 'none'}",
        "",
        "### Reproduced #1 (ST_m3.6_n1_e1)",
        "",
        "| Metric | Block1–3 ref | Block4 | Drift |",
        "|--------|-------------:|-------:|------:|",
        f"| n | {REF_OOS['n_trades']} | {r['n_trades']} | {r['n_trades']-REF_OOS['n_trades']:+d} |",
        f"| PF | {REF_OOS['profit_factor']:.2f} | {r['profit_factor']:.2f} | {r['profit_factor']-REF_OOS['profit_factor']:+.2f} |",
        f"| Tot | {REF_OOS['total_return']*100:.1f}% | {r['total_return']*100:.1f}% | {(r['total_return']-REF_OOS['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_OOS['max_dd']*100:.1f}% | {r['max_dd']*100:.1f}% | {(r['max_dd']-REF_OOS['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_OOS['sharpe']:.2f} | {r['sharpe']:.2f} | {r['sharpe']-REF_OOS['sharpe']:+.2f} |",
        f"| Last WF | 5.8% | {repro.get('last_wf_tot', 0)*100:.1f}% | — |",
        "",
        "### Stress 0.15% RT (#1, ensembles, kill40)",
        "",
        "| Name | n | PF@0.08 | Tot@0.08 | PF@0.15 | Tot@0.15 | ΔTot pp |",
        "|------|--:|--------:|---------:|--------:|---------:|--------:|",
    ]
    for s in stress_table:
        lines.append(
            f"| {s['name']} | {s['n']} | {s['pf_08']:.2f} | {s['tot_08']*100:.1f}% | "
            f"{s['pf_15']:.2f} | {s['tot_15']*100:.1f}% | {s['delta_tot_pp']:+.1f} |"
        )

    lines += [
        "",
        "### Kill-breadth entry-only floors 0.30–0.38 (promote = tot AND lastWF > #1)",
        "",
        "| Floor | n | PF | Tot | MDD | WF+ | LastWF | Beat? |",
        "|------:|--:|---:|----:|----:|----:|-------:|:-----:|",
    ]
    for row in kill_sweep:
        oos = row["OOS"]
        beat = kill_breadth_beats_champ(row, repro)
        lines.append(
            f"| {row['params'].get('breadth_floor', '?')} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['total_return']*100:.1f}% | {oos['max_dd']*100:.1f}% | "
            f"{row['wf_pos']}/{row['wf_n']} | {row['last_wf_tot']*100:.1f}% | {'YES' if beat else 'no'} |"
        )

    lines += [
        "",
        "### Soft vol-target notes",
        "",
    ]
    for note in soft_vol_notes:
        lines.append(f"- {note}")

    top = sorted(
        rows,
        key=lambda rr: (
            rr.get("wf_pos", 0),
            rr["OOS"]["profit_factor"],
            rr["OOS"]["total_return"],
            rr.get("last_wf_tot", 0),
        ),
        reverse=True,
    )[:25]
    lines += [
        "",
        "### Block 4 new variants (top by WF+ / PF / tot)",
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
        "",
        f"**Champion after Block 4:** `{champ['name']}` — OOS PF={o['profit_factor']:.2f} "
        f"tot={o['total_return']*100:.1f}% n={o['n_trades']} WF={champ['wf_pos']}/{champ['wf_n']} "
        f"lastWF={champ.get('last_wf_tot', 0)*100:.1f}%",
        f"**B&H ^NSEI OOS:** tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "",
        "### Honesty",
        "- Soft vol-target (scale_hi≈1.0): promote only tot+lastWF clear OR risk-adj within ~10% tot + better MDD+lastWF.",
        "- Kill entry-only 0.30–0.38: same dual-clear as Block 3.",
        "- Regime half-life / EMA50 soft-gate documented vs hard kill; tradeoff-only → runner-up.",
        "- Hourly ORB skipped (Block 4 mandate unless multi-name n≥40).",
        "- Costs 0.08% / 0.15% RT. No look-ahead. No fake futures.",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in ("trades", "trade_rets", "equity")}
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return str(obj)
    return obj


def write_b4_runner(idx: int, row: dict, fn_name: str) -> Path:
    path = OUT_STRAT / f"nifty_edge_r{idx}.py"
    oos = row["OOS"]
    params = row["params"]
    needs_b3 = any(
        k in params
        for k in ("vol_target", "vol_scale_hi", "vol_scale_lo", "sector_cap")
    )
    if fn_name == "sig_supertrend":
        fn_import = "from run_block1b import sig_supertrend as FN"
    elif fn_name in ("sig_st_kill_breadth", "sig_st_kill_entry_only"):
        fn_import = "from run_block2 import sig_st_kill_breadth as FN"
    elif fn_name == "sig_st_kill_nifty_ema50":
        fn_import = "from run_block2 import sig_st_kill_nifty_ema50 as FN"
    elif fn_name == "sig_st_kill_breadth_force_exit":
        fn_import = "from run_block3 import sig_st_kill_breadth_force_exit as FN"
    else:
        fn_import = f"from run_block4 import {fn_name} as FN"

    runner_fn = "run_portfolio_b3" if needs_b3 else "run_portfolio_ext"
    port_import = (
        "from run_block3 import run_portfolio_b3"
        if needs_b3
        else "from run_block2 import run_portfolio_ext"
    )
    needs_regime = fn_name in (
        "sig_st_ema50_soft_gate",
        "sig_st_ema50_hard_kill",
        "sig_st_regime_halflife",
        "sig_st_kill40_ema50_soft",
        "sig_st_breadth_halflife",
    )
    regime_import = "from run_block4 import attach_regime_features\n" if needs_regime else ""
    regime_call = "    data = attach_regime_features(data, nifty)\n" if needs_regime else ""

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
from run_block2 import attach_market_to_stocks
{regime_import}{port_import}
{fn_import}

PARAMS = {json.dumps(params, indent=2).replace("true","True").replace("false","False")}
NAME = {json.dumps(row["name"])}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
{regime_call}    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    oos = {runner_fn}(data, FN, PARAMS, start_date=oos_start)
    print(json.dumps({{"name": NAME, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
    path.write_text(code)
    return path


def main():
    if past_deadline():
        log("DEADLINE PASSED — Block 4 should not invent; run FINAL synthesis instead")
        print("PAST_DEADLINE")
        return

    log("=== Block 4 start ===")
    log("Loading Nifty + Bank + 20 stocks…")
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)

    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    bh_oos = buy_hold_stats(nifty.loc[nifty.index >= oos_start], "OOS")
    log(f"Buy&hold ^NSEI OOS: tot={bh_oos['total_return']*100:.1f}% Sharpe={bh_oos['sharpe']:.2f}")

    # ── 1) Reproduce #1 ───────────────────────────────────────────────────────
    log("Reproducing #1 ST_m3.6_n1_e1…")
    champ_params = {"mult": 3.6, "use_nifty": True, "use_ema200": True}
    champ = portfolio_eval("ST_m3.6_n1_e1", data, sig_supertrend, champ_params, oos_start)
    champ["last_wf_tot"] = champ["wf"][-1]["total_return"] if champ["wf"] else 0.0
    o = champ["OOS"]
    log(
        f"  REPRO n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} "
        f"WF={champ['wf_pos']}/{champ['wf_n']} lastWF={champ['last_wf_tot']*100:.1f}% "
        f"drift_PF={o['profit_factor']-REF_OOS['profit_factor']:+.2f}"
    )

    new_rows: List[dict] = []
    fn_map: Dict[str, str] = {}
    kill_sweep: List[dict] = []
    soft_vol_notes: List[str] = []
    stress_table: List[dict] = []

    # ── 2) Stress 0.15% on #1, ensembles, kill40 ──────────────────────────────
    log("Stress 0.15% RT on #1, ensembles, kill40…")
    stress_specs: List[Tuple[str, Callable, dict, bool]] = [
        ("ST_m3.6_n1_e1", sig_supertrend, champ_params, False),
        ("B2_ST_kill_breadth40_m3.6", sig_st_kill_breadth,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.40}, False),
        ("B3_ENS_agree_36_while_30", sig_st_agree_36_while_30,
         {"use_nifty": True, "use_ema200": True}, True),
        ("B3_ENS_or_union_loose_exit", sig_st_or_union,
         {"use_nifty": True, "use_ema200": True}, True),
        ("B3_ENS_agree_both_look5", sig_st_agree_both_cross,
         {"use_nifty": True, "use_ema200": True, "agree_look": 5}, True),
    ]
    for name, fn, params, use_b3 in stress_specs:
        try:
            s = stress_row(name, data, fn, params, oos_start, use_b3=use_b3)
            stress_table.append(s)
            log(
                f"  STRESS {name}: PF {s['pf_08']:.2f}→{s['pf_15']:.2f} "
                f"tot {s['tot_08']*100:.1f}%→{s['tot_15']*100:.1f}% (Δ{s['delta_tot_pp']:+.1f}pp)"
            )
        except Exception as ex:
            log(f"  FAIL stress {name}: {ex}")

    # Equal-risk blend stress
    try:
        base = {"use_nifty": True, "use_ema200": True, "heat_cap": 0.5, "max_positions": 3}
        from run_block3 import run_equal_risk_blend
        pa, pb = {**base, "mult": 3.0}, {**base, "mult": 3.6}
        o08 = run_equal_risk_blend(data, sig_supertrend, pa, sig_supertrend, pb, start_date=oos_start, rt_cost=RT)
        o15 = run_equal_risk_blend(data, sig_supertrend, pa, sig_supertrend, pb, start_date=oos_start, rt_cost=RT_STRESS)
        s = {
            "name": "B3_ENS_equal_risk_3.0_3.6",
            "n": o08["n_trades"],
            "pf_08": o08["profit_factor"],
            "tot_08": o08["total_return"],
            "mdd_08": o08["max_dd"],
            "pf_15": o15["profit_factor"],
            "tot_15": o15["total_return"],
            "mdd_15": o15["max_dd"],
            "delta_tot_pp": (o15["total_return"] - o08["total_return"]) * 100,
        }
        stress_table.append(s)
        log(
            f"  STRESS {s['name']}: PF {s['pf_08']:.2f}→{s['pf_15']:.2f} "
            f"tot {s['tot_08']*100:.1f}%→{s['tot_15']*100:.1f}% (Δ{s['delta_tot_pp']:+.1f}pp)"
        )
    except Exception as ex:
        log(f"  FAIL stress equal_risk: {ex}")

    # ── 3) Soft vol-target (scale_hi near 1.0) ────────────────────────────────
    log("Soft vol-target (scale_hi≈1.0)…")
    soft_vol_variants: List[Tuple[str, dict]] = [
        ("B4_ST_softvol18_shi1.0_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "vol_target": 0.18, "vol_scale_lo": 0.70, "vol_scale_hi": 1.0,
        }),
        ("B4_ST_softvol20_shi1.0_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "vol_target": 0.20, "vol_scale_lo": 0.75, "vol_scale_hi": 1.0,
        }),
        ("B4_ST_softvol16_shi1.05_m3.6", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "vol_target": 0.16, "vol_scale_lo": 0.70, "vol_scale_hi": 1.05,
        }),
        ("B4_ST_softvol18_shi1.0_m3.0", {
            "mult": 3.0, "use_nifty": True, "use_ema200": True,
            "vol_target": 0.18, "vol_scale_lo": 0.70, "vol_scale_hi": 1.0,
        }),
        ("B4_ST_kill40_softvol18_shi1.0", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "breadth_floor": 0.40, "vol_target": 0.18,
            "vol_scale_lo": 0.70, "vol_scale_hi": 1.0,
        }),
        ("B4_ST_softvol22_shi1.0_floor0.85", {
            "mult": 3.6, "use_nifty": True, "use_ema200": True,
            "vol_target": 0.22, "vol_scale_lo": 0.85, "vol_scale_hi": 1.0,
        }),
    ]
    soft_vol_rows: List[dict] = []
    for name, params in soft_vol_variants:
        try:
            fn = sig_st_kill_breadth if "breadth_floor" in params else sig_supertrend
            row = portfolio_eval_b3(name, data, fn, params, oos_start)
            new_rows.append(row)
            soft_vol_rows.append(row)
            fn_map[name] = fn.__name__
            ok, reason = soft_vol_promote(row, champ)
            note = (
                f"{name}: tot={row['OOS']['total_return']*100:.1f}% "
                f"MDD={row['OOS']['max_dd']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
                f"vs #1 tot={champ['OOS']['total_return']*100:.1f}% MDD={champ['OOS']['max_dd']*100:.1f}% "
                f"lastWF={champ['last_wf_tot']*100:.1f}% → promote={ok} ({reason})"
            )
            soft_vol_notes.append(note)
            log(f"  {note}")
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")
            soft_vol_notes.append(f"{name}: FAIL {ex}")

    # ── 4) Kill-breadth entry-only floors 0.30–0.38 ───────────────────────────
    log("Kill-breadth entry-only floors 0.30–0.38…")
    floors = [0.30, 0.32, 0.34, 0.36, 0.38]
    for fl in floors:
        name = f"B4_ST_kill_entry_br{int(fl*100)}_m3.6"
        params = {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": fl}
        try:
            row = portfolio_eval(name, data, sig_st_kill_entry_only, params, oos_start)
            row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            kill_sweep.append(row)
            new_rows.append(row)
            fn_map[name] = "sig_st_kill_entry_only"
            beat = kill_breadth_beats_champ(row, champ)
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
                f"beat={('YES' if beat else 'no')}"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    # Reference kill40 for paper rules
    kill40 = portfolio_eval(
        "B4_REF_kill_breadth40_m3.6",
        data,
        sig_st_kill_breadth,
        {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.40},
        oos_start,
    )
    kill40["last_wf_tot"] = kill40["wf"][-1]["total_return"] if kill40["wf"] else 0.0

    # ── 5) Regime half-life / EMA50 soft-gate hybrids ─────────────────────────
    log("Regime half-life / Nifty EMA50 soft-gate hybrids…")
    regime_variants: List[Tuple[str, Callable, dict, str]] = [
        ("B4_ST_ema50_soft_tol1_d5", sig_st_ema50_soft_gate,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "soft_tol": 0.01, "max_days_below": 5},
         "sig_st_ema50_soft_gate"),
        ("B4_ST_ema50_soft_tol15_d8", sig_st_ema50_soft_gate,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "soft_tol": 0.015, "max_days_below": 8},
         "sig_st_ema50_soft_gate"),
        ("B4_ST_ema50_hard_entry", sig_st_ema50_hard_kill,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "force_exit": False},
         "sig_st_ema50_hard_kill"),
        ("B4_ST_ema50_hard_forcexit", sig_st_ema50_hard_kill,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "force_exit": True},
         "sig_st_ema50_hard_kill"),
        ("B4_ST_regime_hl8", sig_st_regime_halflife,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "hl_days": 8, "soft_exit": False},
         "sig_st_regime_halflife"),
        ("B4_ST_regime_hl5_softexit", sig_st_regime_halflife,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "hl_days": 5, "soft_exit": True},
         "sig_st_regime_halflife"),
        ("B4_ST_regime_hl12", sig_st_regime_halflife,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "hl_days": 12, "soft_exit": False},
         "sig_st_regime_halflife"),
        ("B4_ST_kill40_ema50_soft", sig_st_kill40_ema50_soft,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.40,
          "soft_tol": 0.015, "max_days_below": 8},
         "sig_st_kill40_ema50_soft"),
        ("B4_ST_breadth_hl5_fl40", sig_st_breadth_halflife,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.40, "hl_days": 5},
         "sig_st_breadth_halflife"),
        ("B4_ST_breadth_hl8_fl35", sig_st_breadth_halflife,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.35, "hl_days": 8},
         "sig_st_breadth_halflife"),
        ("B4_ST_kill_nifty_ema50", sig_st_kill_nifty_ema50,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True},
         "sig_st_kill_nifty_ema50"),
        ("B4_ST_killhard_br38_m3.6", sig_st_kill_breadth_force_exit,
         {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.38},
         "sig_st_kill_breadth_force_exit"),
    ]
    for name, fn, params, fn_name in regime_variants:
        try:
            if fn_name == "sig_st_kill_breadth_force_exit":
                row = portfolio_eval(name, data, fn, params, oos_start)
                row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            elif fn_name == "sig_st_kill_nifty_ema50":
                row = portfolio_eval(name, data, fn, params, oos_start)
                row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            else:
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

    # Skip hourly ORB (mandate)
    log("Hourly ORB: SKIPPED (Block 4 — only if multi-name n≥40; not attempted)")

    log(f"Screened {len(new_rows)} Block-4 variants (target ≥10)")

    # ── Promotion ─────────────────────────────────────────────────────────────
    promoted = False
    promote_reason = ""
    new_champ = champ

    for row in kill_sweep:
        if kill_breadth_beats_champ(row, champ):
            log(f"  KILL-ENTRY PROMOTE: {row['name']}")
            new_champ = row
            promoted = True
            promote_reason = f"kill_entry_tot+lastWF:{row['name']}"
            break
    if not promoted and not any(kill_breadth_beats_champ(r, champ) for r in kill_sweep):
        log("  Kill entry-only 0.30–0.38: none cleared tot AND lastWF vs #1")

    if not promoted:
        for row in soft_vol_rows:
            ok, reason = soft_vol_promote(row, champ)
            if ok:
                log(f"  SOFT-VOL PROMOTE: {row['name']} ({reason})")
                new_champ = row
                promoted = True
                promote_reason = f"soft_vol:{reason}:{row['name']}"
                break
            else:
                # tradeoff documented; will save as runner-up later
                pass
        if not promoted:
            log("  Soft vol-target: no promote (tradeoff-only → runners-up)")

    if not promoted:
        contenders = [
            r for r in new_rows
            if r["OOS"]["n_trades"] >= 30
            and r["OOS"]["profit_factor"] >= 1.3
            and r["name"] != champ["name"]
            and "softvol" not in r["name"]  # softvol has its own rule
            and "kill_entry" not in r["name"]
        ]
        contenders = sorted(
            contenders,
            key=lambda r: (r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"]),
            reverse=True,
        )
        for c in contenders:
            if clearly_better(c, champ):
                log(f"  BEAT: {c['name']} clearly better")
                new_champ = c
                promoted = True
                promote_reason = f"clearly_better:{c['name']}"
                break
        if not promoted:
            log("  #1 ST_m3.6_n1_e1 REMAINS best")

    # ── Save runners r11+ ─────────────────────────────────────────────────────
    # Prefer: best soft-vol tradeoff, kill40, best regime hybrid, best kill-entry near-miss
    basket = [
        r for r in new_rows
        if r["OOS"]["n_trades"] >= 30
        and r["OOS"]["profit_factor"] >= 1.5
        and r["name"] != new_champ["name"]
    ]
    # Score: prefer high lastWF + tot near champ + better MDD
    def runner_score(r):
        return (
            r["wf_pos"],
            r.get("last_wf_tot", 0),
            r["OOS"]["profit_factor"],
            r["OOS"]["total_return"],
            r["OOS"]["max_dd"],  # less negative better when sorted reverse... careful
        )

    basket = sorted(basket, key=runner_score, reverse=True)

    # Ensure soft-vol best tradeoff and kill40-like are included
    soft_best = None
    if soft_vol_rows:
        soft_best = max(
            soft_vol_rows,
            key=lambda r: (
                r["OOS"]["total_return"] / max(abs(r["OOS"]["max_dd"]), 1e-6),
                r.get("last_wf_tot", 0),
            ),
        )
    prioritized = []
    if soft_best and soft_best["name"] != new_champ["name"]:
        prioritized.append(soft_best)
    # Best kill entry near-miss by lastWF among those with tot >= 0.95 * champ
    near_kill = [
        r for r in kill_sweep
        if r["OOS"]["total_return"] >= champ["OOS"]["total_return"] * 0.90
    ]
    if near_kill:
        prioritized.append(max(near_kill, key=lambda r: (r.get("last_wf_tot", 0), r["OOS"]["total_return"])))
    # Best regime by lastWF with tot decent
    regime_rows = [r for r in new_rows if r["name"].startswith("B4_ST_regime") or "ema50" in r["name"] or "breadth_hl" in r["name"] or "kill40_ema" in r["name"]]
    if regime_rows:
        prioritized.append(
            max(regime_rows, key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["total_return"]))
        )

    seen = set()
    save_list = []
    for r in prioritized + basket:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        save_list.append(r)
        if len(save_list) >= 4:
            break

    saved = []
    for i, r in enumerate(save_list, start=11):
        fn_name = fn_map.get(r["name"], "sig_supertrend")
        path = write_b4_runner(i, r, fn_name)
        saved.append(str(path))
        log(f"  Saved {path.name}: {r['name']} PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}%")

    if promoted:
        log("  Overwriting nifty_edge_best.py with new champion")
        oos = new_champ["OOS"]
        stress = new_champ["OOS_stress"]
        params = new_champ["params"]
        fn_name = fn_map.get(new_champ["name"], "sig_supertrend")
        if fn_name == "sig_supertrend":
            fn_import = "from run_block1b import sig_supertrend as FN"
            port = "from run_block3 import run_portfolio_b3 as RUN"
        elif fn_name in ("sig_st_kill_breadth", "sig_st_kill_entry_only"):
            fn_import = "from run_block2 import sig_st_kill_breadth as FN"
            port = "from run_block2 import run_portfolio_ext as RUN"
        else:
            fn_import = f"from run_block4 import {fn_name} as FN"
            port = "from run_block2 import run_portfolio_ext as RUN"
        py = f'''"""
Nifty Edge Best — Block 4 champion
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
from run_block2 import attach_market_to_stocks
from run_block4 import attach_regime_features
{port}
{fn_import}

PARAMS = {json.dumps(params, indent=2).replace("true","True").replace("false","False")}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    data = attach_regime_features(data, nifty)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos = RUN(data, FN, PARAMS, start_date=oos_ref.index[0])
    print(json.dumps({{"name": {json.dumps(new_champ["name"])}, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
        (OUT_STRAT / "nifty_edge_best.py").write_text(py)
        log(f"  Wrote {OUT_STRAT / 'nifty_edge_best.py'}")
    else:
        log("  Kept strategies/nifty_edge_best.py unchanged (Block1 #1 still leads)")

    # ── Paper trade rules ─────────────────────────────────────────────────────
    write_paper_trade_rules(champ, kill40)
    log(f"Wrote {PAPER_RULES}")

    # Persist
    summary = {
        "repro": champ,
        "new_variants": new_rows,
        "kill_sweep": kill_sweep,
        "stress_table": stress_table,
        "soft_vol_notes": soft_vol_notes,
        "promoted": promoted,
        "promote_reason": promote_reason,
        "champion": new_champ["name"],
        "runners_up": saved,
        "bh_oos": bh_oos,
        "n_variants": len(new_rows),
        "paper_rules": str(PAPER_RULES),
    }
    path = RESULTS / "block4_summary.json"
    path.write_text(json.dumps(_clean(summary), indent=2, default=str))
    log(f"Wrote {path}")

    append_leaderboard_block4(
        new_champ, champ, new_rows, stress_table, kill_sweep,
        soft_vol_notes, promoted, promote_reason, bh_oos,
    )
    log(f"Updated {LEADERBOARD}")

    top5 = sorted(
        new_rows,
        key=lambda r: (r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"]),
        reverse=True,
    )[:5]
    log("--- Block 4 top 5 ---")
    for r in top5:
        log(
            f"  {r['name']}: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"n={r['OOS']['n_trades']} WF={r['wf_pos']}/3 lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )
    log(
        f"=== Block 4 complete === champion={new_champ['name']} "
        f"PF={new_champ['OOS']['profit_factor']:.2f} tot={new_champ['OOS']['total_return']*100:.1f}% "
        f"promoted={promoted} n_variants={len(new_rows)}"
    )
    log(
        "Next Block 5: freeze paper A/B; attack last-WF chunk with causal features only; "
        "cost ladder 0.10/0.12/0.20; optional FII/OI proxy if clean; no hourly unless n≥40"
    )


if __name__ == "__main__":
    main()
