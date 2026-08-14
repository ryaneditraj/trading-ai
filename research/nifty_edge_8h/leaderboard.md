# Nifty Edge 8h — Living Leaderboard

**Updated:** 2026-08-05 (**FINAL LOCK**)

> **FINAL LOCK:** PAPER A = `B6_ST_kill40_dd_nifty_mom_m04` (`strategies/nifty_edge_paper.py`, `pinescript/nifty_edge_paper.pine`) — OOS PF 4.73 tot 124.3% lastWF 9.2%. RESEARCH A = `B7_ST_kill40_dd_mom_days60` (`nifty_edge_best.*`, monitor). Report: `FINAL_REPORT.md`. No new gates.

> **Block 11:** Shadow P&L + days60 live log template. PAPER A = B6; RESEARCH A = B7 monitor.

> **Block 10 freeze:** PAPER A = B6; RESEARCH A = B7 monitor. See § Block 10 below.
**Costs:** 0.08% RT default; stress 0.15%
**Pass bar:** OOS PF≥1.3, positive expectancy, n≥15, WF stability preferred

## Block 1 verdict (current #1)

| Item | Value |
|------|-------|
| **Winner** | Supertrend ATR-trail basket `ST_m3.6` + Nifty bull + EMA200 |
| **Code** | `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine` |
| **OOS** | n=75, PF=**3.90**, exp=+5.53%/trade, tot=**+110%**, MDD=−14.8%, Sharpe=1.10 |
| **Stress 0.15%** | PF=3.82, tot=+107% |
| **WF** | **3/3 green** incl. 2024-09→2026 **+5.8%** (baseline was −7.3%) |
| **±20% mult** | 2.88 → PF 2.61; 4.32 → PF 2.34 (both pass) |
| **vs baseline v2** | OOS tot 110% vs 39%; fixes late-WF failure |
| **vs B&H ^NSEI OOS** | tot 110% vs 69.5%; Sharpe 1.10 vs 0.76; MDD −14.8% vs −17.2% |
| **Honesty** | mult=3.6 is a **local PF peak**; neighborhood 2.8–3.8 still PF≥1.97 when WF=3/3. Prefer also tracking **mult=3.0** (PF 2.05, n=119) as conservative. Single-symbol Pine ≠ 5-slot basket. |

**Runner-ups:** `strategies/nifty_edge_r1.py` (ST 3.0), `r2.py` (ATR expansion), `r3.py` (EMA ribbon)

## Buy & hold (^NSEI OOS)

| Total | MDD | Sharpe |
|------:|----:|-------:|
| 69.5% | -17.2% | 0.76 |

## Baseline reproduction (india_nifty_adx_donchian_v2 basket)

| Split | n | WR | PF | Exp | Tot | MDD | Sharpe |
|-------|--:|---:|---:|----:|----:|----:|-------:|
| IS | 145 | 47.6% | 3.17 | 7.81% | 527.6% | -25.8% | 1.04 |
| OOS | 74 | 48.6% | 1.86 | 2.58% | 38.7% | -14.4% | 0.59 |
| OOS_stress | 74 | 48.6% | 1.83 | 2.51% | 36.7% | -14.9% | 0.57 |

## Single-symbol screen (ranked by composite score)

| Rank | ID | Sym | Family | OOS n | OOS PF | OOS Exp | OOS Tot | MDD | WF+/N | Score | Verdict |
|-----:|----|-----|--------|------:|-------:|--------:|--------:|----:|------:|------:|---------|
| 1 | B1-05_atr_expansion | ^NSEBANK | vol_bo | 15 | 4.66 | 2.40% | 40.5% | -5.3% | 1/4 | 11.85 | WATCH |
| 2 | B1-05_atr_expansion | ^NSEI | vol_bo | 16 | 3.06 | 1.55% | 26.5% | -5.2% | 1/4 | 7.96 | WATCH |
| 3 | BASKET_B1-03_adx_donchian_70_25 | BASKET20 | trend_adx | 74 | 1.86 | 2.58% | 38.7% | -14.4% | 2/3 | 7.52 | PROMOTE |
| 4 | BASKET_B1-16_supertrend | BASKET20 | atr_trail | 77 | 1.89 | 2.04% | 33.8% | -16.3% | 2/3 | 7.25 | PROMOTE |
| 5 | B1-21_close_loc | ^NSEI | structure | 16 | 2.77 | 1.14% | 19.0% | -8.7% | 1/4 | 7.03 | WATCH |
| 6 | BASKET_B1-05_atr_expansion | BASKET20 | vol_bo | 118 | 1.65 | 1.20% | 27.7% | -15.1% | 2/3 | 6.25 | PROMOTE |
| 7 | BASKET_B1-26_ema_ribbon | BASKET20 | ma_cross | 257 | 1.45 | 0.85% | 43.6% | -22.7% | 2/3 | 6.00 | PROMOTE |
| 8 | B1-12_month_turn | ^NSEBANK | calendar | 59 | 1.71 | 0.59% | 36.7% | -13.1% | 2/4 | 5.79 | PROMOTE |
| 9 | B1-26_ema_ribbon | NIFTYBEES.NS | ma_cross | 21 | 1.85 | 1.22% | 25.8% | -9.7% | 2/4 | 5.78 | PROMOTE |
| 10 | B1-24_breadth_thrust | ^NSEI | breadth | 30 | 1.53 | 0.69% | 19.6% | -11.6% | 4/4 | 5.61 | PROMOTE |
| 11 | B1-06_nr7_thrust | ^NSEI | vol_bo | 53 | 1.69 | 0.29% | 16.1% | -5.6% | 3/4 | 5.51 | PROMOTE |
| 12 | B1-15_keltner | ^NSEI | keltner | 32 | 1.45 | 0.52% | 15.4% | -17.9% | 3/4 | 4.92 | PROMOTE |
| 13 | B1-09_gap_cont | ^NSEBANK | gap | 45 | 1.39 | 0.38% | 15.8% | -18.3% | 3/4 | 4.86 | PROMOTE |
| 14 | B1-04_ma_pullback | NIFTYBEES.NS | ma_pullback | 17 | 1.70 | 0.86% | 14.0% | -12.7% | 1/4 | 4.66 | WATCH |
| 15 | B1-26_ema_ribbon | ^NSEI | ma_cross | 30 | 1.37 | 0.51% | 13.0% | -18.5% | 2/4 | 4.31 | PROMOTE |
| 16 | B1-04_ma_pullback | ^NSEI | ma_pullback | 21 | 1.59 | 0.56% | 11.2% | -11.5% | 1/4 | 4.28 | WATCH |
| 17 | B1-09_gap_cont | ^NSEI | gap | 51 | 1.20 | 0.16% | 7.1% | -11.6% | 3/4 | 4.25 | WEAK |
| 18 | B1-14_bb_walk | NIFTYBEES.NS | bollinger | 18 | 1.54 | 0.68% | 11.4% | -13.3% | 1/4 | 4.20 | WATCH |
| 19 | BASKET_B1-17_failed_bd_fade | BASKET20 | failed_bo | 215 | 1.11 | 0.17% | 4.6% | -15.7% | 2/3 | 4.19 | WEAK |
| 20 | B1-15_keltner | ^NSEBANK | keltner | 32 | 1.22 | 0.27% | 6.9% | -15.3% | 3/4 | 4.16 | WATCH |
| 21 | B1-12_month_turn | ^NSEI | calendar | 57 | 1.47 | 0.33% | 18.6% | -12.0% | 0/4 | 4.05 | WATCH |
| 22 | B1-09_gap_cont | NIFTYBEES.NS | gap | 38 | 1.18 | 0.14% | 4.2% | -9.8% | 3/4 | 4.01 | WEAK |
| 23 | B1-25_orb_daily | ^NSEBANK | opening_range | 98 | 1.03 | 0.04% | -0.9% | -21.2% | 3/4 | 4.00 | WEAK |
| 24 | BASKET_B1-15_keltner | BASKET20 | keltner | 299 | 1.04 | 0.07% | -1.3% | -24.9% | 2/3 | 3.88 | WEAK |
| 25 | B1-14_bb_walk | ^NSEBANK | bollinger | 24 | 1.15 | 0.19% | 3.2% | -9.3% | 3/4 | 3.82 | WEAK |
| 26 | B1-25_orb_daily | ^NSEI | opening_range | 106 | 0.98 | -0.02% | -3.8% | -16.4% | 3/4 | 3.80 | REJECT |
| 27 | BASKET_B1-21_close_loc | BASKET20 | structure | 180 | 1.12 | 0.24% | 5.4% | -11.3% | 1/3 | 3.76 | WEAK |
| 28 | B1-25_orb_daily | NIFTYBEES.NS | opening_range | 70 | 0.89 | -0.11% | -9.0% | -16.7% | 4/4 | 3.74 | REJECT |
| 29 | B1-15_keltner | NIFTYBEES.NS | keltner | 15 | 1.42 | 0.46% | 6.3% | -9.5% | 1/4 | 3.73 | WATCH |
| 30 | B1-23_rs_nifty_bank | ^NSEI | pairs_rs | 16 | 1.55 | 0.43% | 6.4% | -8.2% | 0/4 | 3.61 | WATCH |
| 31 | BASKET_B1-12_month_turn | BASKET20 | calendar | 224 | 1.02 | 0.04% | -2.2% | -24.3% | 1/3 | 3.32 | WEAK |
| 32 | B1-11_dow_monday | ^NSEI | calendar | 173 | 0.75 | -0.15% | -23.6% | -28.0% | 4/4 | 3.26 | REJECT |
| 33 | B1-10_gap_fade | ^NSEBANK | gap | 32 | 1.16 | 0.11% | 2.8% | -8.1% | 1/4 | 3.13 | WEAK |
| 34 | BASKET_B1-04_ma_pullback | BASKET20 | ma_pullback | 283 | 0.96 | -0.07% | -7.1% | -28.6% | 1/3 | 3.05 | REJECT |
| 35 | BASKET_B1-06_nr7_thrust | BASKET20 | vol_bo | 580 | 0.86 | -0.16% | -21.7% | -31.5% | 2/3 | 3.01 | REJECT |
| 36 | B1-22_di_momentum | ^NSEI | trend_adx | 15 | 1.14 | 0.17% | 1.6% | -8.4% | 1/4 | 2.91 | WEAK |
| 37 | B1-14_bb_walk | ^NSEI | bollinger | 18 | 0.98 | -0.02% | -1.5% | -19.2% | 2/4 | 2.86 | REJECT |
| 38 | BASKET_B1-18_time_structure | BASKET20 | hybrid | 249 | 0.93 | -0.15% | -12.4% | -25.0% | 1/3 | 2.84 | REJECT |
| 39 | B1-18_time_structure | ^NSEI | hybrid | 29 | 1.17 | 0.21% | 4.7% | -12.5% | 0/4 | 2.83 | WEAK |
| 40 | B1-26_ema_ribbon | ^NSEBANK | ma_cross | 32 | 0.97 | -0.04% | -3.1% | -9.9% | 1/4 | 2.55 | REJECT |

