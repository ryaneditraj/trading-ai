#!/usr/bin/env python3
"""
Block 8 — Repro new champ; expand A/B mom-skip notes; probe r29;
locked-sleeve cost shock; ≥5 checks; FINAL outline (full FINAL if <1h).

Mandatory:
  1) Repro B6_ST_kill40_dd_nifty_mom_m04; confirm drift_ok
  2) Expand paper A vs B mom-skip save-rate / weekly ΔEquity in CHECKLIST
  3) Probe r29 mom_days60 vs A — promote only dual-clear OR robust risk-adj
  4) Locked-sleeve cost shock (0.08–0.20%) on A and r29 only
  5) ≥5 measured checks; update board/log; r30+ if needed
  6) Full FINAL only if <1h to deadline; else keep outline fresh

Usage:
  python research/nifty_edge_8h/run_block8.py
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
from run_block5 import (  # noqa: E402
    COST_LADDER,
    attach_lastwf_features,
    cost_ladder_row,
    run_bootstrap_for,
    sig_st_kill40_dd,
)
from run_block6 import (  # noqa: E402
    hours_to_deadline,
    sig_st_kill40_dd_days,
    sig_st_kill40_dd_nifty_mom,
    sig_st_kill40_dd_volcalm,
    write_full_final_if_needed,
)
from run_block7 import (  # noqa: E402
    robust_risk_adj_promote,
    sig_st_kill40_dd_mom_days,
    sig_st_kill40_dd_pullback,
    sig_st_kill40_dd_ret5,
)

OUT_STRAT = ROOT / "strategies"
PAPER_RULES = Path(__file__).resolve().parent / "PAPER_TRADE_RULES.md"
CHECKLIST = Path(__file__).resolve().parent / "CHECKLIST.md"
FINAL_OUTLINE = Path(__file__).resolve().parent / "FINAL_REPORT_OUTLINE.md"
FINAL_REPORT = Path(__file__).resolve().parent / "FINAL_REPORT.md"

# New Block-7 champion references
REF_CHAMP = {
    "n_trades": 64,
    "profit_factor": 4.73,
    "expectancy": 0.0711,
    "total_return": 1.243,
    "max_dd": -0.130,
    "sharpe": 1.24,
}
REF_LAST_WF = 0.092

CHAMP_PARAMS = {
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
R29_PARAMS = {
    **CHAMP_PARAMS,
    "max_days_since_high": 60,
}
MOM_FLOOR = -0.04


def signal_day_for_entry(entry: pd.Timestamp, index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    """Entry is next-open fill; signal was prior session in the calendar."""
    idx = index.searchsorted(entry)
    if idx <= 0:
        return None
    # entry may land on index; signal is previous bar
    if idx < len(index) and index[idx] == entry:
        return index[idx - 1]
    pos = index.searchsorted(entry, side="left")
    if pos <= 0:
        return None
    return index[pos - 1]


def analyze_mom_skips(
    data: Dict[str, pd.DataFrame],
    oos_start,
    b_trades: List[dict],
    mom_floor: float = MOM_FLOOR,
) -> dict:
    """
    Historical OOS mom-skip analysis: B trades where nifty_ret20 < mom_floor
    at signal close would be A-only skips. Save-rate = losers / skips.
    """
    # Use any stock frame for nifty_ret20 (broadcast)
    sample = next(iter(data.values()))
    nifty_ret20 = sample["nifty_ret20"] if "nifty_ret20" in sample.columns else None
    if nifty_ret20 is None:
        return {"n_skips": 0, "error": "nifty_ret20 missing"}

    # Build a shared calendar from union
    cal = sample.index
    skips = []
    for t in b_trades:
        entry = pd.Timestamp(t["entry"])
        sig_dt = signal_day_for_entry(entry, cal)
        if sig_dt is None or sig_dt not in nifty_ret20.index:
            # try symbol-specific frame
            sym = t.get("symbol")
            if sym and sym in data and "nifty_ret20" in data[sym].columns:
                cal_s = data[sym].index
                sig_dt = signal_day_for_entry(entry, cal_s)
                if sig_dt is None or sig_dt not in data[sym].index:
                    continue
                r20 = float(data[sym]["nifty_ret20"].loc[sig_dt])
            else:
                continue
        else:
            r20 = float(nifty_ret20.loc[sig_dt])
        if np.isnan(r20):
            continue
        if r20 < mom_floor:
            ret = float(t["ret"])
            skips.append(
                {
                    "symbol": t.get("symbol"),
                    "entry": str(pd.Timestamp(t["entry"]).date()),
                    "exit": str(pd.Timestamp(t["exit"]).date()),
                    "sig_dt": str(pd.Timestamp(sig_dt).date()),
                    "nifty_ret20": r20,
                    "ret": ret,
                    "winner": ret > 0,
                    "loser": ret <= 0,
                }
            )

    n = len(skips)
    n_win = sum(1 for s in skips if s["winner"])
    n_lose = sum(1 for s in skips if s["loser"])
    save_rate = n_lose / n if n else None
    hit_rate = n_win / n if n else None  # skip-winners = over-filter signal
    avg_skip_ret = float(np.mean([s["ret"] for s in skips])) if n else None
    return {
        "n_skips": n,
        "n_winners_skipped": n_win,
        "n_losers_skipped": n_lose,
        "save_rate": save_rate,
        "hit_rate_overfilter": hit_rate,
        "avg_skip_ret": avg_skip_ret,
        "mom_floor": mom_floor,
        "skips": skips,
        "justify_gate": (save_rate is not None and save_rate >= 0.50 and n >= 1),
        "overfilter_flag": (hit_rate is not None and hit_rate > 0.60 and n >= 20),
    }


def weekly_equity_delta(
    eq_a: pd.Series, eq_b: pd.Series
) -> dict:
    """Weekly ΔEquity A−B (Friday-close / week-end resample)."""
    if eq_a is None or eq_b is None or len(eq_a) < 5 or len(eq_b) < 5:
        return {"n_weeks": 0, "error": "thin equity"}
    # Align
    idx = eq_a.index.intersection(eq_b.index)
    a = eq_a.reindex(idx).ffill()
    b = eq_b.reindex(idx).ffill()
    # Weekly last observation
    wa = a.resample("W-FRI").last().dropna()
    wb = b.resample("W-FRI").last().dropna()
    common = wa.index.intersection(wb.index)
    wa, wb = wa.loc[common], wb.loc[common]
    if len(wa) < 2:
        return {"n_weeks": len(wa), "error": "need ≥2 weeks"}
    # Weekly returns
    ra = wa.pct_change().dropna()
    rb = wb.pct_change().dropna()
    common_r = ra.index.intersection(rb.index)
    ra, rb = ra.loc[common_r], rb.loc[common_r]
    delta = ra - rb  # A − B weekly
    # Count consecutive weeks where B beats A by >2pp
    b_beats = (rb - ra) > 0.02
    max_consec = 0
    cur = 0
    for v in b_beats.values:
        if v:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0
    weeks = []
    for dt in common_r:
        weeks.append(
            {
                "week": str(dt.date()),
                "a_ret": float(ra.loc[dt]),
                "b_ret": float(rb.loc[dt]),
                "delta_a_minus_b": float(delta.loc[dt]),
            }
        )
    return {
        "n_weeks": int(len(common_r)),
        "mean_delta_pp": float(delta.mean() * 100),
        "median_delta_pp": float(delta.median() * 100),
        "weeks_a_ahead": int((delta > 0).sum()),
        "weeks_b_ahead": int((delta < 0).sum()),
        "max_consec_b_beats_gt2pp": int(max_consec),
        "flag_3w_b_lead": bool(max_consec >= 3),
        "trailing_4w_delta_pp": float(delta.iloc[-4:].sum() * 100) if len(delta) >= 4 else None,
        "weeks": weeks[-12:],  # last 12 for checklist
    }


def dual_clear(challenger: dict, champ: dict) -> bool:
    r, c = challenger["OOS"], champ["OOS"]
    return bool(
        r["total_return"] > c["total_return"]
        and float(challenger.get("last_wf_tot", 0)) > float(champ.get("last_wf_tot", 0))
    )


def ladder_beats_champ(lad_r: dict, lad_c: dict) -> bool:
    for rl, cl in zip(lad_r["ladder"], lad_c["ladder"]):
        if rl["tot"] < cl["tot"] * 0.98 or rl["pf"] < 1.5:
            return False
    return True


def expand_checklist(
    champ: dict,
    prior_b: dict,
    mom: dict,
    weekly: dict,
    hrs_left: float,
) -> None:
    co, po = champ["OOS"], prior_b["OOS"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sr = mom.get("save_rate")
    hr = mom.get("hit_rate_overfilter")
    sr_s = f"{sr*100:.0f}%" if sr is not None else "n/a"
    hr_s = f"{hr*100:.0f}%" if hr is not None else "n/a"
    avg_s = (
        f"{mom['avg_skip_ret']*100:.2f}%"
        if mom.get("avg_skip_ret") is not None
        else "n/a"
    )
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
    for s in mom.get("skips", [])[:15]:
        tag = "SAVE" if s["loser"] else "MISS"
        skip_rows += (
            f"| {s['entry']} | {s['symbol']} | {s['nifty_ret20']*100:.2f}% | "
            f"{s['ret']*100:+.2f}% | {tag} |\n"
        )
    if not skip_rows:
        skip_rows = "| — | — | — | — | no OOS mom-skips |\n"

    text = f"""# Paper A vs B — Live Divergence Checklist

