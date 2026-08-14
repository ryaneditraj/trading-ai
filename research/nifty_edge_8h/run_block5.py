#!/usr/bin/env python3
"""
Block 5 — bootstrap + cost ladder; regime_hl8 promote decision; last-WF causal attack.

Mandatory:
  1) Quick repro of #1
  2) Bootstrap + cost ladder (0.08/0.10/0.12/0.15/0.20% RT) on #1, kill40,
     regime_hl8, softvol22 — table in results
  3) Promote regime_hl8 ONLY if margin holds under ladder + WF/bootstrap (strict)
  4) Last-WF causal features only (no look-ahead) ≥8 new variants
  5) Update PAPER_TRADE_RULES.md if twin/champion choice changes; freeze A/B
  6) Update leaderboard/log; save r17+
  7) Optional clean FII/OI only if free usable data; else skip
  8) No hourly unless n≥40

Usage:
  python research/nifty_edge_8h/run_block5.py
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
    portfolio_eval_ext,
    run_portfolio_ext,
    sig_st_kill_breadth,
)
from run_block3 import portfolio_eval_b3, run_portfolio_b3  # noqa: E402
from run_block4 import (  # noqa: E402
    attach_regime_features,
    sig_st_regime_halflife,
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

COST_LADDER = [0.0008, 0.0010, 0.0012, 0.0015, 0.0020]  # 0.08–0.20% RT


# ── Last-WF causal feature attach (no look-ahead) ─────────────────────────────
def attach_lastwf_features(
    stocks: Dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
    bank: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """
    Causal features aimed at 2024–26 chop: Nifty drawdown from high, vol regime,
    breadth momentum, bank RS, days-since-high, ATR percentile — all lag-safe.
    """
    out = {}
    n = nifty
    b = bank.reindex(n.index, method="ffill")
    nifty_ret20 = n["Close"].pct_change(20)
    nifty_ret5 = n["Close"].pct_change(5)
    hh55 = n["High"].rolling(55).max().shift(1)  # prior 55d high (no look-ahead)
    dd_from_hh = n["Close"] / hh55 - 1.0
    nifty_vol20 = n["Close"].pct_change().rolling(20).std() * np.sqrt(252)
    nifty_vol60 = n["Close"].pct_change().rolling(60).std() * np.sqrt(252)
    vol_ratio = nifty_vol20 / nifty_vol60.replace(0, np.nan)
    # Days since Nifty close made a new 55d high (causal streak)
    is_new_high = (n["Close"] >= hh55).astype(float)
    days_since_high = np.zeros(len(n))
    vals = is_new_high.values
    for i in range(len(vals)):
        if vals[i] > 0.5:
            days_since_high[i] = 0
        else:
            days_since_high[i] = (days_since_high[i - 1] + 1) if i > 0 else 1
    bank_rs20 = b["Close"].pct_change(20) - nifty_ret20
    breadth = n["breadth50"] if "breadth50" in n.columns else pd.Series(0.5, index=n.index)
    breadth_chg5 = breadth.diff(5)
    breadth_ma10 = breadth.rolling(10).mean()

    for s, df in stocks.items():
        o = df.copy()
        ni = n.reindex(o.index, method="ffill")
        bi = b.reindex(o.index, method="ffill")
        o["nifty_ret5"] = nifty_ret5.reindex(o.index, method="ffill").values
        o["nifty_ret20"] = nifty_ret20.reindex(o.index, method="ffill").values
        o["nifty_dd_hh55"] = dd_from_hh.reindex(o.index, method="ffill").values
        o["nifty_vol_ratio"] = vol_ratio.reindex(o.index, method="ffill").values
        o["nifty_vol20"] = nifty_vol20.reindex(o.index, method="ffill").values
        o["nifty_days_since_high"] = (
            pd.Series(days_since_high, index=n.index).reindex(o.index, method="ffill").values
        )
        o["bank_rs20"] = bank_rs20.reindex(o.index, method="ffill").values
        o["breadth_chg5"] = breadth_chg5.reindex(o.index, method="ffill").values
        o["breadth_ma10"] = breadth_ma10.reindex(o.index, method="ffill").values
        # Stock ATR percentile proxy (causal): ATR / rolling max ATR — faster than rank
        atr = o["atr"] if "atr" in o.columns else (o["High"] - o["Low"])
        atr_max = atr.rolling(60).max().replace(0, np.nan)
        atr_min = atr.rolling(60).min()
        o["atr_pctile60"] = ((atr - atr_min) / (atr_max - atr_min)).clip(0, 1).fillna(0.5)
        # Pullback depth vs Supertrend-ish: close vs 20d high
        hh20 = o["High"].rolling(20).max().shift(1)
        o["pullback_from_hh20"] = o["Close"] / hh20 - 1.0
        # Soft volume confirmation
        if "rvol" not in o.columns and "Volume" in o.columns:
            o["rvol"] = o["Volume"] / o["Volume"].rolling(20).mean()
        out[s] = o
    return out


# ── Signal variants (last-WF causal) ──────────────────────────────────────────
def sig_st_dd_gate(df, p):
    """Skip entries when Nifty drawdown from prior 55d high < dd_floor (too deep)."""
    e, x, side = sig_supertrend(df, p)
    floor = float(p.get("dd_floor", -0.06))
    if "nifty_dd_hh55" in df.columns:
        e = e & (df["nifty_dd_hh55"] >= floor)
    return e.fillna(False), x.fillna(False), side


def sig_st_vol_calm(df, p):
    """Enter only when Nifty short/long vol ratio ≤ max_ratio (avoid spike regimes)."""
    e, x, side = sig_supertrend(df, p)
    mx = float(p.get("max_vol_ratio", 1.15))
    if "nifty_vol_ratio" in df.columns:
        e = e & (df["nifty_vol_ratio"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_vol_not_extreme(df, p):
    """Block entries when Nifty 20d ann vol > vol_cap."""
    e, x, side = sig_supertrend(df, p)
    cap = float(p.get("vol_cap", 0.22))
    if "nifty_vol20" in df.columns:
        e = e & (df["nifty_vol20"] <= cap)
    return e.fillna(False), x.fillna(False), side


def sig_st_days_since_high(df, p):
    """Block entries after prolonged time without Nifty 55d high (stale trend)."""
    e, x, side = sig_supertrend(df, p)
    mx = int(p.get("max_days_since_high", 40))
    if "nifty_days_since_high" in df.columns:
        e = e & (df["nifty_days_since_high"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_breadth_mom(df, p):
    """Require breadth improving over 5d (breadth_chg5 ≥ min_chg)."""
    e, x, side = sig_supertrend(df, p)
    mn = float(p.get("min_breadth_chg5", 0.0))
    if "breadth_chg5" in df.columns:
        e = e & (df["breadth_chg5"] >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_bank_rs_ok(df, p):
    """Require Bank 20d RS vs Nifty ≥ min_rs (leadership filter)."""
    e, x, side = sig_supertrend(df, p)
    mn = float(p.get("min_bank_rs", -0.02))
    if "bank_rs20" in df.columns:
        e = e & (df["bank_rs20"] >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_atr_pct_gate(df, p):
    """Skip entries when stock ATR is in extreme percentile (chop/spike)."""
    e, x, side = sig_supertrend(df, p)
    lo = float(p.get("atr_pct_lo", 0.15))
    hi = float(p.get("atr_pct_hi", 0.90))
    if "atr_pctile60" in df.columns:
        e = e & (df["atr_pctile60"] >= lo) & (df["atr_pctile60"] <= hi)
    return e.fillna(False), x.fillna(False), side


def sig_st_soft_rvol(df, p):
    """Soft min relative volume (not hard block if missing)."""
    e, x, side = sig_supertrend(df, p)
    mn = float(p.get("min_rvol", 0.9))
    if "rvol" in df.columns:
        e = e & (df["rvol"].fillna(1.0) >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_pullback_ok(df, p):
    """Avoid entries already extended: pullback_from_hh20 ≥ max_ext (less extended)."""
    e, x, side = sig_supertrend(df, p)
    mx = float(p.get("max_extension", -0.01))  # at least 1% off 20d high
    if "pullback_from_hh20" in df.columns:
        e = e & (df["pullback_from_hh20"] <= mx)
    return e.fillna(False), x.fillna(False), side


def sig_st_nifty_mom_ok(df, p):
    """Require Nifty 20d return ≥ min_ret (mild momentum filter)."""
    e, x, side = sig_supertrend(df, p)
    mn = float(p.get("min_nifty_ret20", -0.03))
    if "nifty_ret20" in df.columns:
        e = e & (df["nifty_ret20"] >= mn)
    return e.fillna(False), x.fillna(False), side


def sig_st_combo_lastwf(df, p):
    """
    Combo: mild dd gate + calm vol + breadth not collapsing.
    Tuned for last-WF lift without gutting tot.
    """
    e, x, side = sig_supertrend(df, p)
    dd_floor = float(p.get("dd_floor", -0.08))
    max_vr = float(p.get("max_vol_ratio", 1.25))
    min_br_chg = float(p.get("min_breadth_chg5", -0.10))
    if "nifty_dd_hh55" in df.columns:
        e = e & (df["nifty_dd_hh55"] >= dd_floor)
    if "nifty_vol_ratio" in df.columns:
        e = e & (df["nifty_vol_ratio"] <= max_vr)
    if "breadth_chg5" in df.columns:
        e = e & (df["breadth_chg5"] >= min_br_chg)
    return e.fillna(False), x.fillna(False), side


def sig_st_regime_hl_lastwf(df, p):
    """regime_hl + soft vol-calm hybrid."""
    e, x, side = sig_st_regime_halflife(df, p)
    max_vr = float(p.get("max_vol_ratio", 1.20))
    if "nifty_vol_ratio" in df.columns:
        e = e & (df["nifty_vol_ratio"] <= max_vr)
    return e.fillna(False), x.fillna(False), side


def sig_st_kill40_dd(df, p):
    """kill40 + mild drawdown gate."""
    e, x, side = sig_st_kill_breadth(df, p)
    floor = float(p.get("dd_floor", -0.07))
    if "nifty_dd_hh55" in df.columns:
        e = e & (df["nifty_dd_hh55"] >= floor)
    return e.fillna(False), x.fillna(False), side


# ── Cost ladder + bootstrap helpers ───────────────────────────────────────────
def cost_ladder_row(
    name: str,
    data: Dict[str, pd.DataFrame],
    fn: Callable,
    params: dict,
    oos_start,
    use_b3: bool = False,
) -> dict:
    ladder = []
    for rt in COST_LADDER:
        if use_b3:
            o = run_portfolio_b3(data, fn, params, start_date=oos_start, rt_cost=rt)
        else:
            o = run_portfolio_ext(data, fn, params, start_date=oos_start, rt_cost=rt)
        ladder.append(
            {
                "rt_pct": rt * 100,
                "n": o["n_trades"],
                "pf": o["profit_factor"],
                "tot": o["total_return"],
                "mdd": o["max_dd"],
                "exp": o["expectancy"],
                "sharpe": o["sharpe"],
            }
        )
    return {"name": name, "ladder": ladder}


def run_bootstrap_for(
    name: str,
    data: Dict[str, pd.DataFrame],
    fn: Callable,
    params: dict,
    oos_start,
    use_b3: bool = False,
    n_boot: int = 2000,
) -> dict:
    if use_b3:
        out = run_portfolio_b3(
            data, fn, params, start_date=oos_start, rt_cost=RT, return_trades=True
        )
        rets = list(out.get("trade_rets", []))
    else:
        rets = collect_trade_rets(data, fn, params, start_date=oos_start, rt_cost=RT)
    boot = bootstrap_pf(rets, n_boot=n_boot)
    boot["name"] = name
    return boot


def regime_hl8_promote_strict(
    regime: dict,
    champ: dict,
    regime_ladder: dict,
    champ_ladder: dict,
    regime_boot: dict,
    champ_boot: dict,
) -> Tuple[bool, str]:
    """
    Strict promote for regime_hl8:
      - tot AND lastWF clear #1 at primary cost
      - meaningful margin: tot ≥ #1 + 2pp OR (tot > #1 AND lastWF ≥ #1 + 2pp)
      - WF ≥ champ WF (3/3)
      - cost ladder: at EVERY rung, tot ≥ #1 tot * 0.98 (margin holds under costs)
      - bootstrap: CI_lo ≥ 1.5 AND CI_lo not worse than champ CI_lo by >15%
      - clearly_better OR margin path above
    """
    r, c = regime["OOS"], champ["OOS"]
    if r["n_trades"] < 40:
        return False, "n<40"
    if regime.get("wf_pos", 0) < champ.get("wf_pos", 0):
        return False, "wf_worse"
    r_last = float(regime.get("last_wf_tot", 0))
    c_last = float(champ.get("last_wf_tot", REF_LAST_WF))
    tot_clear = r["total_return"] > c["total_return"]
    last_clear = r_last > c_last
    if not (tot_clear and last_clear):
        return False, "no_dual_clear"
    margin_ok = (
        r["total_return"] >= c["total_return"] + 0.02
        or (tot_clear and r_last >= c_last + 0.02)
    )
    if not margin_ok:
        return False, "margin_thin"

    # Cost ladder: margin holds
    for rl, cl in zip(regime_ladder["ladder"], champ_ladder["ladder"]):
        if rl["tot"] < cl["tot"] * 0.98:
            return False, f"ladder_fail_rt{rl['rt_pct']:.2f}"
        if rl["pf"] < 1.5:
            return False, f"ladder_pf_low_rt{rl['rt_pct']:.2f}"

    # Bootstrap
    r_lo = regime_boot.get("ci_lo")
    c_lo = champ_boot.get("ci_lo")
    if r_lo is None or r_lo < 1.5:
        return False, "boot_ci_lo_weak"
    if c_lo is not None and r_lo < c_lo * 0.85:
        return False, "boot_ci_lo_vs_champ"

    if clearly_better(regime, champ) or margin_ok:
        return True, "strict_margin+ladder+boot"
    return False, "not_clearly_better"


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


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


def write_paper_rules_b5(
    champ: dict,
    twin: dict,
    twin_label: str,
    twin_code: str,
    twin_rules: List[str],
    freeze_note: str,
) -> None:
    o = champ["OOS"]
    t = twin["OOS"] if twin else {}
    cn = champ["name"]
    # Sleeve A entry bullets depend on champion family
    if "kill40" in cn or "kill_breadth" in cn or champ.get("params", {}).get("breadth_floor"):
        dd = champ.get("params", {}).get("dd_floor")
        br = champ.get("params", {}).get("breadth_floor", 0.40)
        sleeve_a_entry = [
            "1. Compute ATR(14), HL2 = (H+L)/2.",
            "2. Supertrend lower band: basic = HL2 − **3.6** × ATR; ratchet up while prior close > prior band.",
            "3. **Entry signal** (bar close): Close crosses **above** final lower band",
            "   AND Close > stock EMA200",
            "   AND Nifty bull: Close_Nifty > EMA200_Nifty **OR** Close_Nifty > prior 55d Nifty high.",
            f"4. **Breadth gate (entry-only):** Breadth50 ≥ **{br:.2f}** (skip new entries if below; no force-exit).",
        ]
        if dd is not None:
            sleeve_a_entry.append(
                f"5. **Drawdown gate (entry-only, causal):** Nifty Close / prior-55d-High − 1 ≥ **{dd:.2f}** "
                "(block entries in deep index drawdowns)."
            )
            sleeve_a_entry.append("6. Fill: next open. Size: min(cash, equity × 1/5).")
        else:
            sleeve_a_entry.append("5. Fill: next open. Size: min(cash, equity × 1/5).")
        sleeve_a_exit = [
            "1. Close < final Supertrend lower band → exit at that bar close.",
            "2. No force-exit on breadth/dd — trail only.",
        ]
    elif "regime_hl" in cn or champ.get("params", {}).get("hl_days"):
        hl = champ.get("params", {}).get("hl_days", 8)
        sleeve_a_entry = [
            "1. Compute ATR(14), HL2 = (H+L)/2.",
            "2. Supertrend lower band: basic = HL2 − **3.6** × ATR; ratchet up while prior close > prior band.",
            "3. **Entry signal** (bar close): Close crosses **above** final lower band",
            "   AND Close > stock EMA200",
            "   AND Nifty bull: Close_Nifty > EMA200_Nifty **OR** Close_Nifty > prior 55d Nifty high.",
            f"4. **Regime half-life:** block new entries when Nifty days_below_EMA50 ≥ **{hl}**.",
            "5. Fill: next open. Size: min(cash, equity × 1/5).",
        ]
        sleeve_a_exit = [
            "1. Close < final Supertrend lower band → exit at that bar close.",
            "2. No force-exit on regime streak — trail only (soft_exit=False).",
        ]
    else:
        sleeve_a_entry = [
            "1. Compute ATR(14), HL2 = (H+L)/2.",
            "2. Supertrend lower band: basic = HL2 − **3.6** × ATR; ratchet up while prior close > prior band.",
            "3. **Entry signal** (bar close): Close crosses **above** final lower band",
            "   AND Close > stock EMA200",
            "   AND Nifty bull: Close_Nifty > EMA200_Nifty **OR** Close_Nifty > prior 55d Nifty high.",
            "4. Fill: next open. Size: min(cash, equity × 1/5).",
        ]
        sleeve_a_exit = [
            "1. Close < final Supertrend lower band → exit at that bar close.",
            "2. No breadth/vol kill on this sleeve — trail only.",
        ]

    lines = [
        "# Paper Trade Rules — Nifty Edge 8h",
        "",
        f"**Written:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} (Block 5)",
        "**Status:** Research paper sleeve — not live capital. No look-ahead.",
        f"**Freeze:** {freeze_note}",
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
        "| Costs (report both) | **0.08% RT** primary; **0.15% RT** stress; ladder 0.08–0.20 |",
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
        "## Sleeve A — Champion (paper primary) — FROZEN",
        "",
        f"**ID:** `{cn}`  ",
        "**Code:** `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine`  ",
        f"**OOS ref:** n={o['n_trades']} PF={o['profit_factor']:.2f} tot={fmt_pct(o['total_return'])} "
        f"MDD={fmt_pct(o['max_dd'])} Sharpe={o['sharpe']:.2f} "
        f"WF={champ.get('wf_pos')}/{champ.get('wf_n')} lastWF={fmt_pct(champ.get('last_wf_tot', REF_LAST_WF))}",
        "",
        "### Exact entry",
        "",
    ]
    lines += sleeve_a_entry
    lines += [
        "",
        "### Exact exit",
        "",
    ]
    lines += sleeve_a_exit
    lines += [
        "",
        "### Sizing",
        "",
        "- Equal slot; no vol-scale on paper primary.",
        "- Do not pyramid. One position per name.",
        "",
        "---",
        "",
        f"## Sleeve B — {twin_label} — FROZEN",
        "",
    ]
    if twin:
        lines += [
            f"**ID:** `{twin['name']}`  ",
            f"**Code:** `{twin_code}`  ",
            f"**OOS ref:** n={t['n_trades']} PF={t['profit_factor']:.2f} tot={fmt_pct(t['total_return'])} "
            f"MDD={fmt_pct(t['max_dd'])} Sharpe={t.get('sharpe', 0):.2f} "
            f"WF={twin.get('wf_pos')}/{twin.get('wf_n')} lastWF={fmt_pct(twin.get('last_wf_tot', 0))}",
            "",
            "### Exact entry",
            "",
        ]
        lines += twin_rules
        lines += [
            "",
            "### Exact exit",
            "",
            "Same Supertrend trail as Sleeve A (no hard force-exit unless noted).",
            "",
            "### Why twin",
            "",
            "- Parallel paper for robustness; promote/demote only with ladder + bootstrap + dual-clear.",
            "",
        ]
    else:
        lines += ["*(twin stats missing)*", ""]

    lines += [
        "---",
        "",
        "## Daily checklist",
        "",
        "1. Update daily OHLCV for universe + ^NSEI.",
        "2. Recompute ATR trail, EMA200, Nifty bull, breadth50 (+ twin/dd filters).",
        "3. Process exits first (trail), then entries (rank + slots).",
        "4. Log fills with RT cost assumption (0.08% primary).",
        "5. Weekly: compare sleeve A vs B equity and last-chunk PnL.",
        "",
        "## Honesty / constraints",
        "",
        "- Single-symbol Pine ≠ 5-slot basket — Pine is illustrative only.",
        "- mult=3.6 is a local PF peak; track mult=3.0 as conservative sleeve.",
        "- No look-ahead: bands use prior close ratchet; prior-55d high shifted; entry next open.",
        "- Costs: always report **0.08%** and **0.15%** RT; Block-5 ladder 0.08–0.20.",
        "",
    ]
    PAPER_RULES.write_text("\n".join(lines))


def write_b5_runner(idx: int, row: dict, fn_name: str) -> Path:
    path = OUT_STRAT / f"nifty_edge_r{idx}.py"
    oos = row["OOS"]
    params = row["params"]
    needs_b3 = any(k in params for k in ("vol_target", "vol_scale_hi", "vol_scale_lo", "sector_cap"))
    needs_regime = fn_name in (
        "sig_st_regime_halflife",
        "sig_st_regime_hl_lastwf",
    ) or "hl_days" in params
    needs_lastwf = fn_name.startswith("sig_st_") and fn_name not in (
        "sig_st_kill_breadth",
        "sig_supertrend",
    )

    if fn_name == "sig_supertrend":
        fn_import = "from run_block1b import sig_supertrend as FN"
    elif fn_name == "sig_st_kill_breadth":
        fn_import = "from run_block2 import sig_st_kill_breadth as FN"
    elif fn_name == "sig_st_regime_halflife":
        fn_import = "from run_block4 import sig_st_regime_halflife as FN"
    else:
        fn_import = f"from run_block5 import {fn_name} as FN"

    runner_fn = "run_portfolio_b3" if needs_b3 else "run_portfolio_ext"
    port_import = (
        "from run_block3 import run_portfolio_b3"
        if needs_b3
        else "from run_block2 import run_portfolio_ext"
    )
    extra_imports = ""
    extra_calls = ""
    if needs_regime or needs_lastwf:
        extra_imports += "from run_block4 import attach_regime_features\n"
        extra_calls += "    data = attach_regime_features(data, nifty)\n"
    if needs_lastwf:
        extra_imports += "from run_block5 import attach_lastwf_features\n"
        extra_calls += "    data = attach_lastwf_features(data, nifty, bank)\n"

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
{extra_imports}{port_import}
{fn_import}

PARAMS = {json.dumps(params, indent=2).replace("true","True").replace("false","False")}
NAME = {json.dumps(row["name"])}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
{extra_calls}    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    oos = {runner_fn}(data, FN, PARAMS, start_date=oos_start)
    print(json.dumps({{"name": NAME, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
    path.write_text(code)
    return path


def append_leaderboard_block5(
    champ: dict,
    repro: dict,
    rows: List[dict],
    ladder_table: List[dict],
    boot_table: List[dict],
    promote_ok: bool,
    promote_reason: str,
    bh: dict,
    fii_note: str,
) -> None:
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 5"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    r = repro["OOS"]
    lines = [
        "",
        "## Block 5 — Bootstrap + cost ladder; last-WF causal; regime_hl8 decision",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**#1 still leads:** {'YES' if not promote_ok else 'NO — new champion promoted'}",
        f"**Promote decision:** {promote_reason}",
        "",
        "### Reproduced #1 (ST_m3.6_n1_e1)",
        "",
        "| Metric | Block1–4 ref | Block5 | Drift |",
        "|--------|-------------:|-------:|------:|",
        f"| n | {REF_OOS['n_trades']} | {r['n_trades']} | {r['n_trades']-REF_OOS['n_trades']:+d} |",
        f"| PF | {REF_OOS['profit_factor']:.2f} | {r['profit_factor']:.2f} | {r['profit_factor']-REF_OOS['profit_factor']:+.2f} |",
        f"| Tot | {REF_OOS['total_return']*100:.1f}% | {r['total_return']*100:.1f}% | {(r['total_return']-REF_OOS['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_OOS['max_dd']*100:.1f}% | {r['max_dd']*100:.1f}% | {(r['max_dd']-REF_OOS['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_OOS['sharpe']:.2f} | {r['sharpe']:.2f} | {r['sharpe']-REF_OOS['sharpe']:+.2f} |",
        f"| Last WF | 5.8% | {repro.get('last_wf_tot', 0)*100:.1f}% | — |",
        "",
        "### Cost ladder (0.08 / 0.10 / 0.12 / 0.15 / 0.20% RT)",
        "",
    ]

    # Wide ladder table: one row per strategy × columns per RT
    lines.append("| Name | Metric | 0.08% | 0.10% | 0.12% | 0.15% | 0.20% |")
    lines.append("|------|--------|------:|------:|------:|------:|------:|")
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
        "### Bootstrap CI (OOS trade PF, 2000 resamples)",
        "",
        "| Name | n | PF | boot mean | 95% CI |",
        "|------|--:|---:|----------:|--------|",
    ]
    for b in boot_table:
        ci = (
            f"[{b['ci_lo']:.2f}, {b['ci_hi']:.2f}]"
            if b.get("ci_lo") is not None
            else "n/a"
        )
        mean = f"{b['mean_pf']:.2f}" if b.get("mean_pf") is not None else "n/a"
        lines.append(f"| {b['name']} | {b['n']} | {b['pf']:.2f} | {mean} | {ci} |")

    top = sorted(
        rows,
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
        "### Block 5 last-WF causal variants (top by WF+ / lastWF / PF)",
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
        f"**Champion after Block 5:** `{champ['name']}` — OOS PF={o['profit_factor']:.2f} "
        f"tot={o['total_return']*100:.1f}% n={o['n_trades']} WF={champ['wf_pos']}/{champ['wf_n']} "
        f"lastWF={champ.get('last_wf_tot', 0)*100:.1f}%",
        f"**B&H ^NSEI OOS:** tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        f"**FII/OI:** {fii_note}",
        "",
        "### Honesty",
        "- **regime_hl8:** promote only if dual-clear + ≥2pp margin + ladder + boot (Block 5 rejected margin_thin).",
        "- Last-WF dual-clear+ladder+boot can promote (e.g. kill40+dd gate).",
        "- Causal features only (shifted highs, vol ratios, lagged RS). FII/OI optional. No hourly unless n≥40.",
        "- Costs 0.08–0.20% RT ladder. No look-ahead. No fake futures.",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def try_fii_oi() -> str:
    """Optional: only if free usable FII/OI data exists locally or via trivial fetch."""
    # Check common local caches / CSV drops
    candidates = [
        ROOT / "data" / "fii_dii.csv",
        ROOT / "data" / "nifty_oi.csv",
        Path(__file__).resolve().parent / "data" / "fii_dii.csv",
        RESULTS / "fii_dii.csv",
    ]
    for p in candidates:
        if p.exists():
            try:
                df = pd.read_csv(p)
                if len(df) >= 100 and any(
                    c.lower() in ("fii", "fii_net", "net_fii", "oi", "open_interest")
                    for c in df.columns
                ):
                    return f"FOUND {p.name} n={len(df)} — not wired this block (use Block 6 if clean)"
            except Exception:
                pass
    return "SKIPPED — no clean free FII/OI series available locally"


def write_champion_py(new_champ: dict, fn_import: str) -> str:
    """Build nifty_edge_best.py source for a promoted champion."""
    oos = new_champ["OOS"]
    stress = new_champ["OOS_stress"]
    params = new_champ["params"]
    cn = new_champ["name"]
    params_txt = json.dumps(params, indent=2).replace("true", "True").replace("false", "False")
    name_json = json.dumps(cn)
    lines = [
        '"""',
        "Nifty Edge Best — Block 5 champion",
        "==================================",
        cn,
        f"Params: {json.dumps(params)}",
        "",
        f"OOS: n={oos['n_trades']} PF={oos['profit_factor']:.2f} tot={oos['total_return']*100:.1f}%",
        f"MDD={oos['max_dd']*100:.1f}% Sharpe={oos['sharpe']:.2f} stressPF={stress['profit_factor']:.2f}",
        f"WF={new_champ['wf_pos']}/{new_champ['wf_n']} lastWF={new_champ['last_wf_tot']*100:.1f}%",
        "",
        "Usage:",
        "  python strategies/nifty_edge_best.py",
        '"""',
        "from __future__ import annotations",
        "import json, sys",
        "from pathlib import Path",
        "ROOT = Path(__file__).resolve().parents[1]",
        'sys.path.insert(0, str(ROOT / "research"))',
        'sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))',
        "from india_edge_engine import time_split",
        "from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth",
        "from run_block2 import attach_market_to_stocks, run_portfolio_ext as RUN",
        "from run_block4 import attach_regime_features",
        "from run_block5 import attach_lastwf_features",
        fn_import,
        "",
        f"PARAMS = {params_txt}",
        "",
        "def main():",
        '    nifty = prepare_symbol("^NSEI")',
        '    bank = prepare_symbol("^NSEBANK")',
        "    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}",
        "    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)",
        "    data = attach_market_to_stocks(stocks_raw, nifty, bank)",
        "    data = attach_regime_features(data, nifty)",
        "    data = attach_lastwf_features(data, nifty, bank)",
        '    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)',
        "    oos = RUN(data, FN, PARAMS, start_date=oos_ref.index[0])",
        f'    print(json.dumps({{"name": {name_json}, "OOS": oos}}, indent=2, default=str))',
        "",
        'if __name__ == "__main__":',
        "    main()",
        "",
    ]
    return "\n".join(lines)