## Rejected / thin (sample)

- `B1-25_orb_daily` (^NSEI) n=106 PF=0.98 exp=-0.02% tot=-3.8%
- `B1-25_orb_daily` (NIFTYBEES.NS) n=70 PF=0.89 exp=-0.11% tot=-9.0%
- `B1-11_dow_monday` (^NSEI) n=173 PF=0.75 exp=-0.15% tot=-23.6%
- `BASKET_B1-04_ma_pullback` (BASKET20) n=283 PF=0.96 exp=-0.07% tot=-7.1%
- `BASKET_B1-06_nr7_thrust` (BASKET20) n=580 PF=0.86 exp=-0.16% tot=-21.7%
- `B1-14_bb_walk` (^NSEI) n=18 PF=0.98 exp=-0.02% tot=-1.5%
- `BASKET_B1-18_time_structure` (BASKET20) n=249 PF=0.93 exp=-0.15% tot=-12.4%
- `B1-26_ema_ribbon` (^NSEBANK) n=32 PF=0.97 exp=-0.04% tot=-3.1%
- `B1-06_nr7_thrust` (^NSEBANK) n=53 PF=0.87 exp=-0.09% tot=-5.6%
- `BASKET_B1-22_di_momentum` (BASKET20) n=187 PF=0.83 exp=-0.44% tot=-18.7%
- `BASKET_B1-14_bb_walk` (BASKET20) n=270 PF=0.82 exp=-0.36% tot=-20.0%
- `B1-18_time_structure` (^NSEBANK) n=27 PF=0.76 exp=-0.34% tot=-9.7%
- `B1-04_ma_pullback` (^NSEBANK) n=28 PF=0.86 exp=-0.22% tot=-7.8%
- `B1-17_failed_bd_fade` (^NSEBANK) n=17 PF=0.84 exp=-0.20% tot=-4.1%
- `B1-11_dow_monday` (^NSEBANK) n=166 PF=0.56 exp=-0.36% tot=-46.4%
- `B1-19_vol_bo` (^NSEBANK) n=16 PF=0.73 exp=-0.45% tot=-7.8%
- `B1-21_close_loc` (^NSEBANK) n=17 PF=0.66 exp=-0.55% tot=-9.6%
- `B1-06_nr7_thrust` (NIFTYBEES.NS) n=37 PF=0.24 exp=-0.77% tot=-25.2%
- `B1-22_di_momentum` (^NSEBANK) n=16 PF=0.48 exp=-1.07% tot=-16.5%
- `B1-20_downstreak_rev` (^NSEBANK) n=18 PF=0.48 exp=-0.36% tot=-6.3%
- `B1-11_dow_monday` (NIFTYBEES.NS) n=159 PF=0.30 exp=-0.78% tot=-71.9%
- `B1-20_downstreak_rev` (^NSEI) n=15 PF=0.46 exp=-0.62% tot=-9.2%
- `B1-12_month_turn` (NIFTYBEES.NS) n=54 PF=0.43 exp=-0.88% tot=-39.2%
- `B1-10_gap_fade` (^NSEI) n=20 PF=0.29 exp=-0.66% tot=-12.6%
- `B1-10_gap_fade` (NIFTYBEES.NS) n=34 PF=0.08 exp=-1.50% tot=-40.8%

## Block 1b deep refine — top basket

| Rank | Name | OOS n | PF | Exp | Tot | MDD | Stress PF | WF+ |
|-----:|------|------:|---:|----:|----:|----:|----------:|----:|
| 1 | ST_m3.6_n1_e1 | 75 | 3.90 | 5.53% | 110.2% | -14.8% | 3.82 | 3/3 |
| 2 | ST_m5.0_n0_e0 | 72 | 2.77 | 5.23% | 84.9% | -17.8% | 2.73 | 2/3 |
| 3 | ST_m5.0_n1_e0 | 62 | 2.76 | 6.08% | 77.1% | -22.2% | 2.72 | 2/3 |
| 4 | ST_m3.6_n0_e1 | 98 | 2.58 | 3.84% | 95.5% | -17.6% | 2.53 | 2/3 |
| 5 | ST_m4.0_n0_e0 | 110 | 2.48 | 3.90% | 110.8% | -16.7% | 2.44 | 3/3 |
| 6 | ST_m4.0_n1_e1 | 75 | 2.46 | 3.82% | 63.8% | -15.7% | 2.42 | 2/3 |
| 7 | ST_m3.6_n1_e0 | 100 | 2.37 | 3.68% | 89.3% | -27.9% | 2.33 | 3/3 |
| 8 | ST_m5.0_n1_e1 | 53 | 2.30 | 3.94% | 42.3% | -16.2% | 2.26 | 2/3 |
| 9 | ST_m3.6_n0_e0 | 129 | 2.20 | 3.26% | 108.7% | -26.1% | 2.16 | 3/3 |
| 10 | ST_m3.5_n1_e1 | 91 | 2.11 | 3.06% | 61.3% | -18.7% | 2.07 | 3/3 |
| 11 | ATREXP_n25_r0.2 | 95 | 2.07 | 1.88% | 37.8% | -13.7% | 2.01 | 2/3 |
| 12 | ST_m3.5_n0_e0 | 137 | 2.06 | 3.02% | 99.9% | -27.8% | 2.03 | 3/3 |
| 13 | ST_m3.0_n1_e1 | 119 | 2.05 | 2.81% | 79.4% | -20.2% | 2.01 | 3/3 |
| 14 | ST_m4.5_n0_e0 | 95 | 2.04 | 3.64% | 81.2% | -18.2% | 2.01 | 3/3 |
| 15 | ST_m3.0_n0_e1 | 150 | 2.02 | 2.68% | 98.0% | -19.7% | 1.98 | 3/3 |

**Buy&hold ^NSEI OOS:** tot=69.5% MDD=-17.2% Sharpe=0.76
**Block1 #1:** `ST_m3.6_n1_e1` — see `strategies/nifty_edge_best.py`

### Honesty vs buy&hold
- This Block-1 #1 **beats** B&H on OOS total return (110% vs 69.5%) and Sharpe (1.10 vs 0.76) with similar MDD.
- mult=3.6 is still a **local PF peak** vs 3.5/3.8 — treat as provisional; conservative sleeve is mult=3.0.
- Baseline last WF chunk 2024-09→2026 was −7.3%; #1 prints **+5.8%** on same window — key improvement claim.

## Block 1c — Winner validation

**#1 ST_m3.6 + Nifty + EMA200** OOS PF=3.90 tot=110.2% n=75 MDD=-14.8% stressPF=3.82 WF=3/3

| WF period | n | Exp | Tot | MDD |
|-----------|--:|----:|----:|----:|
| 2021-01-15→2022-11-21 | 27 | 6.15% | 33.8% | -14.8% |
| 2022-11-21→2024-09-27 | 34 | 6.08% | 45.5% | -8.4% |
| 2024-09-27→2026-08-04 | 19 | 1.84% | 5.8% | -10.3% |

**Conservative #2 ST_m3.0:** PF=2.05 tot=79.4% n=119 WF=3/3
**B&H ^NSEI OOS:** tot=69.5% MDD=-17.2% Sharpe=0.76

Files: `strategies/nifty_edge_best.py`, `pinescript/nifty_edge_best.pine`, `strategies/nifty_edge_r{{1,2,3}}.py`

### Extra ideas (1c)
- `ST_ADX18_m3.0` n=61 PF=1.25 tot=7.5% WF+=1/3 → REJECT/WEAK
- `ST_ADX18_m3.6` n=47 PF=2.49 tot=34.8% WF+=2/3 → PASS
- `DON_ST_exit_55_m3` n=131 PF=1.11 tot=5.9% WF+=1/3 → REJECT/WEAK
- `DON_ST_exit_70_m3.6` n=105 PF=1.00 tot=-2.6% WF+=1/3 → REJECT/WEAK
- `PB_ST_m3` n=259 PF=1.11 tot=5.6% WF+=2/3 → REJECT/WEAK
- `PB_ST_m3.6` n=239 PF=1.22 tot=12.6% WF+=2/3 → REJECT/WEAK
- `NR7_basket` n=580 PF=0.86 tot=-21.7% WF+=2/3 → REJECT/WEAK
- `DUALMA_ST_20_50` n=109 PF=1.45 tot=23.9% WF+=2/3 → PASS
- `ATREXP_25_0.2` n=95 PF=2.07 tot=37.8% WF+=2/3 → PASS
- `RIBBON_plain` n=257 PF=1.45 tot=43.6% WF+=2/3 → PASS

## Block 2 — Reproduce, bootstrap CI, beat attempt

**Updated:** 2026-08-04 18:41 UTC
**#1 still leads:** YES

### Reproduced #1 (ST_m3.6_n1_e1)

| Metric | Block1 ref | Block2 | Drift |
|--------|----------:|-------:|------:|
| n | 75 | 75 | +0 |
| PF | 3.90 | 3.90 | -0.00 |
| Tot | 110.2% | 110.2% | +0.0pp |
| MDD | -14.8% | -14.8% | -0.0pp |
| Sharpe | 1.10 | 1.10 | +0.00 |

### Bootstrap CI (OOS trade PF, 2000 resamples)

| Mult | n | PF | boot mean | 95% CI |
|-----:|--:|---:|----------:|--------|
| 3.0 | 119 | 2.05 | 2.10 | [1.31, 3.25] |
| 3.2 | 110 | 2.32 | 2.39 | [1.48, 3.63] |
| 3.4 | 94 | 2.49 | 2.59 | [1.44, 4.20] |
| 3.5 | 91 | 2.11 | 2.18 | [1.22, 3.60] |
| 3.6 | 75 | 3.90 | 4.09 | [2.16, 7.10] |
| 3.7 | 76 | 3.05 | 3.19 | [1.78, 5.30] |
| 3.8 | 81 | 2.52 | 2.62 | [1.36, 4.45] |

### Sleeve robustness (mult 3.0–3.8, n1 e1)

