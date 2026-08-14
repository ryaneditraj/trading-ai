# Paper Trade Rules — Nifty Edge 8h

**Written:** Block 5; flipped B7–8; anti-overfit B9; **operationalized Block 10** 2026-08-04 19:37 UTC
**Status:** **FINAL LOCK** 2026-08-05 — research paper sleeves only. No look-ahead. No live capital.
**Block 11:** Shadow hygiene + days60 log — see `SHADOW.md`, `DAYS60_SKIP_LOG.md`.
**FINAL:** `FINAL_REPORT.md` (locked; &lt;1h to deadline). **Paper A = B6.** No new gates.

---

## ★ PAPER vs RESEARCH (FINAL — read this first)

| Role | ID | Code | Gates | OOS ref |
|------|----|------|-------|---------|
| **PAPER A (trade this)** | `B6_ST_kill40_dd_nifty_mom_m04` | `strategies/nifty_edge_paper.py` (+ `b6_prior.py` / `r21.py`) | kill40 + dd−7% + mom−4% | n=64 PF=4.73 tot=124.3% lastWF=9.2% |
| **RESEARCH A (monitor only)** | `B7_ST_kill40_dd_mom_days60` | `strategies/nifty_edge_best.py` / `r29.py` | Paper A **+ days≤60** | n=63 PF=5.17 tot=129.4% lastWF=9.2% |
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

| Check | n | PF | Tot | MDD | LastWF / note |
|-------|--:|---:|----:|----:|---------------|
| exec next-open (PRIMARY) | 64 | 4.73 | 124.3% | -13.0% | primary fill |
| exec close-entry (stress) | 65 | 4.57 | 124.2% | -14.9% | Δtot=-0.0pp |
| cost 0.08% RT | 64 | 4.73 | 124.3% | -13.0% | ladder_ok=True |
| cost 0.10% RT | 64 | 4.70 | 123.5% | -13.0% | ladder_ok=True |
| cost 0.12% RT | 64 | 4.68 | 122.7% | -13.1% | ladder_ok=True |
| cost 0.15% RT | 64 | 4.64 | 121.6% | -13.1% | ladder_ok=True |
| cost 0.20% RT | 64 | 4.57 | 119.6% | -13.3% | ladder_ok=True |
| max_slots=5 | 64 | 4.73 | 124.3% | -13.0% | lastWF=9.2% |
| max_slots=4 | 52 | 4.69 | 112.1% | -12.1% | lastWF=4.7% |
| ST mult=3.4 | 76 | 2.83 | 91.7% | -13.1% | lastWF=2.7% |
| ST mult=3.5 | 75 | 2.57 | 76.7% | -12.1% | lastWF=-3.5% FRAGILE |
| ST mult=3.6 | 64 | 4.73 | 124.3% | -13.0% | lastWF=9.2% |
| ST mult=3.7 | 62 | 4.36 | 117.8% | -12.7% | lastWF=6.2% |
| ST mult=3.8 | 60 | 3.25 | 80.7% | -13.4% | lastWF=0.4% |
| univ drop_WIPRO | 61 | 5.41 | 131.1% | -11.0% | Δtot=+6.9pp lastWF=9.2% |
| univ drop_WIPRO_BAJFINANCE | 62 | 4.30 | 117.0% | -9.7% | Δtot=-7.3pp lastWF=7.7% |

- Cost ΔTot 0.08→0.20% = -4.6pp; all rungs PF≥1.3: **True**
- Close-entry ΔTot vs next-open = -0.0pp (stress only; keep next-open as paper fill).
- Fragile ST mults: [3.5]; keep Paper A mult=**3.6**.
- Default universe 20 names / max_slots=5 unchanged.

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
- **FINAL LOCK:** Paper A remains B6; see `FINAL_REPORT.md`.
