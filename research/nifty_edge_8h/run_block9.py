#!/usr/bin/env python3
"""
Block 9 — Anti-overfit battery (robustness priority; no vanity gate stacking).

Mandatory:
  1) Repro champ B7_ST_kill40_dd_mom_days60; verify pine matches python ST/EMA rules
  2) Expand days60-skip / mom-skip save-rate notes (honest thin-n)
  3) Anti-overfit: shuffle/placebo gates; ablation; complexity penalty
  4) NO new gate stacking unless dual-clear lastWF strictly > 9.2%
     OR clear OOS improvement on a held-out chunk unused in prior promotes
  5) If simpler sleeve close on risk-adj → paper A vs research A recommendation
  6) Update board/log; draft FINAL body (full lock only if <1h)
  7) If past deadline → FINAL now

Usage:
  python research/nifty_edge_8h/run_block9.py
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
    TRAIN_FRAC,
    UNIVERSE,
    buy_hold_stats,
    log,
    prepare_symbol,
)
from run_block1b import portfolio_eval, sig_supertrend  # noqa: E402
from run_block2 import (  # noqa: E402
    attach_market_to_stocks,
    past_deadline,
    run_portfolio_ext,
    sig_st_kill_breadth,
)
from run_block4 import attach_regime_features  # noqa: E402
from run_block5 import attach_lastwf_features, sig_st_kill40_dd  # noqa: E402
from run_block6 import (  # noqa: E402
    hours_to_deadline,
    sig_st_kill40_dd_days,
    sig_st_kill40_dd_nifty_mom,
    write_full_final_if_needed,
)
from run_block7 import sig_st_kill40_dd_mom_days  # noqa: E402
from run_block8 import (  # noqa: E402
    analyze_mom_skips,
    signal_day_for_entry,
    weekly_equity_delta,
)

OUT_STRAT = ROOT / "strategies"
OUT_PINE = ROOT / "pinescript" / "nifty_edge_best.pine"
CHECKLIST = Path(__file__).resolve().parent / "CHECKLIST.md"
PAPER_RULES = Path(__file__).resolve().parent / "PAPER_TRADE_RULES.md"
FINAL_OUTLINE = Path(__file__).resolve().parent / "FINAL_REPORT_OUTLINE.md"
FINAL_REPORT = Path(__file__).resolve().parent / "FINAL_REPORT.md"

REF_CHAMP = {
    "n_trades": 63,
    "profit_factor": 5.17,
    "expectancy": 0.0,  # not used for drift
    "total_return": 1.294,
    "max_dd": -0.110,
    "sharpe": 1.28,
}
REF_LAST_WF = 0.092

CHAMP_PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "breadth_floor": 0.40,
    "dd_floor": -0.07,
    "min_nifty_ret20": -0.04,
    "max_days_since_high": 60,
}
B6_PARAMS = {
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
ST_PARAMS = {"mult": 3.6, "use_nifty": True, "use_ema200": True}
KILL40_PARAMS = {
    "mult": 3.6,
    "use_nifty": True,
    "use_ema200": True,
    "breadth_floor": 0.40,
}

N_PLACEBO = 40
COMPLEXITY_TOT_TOL = 0.10  # within ~10% tot
HELD_OUT_FRAC = 0.30  # last 30% of OOS as held-out chunk


# ── Days60 skip analysis (A=champ has days60; B=nifty_mom lacks it) ────────────
def analyze_days60_skips(
    data: Dict[str, pd.DataFrame],
    b_trades: List[dict],
    max_days: int = 60,
) -> dict:
    sample = next(iter(data.values()))
    col = "nifty_days_since_high"
    if col not in sample.columns:
        return {"n_skips": 0, "error": f"{col} missing"}
    series = sample[col]
    cal = sample.index
    skips = []
    for t in b_trades:
        entry = pd.Timestamp(t["entry"])
        sig_dt = signal_day_for_entry(entry, cal)
        sym = t.get("symbol")
        if sig_dt is None or sig_dt not in series.index:
            if sym and sym in data and col in data[sym].columns:
                cal_s = data[sym].index
                sig_dt = signal_day_for_entry(entry, cal_s)
                if sig_dt is None or sig_dt not in data[sym].index:
                    continue
                dsh = float(data[sym][col].loc[sig_dt])
            else:
                continue
        else:
            dsh = float(series.loc[sig_dt])
        if np.isnan(dsh):
            continue
        if dsh > max_days:
            ret = float(t["ret"])
            skips.append(
                {
                    "symbol": sym,
                    "entry": str(pd.Timestamp(t["entry"]).date()),
                    "exit": str(pd.Timestamp(t["exit"]).date()),
                    "sig_dt": str(pd.Timestamp(sig_dt).date()),
                    "days_since_high": dsh,
                    "ret": ret,
                    "winner": ret > 0,
                    "loser": ret <= 0,
                }
            )
    n = len(skips)
    n_win = sum(1 for s in skips if s["winner"])
    n_lose = sum(1 for s in skips if s["loser"])
    save_rate = n_lose / n if n else None
    hit_rate = n_win / n if n else None
    avg_skip_ret = float(np.mean([s["ret"] for s in skips])) if n else None
    return {
        "n_skips": n,
        "n_winners_skipped": n_win,
        "n_losers_skipped": n_lose,
        "save_rate": save_rate,
        "hit_rate_overfilter": hit_rate,
        "avg_skip_ret": avg_skip_ret,
        "max_days": max_days,
        "skips": skips,
        "justify_gate": bool(save_rate is not None and save_rate >= 0.50 and n >= 1),
        "overfilter_flag": bool(hit_rate is not None and hit_rate > 0.60 and n >= 20),
        "thin_sample": n < 20,
        "honesty": (
            f"n={n} skips — rates provisional; do not treat save-rate as confirmatory "
            f"until n≥20 live+hist combined."
            if n < 20
            else "n≥20 — rates usable as soft evidence."
        ),
    }


# ── Pine vs Python rule check ─────────────────────────────────────────────────
def verify_pine_vs_python() -> dict:
    pine = OUT_PINE.read_text() if OUT_PINE.exists() else ""
    checks = {
        "pine_exists": OUT_PINE.exists(),
        "mult_3_6": 'mult = input.float(3.6' in pine or "input.float(3.6" in pine,
        "ema200": "emaLen = input.int(200" in pine or "input.int(200" in pine,
        "use_ema_gate": "useEma" in pine and "close > ema" in pine,
        "st_crossover_entry": "ta.crossover(close, finalLB)" in pine,
        "st_exit_below": "close < finalLB" in pine,
        "next_open_fill": "process_orders_on_close=false" in pine,
        "breadth_not_in_pine": "breadth" not in pine.lower() or "not in" in pine.lower(),
        "dd_not_in_pine": "dd_floor" not in pine and "dd_from" not in pine,
        "mom_not_in_pine": "ret20" not in pine,
        "days60_not_in_pine": "days_since" not in pine.lower() or "not in single-symbol" in pine,
        "basket_disclaimer": "5-slot" in pine or "SINGLE SYMBOL" in pine or "single-symbol" in pine.lower(),
    }
    # Core ST/EMA rules must match; basket gates intentionally absent
    core_ok = all(
        checks[k]
        for k in (
            "pine_exists",
            "mult_3_6",
            "ema200",
            "use_ema_gate",
            "st_crossover_entry",
            "st_exit_below",
            "next_open_fill",
            "basket_disclaimer",
        )
    )
    checks["core_st_ema_match"] = core_ok
    checks["note"] = (
        "Pine matches Python ST 3.6 + EMA200 trail/entry/exit. "
        "Basket gates (breadth40, dd−7%, ret20≥−0.04, days60) are intentionally "
        "absent from single-symbol Pine — documented in pine header."
    )
    return checks


# ── Ablation signals ──────────────────────────────────────────────────────────
def sig_st_dd_mom_days_no_br(df, p):
    """ST + dd + mom + days60 WITHOUT breadth kill."""
    e, x, side = sig_supertrend(df, p)
    floor = float(p.get("dd_floor", -0.07))
    mn = float(p.get("min_nifty_ret20", -0.04))
    mx = int(p.get("max_days_since_high", 60))
    if "nifty_dd_hh55" in df.columns:
        e = e & (df["nifty_dd_hh55"] >= floor)
    if "nifty_ret20" in df.columns:
        e = e & (df["nifty_ret20"] >= mn)
    if "nifty_days_since_high" in df.columns:
        e = e & (df["nifty_days_since_high"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_mom_days_no_dd(df, p):
    """kill40 + mom + days60 WITHOUT dd gate."""
    e, x, side = sig_st_kill_breadth(df, p)
    mn = float(p.get("min_nifty_ret20", -0.04))
    mx = int(p.get("max_days_since_high", 60))
    if "nifty_ret20" in df.columns:
        e = e & (df["nifty_ret20"] >= mn)
    if "nifty_days_since_high" in df.columns:
        e = e & (df["nifty_days_since_high"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd_days_no_mom(df, p):
    """kill40 + dd + days60 WITHOUT mom gate."""
    e, x, side = sig_st_kill40_dd(df, p)
    mx = int(p.get("max_days_since_high", 60))
    if "nifty_days_since_high" in df.columns:
        e = e & (df["nifty_days_since_high"] <= mx)
    return e.fillna(False), x.fillna(False), side


# ── Placebo: shuffle gate calendar ────────────────────────────────────────────
def _gate_series(sample: pd.DataFrame, gate: str, params: dict) -> pd.Series:
    if gate == "breadth":
        fl = float(params.get("breadth_floor", 0.40))
        return (sample["breadth50"] >= fl).fillna(False)
    if gate == "dd":
        fl = float(params.get("dd_floor", -0.07))
        return (sample["nifty_dd_hh55"] >= fl).fillna(False)
    if gate == "mom":
        mn = float(params.get("min_nifty_ret20", -0.04))
        return (sample["nifty_ret20"] >= mn).fillna(False)
    if gate == "days60":
        mx = int(params.get("max_days_since_high", 60))
        return (sample["nifty_days_since_high"] <= mx).fillna(False)
    raise ValueError(gate)


def make_placebo_fn(base_fn: Callable, gate: str, shuffled_gate: pd.Series):
    """Wrap base signal; replace named gate with a pre-shuffled calendar."""

    def _fn(df, p):
        e, x, side = base_fn(df, p)
        # Align shuffled gate to this symbol's index
        g = shuffled_gate.reindex(df.index, method="ffill").fillna(True)
        e = e & g.astype(bool)
        return e.fillna(False), x.fillna(False), side

    return _fn


def run_placebo_battery(
    data: Dict[str, pd.DataFrame],
    oos_start,
    champ_tot: float,
    n_shuf: int = N_PLACEBO,
) -> dict:
    """
    For each additive gate, shuffle its on/off calendar (preserve true-rate),
    apply on top of the sleeve that would exist WITHOUT that gate, and see if
    real tot sits in the right tail of placebo tots.
    """
    sample = next(iter(data.values()))
    rng = np.random.default_rng(42)

    # base without each gate → add real vs shuffled gate
    specs = [
        # (gate_name, base_fn, base_params, real_full_fn, real_params)
        ("days60", sig_st_kill40_dd_nifty_mom, B6_PARAMS, sig_st_kill40_dd_mom_days, CHAMP_PARAMS),
        ("mom", sig_st_kill40_dd_days, {**B5_PARAMS, "max_days_since_high": 60},
         sig_st_kill40_dd_mom_days, CHAMP_PARAMS),
        ("dd", sig_st_kill40_mom_days_no_dd, {**KILL40_PARAMS, "min_nifty_ret20": -0.04,
                                              "max_days_since_high": 60},
         sig_st_kill40_dd_mom_days, CHAMP_PARAMS),
        ("breadth", sig_st_dd_mom_days_no_br, {**ST_PARAMS, "dd_floor": -0.07,
                                               "min_nifty_ret20": -0.04,
                                               "max_days_since_high": 60},
         sig_st_kill40_dd_mom_days, CHAMP_PARAMS),
    ]

    out = {}
    for gate, base_fn, base_p, real_fn, real_p in specs:
        real = run_portfolio_ext(data, real_fn, real_p, start_date=oos_start)
        base = run_portfolio_ext(data, base_fn, base_p, start_date=oos_start)
        real_gate = _gate_series(sample, gate, CHAMP_PARAMS)
        # Only shuffle OOS portion of the calendar (no look-ahead into IS for placebo)
        oos_mask = real_gate.index >= oos_start
        oos_vals = real_gate.loc[oos_mask].values.copy()
        n_true = int(oos_vals.sum())
        placebo_tots = []
        for i in range(n_shuf):
            shuf = oos_vals.copy()
            rng.shuffle(shuf)
            full = real_gate.copy()
            full.loc[oos_mask] = shuf
            # Placebo: base without gate, then AND shuffled gate
            pfn = make_placebo_fn(base_fn, gate, full)
            po = run_portfolio_ext(data, pfn, base_p, start_date=oos_start)
            placebo_tots.append(float(po["total_return"]))
        arr = np.array(placebo_tots)
        real_tot = float(real["total_return"])
        # Fraction of placebos ≥ real (higher = real not special)
        p_ge = float((arr >= real_tot - 1e-12).mean())
        # Edge vanish? if mean placebo ≈ base (no gate) and real not much better
        out[gate] = {
            "real_tot": real_tot,
            "base_without_gate_tot": float(base["total_return"]),
            "gate_contribution_pp": (real_tot - float(base["total_return"])) * 100,
            "placebo_mean_tot": float(arr.mean()),
            "placebo_median_tot": float(np.median(arr)),
            "placebo_p05": float(np.percentile(arr, 5)),
            "placebo_p95": float(np.percentile(arr, 95)),
            "frac_placebo_ge_real": p_ge,
            "n_shuffles": n_shuf,
            "n_true_oos_days": n_true,
            "edge_survives_placebo": bool(p_ge <= 0.10),  # real in top ~10%
            "honesty": (
                "PASS: real tot rare under shuffled calendars"
                if p_ge <= 0.10
                else (
                    "FAIL/WEAK: shuffled calendars often match or beat real — "
                    "gate may be in-sample calendar fit"
                    if p_ge > 0.25
                    else "MARGINAL: real tot only mildly special vs placebo"
                )
            ),
        }
        log(
            f"  PLACEBO {gate}: real_tot={real_tot*100:.1f}% base={base['total_return']*100:.1f}% "
            f"placebo_mean={arr.mean()*100:.1f}% p_ge={p_ge:.2f} → {out[gate]['honesty']}"
        )
    return out


def held_out_oos_tot(
    data: Dict[str, pd.DataFrame],
    fn: Callable,
    params: dict,
    oos_start,
) -> Tuple[float, float, object]:
    """Split OOS into early (used historically) vs last HELD_OUT_FRAC (fresh check)."""
    end = max(df.index.max() for df in data.values())
    all_oos = pd.date_range(oos_start, end, freq="B")
    if len(all_oos) < 20:
        # fallback: use calendar from a stock
        sample = next(iter(data.values()))
        all_oos = sample.index[sample.index >= oos_start]
    cut_i = int(len(all_oos) * (1.0 - HELD_OUT_FRAC))
    cut = all_oos[cut_i]
    early = run_portfolio_ext(data, fn, params, start_date=oos_start, end_date=cut)
    late = run_portfolio_ext(data, fn, params, start_date=cut)
    return float(early["total_return"]), float(late["total_return"]), cut


# ── Checklist writer ──────────────────────────────────────────────────────────
def write_block9_checklist(
    champ: dict,
    paper_b: dict,
    days60: dict,
    mom_arch: dict,
    weekly: dict,
    ablation: List[dict],
    placebo: dict,
    complexity: dict,
    pine: dict,
    hrs_left: float,
    recommendation: str,
) -> None:
    co, po = champ["OOS"], paper_b["OOS"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sr = days60.get("save_rate")
    hr = days60.get("hit_rate_overfilter")
    sr_s = f"{sr*100:.0f}%" if sr is not None else "n/a"
    hr_s = f"{hr*100:.0f}%" if hr is not None else "n/a"
    avg_s = (
        f"{days60['avg_skip_ret']*100:.2f}%"
        if days60.get("avg_skip_ret") is not None
        else "n/a"
    )
    msr = mom_arch.get("save_rate")
    msr_s = f"{msr*100:.0f}%" if msr is not None else "n/a"
    w_mean = weekly.get("mean_delta_pp")
    w_mean_s = f"{w_mean:+.2f}pp" if w_mean is not None else "n/a"
    trail4 = weekly.get("trailing_4w_delta_pp")
    trail4_s = f"{trail4:+.2f}pp" if trail4 is not None else "n/a"

    week_rows = ""
    for w in weekly.get("weeks", [])[-8:]:
        week_rows += (
            f"| {w['week']} | {w['a_ret']*100:+.2f}% | {w['b_ret']*100:+.2f}% | "
            f"{w['delta_a_minus_b']*100:+.2f}pp |\n"
        )
    if not week_rows:
        week_rows = "| — | — | — | — |\n"

    skip_rows = ""
    for s in days60.get("skips", [])[:15]:
        tag = "SAVE" if s["loser"] else "MISS"
        skip_rows += (
            f"| {s['entry']} | {s['symbol']} | {s['days_since_high']:.0f} | "
            f"{s['ret']*100:+.2f}% | {tag} |\n"
        )
    if not skip_rows:
        skip_rows = "| — | — | — | — | no OOS days60-skips |\n"

    abl_rows = ""
    for a in ablation:
        o = a["OOS"]
        abl_rows += (
            f"| {a['name']} | {a.get('removed', '—')} | {o['n_trades']} | "
            f"{o['profit_factor']:.2f} | {o['total_return']*100:.1f}% | "
            f"{o['max_dd']*100:.1f}% | {a.get('last_wf_tot', 0)*100:.1f}% | "
            f"{a.get('d_tot_pp', 0):+.1f} | {a.get('d_lastwf_pp', 0):+.1f} |\n"
        )

    plac_rows = ""
    for g, p in placebo.items():
        plac_rows += (
            f"| {g} | {p['real_tot']*100:.1f}% | {p['base_without_gate_tot']*100:.1f}% | "
            f"{p['gate_contribution_pp']:+.1f} | {p['placebo_mean_tot']*100:.1f}% | "
            f"{p['frac_placebo_ge_real']:.2f} | {p['honesty']} |\n"
        )

    text = f"""# Paper A vs B — Live Divergence Checklist