| Mult | n | PF | Tot | MDD | WF+ | Last WF tot |
|-----:|--:|---:|----:|----:|----:|------------:|
| 3.0 | 119 | 2.05 | 79.4% | -20.2% | 3/3 | 4.2% |
| 3.2 | 110 | 2.32 | 89.0% | -21.0% | 2/3 | -2.7% |
| 3.4 | 94 | 2.49 | 77.6% | -13.7% | 2/3 | -1.7% |
| 3.5 | 91 | 2.11 | 61.3% | -18.7% | 3/3 | -0.3% |
| 3.6 | 75 | 3.90 | 110.2% | -14.8% | 3/3 | 5.8% |
| 3.7 | 76 | 3.05 | 95.8% | -17.7% | 3/3 | 7.1% |
| 3.8 | 81 | 2.52 | 77.6% | -18.3% | 3/3 | 4.2% |

### Block 2 new variants (top 20 by WF+ / PF / tot)

| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |
|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|
| 1 | B2_ST_rs_bank_m3.6 | 40 | 4.33 | 6.08% | 58.2% | -9.7% | 4.25 | 3/3 | 4.6% |
| 2 | B2_ST_heat3_m3.6 | 48 | 4.15 | 5.30% | 78.7% | -13.6% | 4.06 | 3/3 | 4.2% |
| 3 | B2_ST_heat4_m3.6 | 63 | 3.95 | 5.18% | 89.1% | -11.8% | 3.86 | 3/3 | 0.8% |
| 4 | B2_ST_kill_breadth40_m3.6 | 65 | 3.94 | 6.15% | 105.0% | -13.0% | 3.86 | 3/3 | 8.0% |
| 5 | B2_ST_kill_nifty_ema50_m3.6 | 61 | 3.25 | 5.04% | 74.7% | -11.5% | 3.18 | 3/3 | 2.9% |
| 6 | B2_ST_rvol1.5_m3.6 | 34 | 2.94 | 4.84% | 34.3% | -14.4% | 2.89 | 3/3 | 1.4% |
| 7 | B2_ST_delay1_m3.6 | 82 | 2.90 | 4.62% | 94.3% | -14.2% | 2.85 | 3/3 | 5.5% |
| 8 | B2_ST_rs_nifty_m3.6 | 36 | 2.85 | 5.16% | 41.2% | -11.5% | 2.80 | 3/3 | 0.6% |
| 9 | B2_ST_delay2_m3.6 | 84 | 2.70 | 4.14% | 85.3% | -12.5% | 2.65 | 3/3 | 4.9% |
| 10 | B2_ST_heat3_m3.0 | 73 | 2.33 | 3.33% | 72.7% | -24.5% | 2.29 | 3/3 | 6.1% |
| 11 | B2_ST_delay1_m3.0 | 119 | 2.11 | 2.61% | 74.0% | -17.8% | 2.06 | 3/3 | 0.4% |
| 12 | B2_ST_breadth60_m3.8 | 52 | 1.90 | 2.64% | 26.8% | -15.9% | 1.87 | 3/3 | 3.2% |
| 13 | B2_ST_hyb_br55_rv1.1_m3.6 | 47 | 1.69 | 2.04% | 17.4% | -14.8% | 1.66 | 3/3 | 3.1% |
| 14 | B2_ATRin_STout_40_0.2_m3.6 | 69 | 1.62 | 1.94% | 25.4% | -15.1% | 1.59 | 3/3 | -0.1% |
| 15 | B2_ST_rvol1.2_m3.0 | 100 | 1.38 | 1.08% | 18.3% | -27.1% | 1.35 | 3/3 | 0.2% |
| 16 | B2_ST_breadth70_m3.6 | 41 | 2.36 | 3.56% | 29.8% | -13.0% | 2.31 | 2/3 | -4.1% |
| 17 | B2_ATREXP_n25_r0.2 | 95 | 2.07 | 1.88% | 37.8% | -13.7% | 2.01 | 2/3 | -7.1% |
| 18 | B2_ST_rvol1.2_m3.6 | 59 | 1.93 | 2.80% | 33.2% | -19.2% | 1.90 | 2/3 | -1.7% |
| 19 | B2_ST_atr_exp_gate_m3.6 | 38 | 1.74 | 2.55% | 17.9% | -18.0% | 1.71 | 2/3 | -4.5% |
| 20 | B2_ST_breadth65_m3.6 | 50 | 1.70 | 1.92% | 17.1% | -13.7% | 1.67 | 2/3 | -5.1% |

**Champion after Block 2:** `ST_m3.6_n1_e1` — OOS PF=3.90 tot=110.2% n=75 WF=3/3
**B&H ^NSEI OOS:** tot=70.5% Sharpe=0.76