**Updated:** {now} (Block 8 — mom-skip + weekly ΔEquity expanded)
**Hours to deadline:** {hrs_left:.2f}
**Status:** Monitoring only — research paper sleeves. No look-ahead. No live capital.
**A (champ):** `{champ['name']}` — `strategies/nifty_edge_best.py` / `r21.py`
**B (twin):** `B5_ST_kill40_dd07` — `strategies/nifty_edge_b5_prior.py`
**Rules file:** `PAPER_TRADE_RULES.md`
**Historical ST:** `strategies/nifty_edge_r17.py` (optional third sleeve)

---

## What should differ (structural)

| Gate | Sleeve A | Sleeve B | Expected effect |
|------|----------|----------|-----------------|
| Breadth50 ≥ 0.40 | YES | YES | Shared |
| Nifty dd ≥ −7% (causal prior-55d) | YES | YES | Shared |
| Nifty ret20 ≥ −0.04 | YES | NO | A skips weak-mom entries |
| ST mult 3.6 + Nifty bull + EMA200 | YES | YES | Shared core trail |
| Exit | ST trail only | ST trail only | Same exit family |

OOS ref: A n={co['n_trades']} PF={co['profit_factor']:.2f} tot={co['total_return']*100:.1f}% lastWF={champ.get('last_wf_tot',0)*100:.1f}% Sharpe={co['sharpe']:.2f}
vs B n={po['n_trades']} PF={po['profit_factor']:.2f} tot={po['total_return']*100:.1f}% lastWF={prior_b.get('last_wf_tot',0)*100:.1f}% Sharpe={po['sharpe']:.2f}

---

## Block 8 — Historical mom-skip save-rate (OOS backfill)