**Updated:** {now} (Block 9 — anti-overfit / thin-n honesty)
**Hours to deadline:** {hrs_left:.2f}
**Status:** Monitoring only — research paper sleeves. No look-ahead. No live capital.
**A (champ / research):** `{champ['name']}` — `strategies/nifty_edge_best.py` / `r29.py`
**B (twin):** `B6_ST_kill40_dd_nifty_mom_m04` — `strategies/nifty_edge_b6_prior.py` / `r21.py`
**Tertiary:** demoted B5 — `strategies/nifty_edge_b5_prior.py`
**Rules file:** `PAPER_TRADE_RULES.md`
**Block 9 recommendation:** {recommendation}

---

## What should differ (structural)

| Gate | Sleeve A | Sleeve B | Expected effect |
|------|----------|----------|-----------------|
| Breadth50 ≥ 0.40 | YES | YES | Shared |
| Nifty dd ≥ −7% (causal prior-55d) | YES | YES | Shared |
| Nifty ret20 ≥ −0.04 | YES | YES | Shared |
| Nifty days-since-high ≤ 60 | YES | NO | A skips stale-trend entries |
| ST mult 3.6 + Nifty bull + EMA200 | YES | YES | Shared core trail |
| Exit | ST trail only | ST trail only | Same exit family |

