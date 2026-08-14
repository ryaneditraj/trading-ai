# Nifty Edge 8h — FINAL REPORT (DRAFT — superseded)

**Status:** SUPERSEDED by `FINAL_REPORT.md` (FINAL LOCK 2026-08-05).
**Drafted:** 2026-08-04 19:40 UTC (Block 11)

Retained for audit trail. Use **`FINAL_REPORT.md`** as the publishable locked report.

## Executive verdict

| Role | Sleeve | Tot | LastWF | Use |
|------|--------|----:|-------:|-----|
| **PAPER A** | `B6_ST_kill40_dd_nifty_mom_m04` | 124.3% | 9.2% | **Trade / paper this** |
| **RESEARCH A** | `B7_ST_kill40_dd_mom_days60` | 129.4% | 9.2% | Monitor only (days60 stacked) |
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

### Frozen universe (20 names)
- `RELIANCE.NS`
- `TCS.NS`
- `INFY.NS`
- `HDFCBANK.NS`
- `ICICIBANK.NS`
- `SBIN.NS`
- `BHARTIARTL.NS`
- `ITC.NS`
- `LT.NS`
- `AXISBANK.NS`
- `KOTAKBANK.NS`
- `HINDUNILVR.NS`
- `BAJFINANCE.NS`
- `ASIANPAINT.NS`
- `MARUTI.NS`
- `SUNPHARMA.NS`
- `TITAN.NS`
- `ULTRACEMCO.NS`
- `WIPRO.NS`
- `NESTLEIND.NS`

### Promotion rules (campaign)
- Dual-clear: challenger tot **and** lastWF strictly above champ.
- Cost ladder PF≥1.3 across 0.08–0.20% RT.
- Complexity: prefer fewer gates if within ~10% tot and lastWF ≥ champ.
- **No mid-paper param tweaks.** No new gate stacking after Paper A freeze.

## Metrics (Block 11 repro)

| Sleeve | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | drift_ok |
|--------|--:|---:|----:|----:|-------:|----:|-------:|:--------:|
| Paper A | 64 | 4.73 | 124.3% | -13.0% | 1.24 | 3/3 | 9.2% | True |
| Research A | 63 | 5.17 | 129.4% | -11.0% | 1.28 | 3/3 | 9.2% | True |

### Benchmarks (same OOS)

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A @ 0.08% RT | 124.3% | -13.0% | 1.24 |
| Buy&hold ^NSEI | 70.5% | -17.2% | 0.76 |
| EW buy-hold basket | 99.5% | -16.3% | 1.02 |

Paper excess vs ^NSEI: **+53.8pp**;
vs EW basket: **+24.8pp**.

### Shadow books
- 0.08% tot=124.3% · 0.15% tot=121.6%
  (Δ=-2.7pp). See `SHADOW.md`.

### Days60-skip honesty
- Hist n=1; save-rate provisional until n≥20.
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
| Paper pine core_ok | True |
| Research pine core_ok | True |

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