Causal definition: B trade whose **signal-close** `nifty_ret20 < −0.04` would be skipped by A.
Under B Supertrend trail + 0.08% RT: loser = ret ≤ 0 (save), winner = ret > 0 (miss / over-filter).

| Metric | Value | Gate |
|--------|------:|------|
| A-only mom skips (OOS) | {mom.get('n_skips', 0)} | — |
| Losers skipped (saves) | {mom.get('n_losers_skipped', 0)} | — |
| Winners skipped (misses) | {mom.get('n_winners_skipped', 0)} | — |
| **Save-rate** | **{sr_s}** | Target ≥ 50% to justify mom gate |
| Hit-rate (skip-winners) | {hr_s} | Flag if > 60% over ≥20 skips |
| Avg skip ret (B trail) | {avg_s} | Prefer negative |
| Justify gate (hist)? | {"YES" if mom.get("justify_gate") else "NO / thin"} | — |
| Over-filter flag? | {"YES" if mom.get("overfilter_flag") else "NO"} | — |

### Mom-skip sample (up to 15)

| Entry | Symbol | Nifty ret20 | B trail ret | Tag |
|-------|--------|------------:|------------:|-----|
{skip_rows}
**Note:** Sample size {mom.get('n_skips', 0)} — if <20, treat rates as provisional; keep logging live.

---

## Block 8 — Weekly ΔEquity A−B (OOS backfill)

Weekly Friday-close equity returns; Δ = A − B.

| Metric | Value | Alert |
|--------|------:|-------|
| Weeks measured | {weekly.get('n_weeks', 0)} | — |
| Mean Δ (A−B) | {w_mean_s} | — |
| Weeks A ahead | {weekly.get('weeks_a_ahead', 0)} | — |
| Weeks B ahead | {weekly.get('weeks_b_ahead', 0)} | — |
| Max consec B>A by >2pp | {weekly.get('max_consec_b_beats_gt2pp', 0)} | Flag review if ≥3 |
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
| YYYY-MM-DD | | | mom / rank / — | | | | | |

### Skip taxonomy (A-only vs B)

1. **mom** — Nifty ret20 < −0.04 at signal close (B would have entered; A skips).
2. **rank/slot** — Signal ok but no free slot after ranking (not a gate divergence).
3. Shared br/dd skips should match both sleeves — if not, data bug.

### Fill hygiene

- Exit first, then entries (same cadence both sleeves).
- Entry fill = next open; exit fill = signal close.
- Log RT cost assumption 0.08% primary (also track 0.15% shadow P&L weekly).

---

## Weekly review (promote/demote signals)

Check every Friday close (or weekly bar):

1. **ΔEquity A−B (week):** if B beats A by >2pp for **3 consecutive weeks**, flag review (do not auto-flip). Hist max consec = {weekly.get('max_consec_b_beats_gt2pp', 0)}.
2. **Mom-skip hit-rate:** count A-only mom skips that would have been winners under B trail (≥ +RT). If skip-winners > 60% over ≥20 skips, mom gate may be over-filtering. Hist = {hr_s} on n={mom.get('n_skips', 0)}.
3. **Mom-skip save-rate:** A-only skips that would have been losers under B. Target save-rate ≥ 50% to justify mom gate. Hist = {sr_s}.
4. **Last-chunk proxy:** trailing 60 trading days tot A vs B — A should not lag by >5pp without a documented regime note.
5. **MDD gap:** if A MDD worse than B by >3pp peak-to-trough on paper, investigate mom interaction.
6. **No parameter tweak mid-paper** — only log; promote requires dual-clear + ladder + boot **or** documented robust risk-adj + ladder + boot.

### Flip criteria (research only — mirrors campaign)

Promote challenger→A only if:
- tot AND lastWF strictly better vs frozen A, **or**
- robust risk-adj: tot ≥ A+2pp AND Sharpe↑ AND MDD not worse AND stress PF≥A AND lastWF not regress AND WF=3/3
- plus cost ladder 0.08–0.20% holds and bootstrap CI_lo ≥ 1.5

---

## Alert thresholds (immediate log note)

| Alert | Threshold |
|-------|-----------|
| Mom silence | A has 0 entries for ≥15 sessions while B has ≥3 |
| Mom unused | A and B entry sets identical for ≥20 sessions (mom gate unused) |
| Trail mismatch | Same name exit day differs A vs B (should be rare — same ST) |
| Cost shadow | 0.15% RT week PnL flips A/B ranking vs 0.08% |

---

## Honesty