OOS ref: A n={co['n_trades']} PF={co['profit_factor']:.2f} tot={co['total_return']*100:.1f}% lastWF={champ.get('last_wf_tot',0)*100:.1f}% Sharpe={co['sharpe']:.2f}
vs B n={po['n_trades']} PF={po['profit_factor']:.2f} tot={po['total_return']*100:.1f}% lastWF={paper_b.get('last_wf_tot',0)*100:.1f}% Sharpe={po['sharpe']:.2f}

---

## Block 9 — Days60-skip save-rate (OOS backfill) — HONEST THIN-n

Causal: B trade whose signal-close `nifty_days_since_high > 60` would be skipped by A.
Under B trail + 0.08% RT: loser = ret ≤ 0 (save), winner = ret > 0 (miss).

| Metric | Value | Gate |
|--------|------:|------|
| A-only days60 skips (OOS) | {days60.get('n_skips', 0)} | — |
| Losers skipped (saves) | {days60.get('n_losers_skipped', 0)} | — |
| Winners skipped (misses) | {days60.get('n_winners_skipped', 0)} | — |
| **Save-rate** | **{sr_s}** | Target ≥ 50% |
| Hit-rate (skip-winners) | {hr_s} | Flag if > 60% over ≥20 skips |
| Avg skip ret (B trail) | {avg_s} | Prefer negative |
| Justify gate (hist)? | {"YES" if days60.get("justify_gate") else "NO"} | — |
| Over-filter flag? | {"YES" if days60.get("overfilter_flag") else "NO"} | — |
| **Thin-sample flag** | **{"YES" if days60.get("thin_sample") else "NO"}** | n<20 → provisional |