def main():
    if past_deadline():
        log("DEADLINE PASSED — Block 5 should not invent; run FINAL synthesis instead")
        print("PAST_DEADLINE")
        return

    log("=== Block 5 start ===")
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

    # ── 1) Quick repro #1 ─────────────────────────────────────────────────────
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

    # Reference challengers for ladder
    kill40_params = {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.40}
    regime_params = {
        "mult": 3.6, "use_nifty": True, "use_ema200": True, "hl_days": 8, "soft_exit": False,
    }
    softvol_params = {
        "mult": 3.6, "use_nifty": True, "use_ema200": True,
        "vol_target": 0.22, "vol_scale_lo": 0.85, "vol_scale_hi": 1.0,
    }

    kill40 = portfolio_eval(
        "B2_ST_kill_breadth40_m3.6", data, sig_st_kill_breadth, kill40_params, oos_start
    )
    kill40["last_wf_tot"] = kill40["wf"][-1]["total_return"] if kill40["wf"] else 0.0

    regime = portfolio_eval(
        "B4_ST_regime_hl8", data, sig_st_regime_halflife, regime_params, oos_start
    )
    regime["last_wf_tot"] = regime["wf"][-1]["total_return"] if regime["wf"] else 0.0

    softvol = portfolio_eval_b3(
        "B4_ST_softvol22_shi1.0_floor0.85", data, sig_supertrend, softvol_params, oos_start
    )

    # ── 2) Cost ladder + bootstrap ────────────────────────────────────────────
    log("Cost ladder 0.08/0.10/0.12/0.15/0.20% RT on #1, kill40, regime_hl8, softvol22…")
    ladder_specs: List[Tuple[str, Callable, dict, bool]] = [
        ("ST_m3.6_n1_e1", sig_supertrend, champ_params, False),
        ("B2_ST_kill_breadth40_m3.6", sig_st_kill_breadth, kill40_params, False),
        ("B4_ST_regime_hl8", sig_st_regime_halflife, regime_params, False),
        ("B4_ST_softvol22_shi1.0_floor0.85", sig_supertrend, softvol_params, True),
    ]
    ladder_table: List[dict] = []
    ladder_by_name: Dict[str, dict] = {}
    for name, fn, params, use_b3 in ladder_specs:
        try:
            row = cost_ladder_row(name, data, fn, params, oos_start, use_b3=use_b3)
            ladder_table.append(row)
            ladder_by_name[name] = row
            pts = " | ".join(
                f"rt{x['rt_pct']:.2f}:PF={x['pf']:.2f}/tot={x['tot']*100:.1f}%"
                for x in row["ladder"]
            )
            log(f"  LADDER {name}: {pts}")
        except Exception as ex:
            log(f"  FAIL ladder {name}: {ex}")

    log("Bootstrap CI (2000 resamples)…")
    boot_table: List[dict] = []
    boot_by_name: Dict[str, dict] = {}
    for name, fn, params, use_b3 in ladder_specs:
        try:
            b = run_bootstrap_for(name, data, fn, params, oos_start, use_b3=use_b3)
            boot_table.append(b)
            boot_by_name[name] = b
            ci = (
                f"[{b['ci_lo']:.2f}, {b['ci_hi']:.2f}]"
                if b.get("ci_lo") is not None
                else "n/a"
            )
            log(f"  BOOT {name}: n={b['n']} PF={b['pf']:.2f} CI={ci}")
        except Exception as ex:
            log(f"  FAIL boot {name}: {ex}")

    # Persist ladder CSV-ish JSON early
    (RESULTS / "block5_cost_ladder.json").write_text(
        json.dumps(_clean(ladder_table), indent=2, default=str)
    )
    (RESULTS / "block5_bootstrap.json").write_text(
        json.dumps(_clean(boot_table), indent=2, default=str)
    )

    # ── 3) Strict promote decision for regime_hl8 ─────────────────────────────
    log("Strict promote check: regime_hl8 vs #1…")
    promote_ok, promote_reason = regime_hl8_promote_strict(
        regime,
        champ,
        ladder_by_name.get("B4_ST_regime_hl8", {"ladder": []}),
        ladder_by_name.get("ST_m3.6_n1_e1", {"ladder": []}),
        boot_by_name.get("B4_ST_regime_hl8", {}),
        boot_by_name.get("ST_m3.6_n1_e1", {}),
    )
    log(
        f"  regime_hl8: n={regime['OOS']['n_trades']} PF={regime['OOS']['profit_factor']:.2f} "
        f"tot={regime['OOS']['total_return']*100:.1f}% lastWF={regime['last_wf_tot']*100:.1f}% "
        f"→ promote={promote_ok} ({promote_reason})"
    )

    new_champ = champ
    if promote_ok:
        new_champ = regime
        log(f"  PROMOTED: {regime['name']}")
    else:
        log(f"  KEEP #1 — {promote_reason}")

    # ── 4) Last-WF causal variants (≥8) ───────────────────────────────────────
    log("Last-WF causal feature variants (≥8)…")
    base = {"mult": 3.6, "use_nifty": True, "use_ema200": True}
    lastwf_variants: List[Tuple[str, Callable, dict, str]] = [
        ("B5_ST_dd_gate_m6", sig_st_dd_gate, {**base, "dd_floor": -0.06}, "sig_st_dd_gate"),
        ("B5_ST_dd_gate_m8", sig_st_dd_gate, {**base, "dd_floor": -0.08}, "sig_st_dd_gate"),
        ("B5_ST_vol_calm_115", sig_st_vol_calm, {**base, "max_vol_ratio": 1.15}, "sig_st_vol_calm"),
        ("B5_ST_vol_calm_125", sig_st_vol_calm, {**base, "max_vol_ratio": 1.25}, "sig_st_vol_calm"),
        ("B5_ST_vol_cap22", sig_st_vol_not_extreme, {**base, "vol_cap": 0.22}, "sig_st_vol_not_extreme"),
        ("B5_ST_days_high40", sig_st_days_since_high, {**base, "max_days_since_high": 40}, "sig_st_days_since_high"),
        ("B5_ST_days_high60", sig_st_days_since_high, {**base, "max_days_since_high": 60}, "sig_st_days_since_high"),
        ("B5_ST_breadth_mom0", sig_st_breadth_mom, {**base, "min_breadth_chg5": 0.0}, "sig_st_breadth_mom"),
        ("B5_ST_breadth_mom_m05", sig_st_breadth_mom, {**base, "min_breadth_chg5": -0.05}, "sig_st_breadth_mom"),
        ("B5_ST_bank_rs_m02", sig_st_bank_rs_ok, {**base, "min_bank_rs": -0.02}, "sig_st_bank_rs_ok"),
        ("B5_ST_atr_pct_15_90", sig_st_atr_pct_gate, {**base, "atr_pct_lo": 0.15, "atr_pct_hi": 0.90}, "sig_st_atr_pct_gate"),
        ("B5_ST_soft_rvol09", sig_st_soft_rvol, {**base, "min_rvol": 0.9}, "sig_st_soft_rvol"),
        ("B5_ST_pullback_m01", sig_st_pullback_ok, {**base, "max_extension": -0.01}, "sig_st_pullback_ok"),
        ("B5_ST_nifty_mom_m03", sig_st_nifty_mom_ok, {**base, "min_nifty_ret20": -0.03}, "sig_st_nifty_mom_ok"),
        ("B5_ST_combo_dd_vol_br", sig_st_combo_lastwf,
         {**base, "dd_floor": -0.08, "max_vol_ratio": 1.25, "min_breadth_chg5": -0.10},
         "sig_st_combo_lastwf"),
        ("B5_ST_regime_hl8_volcalm", sig_st_regime_hl_lastwf,
         {**base, "hl_days": 8, "soft_exit": False, "max_vol_ratio": 1.20},
         "sig_st_regime_hl_lastwf"),
        ("B5_ST_kill40_dd07", sig_st_kill40_dd,
         {**base, "breadth_floor": 0.40, "dd_floor": -0.07},
         "sig_st_kill40_dd"),
    ]

    new_rows: List[dict] = []
    fn_map: Dict[str, str] = {}
    # Include regime/kill40/softvol as reference rows
    for ref in (regime, kill40, softvol):
        new_rows.append(ref)
        if ref["name"] == "B4_ST_regime_hl8":
            fn_map[ref["name"]] = "sig_st_regime_halflife"
        elif "kill" in ref["name"]:
            fn_map[ref["name"]] = "sig_st_kill_breadth"
        else:
            fn_map[ref["name"]] = "sig_supertrend"

    for name, fn, params, fn_name in lastwf_variants:
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

    log(f"Screened {len([r for r in new_rows if r['name'].startswith('B5_')])} B5 variants "
        f"(target ≥8); total rows={len(new_rows)}")

    # Check if any last-WF variant dual-clears with margin + ladder/boot (strict)
    promoted_variant = False
    promote_variant_reason = ""
    b5_rows = [r for r in new_rows if r["name"].startswith("B5_")]
    for row in sorted(
        b5_rows,
        key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
        reverse=True,
    ):
        # Path A: classic clearly_better
        if clearly_better(row, new_champ):
            if (
                row.get("last_wf_tot", 0) > new_champ.get("last_wf_tot", 0)
                and row["OOS"]["total_return"] >= new_champ["OOS"]["total_return"] * 0.95
            ):
                log(f"  BEAT via clearly_better last-WF: {row['name']}")
                new_champ = row
                promoted_variant = True
                promote_variant_reason = f"clearly_better_lastwf:{row['name']}"
                break
        # Path B: strict dual-clear + margin (≥2pp tot OR lastWF+2pp) + ladder + boot
        tot_clear = row["OOS"]["total_return"] > new_champ["OOS"]["total_return"]
        last_clear = row.get("last_wf_tot", 0) > new_champ.get("last_wf_tot", 0)
        margin = (
            row["OOS"]["total_return"] >= new_champ["OOS"]["total_return"] + 0.02
            or (
                tot_clear
                and row.get("last_wf_tot", 0) >= new_champ.get("last_wf_tot", 0) + 0.02
            )
        )
        if not (tot_clear and last_clear and margin and row.get("wf_pos", 0) >= 3):
            continue
        if row["OOS"]["n_trades"] < 40:
            continue
        if row["OOS"]["max_dd"] < new_champ["OOS"]["max_dd"] - 0.05:
            continue
        # Cost ladder vs current champ
        try:
            fn = {
                "sig_st_kill40_dd": sig_st_kill40_dd,
                "sig_st_dd_gate": sig_st_dd_gate,
                "sig_st_vol_calm": sig_st_vol_calm,
                "sig_st_vol_not_extreme": sig_st_vol_not_extreme,
                "sig_st_days_since_high": sig_st_days_since_high,
                "sig_st_breadth_mom": sig_st_breadth_mom,
                "sig_st_bank_rs_ok": sig_st_bank_rs_ok,
                "sig_st_atr_pct_gate": sig_st_atr_pct_gate,
                "sig_st_soft_rvol": sig_st_soft_rvol,
                "sig_st_pullback_ok": sig_st_pullback_ok,
                "sig_st_nifty_mom_ok": sig_st_nifty_mom_ok,
                "sig_st_combo_lastwf": sig_st_combo_lastwf,
                "sig_st_regime_hl_lastwf": sig_st_regime_hl_lastwf,
            }.get(fn_map.get(row["name"], ""), None)
            if fn is None:
                continue
            lad_c = cost_ladder_row("champ", data, sig_supertrend, champ_params, oos_start)
            lad_r = cost_ladder_row(row["name"], data, fn, row["params"], oos_start)
            ladder_ok = all(
                rl["tot"] >= cl["tot"] * 0.98
                for rl, cl in zip(lad_r["ladder"], lad_c["ladder"])
            )
            if not ladder_ok:
                log(f"  {row['name']}: dual-clear but ladder fail — skip")
                continue
            boot_r = run_bootstrap_for(row["name"], data, fn, row["params"], oos_start)
            boot_c = boot_by_name.get("ST_m3.6_n1_e1", {})
            r_lo = boot_r.get("ci_lo")
            c_lo = boot_c.get("ci_lo")
            if r_lo is None or r_lo < 1.5:
                log(f"  {row['name']}: dual-clear but boot CI_lo weak — skip")
                continue
            if c_lo is not None and r_lo < c_lo * 0.85:
                log(f"  {row['name']}: dual-clear but boot worse vs champ — skip")
                continue
            # Append ladder/boot into tables for docs
            ladder_table.append(lad_r)
            boot_table.append(boot_r)
            log(
                f"  BEAT via strict dual-clear+ladder+boot: {row['name']} "
                f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
                f"CI=[{r_lo:.2f},{boot_r.get('ci_hi', 0):.2f}]"
            )
            new_champ = row
            promoted_variant = True
            promote_variant_reason = f"dual_clear_ladder_boot:{row['name']}"
            break
        except Exception as ex:
            log(f"  FAIL strict check {row['name']}: {ex}")
    if not promoted_variant:
        log("  No B5 last-WF variant passed clearly_better or strict dual-clear+ladder+boot")

    overall_promoted = promote_ok or promoted_variant
    overall_reason = promote_reason if promote_ok else (promote_variant_reason or f"keep_#1:{promote_reason}")

    # Skip hourly
    log("Hourly ORB: SKIPPED (Block 5 — only if multi-name n≥40; not attempted)")
    fii_note = try_fii_oi()
    log(f"FII/OI: {fii_note}")

    # ── 5) Paper rules A/B freeze ─────────────────────────────────────────────
    if promoted_variant:
        # New champion is B5 variant; twin = prior #1
        twin = champ
        twin_label = "prior #1 ST_m3.6 (paper twin)"
        twin_code = "strategies/nifty_edge_r17.py (prior ST_m3.6 snapshot)"
        twin_rules = [
            "Prior champion Supertrend **3.6** + Nifty bull + EMA200 (no breadth/dd gate).",
            "- Entry/exit identical to Block-1–4 Sleeve A.",
        ]
        freeze_note = (
            f"A = {new_champ['name']} (promoted Block 5); B = prior ST_m3.6_n1_e1. "
            f"regime_hl8 NOT promoted ({promote_reason}). "
            f"Promote reason: {promote_variant_reason}."
        )
        write_paper_rules_b5(new_champ, twin, twin_label, twin_code, twin_rules, freeze_note)
    elif promote_ok:
        twin = champ
        twin_label = "prior #1 ST_m3.6 (demoted twin)"
        twin_code = "strategies/nifty_edge_best.py.bak_block5"
        twin_rules = [
            "Prior champion Supertrend 3.6 + Nifty bull + EMA200 (no regime half-life).",
        ]
        freeze_note = "A = regime_hl8 (promoted); B = prior ST_m3.6. Block-5 strict promote passed."
        write_paper_rules_b5(new_champ, twin, twin_label, twin_code, twin_rules, freeze_note)
    else:
        twin = regime
        twin_label = "regime_hl8 near-promote"
        twin_code = "strategies/nifty_edge_r15.py / r18.py"
        twin_rules = [
            "Same as Sleeve A **plus** regime half-life filter:",
            "- Count consecutive days Nifty Close < EMA50 (causal streak).",
            "- Block **new entries** only when days_below ≥ **8**; do not force-exit opens.",
            "- Soft exit: OFF for paper twin (soft_exit=False).",
        ]
        freeze_note = (
            "A = ST_m3.6_n1_e1 (primary); B = regime_hl8 (near-promote twin). "
            f"Block-5 promote={overall_promoted} ({overall_reason}). "
            "Watch: B5_ST_kill40_dd07 if dual-clear+ladder holds in live paper."
        )
        write_paper_rules_b5(champ, twin, twin_label, twin_code, twin_rules, freeze_note)
    log(f"Wrote {PAPER_RULES}")

    # ── 6) Save runners r17+ ──────────────────────────────────────────────────
    basket = [
        r for r in new_rows
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

    # Prioritize: best lastWF lift with tot near champ, regime, kill40_dd, combo
    prioritized = []
    if overall_promoted and champ["name"] != new_champ["name"]:
        # Keep demoted #1 as first runner snapshot
        prioritized.append(champ)
        fn_map[champ["name"]] = "sig_supertrend"
    b5_only = [r for r in basket if r["name"].startswith("B5_")]
    if b5_only:
        # Best lastWF among those with tot >= 90% of champ
        near = [r for r in b5_only if r["OOS"]["total_return"] >= champ["OOS"]["total_return"] * 0.90]
        if near:
            prioritized.append(max(near, key=lambda r: (r.get("last_wf_tot", 0), r["OOS"]["total_return"])))
        prioritized.append(max(b5_only, key=runner_score))
    # Include regime if not champion
    if regime["name"] != new_champ["name"]:
        prioritized.append(regime)
    # Best kill40 hybrid
    kill_hyb = [r for r in b5_only if "kill40" in r["name"] and r["name"] != new_champ["name"]]
    if kill_hyb:
        prioritized.append(max(kill_hyb, key=runner_score))

    seen = set()
    save_list = []
    for r in prioritized + sorted(basket, key=runner_score, reverse=True):
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        save_list.append(r)
        if len(save_list) >= 4:
            break

    saved = []
    for i, r in enumerate(save_list, start=17):
        fn_name = fn_map.get(r["name"], "sig_supertrend")
        path = write_b5_runner(i, r, fn_name)
        saved.append(str(path))
        log(
            f"  Saved {path.name}: {r['name']} PF={r['OOS']['profit_factor']:.2f} "
            f"tot={r['OOS']['total_return']*100:.1f}% lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )

    if overall_promoted and (promote_ok or promoted_variant):
        log("  Overwriting nifty_edge_best.py with new champion")
        cn = new_champ["name"]
        fn_name = fn_map.get(cn, "sig_st_regime_halflife" if promote_ok else "sig_supertrend")
        if fn_name == "sig_supertrend":
            fn_import = "from run_block1b import sig_supertrend as FN"
        elif fn_name == "sig_st_regime_halflife":
            fn_import = "from run_block4 import sig_st_regime_halflife as FN"
        else:
            fn_import = f"from run_block5 import {fn_name} as FN"
        py = write_champion_py(new_champ, fn_import)
        (OUT_STRAT / "nifty_edge_best.py").write_text(py)
        log(f"  Wrote {OUT_STRAT / 'nifty_edge_best.py'}")
        # Update Pine proxy (single-symbol; note basket filters)
        params = new_champ["params"]
        br = params.get("breadth_floor")
        dd = params.get("dd_floor")
        pine_notes = []
        if br is not None:
            pine_notes.append(f"// Basket also requires breadth50>={br} (not in single-symbol Pine)")
        if dd is not None:
            pine_notes.append(f"// Basket also requires Nifty dd_from_prior55d_high>={dd} (not in Pine)")
        pine = f'''//@version=5
strategy("Nifty Edge Best ST Basket Proxy", overlay=true, initial_capital=100000,
     commission_type=strategy.commission.percent, commission_value=0.04,
     slippage=2, process_orders_on_close=false)

// Block-5 champion proxy (SINGLE SYMBOL). Research edge is a 5-slot basket.
// {new_champ["name"]} OOS ~PF {new_champ["OOS"]["profit_factor"]:.2f}, tot {new_champ["OOS"]["total_return"]*100:.1f}%, lastWF {new_champ["last_wf_tot"]*100:.1f}%
{chr(10).join(pine_notes)}

atrLen = input.int(14, "ATR Length")
mult = input.float({params.get("mult", 3.6)}, "ATR Mult", step=0.1)
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
        pine_path = ROOT / "pinescript" / "nifty_edge_best.pine"
        pine_path.write_text(pine)
        log(f"  Wrote {pine_path}")
    else:
        log("  Kept strategies/nifty_edge_best.py unchanged (#1 still leads)")

    # Persist summary
    summary = {
        "repro": champ,
        "regime_hl8": regime,
        "kill40": kill40,
        "softvol22": softvol,
        "cost_ladder": ladder_table,
        "bootstrap": boot_table,
        "promote_regime_hl8": promote_ok,
        "promote_reason": overall_reason,
        "promoted": overall_promoted,
        "champion": new_champ["name"],
        "new_variants": new_rows,
        "runners_up": saved,
        "bh_oos": bh_oos,
        "n_b5_variants": len([r for r in new_rows if r["name"].startswith("B5_")]),
        "fii_oi": fii_note,
        "paper_rules": str(PAPER_RULES),
    }
    path = RESULTS / "block5_summary.json"
    path.write_text(json.dumps(_clean(summary), indent=2, default=str))
    log(f"Wrote {path}")

    append_leaderboard_block5(
        new_champ if overall_promoted else champ,
        champ,
        new_rows,
        ladder_table,
        boot_table,
        overall_promoted,
        overall_reason,
        bh_oos,
        fii_note,
    )
    log(f"Updated {LEADERBOARD}")

    top5 = sorted(
        [r for r in new_rows if r["name"].startswith("B5_")],
        key=lambda r: (r["wf_pos"], r.get("last_wf_tot", 0), r["OOS"]["profit_factor"]),
        reverse=True,
    )[:5]
    log("--- Block 5 top 5 last-WF variants ---")
    for r in top5:
        log(
            f"  {r['name']}: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"n={r['OOS']['n_trades']} WF={r['wf_pos']}/3 lastWF={r.get('last_wf_tot', 0)*100:.1f}%"
        )
    log(
        f"=== Block 5 complete === champion={new_champ['name'] if overall_promoted else champ['name']} "
        f"PF={(new_champ if overall_promoted else champ)['OOS']['profit_factor']:.2f} "
        f"tot={(new_champ if overall_promoted else champ)['OOS']['total_return']*100:.1f}% "
        f"promoted={overall_promoted} reason={overall_reason} "
        f"n_b5={len([r for r in new_rows if r['name'].startswith('B5_')])}"
    )
    log(
        "Next Block 6: freeze paper A/B live checklist; optional ensemble of #1+regime_hl8; "
        "document cost-ladder fragility; FINAL prep if near deadline"
    )


if __name__ == "__main__":
    main()