- Single-symbol Pine ≠ 5-slot basket.
- Causal features only (prior-55d high shifted; next-open entry; ret20 lag-safe).
- Checklist does not authorize live capital or mid-campaign param hunting.
- Block 7 promote used risk-adj path (lastWF tied) — watch live mom-skip save-rate closely.
- Block 8 OOS backfill is research evidence for the gate, not a live fill log.
"""
    CHECKLIST.write_text(text)

    if PAPER_RULES.exists():
        prev = PAPER_RULES.read_text()
        marker = "\n## Block 8 — Mom-skip / weekly ΔEquity"
        if marker in prev:
            prev = prev.split(marker)[0].rstrip() + "\n"
        # Also trim stale Block 7 pointer body if we append after it
        prev += (
            f"{marker}\n\n"
            f"**Updated:** {now}\n"
            f"- Expanded `CHECKLIST.md` with OOS mom-skip save-rate ({sr_s} on n={mom.get('n_skips', 0)}) "
            f"and weekly ΔEquity (mean {w_mean_s}).\n"
            f"- A remains `{champ['name']}`; B remains demoted B5.\n"
            f"- No mid-paper param tweak; promote only dual-clear or robust risk-adj + ladder + boot.\n"
        )
        PAPER_RULES.write_text(prev)


def write_b8_runner(idx: int, row: dict, fn_name: str) -> Path:
    path = OUT_STRAT / f"nifty_edge_r{idx}.py"
    oos = row["OOS"]
    params = row["params"]
    if fn_name == "sig_st_kill40_dd":
        fn_import = "from run_block5 import sig_st_kill40_dd as FN"
    elif fn_name in (
        "sig_st_kill40_dd_volcalm",
        "sig_st_kill40_dd_days",
        "sig_st_kill40_dd_nifty_mom",
        "sig_st_kill40_dd_volcap",
        "sig_st_kill40_dd_regime",
        "sig_st_kill40_dd_bankrs",
        "sig_st_kill40_dd_atr",
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


def append_leaderboard_block8(
    champ: dict,
    repro: dict,
    r29_row: dict,
    ladders: Dict[str, dict],
    mom: dict,
    weekly: dict,
    checks: List[dict],
    promote_ok: bool,
    promote_reason: str,
    hrs_left: float,
    bh: dict,
) -> None:
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    marker = "\n## Block 8"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    r = repro["OOS"]
    lines = [
        "",
        "## Block 8 — Repro champ; mom-skip; r29 probe; locked cost shock",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Hours to deadline:** {hrs_left:.2f}",
        f"**#1 still leads:** {'YES' if not promote_ok else 'NO — new champion promoted'}",
        f"**Promote decision:** {promote_reason}",
        "",
        "### Reproduced champion (B6_ST_kill40_dd_nifty_mom_m04)",
        "",
        "| Metric | Block7 ref | Block8 | Drift |",
        "|--------|-----------:|-------:|------:|",
        f"| n | {REF_CHAMP['n_trades']} | {r['n_trades']} | {r['n_trades']-REF_CHAMP['n_trades']:+d} |",
        f"| PF | {REF_CHAMP['profit_factor']:.2f} | {r['profit_factor']:.2f} | {r['profit_factor']-REF_CHAMP['profit_factor']:+.2f} |",
        f"| Tot | {REF_CHAMP['total_return']*100:.1f}% | {r['total_return']*100:.1f}% | {(r['total_return']-REF_CHAMP['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_CHAMP['max_dd']*100:.1f}% | {r['max_dd']*100:.1f}% | {(r['max_dd']-REF_CHAMP['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_CHAMP['sharpe']:.2f} | {r['sharpe']:.2f} | {r['sharpe']-REF_CHAMP['sharpe']:+.2f} |",
        f"| Last WF | 9.2% | {repro.get('last_wf_tot', 0)*100:.1f}% | — |",
        "",
        "### Mom-skip save-rate / weekly ΔEquity (A vs B)",
        "",
        (
            f"- Mom skips n={mom.get('n_skips', 0)}; save-rate="
            + (f"{mom['save_rate']*100:.0f}%" if mom.get("save_rate") is not None else "n/a")
            + "; hit-rate (overfilter)="
            + (
                f"{mom['hit_rate_overfilter']*100:.0f}%"
                if mom.get("hit_rate_overfilter") is not None
                else "n/a"
            )
        ),
        (
            f"- Weekly ΔEquity mean={weekly.get('mean_delta_pp')}pp; "
            f"max consec B>A>2pp={weekly.get('max_consec_b_beats_gt2pp')}; "
            f"3w flag={weekly.get('flag_3w_b_lead')}"
        ),
        "",
        "### r29 mom_days60 vs A",
        "",
        "| Name | n | PF | Tot | MDD | Sharpe | LastWF | Dual? | Risk-adj? | Ladder? | Boot CI_lo | Decision |",
        "|------|--:|---:|----:|----:|-------:|-------:|:-----:|:---------:|:-------:|-----------:|----------|",
    ]
    oo = r29_row["OOS"]
    boot = r29_row.get("_boot", {})
    ci = boot.get("ci_lo")
    ci_s = f"{ci:.2f}" if ci is not None else "—"
    lines.append(
        f"| {r29_row['name']} | {oo['n_trades']} | {oo['profit_factor']:.2f} | "
        f"{oo['total_return']*100:.1f}% | {oo['max_dd']*100:.1f}% | {oo['sharpe']:.2f} | "
        f"{r29_row.get('last_wf_tot', 0)*100:.1f}% | "
        f"{'Y' if r29_row.get('dual_clear') else 'n'} | "
        f"{'Y' if r29_row.get('risk_adj_ok') else 'n'} | "
        f"{'Y' if r29_row.get('ladder_ok') else 'n'} | {ci_s} | "
        f"{r29_row.get('decision', '—')} |"
    )

    lines += [
        "",
        "### Locked-sleeve cost shock (A + r29 only)",
        "",
        "| Name | Metric | 0.08% | 0.10% | 0.12% | 0.15% | 0.20% |",
        "|------|--------|------:|------:|------:|------:|------:|",
    ]
    for key in ("A", "r29"):
        lad = ladders.get(key)
        if not lad:
            continue
        name = lad["name"]
        for metric, field in (("PF", "pf"), ("Tot", "tot"), ("MDD", "mdd")):
            cells = []
            for x in lad["ladder"]:
                v = x[field]
                if field == "tot" or field == "mdd":
                    cells.append(f"{v*100:.1f}%")
                else:
                    cells.append(f"{v:.2f}")
            lines.append(f"| {name} | {metric} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "### Block 8 measured checks (≥5)",
        "",
        "| Check | n | PF | Tot | MDD | WF+ | LastWF | Note |",
        "|-------|--:|---:|----:|----:|----:|-------:|------|",
    ]
    for c in checks:
        oo = c["OOS"]
        lines.append(
            f"| {c['name']} | {oo['n_trades']} | {oo['profit_factor']:.2f} | "
            f"{oo['total_return']*100:.1f}% | {oo['max_dd']*100:.1f}% | "
            f"{c.get('wf_pos', 0)}/{c.get('wf_n', 3)} | "
            f"{c.get('last_wf_tot', 0)*100:.1f}% | {c.get('note', '')} |"
        )

    lines += [
        "",
        "### Paper / checklist",
        "",
        f"- A = `{champ['name']}` (`strategies/nifty_edge_best.py`, `r21.py`)",
        "- B = demoted B5 (`strategies/nifty_edge_b5_prior.py`)",
        "- Expanded checklist: `research/nifty_edge_8h/CHECKLIST.md`",
        f"- Buy&hold ^NSEI OOS: tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "- No fragile-neighborhood hunting in Block 8 (locked-sleeve cost shock only).",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def expand_final_outline(
    champ: dict,
    r29_row: dict,
    mom: dict,
    weekly: dict,
    ladders: Dict[str, dict],
    promote_reason: str,
    hrs_left: float,
    checks: List[dict],
) -> None:
    o = champ["OOS"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sr = mom.get("save_rate")
    sr_s = f"{sr*100:.0f}%" if sr is not None else "n/a"
    text = f"""# FINAL_REPORT outline (Block 8 draft)