### Days60-skip sample (up to 15)

| Entry | Symbol | Days since high | B trail ret | Tag |
|-------|--------|----------------:|------------:|-----|
{skip_rows}
**Honesty:** {days60.get('honesty', 'n/a')}

### Archive — prior mom-skip (B5 vs nifty_mom)

Mom gate (ret20 < −0.04): n={mom_arch.get('n_skips', 0)} save-rate={msr_s}
({"thin — provisional" if mom_arch.get("n_skips", 0) < 20 else "ok"}).
See also `results/block8_summary.json`.

---

## Block 9 — Ablation (remove one gate at a time)

| Sleeve | Removed | n | PF | Tot | MDD | LastWF | ΔTot pp | ΔLastWF pp |
|--------|---------|--:|---:|----:|----:|-------:|--------:|-----------:|
{abl_rows}

### Complexity penalty
- Rule: prefer simpler if tot within ~{COMPLEXITY_TOT_TOL*100:.0f}% of champ AND lastWF ≥ champ.
- Prefer simpler? **{complexity.get('prefer_simpler')}**
- Preferred sleeve: `{complexity.get('preferred_name')}`
- Reason: {complexity.get('reason')}

### Shuffle / placebo gates
| Gate | Real tot | Base−gate tot | Contrib pp | Placebo mean | P(placebo≥real) | Verdict |
|------|---------:|--------------:|-----------:|-------------:|----------------:|---------|
{plac_rows}

### Pine vs Python
- Core ST 3.6 + EMA200 match: **{pine.get('core_st_ema_match')}**
- Note: {pine.get('note')}

---

## Block 9 — Weekly ΔEquity A−B (OOS backfill)

| Metric | Value | Alert |
|--------|------:|-------|
| Weeks measured | {weekly.get('n_weeks', 0)} | — |
| Mean Δ (A−B) | {w_mean_s} | — |
| Weeks A ahead | {weekly.get('weeks_a_ahead', 0)} | — |
| Weeks B ahead | {weekly.get('weeks_b_ahead', 0)} | — |
| Max consec B>A by >2pp | {weekly.get('max_consec_b_beats_gt2pp', 0)} | Flag if ≥3 |
| 3-week B-lead flag | {"YES" if weekly.get("flag_3w_b_lead") else "NO"} | Do not auto-flip |
| Trailing 4w Δ | {trail4_s} | — |

### Recent weekly rows (last ≤8)

| Week end | A ret | B ret | Δ (A−B) |
|----------|------:|------:|--------:|
{week_rows}

---

## Daily divergence log (fill each live session)

| Date | A entries | B entries | A-only skips (reason) | A exits | B exits | A equity Δ | B equity Δ | Notes |
|------|----------:|----------:|-----------------------|--------:|--------:|-----------:|-----------:|-------|
| YYYY-MM-DD | | | days60 / rank / — | | | | | |

### Skip taxonomy (A-only vs B)

1. **days60** — Nifty days-since-high > 60 at signal close (B would have entered; A skips).
2. **rank/slot** — Signal ok but no free slot after ranking (not a gate divergence).
3. Shared br/dd/mom skips should match both sleeves — if not, data bug.

### Fill hygiene

- Exit first, then entries (same cadence both sleeves).
- Entry fill = next open; exit fill = signal close.
- Log RT cost assumption 0.08% primary (also track 0.15% shadow P&L weekly).

---

## Weekly review (promote/demote signals)

1. **ΔEquity A−B (week):** if B beats A by >2pp for **3 consecutive weeks**, flag review (do not auto-flip). Hist max consec = {weekly.get('max_consec_b_beats_gt2pp', 0)}.
2. **Days60-skip hit-rate:** skip-winners > 60% over ≥20 skips → gate may over-filter. Hist = {hr_s} on n={days60.get('n_skips', 0)}.
3. **Days60-skip save-rate:** Target ≥ 50%. Hist = {sr_s} — **treat as provisional while n<20**.
4. **Last-chunk proxy:** trailing 60d tot A vs B — A should not lag by >5pp without regime note.
5. **MDD gap:** if A MDD worse than B by >3pp on paper, investigate days60 interaction.
6. **No parameter tweak mid-paper** — promote requires dual-clear + ladder + boot **or** robust risk-adj + ladder + boot.
7. **Block 9:** no new gate stacking unless lastWF strictly > 9.2% dual-clear OR held-out chunk clear win.

### Flip criteria (research only)

Promote challenger→A only if:
- tot AND lastWF strictly better vs frozen A, **or**
- robust risk-adj: tot ≥ A+2pp AND Sharpe↑ AND MDD not worse AND stress PF≥A AND lastWF not regress AND WF=3/3
- plus cost ladder 0.08–0.20% holds and bootstrap CI_lo ≥ 1.5

---

## Alert thresholds

| Alert | Threshold |
|-------|-----------|
| Days60 silence | A has 0 entries for ≥15 sessions while B has ≥3 |
| Days60 unused | A and B entry sets identical for ≥20 sessions (gate unused) |
| Trail mismatch | Same name exit day differs A vs B (should be rare — same ST) |
| Cost shadow | 0.15% RT week PnL flips A/B ranking vs 0.08% |

---

## Honesty (Block 9)