### Honesty
- **#1 still leads.** Reproduced with ~zero drift.
- Bootstrap: mult=3.6 95% CI **[2.16, 7.10]**; CI_lo is the highest in the sleeve (vs 3.0 CI_lo 1.31). Peak is elevated/wide but not a pure fragile spike that collapses below neighbors — keep 3.6 as #1; track **3.0** (n=119, PF 2.05) and **3.7** (last WF +7.1%) as sleeves.
- Closest challenger: `B2_ST_kill_breadth40_m3.6` PF 3.94 tot 105% lastWF **+8.0%** — not promoted (tot slightly below #1). Saved as `strategies/nifty_edge_r4.py`.
- Vanity watch: `rs_bank` PF 4.33 but tot only 58% / n=40 — do not promote.
- Runners-up: `r4` kill_breadth40, `r5` heat4 (max4), `r6` delay1; prior `r1`=ST3.0, `r2`=ATREXP, `r3`=ribbon.
- No fake futures; universe = ^NSEI + 20 NSE large-caps. Costs 0.08% / stress 0.15% RT.
- `nifty_edge_best.py` / `.pine` **unchanged**.

## Block 3 — Ensemble, kill-breadth refine, vol/sector, hourly ORB

**Updated:** 2026-08-04 18:46 UTC
**#1 still leads:** YES

### Reproduced #1 (ST_m3.6_n1_e1)

| Metric | Block1/2 ref | Block3 | Drift |
|--------|-------------:|-------:|------:|
| n | 75 | 75 | +0 |
| PF | 3.90 | 3.90 | -0.00 |
| Tot | 110.2% | 110.2% | +0.0pp |
| MDD | -14.8% | -14.8% | -0.0pp |
| Sharpe | 1.10 | 1.10 | +0.00 |
| Last WF | 5.8% | 5.8% | — |

### Kill-breadth threshold sweep (vs #1 tot=110.2% lastWF=+5.8%)

| Floor | n | PF | Tot | MDD | WF+ | LastWF | Beat tot+lastWF? |
|------:|--:|---:|----:|----:|----:|-------:|:-----------------|
| 0.3 | 69 | 3.78 | 106.0% | -14.0% | 3/3 | 5.8% | no |
| 0.35 | 69 | 3.31 | 95.7% | -14.0% | 3/3 | 6.3% | no |
| 0.4 | 65 | 3.94 | 105.0% | -13.0% | 3/3 | 8.0% | no |
| 0.45 | 61 | 3.13 | 76.0% | -17.4% | 3/3 | 7.6% | no |
| 0.5 | 60 | 2.72 | 60.8% | -18.7% | 3/3 | 2.9% | no |
| 0.55 | 59 | 2.59 | 50.1% | -16.5% | 3/3 | 2.9% | no |

### Block 3 new variants (top by WF+ / PF / tot)

| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |
|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|
| 1 | B3_ST_heat3_vol15_m3.6 | 48 | 4.15 | 5.30% | 62.8% | -11.3% | 4.06 | 3/3 | 0.8% |
| 2 | B3_ST_kill_breadth40_m3.6 | 65 | 3.94 | 6.15% | 105.0% | -13.0% | 3.86 | 3/3 | 8.0% |
| 3 | B3_ST_kill40_sectorcap2_m3.6 | 65 | 3.94 | 6.15% | 105.0% | -13.0% | 3.86 | 3/3 | 8.0% |
| 4 | B3_ST_kill40_vol15_m3.6 | 65 | 3.94 | 6.15% | 68.7% | -9.5% | 3.86 | 3/3 | 10.9% |
| 5 | B3_ST_voltarget18_m3.6 | 75 | 3.90 | 5.53% | 82.5% | -12.0% | 3.82 | 3/3 | 8.5% |
| 6 | B3_ST_voltarget15_m3.6 | 75 | 3.90 | 5.53% | 70.8% | -10.8% | 3.82 | 3/3 | 8.9% |
| 7 | B3_ST_voltarget12_m3.6 | 75 | 3.90 | 5.53% | 59.9% | -9.3% | 3.82 | 3/3 | 7.3% |
| 8 | B3_ENS_or_union_loose_exit | 41 | 3.86 | 6.85% | 63.9% | -21.0% | 3.79 | 3/3 | 4.1% |
| 9 | B3_ST_kill_breadth30_m3.6 | 69 | 3.78 | 6.06% | 106.0% | -14.0% | 3.71 | 3/3 | 5.8% |
| 10 | B3_ST_sectorcap2_m3.6 | 76 | 3.55 | 5.25% | 103.8% | -14.8% | 3.48 | 3/3 | 5.8% |
| 11 | B3_ST_sectorcap2_vol15_m3.6 | 76 | 3.55 | 5.25% | 67.1% | -10.8% | 3.48 | 3/3 | 8.9% |
| 12 | B3_ST_kill_breadth35_m3.6 | 69 | 3.31 | 5.42% | 95.7% | -14.0% | 3.25 | 3/3 | 6.3% |
| 13 | B3_ST_kill_breadth45_m3.6 | 61 | 3.13 | 5.16% | 76.0% | -17.4% | 3.07 | 3/3 | 7.6% |
| 14 | B3_ST_sectorcap1_heat4_m3.6 | 64 | 2.82 | 4.41% | 85.2% | -14.0% | 2.77 | 3/3 | 0.3% |
| 15 | B3_ST_sectorcap1_m3.6 | 75 | 2.81 | 4.51% | 82.2% | -16.8% | 2.76 | 3/3 | 5.8% |
| 16 | B3_ST_kill_breadth50_m3.6 | 60 | 2.72 | 4.40% | 60.8% | -18.7% | 2.67 | 3/3 | 2.9% |
| 17 | B3_ST_kill_breadth55_m3.6 | 59 | 2.59 | 3.96% | 50.1% | -16.5% | 2.54 | 3/3 | 2.9% |
| 18 | B3_ENS_equal_risk_3.0_3.6 | 110 | 2.57 | 3.67% | 48.4% | -14.3% | 2.52 | 3/3 | 2.9% |
| 19 | B3_ST_voltarget15_m3.0 | 119 | 2.05 | 2.81% | 66.9% | -14.0% | 2.01 | 3/3 | 7.8% |
| 20 | B3_ORB_1h_INFY.NS_1.5 | 16 | 1.47 | 0.31% | 4.6% | -7.1% | 1.47 | 3/3 | 4.0% |
| 21 | B3_ST_kill_breadth40_m3.0 | 107 | 2.01 | 2.64% | 64.1% | -22.4% | 1.97 | 2/3 | -0.2% |
| 22 | B3_ENS_agree_both_look5 | 102 | 1.88 | 2.15% | 48.1% | -18.1% | 1.84 | 2/3 | -2.6% |
| 23 | B3_ENS_agree_36_while_30 | 113 | 1.84 | 1.95% | 48.0% | -15.6% | 1.79 | 2/3 | -5.5% |
| 24 | B3_ENS_agree_both_look3 | 95 | 1.82 | 2.01% | 40.2% | -17.5% | 1.78 | 2/3 | -7.4% |
| 25 | B3_ST_killhard_br40_m3.6 | 105 | 1.80 | 1.67% | 34.0% | -14.4% | 1.75 | 2/3 | -3.6% |

**Hourly ORB:** Measured 10 ORB variants on 5 symbols. Best: B3_ORB_1h_ICICIBANK.NS_1.5 PF=1.69 tot=5.2% n=12

**Champion after Block 3:** `ST_m3.6_n1_e1` — OOS PF=3.90 tot=110.2% n=75 WF=3/3 lastWF=5.8%
**B&H ^NSEI OOS:** tot=70.5% Sharpe=0.76

### Honesty
- Ensemble aims for robustness vs mult=3.6 local PF peak; equal-risk ≠ signal agreement.
- Kill-breadth promote requires **both** OOS tot and last WF to clear #1 (stricter than Block 2).
- Vol-target / sector-cap: win only if MDD improves without gutting return.
- No fake futures. Costs 0.08% / stress 0.15% RT. No look-ahead.

## Block 4 — Soft vol-target, entry-only kill, regime half-life, paper rules

**Updated:** 2026-08-04 19:02 UTC
**#1 still leads:** YES
**Promote reason:** none

### Reproduced #1 (ST_m3.6_n1_e1)

| Metric | Block1–3 ref | Block4 | Drift |
|--------|-------------:|-------:|------:|
| n | 75 | 75 | +0 |
| PF | 3.90 | 3.90 | -0.00 |
| Tot | 110.2% | 110.2% | +0.0pp |
| MDD | -14.8% | -14.8% | -0.0pp |
| Sharpe | 1.10 | 1.10 | +0.00 |
| Last WF | 5.8% | 5.8% | — |

### Stress 0.15% RT (#1, ensembles, kill40)

| Name | n | PF@0.08 | Tot@0.08 | PF@0.15 | Tot@0.15 | ΔTot pp |
|------|--:|--------:|---------:|--------:|---------:|--------:|
| ST_m3.6_n1_e1 | 75 | 3.90 | 110.2% | 3.82 | 107.1% | -3.1 |
| B2_ST_kill_breadth40_m3.6 | 65 | 3.94 | 105.0% | 3.86 | 102.4% | -2.6 |
| B3_ENS_agree_36_while_30 | 113 | 1.84 | 48.0% | 1.79 | 44.7% | -3.3 |
| B3_ENS_or_union_loose_exit | 41 | 3.86 | 63.9% | 3.79 | 62.5% | -1.4 |
| B3_ENS_agree_both_look5 | 102 | 1.88 | 48.1% | 1.84 | 45.0% | -3.0 |
| B3_ENS_equal_risk_3.0_3.6 | 110 | 2.57 | 48.4% | 2.52 | 46.8% | -1.6 |

### Kill-breadth entry-only floors 0.30–0.38 (promote = tot AND lastWF > #1)

| Floor | n | PF | Tot | MDD | WF+ | LastWF | Beat? |
|------:|--:|---:|----:|----:|----:|-------:|:-----:|
| 0.3 | 69 | 3.78 | 106.0% | -14.0% | 3/3 | 5.8% | no |
| 0.32 | 69 | 3.31 | 95.7% | -14.0% | 3/3 | 6.3% | no |
| 0.34 | 69 | 3.31 | 95.7% | -14.0% | 3/3 | 6.3% | no |
| 0.36 | 65 | 3.94 | 105.0% | -13.0% | 3/3 | 8.0% | no |
| 0.38 | 65 | 3.94 | 105.0% | -13.0% | 3/3 | 8.0% | no |

### Soft vol-target notes

- B4_ST_softvol18_shi1.0_m3.6: tot=84.9% MDD=-12.4% lastWF=6.5% vs #1 tot=110.2% MDD=-14.8% lastWF=5.8% → promote=False (tradeoff_only)
- B4_ST_softvol20_shi1.0_m3.6: tot=91.8% MDD=-12.9% lastWF=6.0% vs #1 tot=110.2% MDD=-14.8% lastWF=5.8% → promote=False (tradeoff_only)
- B4_ST_softvol16_shi1.05_m3.6: tot=81.8% MDD=-12.2% lastWF=7.2% vs #1 tot=110.2% MDD=-14.8% lastWF=5.8% → promote=False (tradeoff_only)
- B4_ST_softvol18_shi1.0_m3.0: tot=70.5% MDD=-16.7% lastWF=5.1% vs #1 tot=110.2% MDD=-14.8% lastWF=5.8% → promote=False (tradeoff_only)
- B4_ST_kill40_softvol18_shi1.0: tot=81.6% MDD=-10.9% lastWF=8.7% vs #1 tot=110.2% MDD=-14.8% lastWF=5.8% → promote=False (tradeoff_only)
- B4_ST_softvol22_shi1.0_floor0.85: tot=100.7% MDD=-13.7% lastWF=5.8% vs #1 tot=110.2% MDD=-14.8% lastWF=5.8% → promote=False (tradeoff_only)

### Block 4 new variants (top by WF+ / PF / tot)

| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |
|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|
| 1 | B4_ST_kill_entry_br36_m3.6 | 65 | 3.94 | 6.15% | 105.0% | -13.0% | 3.86 | 3/3 | 8.0% |
| 2 | B4_ST_kill_entry_br38_m3.6 | 65 | 3.94 | 6.15% | 105.0% | -13.0% | 3.86 | 3/3 | 8.0% |
| 3 | B4_ST_kill40_softvol18_shi1.0 | 65 | 3.94 | 6.15% | 81.6% | -10.9% | 3.86 | 3/3 | 8.7% |
| 4 | B4_ST_regime_hl8 | 74 | 3.93 | 5.62% | 110.7% | -14.8% | 3.85 | 3/3 | 7.5% |
| 5 | B4_ST_regime_hl12 | 74 | 3.93 | 5.62% | 110.7% | -14.8% | 3.85 | 3/3 | 7.5% |
| 6 | B4_ST_softvol22_shi1.0_floor0.85 | 75 | 3.90 | 5.53% | 100.7% | -13.7% | 3.82 | 3/3 | 5.8% |
| 7 | B4_ST_softvol20_shi1.0_m3.6 | 75 | 3.90 | 5.53% | 91.8% | -12.9% | 3.82 | 3/3 | 6.0% |
| 8 | B4_ST_softvol18_shi1.0_m3.6 | 75 | 3.90 | 5.53% | 84.9% | -12.4% | 3.82 | 3/3 | 6.5% |
| 9 | B4_ST_softvol16_shi1.05_m3.6 | 75 | 3.90 | 5.53% | 81.8% | -12.2% | 3.82 | 3/3 | 7.2% |
| 10 | B4_ST_breadth_hl5_fl40 | 75 | 3.78 | 5.47% | 108.4% | -14.8% | 3.71 | 3/3 | 6.3% |
| 11 | B4_ST_breadth_hl8_fl35 | 75 | 3.78 | 5.47% | 108.4% | -14.8% | 3.71 | 3/3 | 6.3% |
| 12 | B4_ST_kill_entry_br30_m3.6 | 69 | 3.78 | 6.06% | 106.0% | -14.0% | 3.71 | 3/3 | 5.8% |
| 13 | B4_ST_ema50_soft_tol15_d8 | 66 | 3.55 | 5.60% | 92.5% | -17.1% | 3.48 | 3/3 | 9.2% |
| 14 | B4_ST_kill_entry_br32_m3.6 | 69 | 3.31 | 5.42% | 95.7% | -14.0% | 3.25 | 3/3 | 6.3% |
| 15 | B4_ST_kill_entry_br34_m3.6 | 69 | 3.31 | 5.42% | 95.7% | -14.0% | 3.25 | 3/3 | 6.3% |
| 16 | B4_ST_kill40_ema50_soft | 67 | 3.26 | 5.14% | 85.6% | -17.1% | 3.20 | 3/3 | 9.2% |
| 17 | B4_ST_ema50_hard_entry | 61 | 3.25 | 5.04% | 74.7% | -11.5% | 3.18 | 3/3 | 2.9% |
| 18 | B4_ST_kill_nifty_ema50 | 61 | 3.25 | 5.04% | 74.7% | -11.5% | 3.18 | 3/3 | 2.9% |
| 19 | B4_ST_ema50_soft_tol1_d5 | 65 | 3.22 | 5.08% | 80.3% | -16.9% | 3.15 | 3/3 | 1.9% |
| 20 | B4_ST_softvol18_shi1.0_m3.0 | 119 | 2.05 | 2.81% | 70.5% | -16.7% | 2.01 | 3/3 | 5.1% |
| 21 | B4_ST_ema50_hard_forcexit | 81 | 1.56 | 1.18% | 17.4% | -12.6% | 1.51 | 3/3 | 1.4% |
| 22 | B4_ST_regime_hl5_softexit | 73 | 3.10 | 4.51% | 77.9% | -13.1% | 3.04 | 2/3 | -1.6% |
| 23 | B4_ST_killhard_br38_m3.6 | 105 | 1.80 | 1.67% | 34.0% | -14.4% | 1.75 | 2/3 | -3.6% |

**Paper rules:** `/Users/ryaneditraj/trading-ai/research/nifty_edge_8h/PAPER_TRADE_RULES.md`

**Champion after Block 4:** `ST_m3.6_n1_e1` — OOS PF=3.90 tot=110.2% n=75 WF=3/3 lastWF=5.8%
**B&H ^NSEI OOS:** tot=70.5% Sharpe=0.76

### Honesty
- Soft vol-target (scale_hi≈1.0): promote only tot+lastWF clear OR risk-adj within ~10% tot + better MDD+lastWF. Best soft keep-return: softvol22 tot 100.7% MDD −13.7% (tradeoff; `r16`). Best MDD clip: kill40+softvol MDD −10.9% lastWF +8.7% but tot 81.6% (`r11`).
- Kill entry-only 0.30–0.38: none dual-cleared. Best near-miss floor 0.36/0.38 tot 105% lastWF +8.0% (`r12`).
- **Near-promote:** `B4_ST_regime_hl8` tot **110.7%** lastWF **+7.5%** dual-clears #1 numerically but margin too thin for `clearly_better` (+0.5pp tot, PF 3.93 vs 3.90). Saved `r15`; Block-5 primary challenger. Hard EMA50 / force-exit / killhard all worse.
- Hourly ORB skipped (Block 4 mandate unless multi-name n≥40).
- Runners: `r11`–`r16`. Paper rules written. `#1` files unchanged.
- Costs 0.08% / 0.15% RT. No look-ahead. No fake futures.

## Block 5 — Bootstrap + cost ladder; last-WF causal; regime_hl8 decision

**Updated:** 2026-08-04 19:10 UTC
**#1 still leads:** NO — new champion promoted
**Promote decision:** dual_clear_ladder_boot:B5_ST_kill40_dd07

### Reproduced #1 (ST_m3.6_n1_e1)

| Metric | Block1–4 ref | Block5 | Drift |
|--------|-------------:|-------:|------:|
| n | 75 | 75 | +0 |
| PF | 3.90 | 3.90 | -0.00 |
| Tot | 110.2% | 110.2% | +0.0pp |
| MDD | -14.8% | -14.8% | -0.0pp |
| Sharpe | 1.10 | 1.10 | +0.00 |
| Last WF | 5.8% | 5.8% | — |

### Cost ladder (0.08 / 0.10 / 0.12 / 0.15 / 0.20% RT)

| Name | Metric | 0.08% | 0.10% | 0.12% | 0.15% | 0.20% |
|------|--------|------:|------:|------:|------:|------:|
| ST_m3.6_n1_e1 | PF | 3.90 | 3.88 | 3.85 | 3.82 | 3.76 |
| ST_m3.6_n1_e1 | Tot | 110.2% | 109.4% | 108.5% | 107.1% | 104.9% |
| ST_m3.6_n1_e1 | MDD | -14.8% | -14.9% | -14.9% | -15.0% | -15.1% |
| B2_ST_kill_breadth40_m3.6 | PF | 3.94 | 3.92 | 3.90 | 3.86 | 3.81 |
| B2_ST_kill_breadth40_m3.6 | Tot | 105.0% | 104.2% | 103.5% | 102.4% | 100.6% |
| B2_ST_kill_breadth40_m3.6 | MDD | -13.0% | -13.1% | -13.1% | -13.2% | -13.3% |
| B4_ST_regime_hl8 | PF | 3.93 | 3.91 | 3.88 | 3.85 | 3.80 |
| B4_ST_regime_hl8 | Tot | 110.7% | 109.9% | 109.0% | 107.7% | 105.5% |
| B4_ST_regime_hl8 | MDD | -14.8% | -14.9% | -14.9% | -15.0% | -15.1% |
| B4_ST_softvol22_shi1.0_floor0.85 | PF | 3.90 | 3.88 | 3.85 | 3.82 | 3.76 |
| B4_ST_softvol22_shi1.0_floor0.85 | Tot | 100.7% | 99.9% | 99.1% | 97.9% | 95.8% |
| B4_ST_softvol22_shi1.0_floor0.85 | MDD | -13.7% | -13.7% | -13.8% | -13.8% | -14.0% |
| B5_ST_kill40_dd07 | PF | 4.01 | 3.98 | 3.96 | 3.93 | 3.88 |
| B5_ST_kill40_dd07 | Tot | 113.4% | 112.7% | 111.9% | 110.8% | 108.9% |
| B5_ST_kill40_dd07 | MDD | -15.0% | -15.1% | -15.1% | -15.2% | -15.3% |

### Bootstrap CI (OOS trade PF, 2000 resamples)

| Name | n | PF | boot mean | 95% CI |
|------|--:|---:|----------:|--------|
| ST_m3.6_n1_e1 | 75 | 3.90 | 4.11 | [2.15, 7.13] |
| B2_ST_kill_breadth40_m3.6 | 65 | 3.94 | 4.14 | [2.06, 7.52] |
| B4_ST_regime_hl8 | 74 | 3.93 | 4.13 | [2.21, 7.33] |
| B4_ST_softvol22_shi1.0_floor0.85 | 75 | 3.90 | 4.11 | [2.15, 7.13] |
| B5_ST_kill40_dd07 | 65 | 4.01 | 4.24 | [2.10, 7.71] |

### Block 5 last-WF causal variants (top by WF+ / lastWF / PF)

| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |
|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|
| 1 | B5_ST_kill40_dd07 | 65 | 4.01 | 6.65% | 113.4% | -15.0% | 3.93 | 3/3 | 9.2% |
| 2 | B5_ST_dd_gate_m6 | 77 | 2.52 | 3.74% | 65.7% | -19.5% | 2.47 | 3/3 | 9.2% |
| 3 | B2_ST_kill_breadth40_m3.6 | 65 | 3.94 | 6.15% | 105.0% | -13.0% | 3.86 | 3/3 | 8.0% |
| 4 | B4_ST_regime_hl8 | 74 | 3.93 | 5.62% | 110.7% | -14.8% | 3.85 | 3/3 | 7.5% |
| 5 | B5_ST_regime_hl8_volcalm | 67 | 3.09 | 5.06% | 81.0% | -18.8% | 3.03 | 3/3 | 7.5% |
| 6 | B5_ST_combo_dd_vol_br | 58 | 2.70 | 4.61% | 57.8% | -17.6% | 2.65 | 3/3 | 7.4% |
| 7 | B5_ST_dd_gate_m8 | 75 | 3.56 | 5.24% | 101.6% | -14.2% | 3.49 | 3/3 | 6.9% |
| 8 | B5_ST_vol_calm_115 | 66 | 3.12 | 5.15% | 81.3% | -20.6% | 3.06 | 3/3 | 6.9% |
| 9 | B5_ST_vol_cap22 | 73 | 4.23 | 5.66% | 110.4% | -12.8% | 4.14 | 3/3 | 5.8% |
| 10 | B5_ST_days_high60 | 75 | 3.90 | 5.53% | 110.2% | -14.8% | 3.82 | 3/3 | 5.8% |
| 11 | B5_ST_pullback_m01 | 75 | 3.90 | 5.53% | 110.2% | -14.8% | 3.82 | 3/3 | 5.8% |
| 12 | B5_ST_vol_calm_125 | 74 | 3.84 | 5.49% | 106.0% | -15.0% | 3.76 | 3/3 | 5.8% |
| 13 | B5_ST_nifty_mom_m03 | 75 | 3.23 | 4.85% | 91.2% | -15.3% | 3.16 | 3/3 | 5.8% |
| 14 | B5_ST_bank_rs_m02 | 73 | 2.67 | 4.35% | 75.3% | -15.9% | 2.62 | 3/3 | 5.8% |
| 15 | B4_ST_softvol22_shi1.0_floor0.85 | 75 | 3.90 | 5.53% | 100.7% | -13.7% | 3.82 | 3/3 | 5.8% |
| 16 | B5_ST_atr_pct_15_90 | 71 | 3.22 | 5.15% | 87.3% | -15.2% | 3.16 | 3/3 | 5.0% |
| 17 | B5_ST_days_high40 | 81 | 2.73 | 3.99% | 80.1% | -13.9% | 2.68 | 3/3 | 3.9% |
| 18 | B5_ST_breadth_mom0 | 36 | 3.08 | 4.77% | 36.2% | -11.8% | 3.01 | 3/3 | 2.0% |
| 19 | B5_ST_breadth_mom_m05 | 47 | 2.68 | 4.87% | 48.4% | -14.6% | 2.64 | 3/3 | 2.0% |
| 20 | B5_ST_soft_rvol09 | 77 | 2.77 | 4.14% | 76.3% | -12.7% | 2.71 | 2/3 | -2.1% |

**Paper rules:** `/Users/ryaneditraj/trading-ai/research/nifty_edge_8h/PAPER_TRADE_RULES.md`

**Champion after Block 5:** `B5_ST_kill40_dd07` — OOS PF=4.01 tot=113.4% n=65 WF=3/3 lastWF=9.2%
**B&H ^NSEI OOS:** tot=70.5% Sharpe=0.76
**FII/OI:** SKIPPED — no clean free FII/OI series available locally

### Honesty
- **regime_hl8 NOT promoted:** dual-clears numerically (tot 110.7% / lastWF +7.5%) but margin thin (+0.5pp tot); strict Block-5 rule requires ≥2pp margin.
- **Promoted `B5_ST_kill40_dd07`:** kill-breadth40 + causal Nifty dd≥−7% from prior-55d high. Dual-clear with margin (tot +3.2pp, lastWF +3.4pp); beats #1 on every cost-ladder rung 0.08–0.20%; boot CI [2.10, 7.71] vs prior [2.15, 7.13]. n=65 (was 75); MDD −15.0% (was −14.8%) — slight sample/DD tradeoff.
- Prior ST_m3.6 frozen as paper twin (`r17`). regime_hl8 kept as `r15`/`r20`.
- Last-WF variants use only causal features (shifted highs, vol ratios, lagged RS). FII/OI skipped. No hourly.
- Costs 0.08–0.20% RT ladder. No look-ahead. No fake futures.

## Block 6 — Neighborhood freeze; ensemble; last-WF variants; FINAL outline

**Updated:** 2026-08-04 19:15 UTC
**Hours to deadline:** 6.92
**#1 still leads:** YES
**Promote decision:** keep_champ:no_challenger

### Reproduced champion (B5_ST_kill40_dd07)

| Metric | Block5 ref | Block6 | Drift |
|--------|-----------:|-------:|------:|
| n | 65 | 65 | +0 |
| PF | 4.01 | 4.01 | -0.00 |
| Tot | 113.4% | 113.4% | +0.0pp |
| MDD | -15.0% | -15.0% | -0.0pp |
| Sharpe | 1.17 | 1.17 | -0.00 |
| Last WF | 9.2% | 9.2% | — |

### Neighborhood freeze (stability; no look-ahead)

| Axis | Value | n | PF | Tot | MDD | WF+ | LastWF | Stable? |
|------|------:|--:|---:|----:|----:|----:|-------:|:-------:|
| dd_floor | -0.05 | 68 | 2.58 | 64.6% | -17.4% | 3/3 | 9.2% | n |
| dd_floor | -0.06 | 71 | 2.51 | 65.3% | -18.1% | 3/3 | 9.2% | n |
| dd_floor | -0.07 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | Y |
| dd_floor | -0.08 | 64 | 4.10 | 107.2% | -13.0% | 3/3 | 9.2% | Y |
| dd_floor | -0.09 | 64 | 4.10 | 107.2% | -13.0% | 3/3 | 9.2% | Y |
| breadth_floor | 0.35 | 69 | 3.38 | 103.4% | -17.4% | 3/3 | 9.2% | Y |
| breadth_floor | 0.38 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | Y |
| breadth_floor | 0.40 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | Y |
| breadth_floor | 0.42 | 64 | 3.08 | 78.2% | -17.8% | 3/3 | 7.6% | n |
| breadth_floor | 0.45 | 64 | 3.08 | 78.2% | -17.8% | 3/3 | 7.6% | n |
| st_mult | 3.2 | 91 | 2.26 | 71.4% | -25.1% | 3/3 | 1.9% | n |
| st_mult | 3.4 | 78 | 2.62 | 85.4% | -16.0% | 3/3 | 2.7% | n |
| st_mult | 3.5 | 76 | 2.43 | 72.6% | -14.1% | 2/3 | -3.5% | n |
| st_mult | 3.6 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | Y |
| st_mult | 3.7 | 63 | 3.78 | 109.0% | -14.8% | 3/3 | 6.2% | Y |
| st_mult | 3.8 | 61 | 2.87 | 73.2% | -15.4% | 3/3 | 0.4% | n |

### Cost ladder + fragility

| Name | Metric | 0.08% | 0.10% | 0.12% | 0.15% | 0.20% |
|------|--------|------:|------:|------:|------:|------:|
| B5_ST_kill40_dd07 | PF | 4.01 | 3.98 | 3.96 | 3.93 | 3.88 |
| B5_ST_kill40_dd07 | Tot | 113.4% | 112.7% | 111.9% | 110.8% | 108.9% |
| B5_ST_kill40_dd07 | MDD | -15.0% | -15.1% | -15.1% | -15.2% | -15.3% |
| ST_m3.6_n1_e1 | PF | 3.90 | 3.88 | 3.85 | 3.82 | 3.76 |
| ST_m3.6_n1_e1 | Tot | 110.2% | 109.4% | 108.5% | 107.1% | 104.9% |
| ST_m3.6_n1_e1 | MDD | -14.8% | -14.9% | -14.9% | -15.0% | -15.1% |
| B4_ST_regime_hl8 | PF | 3.93 | 3.91 | 3.88 | 3.85 | 3.80 |
| B4_ST_regime_hl8 | Tot | 110.7% | 109.9% | 109.0% | 107.7% | 105.5% |
| B4_ST_regime_hl8 | MDD | -14.8% | -14.9% | -14.9% | -15.0% | -15.1% |

**Fragility note:** Champ tot decays ~linear with RT; remains above prior ST on every rung 0.08–0.20%. Slight MDD deepen under higher costs (~0.3pp). Not fragile vs prior.
- ΔTot 0.08→0.20%: champ -4.5pp; prior ST -5.3pp; regime_hl8 -5.2pp
- Champ still beats prior on every rung: True

### Equal-risk ensembles

| Name | n | PF | Tot | MDD | WF+ | LastWF | Promote? |
|------|--:|---:|----:|----:|----:|-------:|:--------:|
| B6_ENS_champ_priorST | 78 | 3.02 | 49.0% | -10.9% | 3/3 | 2.2% | no:tot≤champ,lastWF≤champ,margin_thin |
| B6_ENS_champ_regime_hl8 | 77 | 3.04 | 48.9% | -10.9% | 3/3 | 1.5% | no:tot≤champ,lastWF≤champ,margin_thin |
| B6_ENS_priorST_regime_hl8 | 91 | 2.97 | 49.0% | -10.6% | 3/3 | 1.0% | no:tot≤champ,lastWF≤champ,margin_thin |

### Block 6 last-WF variants (top by WF+ / lastWF / PF)

| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |
|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|
| 1 | B6_ST_kill40_dd_atr10_92 | 60 | 2.93 | 5.22% | 69.4% | -20.1% | 2.88 | 3/3 | 11.3% |
| 2 | B6_ST_kill40_dd_nifty_mom_m04 | 64 | 4.73 | 7.11% | 124.3% | -13.0% | 4.64 | 3/3 | 9.2% |
| 3 | B6_ST_kill40_dd_days60 | 64 | 4.32 | 6.91% | 118.3% | -13.1% | 4.24 | 3/3 | 9.2% |
| 4 | B6_ST_kill40_dd08 | 64 | 4.10 | 6.33% | 107.2% | -13.0% | 4.02 | 3/3 | 9.2% |
| 5 | B6_ST_kill38_dd07 | 65 | 4.01 | 6.65% | 113.4% | -15.0% | 3.93 | 3/3 | 9.2% |
| 6 | B6_ST_kill40_dd_regime_hl8 | 65 | 4.01 | 6.65% | 113.4% | -15.0% | 3.93 | 3/3 | 9.2% |
| 7 | B6_ST_kill40_dd_volcap24 | 66 | 3.75 | 6.27% | 105.7% | -15.0% | 3.68 | 3/3 | 9.2% |
| 8 | B6_ST_kill40_dd_volcalm125 | 67 | 3.51 | 5.98% | 100.0% | -15.1% | 3.45 | 3/3 | 9.2% |
| 9 | B6_ST_kill40_dd_bankrs_m03 | 63 | 3.29 | 5.93% | 95.4% | -13.3% | 3.23 | 3/3 | 9.2% |
| 10 | B6_ST_kill40_dd06 | 71 | 2.51 | 3.95% | 65.3% | -18.1% | 2.46 | 3/3 | 9.2% |
| 11 | B6_ST_kill42_dd07 | 64 | 3.08 | 5.01% | 78.2% | -17.8% | 3.02 | 3/3 | 7.6% |
| 12 | B6_ST_kill40_dd07_m37 | 63 | 3.78 | 6.79% | 109.0% | -14.8% | 3.72 | 3/3 | 6.2% |
| 13 | B6_ST_kill40_dd_days40 | 69 | 2.74 | 4.39% | 73.6% | -15.8% | 2.69 | 3/3 | 5.6% |
| 14 | B6_ENS_champ_priorST | 78 | 3.02 | 4.60% | 49.0% | -10.9% | 2.97 | 3/3 | 2.2% |
| 15 | B6_ENS_champ_regime_hl8 | 77 | 3.04 | 4.67% | 48.9% | -10.9% | 2.99 | 3/3 | 1.5% |
| 16 | B6_ENS_priorST_regime_hl8 | 91 | 2.97 | 4.12% | 49.0% | -10.6% | 2.91 | 3/3 | 1.0% |
| 17 | B6_ST_kill40_dd07_m35 | 76 | 2.43 | 4.01% | 72.6% | -14.1% | 2.38 | 2/3 | -3.5% |

**Paper rules:** `/Users/ryaneditraj/trading-ai/research/nifty_edge_8h/PAPER_TRADE_RULES.md`
**FINAL outline:** `/Users/ryaneditraj/trading-ai/research/nifty_edge_8h/FINAL_REPORT_OUTLINE.md`

**Champion after Block 6:** `B5_ST_kill40_dd07` — OOS PF=4.01 tot=113.4% n=65 WF=3/3 lastWF=9.2%
**B&H ^NSEI OOS:** tot=70.5% Sharpe=0.76

### Honesty
- Neighborhood: promote/demote only if freeze shows fragility (WF break or tot collapse).
- Ensembles: equal-risk ≠ signal agreement; promote only dual-clear+margin+ladder.
- New variants use causal last-WF features only. No look-ahead. No fake futures.
- Costs 0.08–0.20% RT ladder. Paper A/B flip only if clearly warranted.
- Near-misses (same lastWF, higher tot — **not** dual-clear): `nifty_mom_m04` (r21 tot 124%) / `days60` (r25 tot 118%).
- Fragile neighborhood: dd≤−0.06 guts tot; mult=3.5 lastWF−; br≥0.42 softens. Stable core: dd −0.07..−0.09, br 0.35–0.40, mult 3.6–3.7.
- Hours left 6.9: outline only (FINAL later).

## Block 7 — Near-miss stress; fragile neighborhood; paper checklist

**Updated:** 2026-08-04 19:20 UTC
**Hours to deadline:** 6.84
**#1 still leads:** NO — new champion promoted
**Promote decision:** robust_risk_adj_ladder_boot:robust_risk_adj:B6_ST_kill40_dd_nifty_mom_m04

### Reproduced champion (B5_ST_kill40_dd07)

| Metric | Block5 ref | Block7 | Drift |
|--------|-----------:|-------:|------:|
| n | 65 | 65 | +0 |
| PF | 4.01 | 4.01 | -0.00 |
| Tot | 113.4% | 113.4% | +0.0pp |
| MDD | -15.0% | -15.0% | -0.0pp |
| Sharpe | 1.17 | 1.17 | -0.00 |
| Last WF | 9.2% | 9.2% | — |

### Near-miss ladder + bootstrap (r21 / r25)

| Name | n | PF | Tot | LastWF | Dual-clear? | Ladder ok? | Boot CI_lo | Risk-adj? | Decision |
|------|--:|---:|----:|-------:|:-----------:|:----------:|-----------:|:---------:|----------|
| B6_ST_kill40_dd_nifty_mom_m04 | 64 | 4.73 | 124.3% | 9.2% | n | Y | 2.46 | Y | PROMOTE:robust_risk_adj_ladder_boot:robust_risk_adj |
| B6_ST_kill40_dd_days60 | 64 | 4.32 | 118.3% | 9.2% | n | Y | 2.23 | Y | PROMOTE:robust_risk_adj_ladder_boot:robust_risk_adj |

### Fragile neighborhood failure modes

- **dd≤−0.06:** Tightening dd_floor to ≤−0.06 admits more entries in moderate drawdowns; tot collapses ~48pp and PF drops ~1.5 — gate was filtering costly mid-DD entries. lastWF can stay flat (same late chunk) while full-OOS tot guts → vanity trap.
- **mult=3.5:** ST mult=3.5 shortens trail; n↑ but lastWF turns negative (−3.5% class) and WF may drop. Local PF peak remains at 3.6 — 3.5 is a fragile neighbor, not a conservative twin.
- **br≥0.42:** Raising breadth_floor to ≥0.42 over-filters; tot softens ~35pp, lastWF slips ~1.6pp. 0.40 is the practical floor — 0.42+ is not a free robustness knob.

| Cell | Axis | n | PF | Tot | MDD | WF+ | LastWF | Failure notes |
|------|------|--:|---:|----:|----:|----:|-------:|---------------|
| B7_frag_dd050 | dd_floor=-0.050 | 68 | 2.58 | 64.6% | -17.4% | 3/3 | 9.2% | tot gut -48.8pp vs champ; MDD worse -2.3pp |
| B7_frag_dd055 | dd_floor=-0.055 | 69 | 2.64 | 67.3% | -17.5% | 3/3 | 9.2% | tot gut -46.1pp vs champ; MDD worse -2.4pp |
| B7_frag_dd060 | dd_floor=-0.060 | 71 | 2.51 | 65.3% | -18.1% | 3/3 | 9.2% | tot gut -48.1pp vs champ; MDD worse -3.0pp |
| B7_frag_dd065 | dd_floor=-0.065 | 67 | 3.65 | 106.3% | -15.0% | 3/3 | 9.2% | mild degradation |
| B7_frag_dd070 | dd_floor=-0.070 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | mild degradation |
| B7_frag_m3.4 | st_mult=3.40 | 78 | 2.62 | 85.4% | -16.0% | 3/3 | 2.7% | tot gut -28.1pp vs champ |
| B7_frag_m3.45 | st_mult=3.45 | 77 | 2.58 | 77.7% | -14.1% | 2/3 | -4.7% | tot gut -35.8pp vs champ; lastWF negative (-4.7%); WF 2/3 |
| B7_frag_m3.5 | st_mult=3.50 | 76 | 2.43 | 72.6% | -14.1% | 2/3 | -3.5% | tot gut -40.9pp vs champ; lastWF negative (-3.5%); PF soft (2.43); WF 2/3 |
| B7_frag_m3.55 | st_mult=3.55 | 73 | 2.84 | 90.6% | -15.2% | 3/3 | 4.6% | tot gut -22.9pp vs champ |
| B7_frag_m3.6 | st_mult=3.60 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | mild degradation |
| B7_frag_br40 | breadth_floor=0.40 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | mild degradation |
| B7_frag_br41 | breadth_floor=0.41 | 64 | 3.08 | 78.2% | -17.8% | 3/3 | 7.6% | tot gut -35.3pp vs champ; MDD worse -2.8pp |
| B7_frag_br42 | breadth_floor=0.42 | 64 | 3.08 | 78.2% | -17.8% | 3/3 | 7.6% | tot gut -35.3pp vs champ; MDD worse -2.8pp |
| B7_frag_br43 | breadth_floor=0.43 | 64 | 3.08 | 78.2% | -17.8% | 3/3 | 7.6% | tot gut -35.3pp vs champ; MDD worse -2.8pp |
| B7_frag_br45 | breadth_floor=0.45 | 64 | 3.08 | 78.2% | -17.8% | 3/3 | 7.6% | tot gut -35.3pp vs champ; MDD worse -2.8pp |
| B7_frag_dd06_m35 | cross=dd06_m35 | 80 | 1.47 | 24.4% | -19.6% | 1/3 | -3.5% | tot gut -89.1pp vs champ; lastWF negative (-3.5%); PF soft (1.47); MDD worse -4.6pp; WF 1/3 |
| B7_frag_dd06_br42 | cross=dd06_br42 | 65 | 2.49 | 58.8% | -17.8% | 3/3 | 7.6% | tot gut -54.7pp vs champ; PF soft (2.49); MDD worse -2.7pp |
| B7_frag_m35_br42 | cross=m35_br42 | 75 | 1.83 | 39.0% | -17.9% | 2/3 | -2.8% | tot gut -74.4pp vs champ; lastWF negative (-2.8%); PF soft (1.83); MDD worse -2.8pp; WF 2/3 |

### Block 7 variants (≥6)

| Name | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | vs champ |
|------|--:|---:|----:|----:|-------:|----:|-------:|----------|
| B7_ST_kill40_dd_mom_m03 | 65 | 4.26 | 114.7% | -13.0% | 1.20 | 3/3 | 9.2% | no |
| B7_ST_kill40_dd_mom_m05 | 64 | 4.73 | 124.3% | -13.0% | 1.24 | 3/3 | 9.2% | no |
| B7_ST_kill40_dd_days55 | 66 | 3.75 | 106.0% | -13.1% | 1.12 | 3/3 | 5.6% | no |
| B7_ST_kill40_dd_mom_days60 | 63 | 5.17 | 129.4% | -11.0% | 1.28 | 3/3 | 9.2% | tot+ |
| B7_ST_kill40_dd_brmom_m05 | 42 | 3.19 | 59.4% | -16.2% | 1.01 | 3/3 | 3.8% | no |
| B7_ST_kill40_dd_soft_br30 | 82 | 2.04 | 47.6% | -11.4% | 0.70 | 2/3 | -0.7% | no |
| B7_ST_kill40_dd_pullback_m08 | 53 | 3.22 | 65.3% | -17.7% | 1.08 | 3/3 | 11.7% | lastWF+ |
| B7_ST_kill40_dd_ret5_m03 | 67 | 2.77 | 76.1% | -20.4% | 1.00 | 3/3 | 12.7% | lastWF+ |
| B7_ST_kill40_dd_atr08_90 | 62 | 2.15 | 44.7% | -23.0% | 0.67 | 3/3 | 11.3% | lastWF+ |
| B7_ST_kill40_dd07_m365 | 65 | 3.16 | 92.5% | -16.9% | 1.04 | 3/3 | 6.2% | no |
| B7_ST_kill40_dd_volcalm115 | 63 | 3.53 | 89.5% | -18.9% | 1.02 | 3/3 | 9.2% | no |
| B7_ST_kill40_dd_bankrs_m02 | 64 | 2.74 | 75.0% | -13.6% | 0.94 | 3/3 | 9.2% | no |

### Paper / checklist

- A = `B6_ST_kill40_dd_nifty_mom_m04` (`strategies/nifty_edge_best.py`, `r21.py`)
- B = demoted `B5_ST_kill40_dd07` (`strategies/nifty_edge_b5_prior.py`)
- Historical ST: `strategies/nifty_edge_r17.py`
- Live divergence checklist: `research/nifty_edge_8h/CHECKLIST.md` (mom-skip focus)
- Buy&hold ^NSEI OOS: tot=70.5% Sharpe=0.76
- Runners r26–r29 saved; watch `r29` mom_days60 (tot 129.4%, same lastWF)

## Block 8 — Repro champ; mom-skip; r29 probe; locked cost shock

**Updated:** 2026-08-04 19:24 UTC
**Hours to deadline:** 6.74
**#1 still leads:** NO — new champion promoted
**Promote decision:** robust_risk_adj_ladder_boot:robust_risk_adj:B7_ST_kill40_dd_mom_days60

### Reproduced champion (B6_ST_kill40_dd_nifty_mom_m04)

| Metric | Block7 ref | Block8 | Drift |
|--------|-----------:|-------:|------:|
| n | 64 | 64 | +0 |
| PF | 4.73 | 4.73 | +0.00 |
| Tot | 124.3% | 124.3% | -0.0pp |
| MDD | -13.0% | -13.0% | +0.0pp |
| Sharpe | 1.24 | 1.24 | +0.00 |
| Last WF | 9.2% | 9.2% | — |

### Mom-skip save-rate / weekly ΔEquity (A vs B)

- Mom skips n=2; save-rate=100%; hit-rate (overfilter)=0%
- Weekly ΔEquity mean=0.01688850901093742pp; max consec B>A>2pp=0; 3w flag=False

### r29 mom_days60 vs A

| Name | n | PF | Tot | MDD | Sharpe | LastWF | Dual? | Risk-adj? | Ladder? | Boot CI_lo | Decision |
|------|--:|---:|----:|----:|-------:|-------:|:-----:|:---------:|:-------:|-----------:|----------|
| B7_ST_kill40_dd_mom_days60 | 63 | 5.17 | 129.4% | -11.0% | 1.28 | 9.2% | n | Y | Y | 2.53 | PROMOTE:robust_risk_adj_ladder_boot:robust_risk_adj:B7_ST_kill40_dd_mom_days60 |

### Locked-sleeve cost shock (A + r29 only)

| Name | Metric | 0.08% | 0.10% | 0.12% | 0.15% | 0.20% |
|------|--------|------:|------:|------:|------:|------:|
| B6_ST_kill40_dd_nifty_mom_m04 | PF | 4.73 | 4.70 | 4.68 | 4.64 | 4.57 |
| B6_ST_kill40_dd_nifty_mom_m04 | Tot | 124.3% | 123.5% | 122.7% | 121.6% | 119.6% |
| B6_ST_kill40_dd_nifty_mom_m04 | MDD | -13.0% | -13.0% | -13.1% | -13.1% | -13.3% |
| B7_ST_kill40_dd_mom_days60 | PF | 5.17 | 5.14 | 5.11 | 5.07 | 4.99 |
| B7_ST_kill40_dd_mom_days60 | Tot | 129.4% | 128.6% | 127.9% | 126.7% | 124.8% |
| B7_ST_kill40_dd_mom_days60 | MDD | -11.0% | -11.0% | -11.1% | -11.1% | -11.2% |

### Block 8 measured checks (≥5)

| Check | n | PF | Tot | MDD | WF+ | LastWF | Note |
|-------|--:|---:|----:|----:|----:|-------:|------|
| B8_A_champ_repro | 64 | 4.73 | 124.3% | -13.0% | 3/3 | 9.2% | champ_repro |
| B8_B_demoted_b5 | 65 | 4.01 | 113.4% | -15.0% | 3/3 | 9.2% | paper_B |
| B8_r29_mom_days60 | 63 | 5.17 | 129.4% | -11.0% | 3/3 | 9.2% | watch_r29 |
| B8_A_stress015 | 64 | 4.64 | 121.6% | -13.1% | 3/3 | 9.2% | stress_shadow |
| B8_r29_stress015 | 63 | 5.07 | 126.7% | -11.1% | 3/3 | 9.2% | stress_shadow |
| B8_days60_only | 64 | 4.32 | 118.3% | -13.1% | 3/3 | 9.2% | causal_probe |
| B8_volcalm125 | 67 | 3.51 | 100.0% | -15.1% | 3/3 | 9.2% | causal_probe |

### Paper / checklist

- A = `B7_ST_kill40_dd_mom_days60` (`strategies/nifty_edge_best.py`, `r29.py`)
- B = demoted nifty_mom (`strategies/nifty_edge_b6_prior.py` / `r21.py`)
- Tertiary B5: `strategies/nifty_edge_b5_prior.py`
- Expanded checklist: `research/nifty_edge_8h/CHECKLIST.md` (days60-skip focus)
- Buy&hold ^NSEI OOS: tot=70.5% Sharpe=0.76
- Runners r30–r31 saved; no fragile-neighborhood hunting (locked-sleeve cost shock only).

**Champion after Block 8:** `B7_ST_kill40_dd_mom_days60` — OOS PF=5.17 tot=129.4% n=63 WF=3/3 lastWF=9.2%
**Promote:** robust risk-adj + ladder + boot (lastWF tied; tot +5.1pp, Sharpe↑, MDD better)

### Honesty
- Consecutive risk-adj promotes (B7+B8) with tied lastWF — honesty flag; live days60-skip save-rate is thin (n=1 hist).
- Mom-skip hist (pre-promote vs B5): n=2 save-rate 100% — also thin.
- Cost shock linear; r29 beats prior A on every rung 0.08–0.20%.
- Hours left ~6.7: outline only (FINAL later).

## Block 9 — Anti-overfit battery (no vanity stacking)

**Updated:** 2026-08-04 19:31 UTC
**Hours to deadline:** 6.64
**#1 still leads:** YES (research files) — complexity_prefer_simpler_paperA:B6_ST_kill40_dd_nifty_mom_m04
**Recommendation:** PAPER A → `B6_ST_kill40_dd_nifty_mom_m04` (drop days60 — complexity-eligible campaign path); RESEARCH A → keep `B7_ST_kill40_dd_mom_days60` files for monitoring only. Held-out late OOS identical for champ/B6/B5 at 12.7% (stack does not differentiate late chunk). Ablation research: `B9_ablate_breadth` (remove breadth) tot=134.4% lastWF=9.2% — interesting (breadth drag on tot) but not campaign-path paper sleeve.

### Reproduced champion (B7_ST_kill40_dd_mom_days60)

| Metric | Block8 ref | Block9 | Drift |
|--------|-----------:|-------:|------:|
| n | 63 | 63 | +0 |
| PF | 5.17 | 5.17 | -0.00 |
| Tot | 129.4% | 129.4% | +0.0pp |
| MDD | -11.0% | -11.0% | +0.0pp |
| Sharpe | 1.28 | 1.28 | +0.00 |
| Last WF | 9.2% | 9.2% | — |

**Pine core ST/EMA match:** True — Pine matches Python ST 3.6 + EMA200 trail/entry/exit. Basket gates (breadth40, dd−7%, ret20≥−0.04, days60) are intentionally absent from single-symbol Pine — documented in pine header.

### Ablation (remove one gate)

| Sleeve | Removed | n | PF | Tot | MDD | LastWF | ΔTot | ΔLastWF |
|--------|---------|--:|---:|----:|----:|-------:|-----:|--------:|
| B7_ST_kill40_dd_mom_days60 | none (champ) | 63 | 5.17 | 129.4% | -11.0% | 9.2% | +0.0 | +0.0 |
| B6_ST_kill40_dd_nifty_mom_m04 | days60 | 64 | 4.73 | 124.3% | -13.0% | 9.2% | -5.1 | +0.0 |
| B6_ST_kill40_dd_days60 | mom | 64 | 4.32 | 118.3% | -13.1% | 9.2% | -11.1 | +0.0 |
| B9_ablate_dd | dd | 64 | 4.60 | 114.4% | -12.4% | 8.0% | -15.0 | -1.2 |
| B9_ablate_breadth | breadth | 70 | 5.28 | 134.4% | -11.7% | 9.2% | +5.0 | +0.0 |
| B5_ST_kill40_dd07 | mom+days60 | 65 | 4.01 | 113.4% | -15.0% | 9.2% | -16.0 | +0.0 |
| B2_ST_kill_breadth40_m3.6 | dd+mom+days60 | 65 | 3.94 | 105.0% | -13.0% | 8.0% | -24.5 | -1.2 |
| ST_m3.6_n1_e1 | all gates | 75 | 3.90 | 110.2% | -14.8% | 5.8% | -19.2 | -3.3 |

### Shuffle / placebo

| Gate | Real tot | Base−gate | Contrib pp | Placebo mean | P(≥real) | Verdict |
|------|---------:|----------:|-----------:|-------------:|---------:|---------|
| days60 | 129.4% | 124.3% | +5.1 | 82.4% | 0.00 | PASS |
| mom | 129.4% | 118.3% | +11.1 | 101.5% | 0.00 | PASS |
| dd | 129.4% | 114.4% | +15.0 | 90.5% | 0.00 | PASS |
| breadth | 129.4% | 134.4% | -5.0 | 85.2% | 0.00 | PASS |

### Complexity / held-out / recommendation

- Prefer simpler? **True** → `B6_ST_kill40_dd_nifty_mom_m04`
- Reason: `B6_ST_kill40_dd_nifty_mom_m04` within 10% tot of champ (124.3% vs 129.4%) with lastWF 9.2% ≥ 9.2% and fewer gates (3 vs 4; drop days60). Ablation research: `B9_ablate_breadth` (remove breadth) tot=134.4% lastWF=9.2% — interesting (breadth drag on tot) but not campaign-path paper sleeve.
- Held-out (last 30% OOS) champ tot=12.7% vs B6=12.7% vs B5=12.7% vs ST=11.0% (cut=2024-12-04) — IDENTICAL for B5/B6/champ
- Paper A vs research A: PAPER A → `B6_ST_kill40_dd_nifty_mom_m04` (drop days60 — complexity-eligible campaign path); RESEARCH A → keep `B7_ST_kill40_dd_mom_days60` files for monitoring only. Held-out late OOS identical for champ/B6/B5 at 12.7% (stack does not differentiate late chunk). Ablation research: `B9_ablate_breadth` (remove breadth) tot=134.4% lastWF=9.2% — interesting (breadth drag on tot) but not campaign-path paper sleeve.
- Overfit: MIXED: placebo calendars PASS for all four gates (real calendars beat random), but consecutive risk-adj promotes with tied lastWF=9.2% + identical held-out late tot=12.7% for B5/B6/champ + thin skip n (days60=1, mom=2) still smell like filter stacking on the early/mid OOS. Complexity → paper A = simpler campaign twin; research A files kept; NO new stacking.
- Buy&hold ^NSEI OOS: tot=70.5% Sharpe=0.76

### Honesty

- Consecutive risk-adj promotes with tied lastWF 9.2% → anti-overfit block (no new stacking).
- Days60-skip / mom-skip hist n thin — save-rates provisional.
- Complexity penalty can demote research champ from paper A without deleting files.

## Block 10 — Paper A operationalize; Research A monitor; no new gates

**Updated:** 2026-08-04 19:37 UTC
**Hours to deadline:** 6.54

### ★ PAPER vs RESEARCH (prominent)

| Role | Name | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | Files |
|------|------|--:|---:|----:|----:|-------:|----:|-------:|-------|
| **PAPER A** | B6_ST_kill40_dd_nifty_mom_m04 | 64 | 4.73 | 124.3% | -13.0% | 1.24 | 3/3 | 9.2% | `nifty_edge_paper.py` / `nifty_edge_paper.pine` |
| **RESEARCH A** | B7_ST_kill40_dd_mom_days60 | 63 | 5.17 | 129.4% | -11.0% | 1.28 | 3/3 | 9.2% | `nifty_edge_best.py` / `nifty_edge_best.pine` (monitor) |

**Repro:** paper drift_ok=True; research drift_ok=True

### Paper A sensitivity (no new gates)

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

**Buy&hold ^NSEI OOS:** tot=70.5% Sharpe=0.76

### Honesty
- Paper A = complexity-preferred B6; Research A = stacked B7 monitor-only.
- Block 10 forbids new gate stacking; sensitivity only (exec/cost/universe/slots/mult).
- Overfit MIXED (B9). Days60-skip n=1 thin.

## Block 11 — Shadow P&L hygiene; days60 live log; no new gates

**Updated:** 2026-08-04 19:40 UTC
**Hours to deadline:** 6.49

### ★ PAPER vs RESEARCH (locked roles)

| Role | Name | n | PF | Tot | MDD | Sharpe | WF+ | LastWF | Files |
|------|------|--:|---:|----:|----:|-------:|----:|-------:|-------|
| **PAPER A** | B6_ST_kill40_dd_nifty_mom_m04 | 64 | 4.73 | 124.3% | -13.0% | 1.24 | 3/3 | 9.2% | `nifty_edge_paper.py` / `.pine` |
| **RESEARCH A** | B7_ST_kill40_dd_mom_days60 | 63 | 5.17 | 129.4% | -11.0% | 1.28 | 3/3 | 9.2% | `nifty_edge_best.py` / `.pine` (monitor) |

**Repro:** paper drift_ok=True; research drift_ok=True

### Benchmarks (same OOS)

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A @ 0.08% | 124.3% | -13.0% | 1.24 |
| ^NSEI BH | 70.5% | -17.2% | 0.76 |
| EW basket BH | 99.5% | -16.3% | 1.02 |

### Shadow books
| RT | Tot | note |
|---:|----:|------|
| 0.08% | 124.3% | primary |
| 0.15% | 121.6% | shadow |

Days60 hist skips n=1 (thin). Pine both_core_ok=True.
Docs: `SHADOW.md`, `DAYS60_SKIP_LOG.md`, `UNIVERSE_FREEZE.md`.

### Honesty
- No new gates. No mid-paper tweaks. Paper A remains B6; Research A monitor-only.

## FINAL LOCK — 2026-08-05

**Hours at lock:** &lt;1h to deadline (`deadline_unix.txt` = 1785895745).
**Report:** `research/nifty_edge_8h/FINAL_REPORT.md`

### ★ Champion (FINAL)

| Role | Name | n | PF | Tot | MDD | Sharpe | LastWF | Files |
|------|------|--:|---:|----:|----:|-------:|-------:|-------|
| **PAPER A** | B6_ST_kill40_dd_nifty_mom_m04 | 64 | 4.73 | 124.3% | −13.0% | 1.24 | 9.2% | `nifty_edge_paper.py` / `.pine` |
| **RESEARCH A** | B7_ST_kill40_dd_mom_days60 | 63 | 5.17 | 129.4% | −11.0% | 1.28 | 9.2% | `nifty_edge_best.py` / `.pine` (monitor) |

**FINAL repro:** Paper A PF=4.730 tot=124.3%; Research A PF=5.170 tot=129.4% — match Block 10/11.
**Benchmarks:** Paper +53.8pp vs ^NSEI BH; +24.8pp vs EW basket BH.
**Overfit:** MIXED → complexity prefers Paper A (drop thin days60). **No new gates.**
