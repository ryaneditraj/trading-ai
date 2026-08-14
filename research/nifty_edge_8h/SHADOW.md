# Paper A Shadow P&L — Block 11

**Updated:** 2026-08-05 (FINAL LOCK — stats unchanged from Block 11)
**Sleeve:** `B6_ST_kill40_dd_nifty_mom_m04` (`strategies/nifty_edge_paper.py`)
**Status:** Simulated paper book on historical OOS — not live capital. See `FINAL_REPORT.md`.

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
| Paper A @ 0.08% RT | 64 | 4.73 | 124.3% | -13.0% | 1.24 |
| Paper A @ 0.15% RT | 64 | 4.64 | 121.6% | -13.1% | 1.22 |
| Δ (0.15 − 0.08) | — | — | -2.7pp | — | — |

## Benchmarks (same OOS window)

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A @ 0.08% | 124.3% | -13.0% | 1.24 |
| Buy&hold ^NSEI | 70.5% | -17.2% | 0.76 |
| EW buy-hold basket (20) | 99.5% | -16.3% | 1.02 |

Excess vs ^NSEI: **+53.8pp**
Excess vs EW basket: **+24.8pp**

## Weekly equity — 0.08% RT (last ≤12 weeks)

| Week (Fri) | Equity | Week ret |
|------------|-------:|---------:|
| 2026-05-22 | 2.2428 | +0.00% |
| 2026-05-29 | 2.2428 | +0.00% |
| 2026-06-05 | 2.2428 | +0.00% |
| 2026-06-12 | 2.2428 | +0.00% |
| 2026-06-19 | 2.2428 | +0.00% |
| 2026-06-26 | 2.2428 | +0.00% |
| 2026-07-03 | 2.2428 | +0.00% |
| 2026-07-10 | 2.2428 | +0.00% |
| 2026-07-17 | 2.2428 | +0.00% |
| 2026-07-24 | 2.2428 | +0.00% |
| 2026-07-31 | 2.2428 | +0.00% |
| 2026-08-07 | 2.2428 | +0.00% |

n_weeks=290 mean=0.2927286323039515pp worst=-6.169332443475383pp

## Weekly equity — 0.15% RT shadow (last ≤12 weeks)

| Week (Fri) | Equity | Week ret |
|------------|-------:|---------:|
| 2026-05-22 | 2.2156 | +0.00% |
| 2026-05-29 | 2.2156 | +0.00% |
| 2026-06-05 | 2.2156 | +0.00% |
| 2026-06-12 | 2.2156 | +0.00% |
| 2026-06-19 | 2.2156 | +0.00% |
| 2026-06-26 | 2.2156 | +0.00% |
| 2026-07-03 | 2.2156 | +0.00% |
| 2026-07-10 | 2.2156 | +0.00% |
| 2026-07-17 | 2.2156 | +0.00% |
| 2026-07-24 | 2.2156 | +0.00% |
| 2026-07-31 | 2.2156 | +0.00% |
| 2026-08-07 | 2.2156 | +0.00% |

n_weeks=290 mean=0.28857286343243416pp worst=-6.2077802047584285pp

## Weekly Δ (0.08 − 0.15) recent

| Week | ret_0.08 | ret_0.15 | Δ pp |
|------|---------:|---------:|-----:|
| 2026-06-19 | +0.00% | +0.00% | +0.00pp |
| 2026-06-26 | +0.00% | +0.00% | +0.00pp |
| 2026-07-03 | +0.00% | +0.00% | +0.00pp |
| 2026-07-10 | +0.00% | +0.00% | +0.00pp |
| 2026-07-17 | +0.00% | +0.00% | +0.00pp |
| 2026-07-24 | +0.00% | +0.00% | +0.00pp |
| 2026-07-31 | +0.00% | +0.00% | +0.00pp |
| 2026-08-07 | +0.00% | +0.00% | +0.00pp |

mean Δ=0.004155768871517389pp · flag_3w_stress_lead=False

## Live paper template (append weekly)

| Week ending | Eq 0.08 | WeekΔ 0.08 | Eq 0.15 | WeekΔ 0.15 | Notes |
|-------------|--------:|-----------:|--------:|-----------:|-------|
| YYYY-MM-DD | | | | | |