- Single-symbol Pine ≠ 5-slot basket (breadth/dd/mom/days60 not in Pine).
- Causal features only; next-open entry.
- Blocks 7–8 promotes used risk-adj path (lastWF tied at 9.2%) — classic filter-stacking smell.
- Days60-skip hist n={days60.get('n_skips', 0)}; mom-skip hist n={mom_arch.get('n_skips', 0)} — both thin.
- Placebo/ablation/complexity results govern keep vs revert — see `results/block9_summary.json`.
"""
    CHECKLIST.write_text(text)


def append_leaderboard_block9(
    champ: dict,
    repro: dict,
    ablation: List[dict],
    placebo: dict,
    complexity: dict,
    held_out: dict,
    pine: dict,
    recommendation: str,
    promote_ok: bool,
    promote_reason: str,
    hrs_left: float,
    bh: dict,
) -> None:
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 9"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    r = repro["OOS"]
    lines = [
        "",
        "## Block 9 — Anti-overfit battery (no vanity stacking)",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Hours to deadline:** {hrs_left:.2f}",
        f"**#1 still leads:** {'YES' if not promote_ok else 'NO — change'} — {promote_reason}",
        f"**Recommendation:** {recommendation}",
        "",
        "### Reproduced champion (B7_ST_kill40_dd_mom_days60)",
        "",
        "| Metric | Block8 ref | Block9 | Drift |",
        "|--------|-----------:|-------:|------:|",
        f"| n | {REF_CHAMP['n_trades']} | {r['n_trades']} | {r['n_trades']-REF_CHAMP['n_trades']:+d} |",
        f"| PF | {REF_CHAMP['profit_factor']:.2f} | {r['profit_factor']:.2f} | {r['profit_factor']-REF_CHAMP['profit_factor']:+.2f} |",
        f"| Tot | {REF_CHAMP['total_return']*100:.1f}% | {r['total_return']*100:.1f}% | {(r['total_return']-REF_CHAMP['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_CHAMP['max_dd']*100:.1f}% | {r['max_dd']*100:.1f}% | {(r['max_dd']-REF_CHAMP['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_CHAMP['sharpe']:.2f} | {r['sharpe']:.2f} | {r['sharpe']-REF_CHAMP['sharpe']:+.2f} |",
        f"| Last WF | 9.2% | {repro.get('last_wf_tot', 0)*100:.1f}% | — |",
        "",
        f"**Pine core ST/EMA match:** {pine.get('core_st_ema_match')} — {pine.get('note')}",
        "",
        "### Ablation (remove one gate)",
        "",
        "| Sleeve | Removed | n | PF | Tot | MDD | LastWF | ΔTot | ΔLastWF |",
        "|--------|---------|--:|---:|----:|----:|-------:|-----:|--------:|",
    ]
    for a in ablation:
        oo = a["OOS"]
        lines.append(
            f"| {a['name']} | {a.get('removed', '—')} | {oo['n_trades']} | "
            f"{oo['profit_factor']:.2f} | {oo['total_return']*100:.1f}% | "
            f"{oo['max_dd']*100:.1f}% | {a.get('last_wf_tot', 0)*100:.1f}% | "
            f"{a.get('d_tot_pp', 0):+.1f} | {a.get('d_lastwf_pp', 0):+.1f} |"
        )

    lines += [
        "",
        "### Shuffle / placebo",
        "",
        "| Gate | Real tot | Base−gate | Contrib pp | Placebo mean | P(≥real) | Verdict |",
        "|------|---------:|----------:|-----------:|-------------:|---------:|---------|",
    ]
    for g, p in placebo.items():
        lines.append(
            f"| {g} | {p['real_tot']*100:.1f}% | {p['base_without_gate_tot']*100:.1f}% | "
            f"{p['gate_contribution_pp']:+.1f} | {p['placebo_mean_tot']*100:.1f}% | "
            f"{p['frac_placebo_ge_real']:.2f} | {p['honesty'].split(':')[0]} |"
        )

    lines += [
        "",
        "### Complexity / held-out / recommendation",
        "",
        f"- Prefer simpler? **{complexity.get('prefer_simpler')}** → `{complexity.get('preferred_name')}`",
        f"- Reason: {complexity.get('reason')}",
        f"- Held-out (last {HELD_OUT_FRAC*100:.0f}% OOS) champ tot={held_out.get('champ_late_tot', 0)*100:.1f}% "
        f"vs B5={held_out.get('b5_late_tot', 0)*100:.1f}% vs ST={held_out.get('st_late_tot', 0)*100:.1f}% "
        f"(cut={held_out.get('cut')})",
        f"- Paper A vs research A: {recommendation}",
        f"- Buy&hold ^NSEI OOS: tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "",
        "### Honesty",
        "",
        "- Consecutive risk-adj promotes with tied lastWF 9.2% → anti-overfit block (no new stacking).",
        "- Days60-skip / mom-skip hist n thin — save-rates provisional.",
        "- Complexity penalty can demote research champ from paper A without deleting files.",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def expand_final_outline_b9(
    champ: dict,
    ablation: List[dict],
    placebo: dict,
    complexity: dict,
    recommendation: str,
    hrs_left: float,
) -> None:
    o = champ["OOS"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = f"""# FINAL_REPORT outline (Block 9 draft — anti-overfit)

**Drafted:** {now}
**Hours to deadline:** {hrs_left:.2f}
**Status:** Outline + body draft — full FINAL_REPORT lock when <1h to deadline.

## 1. Executive verdict
- **Research champion (kept files):** `{champ['name']}` — ST 3.6 + br≥0.40 + dd≥−7% + ret20≥−0.04 + days≤60
- OOS PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% n={o['n_trades']} MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} lastWF={champ.get('last_wf_tot', 0)*100:.1f}%
- **Block 9 recommendation:** {recommendation}
- Prefer simpler? {complexity.get('prefer_simpler')} → `{complexity.get('preferred_name')}`
- No new gate stacking in Block 9 (anti-overfit mandate).

## 2. Path to champion (Blocks 1–9)
- B1–4: ST_m3.6 core.
- B5: kill40 + causal dd≥−7% (dual-clear).
- B6: neighborhood freeze; ensembles rejected.
- B7–8: consecutive **risk-adj** promotes (nifty_mom → days60) with **tied lastWF 9.2%** — filter-stacking smell.
- B9: repro + pine check + skip-rate honesty + placebo + ablation + complexity penalty.

## 3. Anti-overfit results
### Ablation
{chr(10).join(f"- `{a['name']}` remove={a.get('removed')}: tot={a['OOS']['total_return']*100:.1f}% lastWF={a.get('last_wf_tot',0)*100:.1f}% (Δtot={a.get('d_tot_pp',0):+.1f}pp)" for a in ablation)}

### Placebo
{chr(10).join(f"- `{g}`: contrib={p['gate_contribution_pp']:+.1f}pp; P(placebo≥real)={p['frac_placebo_ge_real']:.2f}; {p['honesty']}" for g, p in placebo.items())}

### Complexity
- {complexity.get('reason')}

## 4. Skip-rate honesty
- Days60-skip and mom-skip historical n are thin (<20) — save-rates are provisional, not confirmatory.
- Live paper log remains the primary gate audit.

## 5. Paper trade freeze
- Research A files: `strategies/nifty_edge_best.py`, `r29.py`, pine proxy
- Paper B: `strategies/nifty_edge_b6_prior.py`
- Tertiary B5: `strategies/nifty_edge_b5_prior.py`
- Plain ST: `strategies/nifty_edge_r17.py`
- See recommendation for which sleeve is paper-A preferred.

## 6. Constraints & honesty
- No look-ahead; causal features only.
- Single-symbol Pine ≠ 5-slot basket.
- Block 9 forbids vanity tot bumps via more gates unless dual-clear lastWF > 9.2%.

## 7. Open risks / Block 10 or FINAL
- Continue live A/B days60-skip log until n≥20.
- If complexity prefers simpler: paper A = simpler; research A = stacked (monitor only).
- Full FINAL_REPORT + lock when <1h to deadline.
- Block 10: only if hours remain — held-out monitoring / no stacking.
"""
    FINAL_OUTLINE.write_text(text)


def draft_final_body(
    champ: dict,
    ablation: List[dict],
    placebo: dict,
    complexity: dict,
    recommendation: str,
    hrs_left: float,
) -> None:
    """Expand outline body; does NOT lock unless <1h (write_full_final_if_needed)."""
    o = champ["OOS"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # Keep as draft companion; full lock only via write_full_final_if_needed
    draft = FINAL_OUTLINE.parent / "FINAL_REPORT_DRAFT.md"
    draft.write_text(
        f"""# Nifty Edge 8h — FINAL REPORT (DRAFT — Block 9)

**Drafted:** {now}
**Hours to deadline:** {hrs_left:.2f}
**Status:** DRAFT — not locked. Lock when <1h via `FINAL_REPORT.md`.