**Drafted:** {now}
**Hours to deadline:** {hrs_left:.2f}
**Status:** Outline only — full FINAL_REPORT when <1h to deadline or campaign end.

## 1. Executive verdict
- **Champion (still):** `{champ['name']}` — ST 3.6 + breadth≥0.40 + Nifty dd≥−7% + Nifty ret20≥−0.04
- OOS PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% n={o['n_trades']} MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} lastWF={champ.get('last_wf_tot', 0)*100:.1f}%
- Block 8 promote decision: `{promote_reason}`
- Demoted twin: `B5_ST_kill40_dd07` (paper B)
- Watch (not promoted): `B7_ST_kill40_dd_mom_days60` (r29) — {r29_row.get('decision', 'hold')}

## 2. Path to champion (Blocks 1–8)
- B1–4: ST_m3.6 core; kill-breadth / regime near-misses.
- B5: promote kill40 + causal dd≥−7%.
- B6: neighborhood freeze; ensembles rejected; near-misses held.
- B7: promote nifty_mom via robust risk-adj + ladder + boot; paper A/B flip.
- B8: repro new champ; mom-skip/weekly ΔEquity checklist; r29 probe; locked cost shock; no fragile hunting.

## 3. Mom-skip / weekly ΔEquity (Block 8)
- OOS mom-skips n={mom.get('n_skips', 0)}; save-rate={sr_s}; overfilter_flag={mom.get('overfilter_flag')}
- Weekly ΔEquity mean={weekly.get('mean_delta_pp')}pp; 3w B-lead flag={weekly.get('flag_3w_b_lead')}
- See `CHECKLIST.md` for full tables.

## 4. r29 probe (mom_days60 vs A)
- dual_clear={r29_row.get('dual_clear')}; risk_adj={r29_row.get('risk_adj_ok')}; ladder_ok={r29_row.get('ladder_ok')}
- Decision: **{r29_row.get('decision')}**
- Rule: promote only dual-clear (tot AND lastWF strict) OR robust risk-adj + ladder + boot CI_lo≥1.5.

## 5. Locked-sleeve cost shock (A + r29 only)
- No fragile-neighborhood re-hunt.
- A ladder 0.08→0.20%: see `results/block8_summary.json` / leaderboard.
- r29 ladder same rungs — compare vs A on every rung before any promote.

## 6. Measured checks (≥5)
{chr(10).join(f"- `{c['name']}`: PF={c['OOS']['profit_factor']:.2f} tot={c['OOS']['total_return']*100:.1f}% lastWF={c.get('last_wf_tot',0)*100:.1f}% — {c.get('note','')}" for c in checks)}

## 7. Paper trade freeze
- A = `{champ['name']}` (`strategies/nifty_edge_best.py`, `r21.py`)
- B = demoted B5 (`strategies/nifty_edge_b5_prior.py`)
- Rules: `PAPER_TRADE_RULES.md` · Checklist: `CHECKLIST.md`

## 8. Constraints & honesty
- No look-ahead; causal dd / ret20 / days-since-high.
- Single-symbol Pine ≠ 5-slot basket.
- Costs 0.08–0.20% RT ladder on locked sleeves only.
- Block 7 promote was risk-adj (lastWF tied) — mom-skip save-rate is the honesty check.