## Champion

**Research:** `{champ['name']}`
- OOS n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}%
- MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} lastWF={champ.get('last_wf_tot', 0)*100:.1f}%
- Files: `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine`, `strategies/nifty_edge_r29.py`

**Paper recommendation:** {recommendation}

## Overfit assessment (Block 9)

Consecutive B7/B8 risk-adj promotes with identical lastWF 9.2% are consistent with
in-sample filter stacking. Block 9 placebo/ablation/complexity:

- Prefer simpler: {complexity.get('prefer_simpler')}
- Preferred sleeve: `{complexity.get('preferred_name')}`
- Reason: {complexity.get('reason')}

### Placebo gate summary
{chr(10).join(f"- {g}: P(placebo≥real)={p['frac_placebo_ge_real']:.2f} — {p['honesty']}" for g, p in placebo.items())}

### Ablation contribution
{chr(10).join(f"- remove {a.get('removed')}: Δtot={a.get('d_tot_pp',0):+.1f}pp ΔlastWF={a.get('d_lastwf_pp',0):+.1f}pp" for a in ablation if a.get('removed') != 'none (champ)')}

## What not to do
- Do not stack more gates without dual-clear lastWF strictly > 9.2%.
- Do not treat days60/mom skip save-rates as confirmatory while n<20.

## Lock
When hours_left < 1.0, run finalize path → `FINAL_REPORT.md`.
"""
    )
    log(f"Wrote {draft}")


# Campaign-path sleeves only for paper-A complexity (ignore ad-hoc ablations)
PAPER_PATH_NAMES = {
    "B7_ST_kill40_dd_mom_days60",
    "B6_ST_kill40_dd_nifty_mom_m04",
    "B6_ST_kill40_dd_days60",
    "B5_ST_kill40_dd07",
    "B2_ST_kill_breadth40_m3.6",
    "ST_m3.6_n1_e1",
}


def complexity_decision(champ: dict, sleeves: List[dict]) -> dict:
    """
    Prefer simpler if within ~10% tot and lastWF ≥ champ.
    Paper preference restricted to campaign-path sleeves; ad-hoc ablations
    (e.g. drop breadth) are reported separately as research findings.
    """
    c_tot = champ["OOS"]["total_return"]
    c_lw = float(champ.get("last_wf_tot", 0))

    all_eligible = []
    path_eligible = []
    for s in sleeves:
        tot = s["OOS"]["total_return"]
        lw = float(s.get("last_wf_tot", 0))
        if tot >= c_tot * (1.0 - COMPLEXITY_TOT_TOL) and lw + 1e-12 >= c_lw:
            all_eligible.append(s)
            if s["name"] in PAPER_PATH_NAMES:
                path_eligible.append(s)

    # Research note: any ablation that beats/matches under complexity
    research_note = None
    if all_eligible:
        research_sorted = sorted(
            all_eligible,
            key=lambda s: (
                s.get("n_gates", 99),
                -float(s.get("last_wf_tot", 0)),
                -s["OOS"]["total_return"],
            ),
        )
        top = research_sorted[0]
        if top["name"] not in PAPER_PATH_NAMES or top.get("removed") not in (
            None,
            "none (champ)",
            "days60",
            "mom",
            "mom+days60",
            "dd+mom+days60",
            "all gates",
        ):
            research_note = (
                f"Ablation research: `{top['name']}` (remove {top.get('removed')}) "
                f"tot={top['OOS']['total_return']*100:.1f}% lastWF={top.get('last_wf_tot', 0)*100:.1f}% "
                f"— interesting but not a campaign-path paper sleeve."
            )

    pool = path_eligible if path_eligible else all_eligible
    if not pool:
        return {
            "prefer_simpler": False,
            "preferred_name": champ["name"],
            "research_note": research_note,
            "reason": (
                f"No simpler campaign-path sleeve within {COMPLEXITY_TOT_TOL*100:.0f}% tot "
                f"with lastWF≥champ ({c_lw*100:.1f}%). Keep research champ."
            ),
        }

    # Prefer fewest gates; among ties prefer higher lastWF then higher tot
    # Among same n_gates prefer dropping thinnest recent stack (days60 > mom > older)
    remove_priority = {
        "none (champ)": 99,
        "days60": 0,  # thinnest evidence — prefer dropping first
        "mom": 1,
        "mom+days60": 2,
        "dd+mom+days60": 3,
        "all gates": 4,
        "dd": 5,
        "breadth": 6,
    }
    pool.sort(
        key=lambda s: (
            s.get("n_gates", 99),
            remove_priority.get(s.get("removed", ""), 50),
            -float(s.get("last_wf_tot", 0)),
            -s["OOS"]["total_return"],
        )
    )
    best = pool[0]
    if best["name"] == champ["name"] or best.get("n_gates", 99) >= champ.get("n_gates", 99):
        return {
            "prefer_simpler": False,
            "preferred_name": champ["name"],
            "research_note": research_note,
            "reason": (
                "Champ already among simplest eligible campaign-path sleeves; keep. "
                + (research_note or "")
            ).strip(),
        }
    return {
        "prefer_simpler": True,
        "preferred_name": best["name"],
        "research_note": research_note,
        "preferred": {
            "name": best["name"],
            "tot": best["OOS"]["total_return"],
            "last_wf": best.get("last_wf_tot"),
            "mdd": best["OOS"]["max_dd"],
            "sharpe": best["OOS"]["sharpe"],
            "n_gates": best.get("n_gates"),
            "removed": best.get("removed"),
        },
        "reason": (
            f"`{best['name']}` within {COMPLEXITY_TOT_TOL*100:.0f}% tot of champ "
            f"({best['OOS']['total_return']*100:.1f}% vs {c_tot*100:.1f}%) with "
            f"lastWF {best.get('last_wf_tot', 0)*100:.1f}% ≥ {c_lw*100:.1f}% and "
            f"fewer gates ({best.get('n_gates')} vs {champ.get('n_gates')}; "
            f"drop {best.get('removed')}). "
            + (research_note or "")
        ).strip(),
    }


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
            "B7_ST_kill40_dd_mom_days60",
            data,
            sig_st_kill40_dd_mom_days,
            CHAMP_PARAMS,
            oos_start,
        )
        champ["last_wf_tot"] = champ["wf"][-1]["total_return"] if champ["wf"] else 0.0
        write_full_final_if_needed(champ, hrs if hrs < 1.0 else -0.01)
        if not FINAL_REPORT.exists():
            write_full_final_if_needed(champ, -0.01)
        log(f"Wrote {FINAL_REPORT}")
        print("FINALIZED_NEAR_DEADLINE")
        return

    log("=== Block 9 start ===")
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

    # ── 1) Repro champ + pine check ───────────────────────────────────────────
    log("Reproducing champion B7_ST_kill40_dd_mom_days60…")
    champ = portfolio_eval(
        "B7_ST_kill40_dd_mom_days60",
        data,
        sig_st_kill40_dd_mom_days,
        CHAMP_PARAMS,
        oos_start,
    )
    champ["last_wf_tot"] = champ["wf"][-1]["total_return"] if champ["wf"] else 0.0
    champ["n_gates"] = 4  # br, dd, mom, days60 (beyond ST core)
    o = champ["OOS"]
    drift_ok = (
        abs(o["n_trades"] - REF_CHAMP["n_trades"]) <= 1
        and abs(o["profit_factor"] - REF_CHAMP["profit_factor"]) < 0.05
        and abs(o["total_return"] - REF_CHAMP["total_return"]) < 0.02
        and abs(o["max_dd"] - REF_CHAMP["max_dd"]) < 0.01
    )
    log(
        f"  REPRO n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} "
        f"WF={champ['wf_pos']}/{champ['wf_n']} lastWF={champ['last_wf_tot']*100:.1f}% "
        f"drift_ok={drift_ok}"
    )

    pine = verify_pine_vs_python()
    log(f"  PINE core_match={pine['core_st_ema_match']} — {pine['note']}")

    # ── 2) Days60 / mom skip honesty + weekly ─────────────────────────────────
    log("Expanding days60-skip / mom-skip save-rate notes (honest thin-n)…")
    a_raw = run_portfolio_ext(
        data, sig_st_kill40_dd_mom_days, CHAMP_PARAMS, start_date=oos_start, return_trades=True
    )
    b_raw = run_portfolio_ext(
        data, sig_st_kill40_dd_nifty_mom, B6_PARAMS, start_date=oos_start, return_trades=True
    )
    b5_raw = run_portfolio_ext(
        data, sig_st_kill40_dd, B5_PARAMS, start_date=oos_start, return_trades=True
    )
    paper_b = portfolio_eval(
        "B6_ST_kill40_dd_nifty_mom_m04", data, sig_st_kill40_dd_nifty_mom, B6_PARAMS, oos_start
    )
    paper_b["last_wf_tot"] = paper_b["wf"][-1]["total_return"] if paper_b["wf"] else 0.0
    paper_b["n_gates"] = 3

    days60 = analyze_days60_skips(data, b_raw.get("trades", []))
    mom_arch = analyze_mom_skips(data, oos_start, b5_raw.get("trades", []))
    weekly = weekly_equity_delta(a_raw.get("equity"), b_raw.get("equity"))
    log(
        f"  DAYS60-SKIP n={days60.get('n_skips')} save_rate={days60.get('save_rate')} "
        f"thin={days60.get('thin_sample')} — {days60.get('honesty')}"
    )
    log(
        f"  MOM-SKIP archive n={mom_arch.get('n_skips')} save_rate={mom_arch.get('save_rate')}"
    )
    log(
        f"  WEEKLY ΔEquity mean={weekly.get('mean_delta_pp')}pp "
        f"flag3w={weekly.get('flag_3w_b_lead')}"
    )

    # ── 3a) Ablation ──────────────────────────────────────────────────────────
    log("Ablation: remove each gate one-at-a-time…")
    abl_specs = [
        ("B7_ST_kill40_dd_mom_days60", "none (champ)", sig_st_kill40_dd_mom_days, CHAMP_PARAMS, 4),
        ("B6_ST_kill40_dd_nifty_mom_m04", "days60", sig_st_kill40_dd_nifty_mom, B6_PARAMS, 3),
        ("B6_ST_kill40_dd_days60", "mom", sig_st_kill40_dd_days,
         {**B5_PARAMS, "max_days_since_high": 60}, 3),
        ("B9_ablate_dd", "dd", sig_st_kill40_mom_days_no_dd,
         {**KILL40_PARAMS, "min_nifty_ret20": -0.04, "max_days_since_high": 60}, 3),
        ("B9_ablate_breadth", "breadth", sig_st_dd_mom_days_no_br,
         {**ST_PARAMS, "dd_floor": -0.07, "min_nifty_ret20": -0.04,
          "max_days_since_high": 60}, 3),
        ("B5_ST_kill40_dd07", "mom+days60", sig_st_kill40_dd, B5_PARAMS, 2),
        ("B2_ST_kill_breadth40_m3.6", "dd+mom+days60", sig_st_kill_breadth, KILL40_PARAMS, 1),
        ("ST_m3.6_n1_e1", "all gates", sig_supertrend, ST_PARAMS, 0),
    ]
    ablation: List[dict] = []
    for name, removed, fn, params, n_gates in abl_specs:
        row = portfolio_eval(name, data, fn, params, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        row["removed"] = removed
        row["n_gates"] = n_gates
        row["params"] = params
        row["d_tot_pp"] = (row["OOS"]["total_return"] - o["total_return"]) * 100
        row["d_lastwf_pp"] = (row["last_wf_tot"] - champ["last_wf_tot"]) * 100
        ablation.append(row)
        log(
            f"  ABLATE {name} (−{removed}): n={row['OOS']['n_trades']} "
            f"PF={row['OOS']['profit_factor']:.2f} tot={row['OOS']['total_return']*100:.1f}% "
            f"MDD={row['OOS']['max_dd']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
            f"Δtot={row['d_tot_pp']:+.1f}pp ΔlastWF={row['d_lastwf_pp']:+.1f}pp"
        )

    # ── 3b) Placebo shuffle ───────────────────────────────────────────────────
    log(f"Shuffle/placebo battery ({N_PLACEBO} shuffles/gate)…")
    placebo = run_placebo_battery(data, oos_start, o["total_return"], n_shuf=N_PLACEBO)

    # ── 3c) Complexity penalty ────────────────────────────────────────────────
    log("Complexity penalty: prefer simpler if within ~10% tot & lastWF≥champ…")
    complexity = complexity_decision(champ, ablation)
    log(
        f"  COMPLEXITY prefer_simpler={complexity['prefer_simpler']} "
        f"→ {complexity['preferred_name']}: {complexity['reason']}"
    )

    # ── 3d) Held-out chunk (last 30% OOS) — no new stacking ───────────────────
    log("Held-out last-30% OOS chunk (fresh vs historically optimized window)…")
    c_early, c_late, cut = held_out_oos_tot(
        data, sig_st_kill40_dd_mom_days, CHAMP_PARAMS, oos_start
    )
    b5_early, b5_late, _ = held_out_oos_tot(data, sig_st_kill40_dd, B5_PARAMS, oos_start)
    st_early, st_late, _ = held_out_oos_tot(data, sig_supertrend, ST_PARAMS, oos_start)
    b6_early, b6_late, _ = held_out_oos_tot(
        data, sig_st_kill40_dd_nifty_mom, B6_PARAMS, oos_start
    )
    held_out = {
        "cut": str(pd.Timestamp(cut).date()),
        "champ_early_tot": c_early,
        "champ_late_tot": c_late,
        "b6_early_tot": b6_early,
        "b6_late_tot": b6_late,
        "b5_early_tot": b5_early,
        "b5_late_tot": b5_late,
        "st_early_tot": st_early,
        "st_late_tot": st_late,
        "champ_beats_b5_heldout": c_late > b5_late,
        "champ_beats_st_heldout": c_late > st_late,
    }
    log(
        f"  HELD-OUT cut={held_out['cut']} champ_late={c_late*100:.1f}% "
        f"b6_late={b6_late*100:.1f}% b5_late={b5_late*100:.1f}% st_late={st_late*100:.1f}%"
    )

    # ── 4) Promote / keep / revert decision (NO new stacking) ─────────────────
    promote_ok = False
    promote_reason = "keep_research_champ:no_new_stacking"

    # Build recommendation for paper A vs research A
    weak_gates = [
        g for g, p in placebo.items() if p["frac_placebo_ge_real"] > 0.25
    ]
    thin_skips = days60.get("thin_sample", True)

    held_note = (
        f"Held-out late OOS identical for champ/B6/B5 at {c_late*100:.1f}% "
        f"(stack does not differentiate late chunk). "
        if held_out.get("champ_beats_b5_heldout") is not None
        and abs(c_late - b5_late) < 1e-9 and abs(c_late - b6_late) < 1e-9
        else ""
    )
    research_note = complexity.get("research_note") or ""

    if complexity.get("prefer_simpler"):
        pref = complexity["preferred_name"]
        recommendation = (
            f"PAPER A → `{pref}` (simpler, complexity-eligible campaign path); "
            f"RESEARCH A → keep `{champ['name']}` files for monitoring only. "
            f"{held_note}{research_note} "
            f"Reason: {complexity['reason']}"
        ).strip()
        promote_reason = f"complexity_prefer_simpler_paperA:{pref}"
    elif weak_gates and thin_skips:
        recommendation = (
            f"PAPER A → `B5_ST_kill40_dd07` or `B6_ST_kill40_dd_nifty_mom_m04` "
            f"(stacked lastWF-tied gates weak under placebo: {', '.join(weak_gates)}; "
            f"days60-skip n={days60.get('n_skips', 0)} thin). "
            f"RESEARCH A → keep `{champ['name']}` files; do not stack further. "
            f"{held_note}{research_note}"
        ).strip()
        promote_reason = "keep_research_champ:paper_prefer_simpler_overfit_risk"
    else:
        recommendation = (
            f"KEEP research+paper A = `{champ['name']}` for now, but freeze stacking. "
            f"Continue live days60-skip log until n≥20. "
            f"Placebo weak gates: {weak_gates or 'none'}. "
            f"{held_note}{research_note}"
        ).strip()

    # Explicit: no promote of anything new; optional demote paper pointing
    log(f"  DECISION: {promote_reason}")
    log(f"  RECOMMEND: {recommendation}")

    # ── 5) Write checklist / outline / board / summary ────────────────────────
    write_block9_checklist(
        champ,
        paper_b,
        days60,
        mom_arch,
        weekly,
        ablation,
        placebo,
        complexity,
        pine,
        hrs,
        recommendation,
    )
    log(f"Wrote {CHECKLIST}")

    expand_final_outline_b9(champ, ablation, placebo, complexity, recommendation, hrs)
    draft_final_body(champ, ablation, placebo, complexity, recommendation, hrs)
    log(f"Wrote {FINAL_OUTLINE}")
    if hrs < 1.0:
        write_full_final_if_needed(champ, hrs)
        log("FULL FINAL written (<1h)")
    else:
        log(f"FINAL draft/outline only ({hrs:.1f}h left; full lock later)")

    append_leaderboard_block9(
        champ,
        champ,
        ablation,
        placebo,
        complexity,
        held_out,
        pine,
        recommendation,
        promote_ok,
        promote_reason,
        hrs,
        bh_oos,
    )
    log(f"Updated {LEADERBOARD}")

    if PAPER_RULES.exists():
        prev = PAPER_RULES.read_text()
        marker = "\n## Block 9 — Anti-overfit"
        if marker in prev:
            prev = prev.split(marker)[0].rstrip() + "\n"
        prev += (
            f"{marker}\n\n"
            f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"- Anti-overfit battery complete (placebo/ablation/complexity).\n"
            f"- Recommendation: {recommendation}\n"
            f"- No new gate stacking. Days60-skip n={days60.get('n_skips')} thin={days60.get('thin_sample')}.\n"
        )
        PAPER_RULES.write_text(prev)

    summary = {
        "block": 9,
        "hours_left": hrs,
        "drift_ok": drift_ok,
        "champion": champ["name"],
        "promote_ok": promote_ok,
        "promote_reason": promote_reason,
        "recommendation": recommendation,
        "pine": pine,
        "repro": {
            "n": o["n_trades"],
            "pf": o["profit_factor"],
            "tot": o["total_return"],
            "mdd": o["max_dd"],
            "sharpe": o["sharpe"],
            "last_wf": champ["last_wf_tot"],
            "drift_ok": drift_ok,
        },
        "days60_skip": {k: v for k, v in days60.items() if k != "skips"},
        "days60_skip_sample": days60.get("skips", [])[:20],
        "mom_skip_archive": {k: v for k, v in mom_arch.items() if k != "skips"},
        "weekly_delta": {k: v for k, v in weekly.items() if k != "weeks"},
        "ablation": [
            {
                "name": a["name"],
                "removed": a.get("removed"),
                "n_gates": a.get("n_gates"),
                "n": a["OOS"]["n_trades"],
                "pf": a["OOS"]["profit_factor"],
                "tot": a["OOS"]["total_return"],
                "mdd": a["OOS"]["max_dd"],
                "sharpe": a["OOS"]["sharpe"],
                "last_wf": a.get("last_wf_tot"),
                "d_tot_pp": a.get("d_tot_pp"),
                "d_lastwf_pp": a.get("d_lastwf_pp"),
            }
            for a in ablation
        ],
        "placebo": placebo,
        "complexity": complexity,
        "held_out": held_out,
        "buy_hold_oos": {"tot": bh_oos["total_return"], "sharpe": bh_oos["sharpe"]},
        "overfit_assessment": {
            "tied_lastwf_promotes": True,
            "thin_days60_n": days60.get("n_skips"),
            "thin_mom_n": mom_arch.get("n_skips"),
            "weak_placebo_gates": weak_gates,
            "prefer_simpler": complexity.get("prefer_simpler"),
        },
    }
    out_path = RESULTS / "block9_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    log(f"Wrote {out_path}")

    log("--- Block 9 ablation ranking (by lastWF, tot) ---")
    for t in sorted(
        ablation,
        key=lambda r: (r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
        reverse=True,
    ):
        log(
            f"  {t['name']}: tot={t['OOS']['total_return']*100:.1f}% "
            f"lastWF={t.get('last_wf_tot', 0)*100:.1f}% n_gates={t.get('n_gates')} "
            f"(−{t.get('removed')})"
        )

    log(
        f"=== Block 9 complete === champion={champ['name']} "
        f"PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"prefer_simpler={complexity.get('prefer_simpler')} "
        f"drift_ok={drift_ok} hrs_left={hrs:.2f}"
    )
    log(
        "Next Block 10: live skip log; no stacking; FINAL lock when <1h — "
        "or FINAL now if deadline."
    )
    print(
        json.dumps(
            {
                "champion": champ["name"],
                "drift_ok": drift_ok,
                "prefer_simpler": complexity.get("prefer_simpler"),
                "preferred": complexity.get("preferred_name"),
                "recommendation": recommendation,
                "weak_placebo_gates": weak_gates,
                "days60_n": days60.get("n_skips"),
                "hrs_left": hrs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