## 9. Open risks / Block 9 TODO
- Continue live paper A/B log (mom-skip save-rate, weekly ΔEquity).
- Re-check r29 only if lastWF strictly clears A or risk-adj still holds under fresh ladder+boot.
- No fragile neighborhood hunting.
- Full FINAL_REPORT + lock when <1h to deadline.
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
            "B6_ST_kill40_dd_nifty_mom_m04",
            data,
            sig_st_kill40_dd_nifty_mom,
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

    log("=== Block 8 start ===")
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

    # ── 1) Repro new champion ─────────────────────────────────────────────────
    log("Reproducing champion B6_ST_kill40_dd_nifty_mom_m04…")
    champ = portfolio_eval(
        "B6_ST_kill40_dd_nifty_mom_m04",
        data,
        sig_st_kill40_dd_nifty_mom,
        CHAMP_PARAMS,
        oos_start,
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

    # ── 2) Paper A vs B mom-skip + weekly ΔEquity ─────────────────────────────
    log("Expanding paper A/B mom-skip save-rate and weekly ΔEquity…")
    a_raw = run_portfolio_ext(
        data, sig_st_kill40_dd_nifty_mom, CHAMP_PARAMS, start_date=oos_start, return_trades=True
    )
    b_raw = run_portfolio_ext(
        data, sig_st_kill40_dd, B5_PARAMS, start_date=oos_start, return_trades=True
    )
    prior_b = portfolio_eval(
        "B5_ST_kill40_dd07", data, sig_st_kill40_dd, B5_PARAMS, oos_start
    )
    prior_b["last_wf_tot"] = prior_b["wf"][-1]["total_return"] if prior_b["wf"] else 0.0

    mom = analyze_mom_skips(data, oos_start, b_raw.get("trades", []))
    weekly = weekly_equity_delta(a_raw.get("equity"), b_raw.get("equity"))
    sr_log = f"{mom['save_rate']*100:.0f}%" if mom.get("save_rate") is not None else "n/a"
    hr_log = (
        f"{mom['hit_rate_overfilter']*100:.0f}%"
        if mom.get("hit_rate_overfilter") is not None
        else "n/a"
    )
    log(
        f"  MOM-SKIP n={mom.get('n_skips')} save_rate={sr_log} "
        f"hit_rate={hr_log} avg_ret={mom.get('avg_skip_ret')}"
    )
    log(
        f"  WEEKLY ΔEquity mean={weekly.get('mean_delta_pp')}pp "
        f"n_weeks={weekly.get('n_weeks')} max_consec_B>2pp={weekly.get('max_consec_b_beats_gt2pp')} "
        f"flag3w={weekly.get('flag_3w_b_lead')}"
    )
    expand_checklist(champ, prior_b, mom, weekly, hrs)
    log(f"  Wrote {CHECKLIST}")

    # ── 3) Probe r29 mom_days60 vs A ──────────────────────────────────────────
    log("Probing r29 B7_ST_kill40_dd_mom_days60 vs champion A…")
    champ_ladder = cost_ladder_row(
        "B6_ST_kill40_dd_nifty_mom_m04",
        data,
        sig_st_kill40_dd_nifty_mom,
        CHAMP_PARAMS,
        oos_start,
    )
    champ_boot = run_bootstrap_for(
        "B6_ST_kill40_dd_nifty_mom_m04",
        data,
        sig_st_kill40_dd_nifty_mom,
        CHAMP_PARAMS,
        oos_start,
    )
    log(
        f"  Champ boot CI_lo={champ_boot.get('ci_lo')} CI_hi={champ_boot.get('ci_hi')}"
    )

    r29 = portfolio_eval(
        "B7_ST_kill40_dd_mom_days60",
        data,
        sig_st_kill40_dd_mom_days,
        R29_PARAMS,
        oos_start,
    )
    r29["last_wf_tot"] = r29["wf"][-1]["total_return"] if r29["wf"] else 0.0
    r29["dual_clear"] = dual_clear(r29, champ)
    r29_lad = cost_ladder_row(
        "B7_ST_kill40_dd_mom_days60",
        data,
        sig_st_kill40_dd_mom_days,
        R29_PARAMS,
        oos_start,
    )
    r29_boot = run_bootstrap_for(
        "B7_ST_kill40_dd_mom_days60",
        data,
        sig_st_kill40_dd_mom_days,
        R29_PARAMS,
        oos_start,
    )
    r29["_ladder"] = r29_lad
    r29["_boot"] = r29_boot
    r29["ladder_ok"] = ladder_beats_champ(r29_lad, champ_ladder)
    risk_ok, risk_reason = robust_risk_adj_promote(r29, champ)
    r29["risk_adj_ok"] = risk_ok

    promote_ok = False
    promote_reason = "keep_champ:A_B6_nifty_mom"
    new_champ = champ
    # Dual-clear path
    if r29["dual_clear"] and r29["ladder_ok"]:
        r_lo = r29_boot.get("ci_lo")
        c_lo = champ_boot.get("ci_lo")
        if r_lo is not None and r_lo >= 1.5 and (c_lo is None or r_lo >= c_lo * 0.85):
            # Also require ≥2pp margin on tot or lastWF
            margin = (
                r29["OOS"]["total_return"] >= champ["OOS"]["total_return"] + 0.02
                or r29["last_wf_tot"] >= champ["last_wf_tot"] + 0.02
            )
            if margin:
                promote_ok = True
                promote_reason = "dual_clear_ladder_boot:B7_ST_kill40_dd_mom_days60"
                new_champ = r29
                r29["decision"] = f"PROMOTE:{promote_reason}"
            else:
                r29["decision"] = "hold:dual_clear_margin_thin"
        else:
            r29["decision"] = "hold:dual_clear_boot_weak"
    elif risk_ok and r29["ladder_ok"]:
        r_lo = r29_boot.get("ci_lo")
        c_lo = champ_boot.get("ci_lo")
        if r_lo is not None and r_lo >= 1.5 and (c_lo is None or r_lo >= c_lo * 0.85):
            promote_ok = True
            promote_reason = f"robust_risk_adj_ladder_boot:{risk_reason}:B7_ST_kill40_dd_mom_days60"
            new_champ = r29
            r29["decision"] = f"PROMOTE:{promote_reason}"
        else:
            r29["decision"] = f"hold:risk_adj_boot_weak:{risk_reason}"
    else:
        if not r29["dual_clear"]:
            r29["decision"] = f"hold:no_dual_clear;risk_adj={risk_ok}:{risk_reason}"
        else:
            r29["decision"] = f"hold:ladder_fail;risk_adj={risk_ok}"

    log(
        f"  r29 n={r29['OOS']['n_trades']} PF={r29['OOS']['profit_factor']:.2f} "
        f"tot={r29['OOS']['total_return']*100:.1f}% lastWF={r29['last_wf_tot']*100:.1f}% "
        f"dual={r29['dual_clear']} risk_adj={risk_ok} ladder_ok={r29['ladder_ok']} "
        f"boot_lo={r29_boot.get('ci_lo')} → {r29['decision']}"
    )
    pts = " | ".join(
        f"rt{x['rt_pct']:.2f}:PF={x['pf']:.2f}/tot={x['tot']*100:.1f}%"
        for x in r29_lad["ladder"]
    )
    log(f"  LADDER r29: {pts}")

    # ── 4) Locked-sleeve cost shock (A + r29 only) ────────────────────────────
    log("Locked-sleeve cost shock 0.08–0.20% on A and r29 only…")
    ladders = {"A": champ_ladder, "r29": r29_lad}
    for key, lad in ladders.items():
        pts = " | ".join(
            f"rt{x['rt_pct']:.2f}:PF={x['pf']:.2f}/tot={x['tot']*100:.1f}%/MDD={x['mdd']*100:.1f}%"
            for x in lad["ladder"]
        )
        log(f"  LADDER {key} {lad['name']}: {pts}")
    # Fragility note: linear decay, no neighborhood hunt
    a0, a1 = champ_ladder["ladder"][0], champ_ladder["ladder"][-1]
    r0, r1 = r29_lad["ladder"][0], r29_lad["ladder"][-1]
    log(
        f"  Shock note: A ΔTot 0.08→0.20%={(a1['tot']-a0['tot'])*100:+.1f}pp; "
        f"r29 ΔTot={(r1['tot']-r0['tot'])*100:+.1f}pp; "
        f"r29 beats A every rung={all(rl['tot'] >= cl['tot'] for rl, cl in zip(r29_lad['ladder'], champ_ladder['ladder']))}"
    )

    # ── 5) ≥5 measured checks (no fragile neighborhood hunting) ───────────────
    log("Block 8 measured checks (≥5) — locked sleeves + light causal probes…")
    checks: List[dict] = []
    check_specs = [
        ("B8_A_champ_repro", sig_st_kill40_dd_nifty_mom, CHAMP_PARAMS, "sig_st_kill40_dd_nifty_mom", "champ_repro"),
        ("B8_B_demoted_b5", sig_st_kill40_dd, B5_PARAMS, "sig_st_kill40_dd", "paper_B"),
        ("B8_r29_mom_days60", sig_st_kill40_dd_mom_days, R29_PARAMS, "sig_st_kill40_dd_mom_days", "watch_r29"),
        (
            "B8_A_stress015",
            sig_st_kill40_dd_nifty_mom,
            CHAMP_PARAMS,
            "sig_st_kill40_dd_nifty_mom",
            "stress_shadow",
        ),
        (
            "B8_r29_stress015",
            sig_st_kill40_dd_mom_days,
            R29_PARAMS,
            "sig_st_kill40_dd_mom_days",
            "stress_shadow",
        ),
        # Light causal probes — not neighborhood hunting; fixed previously-seen variants
        (
            "B8_days60_only",
            sig_st_kill40_dd_days,
            {**B5_PARAMS, "max_days_since_high": 60},
            "sig_st_kill40_dd_days",
            "causal_probe",
        ),
        (
            "B8_volcalm125",
            sig_st_kill40_dd_volcalm,
            {**B5_PARAMS, "max_vol_ratio": 1.25},
            "sig_st_kill40_dd_volcalm",
            "causal_probe",
        ),
    ]
    for name, fn, params, fn_name, note in check_specs:
        if "stress015" in name:
            # Evaluate at 0.15% via portfolio_eval then overwrite OOS with stress cost run
            row = portfolio_eval(name, data, fn, params, oos_start)
            stress = run_portfolio_ext(
                data, fn, params, start_date=oos_start, rt_cost=0.0015
            )
            row["OOS"] = stress
            row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            row["note"] = note
            row["fn_name"] = fn_name
            row["params"] = params
        else:
            row = portfolio_eval(name, data, fn, params, oos_start)
            row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            row["note"] = note
            row["fn_name"] = fn_name
            row["params"] = params
        checks.append(row)
        log(
            f"  CHECK {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
            f"tot={row['OOS']['total_return']*100:.1f}% lastWF={row['last_wf_tot']*100:.1f}% "
            f"({note})"
        )

    # Promote files if needed
    if promote_ok and new_champ is r29:
        log(f"  PROMOTED {new_champ['name']} reason={promote_reason}")
        # Update best.py
        best_path = OUT_STRAT / "nifty_edge_best.py"
        best_code = f'''"""
Nifty Edge Best — Block 8 champion
==================================
{new_champ['name']}
Params: {json.dumps(R29_PARAMS)}

OOS: n={new_champ['OOS']['n_trades']} PF={new_champ['OOS']['profit_factor']:.2f} tot={new_champ['OOS']['total_return']*100:.1f}%
MDD={new_champ['OOS']['max_dd']*100:.1f}% Sharpe={new_champ['OOS']['sharpe']:.2f}
WF={new_champ['wf_pos']}/{new_champ['wf_n']} lastWF={new_champ.get('last_wf_tot', 0)*100:.1f}%

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
from run_block7 import sig_st_kill40_dd_mom_days as FN

PARAMS = {json.dumps(R29_PARAMS, indent=2).replace("true", "True").replace("false", "False")}

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
    print(json.dumps({{"name": {json.dumps(new_champ['name'])}, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
        best_path.write_text(best_code)
        log(f"  Wrote {best_path}")
        # Demote prior A to a prior file if needed — keep b5_prior as B; save old A as optional
        log("  Paper A flipped to r29; prior nifty_mom remains as r21")

    # Save r30+ for interesting checks (non-champ)
    log("Saving runners r30+…")
    next_idx = 30
    saved = []
    # Prefer r29 already exists; save days60-only and any dual/risk candidates
    for row in checks:
        if row["note"] in ("causal_probe",) and row["OOS"]["total_return"] > 0.5:
            p = write_b8_runner(next_idx, row, row["fn_name"])
            log(f"  Saved {p.name}: {row['name']} PF={row['OOS']['profit_factor']:.2f} tot={row['OOS']['total_return']*100:.1f}%")
            saved.append(str(p))
            next_idx += 1
    # Also persist a stress-note runner if promote didn't happen — reaffirm r29 watch
    if not promote_ok:
        # Save a Block-8 snapshot of r29 decision as r30 if no causal probes saved yet
        if next_idx == 30:
            snap = {
                "name": "B8_r29_watch_mom_days60",
                "params": R29_PARAMS,
                "OOS": r29["OOS"],
                "wf_pos": r29["wf_pos"],
                "wf_n": r29["wf_n"],
                "last_wf_tot": r29["last_wf_tot"],
            }
            p = write_b8_runner(30, snap, "sig_st_kill40_dd_mom_days")
            log(f"  Saved {p.name}: watch snapshot of r29")
            saved.append(str(p))
            next_idx = 31

    # ── 6) Outline / board / summary ──────────────────────────────────────────
    expand_final_outline(
        new_champ if promote_ok else champ,
        r29,
        mom,
        weekly,
        ladders,
        promote_reason,
        hrs,
        checks,
    )
    log(f"Wrote {FINAL_OUTLINE}")
    if hrs < 1.0:
        write_full_final_if_needed(new_champ if promote_ok else champ, hrs)
        log("FULL FINAL written (<1h)")
    else:
        log(f"FINAL outline only ({hrs:.1f}h left; full FINAL later)")

    append_leaderboard_block8(
        new_champ if promote_ok else champ,
        champ,  # repro of Block-7 champ
        r29,
        ladders,
        mom,
        weekly,
        checks,
        promote_ok,
        promote_reason,
        hrs,
        bh_oos,
    )
    log(f"Updated {LEADERBOARD}")

    summary = {
        "block": 8,
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
            "drift_ok": drift_ok,
        },
        "mom_skip": {
            k: v
            for k, v in mom.items()
            if k != "skips"
        },
        "mom_skip_sample": mom.get("skips", [])[:20],
        "weekly_delta": {k: v for k, v in weekly.items() if k != "weeks"},
        "weekly_sample": weekly.get("weeks", []),
        "r29": {
            "name": r29["name"],
            "dual_clear": r29.get("dual_clear"),
            "risk_adj_ok": r29.get("risk_adj_ok"),
            "ladder_ok": r29.get("ladder_ok"),
            "decision": r29.get("decision"),
            "boot_ci_lo": r29_boot.get("ci_lo"),
            "tot": r29["OOS"]["total_return"],
            "last_wf": r29["last_wf_tot"],
            "pf": r29["OOS"]["profit_factor"],
            "mdd": r29["OOS"]["max_dd"],
            "sharpe": r29["OOS"]["sharpe"],
        },
        "cost_shock": {
            "A": champ_ladder,
            "r29": r29_lad,
            "a_dtot_08_to_20_pp": (a1["tot"] - a0["tot"]) * 100,
            "r29_dtot_08_to_20_pp": (r1["tot"] - r0["tot"]) * 100,
        },
        "checks": [
            {
                "name": c["name"],
                "n": c["OOS"]["n_trades"],
                "pf": c["OOS"]["profit_factor"],
                "tot": c["OOS"]["total_return"],
                "mdd": c["OOS"]["max_dd"],
                "last_wf": c.get("last_wf_tot"),
                "note": c.get("note"),
            }
            for c in checks
        ],
        "saved_runners": saved,
        "buy_hold_oos": {
            "tot": bh_oos["total_return"],
            "sharpe": bh_oos["sharpe"],
        },
    }
    out_path = RESULTS / "block8_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    log(f"Wrote {out_path}")

    top = sorted(
        checks,
        key=lambda r: (r.get("wf_pos", 0), r.get("last_wf_tot", 0), r["OOS"]["total_return"]),
        reverse=True,
    )[:5]
    log("--- Block 8 top checks ---")
    for t in top:
        log(
            f"  {t['name']}: PF={t['OOS']['profit_factor']:.2f} tot={t['OOS']['total_return']*100:.1f}% "
            f"n={t['OOS']['n_trades']} WF={t.get('wf_pos')}/{t.get('wf_n')} "
            f"lastWF={t.get('last_wf_tot', 0)*100:.1f}%"
        )

    final_champ = new_champ if promote_ok else champ
    fo = final_champ["OOS"]
    log(
        f"=== Block 8 complete === champion={final_champ['name']} "
        f"PF={fo['profit_factor']:.2f} tot={fo['total_return']*100:.1f}% "
        f"promoted={promote_ok} reason={promote_reason} "
        f"n_checks={len(checks)} drift_ok={drift_ok} hrs_left={hrs:.2f}"
    )
    log(
        "Next Block 9: continue paper A/B live log; optional re-check r29 only if lastWF clears; "
        "FINAL_REPORT + lock when <1h to deadline"
    )
    print(
        json.dumps(
            {
                "champion": final_champ["name"],
                "promoted": promote_ok,
                "reason": promote_reason,
                "drift_ok": drift_ok,
                "r29_decision": r29.get("decision"),
                "mom_save_rate": mom.get("save_rate"),
                "hrs_left": hrs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
