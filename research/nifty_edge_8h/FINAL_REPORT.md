# Nifty Edge 8h — FINAL REPORT (LOCKED)

**Locked:** 2026-08-05 ~01:35 UTC (07:05 IST)  
**Deadline:** 2026-08-05 07:39 IST (`deadline_unix.txt` = 1785895745)  
**Status:** **FINAL LOCK** — hours remaining &lt;1h at lock; no new gates; Block 11 leftovers complete.

---

## 1. Executive verdict

| Role | Sleeve | n | PF | Tot | MDD | Sharpe | LastWF | Use |
|------|--------|--:|---:|----:|----:|-------:|-------:|-----|
| **PAPER A (TRADE)** | `B6_ST_kill40_dd_nifty_mom_m04` | 64 | **4.73** | **124.3%** | −13.0% | 1.24 | **+9.2%** | **Paper / trade this** |
| **RESEARCH A (monitor)** | `B7_ST_kill40_dd_mom_days60` | 63 | 5.17 | 129.4% | −11.0% | 1.28 | +9.2% | Monitor only (days60 stacked) |
| Tertiary | `B5_ST_kill40_dd07` | 65 | 4.01 | 113.4% | −15.0% | 1.17 | +9.2% | Fallback |
| Core | `ST_m3.6_n1_e1` | — | — | ~110% | — | — | +5.8% | Trail baseline |

**Champion recommendation:** Paper A = **B6** (ST mult=3.6 + breadth≥0.40 + Nifty dd≥−7% + Nifty mom ret20≥−0.04; **no days60**).

**Files**
| Role | Python | Pine |
|------|--------|------|
| Paper A | `strategies/nifty_edge_paper.py` | `pinescript/nifty_edge_paper.pine` |
| Research A | `strategies/nifty_edge_best.py` (+ `r29.py`) | `pinescript/nifty_edge_best.pine` |
| Ops | `PAPER_TRADE_RULES.md` · `CHECKLIST.md` · `SHADOW.md` · `DAYS60_SKIP_LOG.md` · `UNIVERSE_FREEZE.md` · `leaderboard.md` |

**FINAL repro (2026-08-05):** Paper A n=64 PF=4.730 tot=124.3% MDD=−13.0% Sharpe=1.24; Research A n=63 PF=5.170 tot=129.4% MDD=−11.0% Sharpe=1.28 — matches Block 10/11.

---

## 2. Thesis

Long-only Supertrend ATR trail on a **frozen 20-name NSE large-cap basket** (max 5 equal-risk slots), filtered by Nifty bull regime and stock EMA200, plus **entry-only** causal market gates that skip weak-breadth / deep-drawdown / soft-momentum regimes. The campaign preferred **fewer gates** when lastWF tied and late held-out OOS was identical — hence Paper A drops the thin days60 stack that Research A keeps for monitoring.

This is a **research paper sleeve**, not a guarantee of live profit. Basket backtests ≠ single-symbol TradingView charts.

---

## 3. Exact Paper A rules

### Universe & engine
- **20 names** (frozen): see `UNIVERSE_FREEZE.md` / `run_block1.py` `UNIVERSE`
- Index: `^NSEI`; Bank ref: `^NSEBANK` (RS/breadth)
- Max **5** slots; rank free slots by Close/EMA200 − 1
- Entry fill: **next open** after signal close (primary)
- Exit fill: signal-bar **close** when Close &lt; ST lower band
- Costs: **0.08% RT** primary; shadow **0.15%**; ladder 0.08–0.20%
- Side: long-only; daily bars; **no look-ahead**

### Entry (all must hold on signal close)
1. Supertrend lower band ATR(14)×**3.6** (HL2, ratchet on prior close): Close **crosses above** final lower band  
2. Close &gt; stock **EMA200**  
3. Nifty bull: Close_Nifty &gt; EMA200_Nifty **OR** Close_Nifty &gt; prior 55d Nifty high  
4. **Breadth50 ≥ 0.40** (entry-only)  
5. **Nifty dd** from prior-55d high ≥ **−0.07** (entry-only, causal)  
6. **Nifty ret20 ≥ −0.04** (entry-only, causal)  
7. **No days-since-high gate** on Paper A  

### Exit
- Close &lt; final Supertrend lower band → exit that bar close  
- Gates do **not** force-exit open positions  

### Research A (monitor only)
Same as Paper A **plus** `nifty_days_since_high ≤ 60`. Do not paper-trade as primary while skip n&lt;20.

---

## 4. OOS statistics (locked)

| Sleeve | n | Win% | PF | Exp/trade | Tot | MDD | Sharpe | WF+ | LastWF | drift_ok |
|--------|--:|-----:|---:|----------:|----:|----:|-------:|----:|-------:|:--------:|
| Paper A @ 0.08% | 64 | 59.4% | 4.73 | +7.11% | **124.3%** | −13.0% | 1.24 | 3/3 | **9.2%** | True |
| Research A @ 0.08% | 63 | 60.3% | 5.17 | +7.39% | 129.4% | −11.0% | 1.28 | 3/3 | 9.2% | True |

### Walk-forward
- 3 equal OOS chunks; lastWF = last chunk total return  
- Paper A / Research A / B5 all lastWF **+9.2%** (tied)  
- Held-out late OOS (last ~30%): B5/B6/B7 identical **~12.7%** — stack does not differentiate late period  

### Cost ladder (Paper A)

| RT | PF | Tot | MDD |
|---:|---:|----:|----:|
| 0.08% | 4.73 | 124.3% | −13.0% |
| 0.10% | 4.70 | 123.5% | −13.0% |
| 0.12% | 4.68 | 122.7% | −13.1% |
| 0.15% | 4.64 | 121.6% | −13.1% |
| 0.20% | 4.57 | 119.6% | −13.3% |

ΔTot 0.08→0.20% = **−4.6pp**; all rungs PF≥1.3: **True**.

### Benchmarks (same OOS window)

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| **Paper A @ 0.08%** | **124.3%** | −13.0% | 1.24 |
| Buy&hold ^NSEI | 70.5% | −17.2% | 0.76 |
| EW buy-hold basket (20) | 99.5% | −16.3% | 1.02 |

Paper excess vs ^NSEI: **+53.8pp**; vs EW basket: **+24.8pp**.

### Shadow books (Block 11)
| Book | Tot | MDD | Weekly mean |
|------|----:|----:|------------:|
| 0.08% RT | 124.3% | −13.0% | +0.29pp |
| 0.15% RT | 121.6% | −13.1% | +0.29pp |

Assumptions & weekly template: `SHADOW.md`.

### Days60-skip honesty
- Hist OOS skips **n=1** (WIPRO.NS loser, save-rate provisional)  
- Live template until **n≥20**: `DAYS60_SKIP_LOG.md`  
- Do **not** promote Research→Paper on skip-rate alone while n&lt;20  

---

## 5. Anti-overfit verdict: **MIXED**

| Evidence | Read |
|----------|------|
| Placebo calendars PASS (real calendars beat random for gates) | Supportive |
| Consecutive risk-adj promotes (B7→B8) with **tied lastWF=9.2%** | Stacking smell |
| Held-out late OOS **identical** for B5/B6/B7 (~12.7%) | Stack adds no late edge |
| Days60 hist skip n=1; mom skip n≈2 | Thin — provisional |
| Complexity rule: within ~10% tot + lastWF ≥ champ → fewer gates | **Paper A = B6** |

**Conclusion:** Prefer simpler Paper A. Keep Research A labeled monitor-only. **No new gate stacking** after freeze.

---

## 6. Paper A vs Research A

| Gate | Paper A | Research A |
|------|:-------:|:----------:|
| ST 3.6 + Nifty bull + EMA200 | YES | YES |
| Breadth50 ≥ 0.40 | YES | YES |
| Nifty dd ≥ −7% | YES | YES |
| Nifty ret20 ≥ −0.04 | YES | YES |
| Days-since-high ≤ 60 | **NO** | YES |

Divergence checklist: `CHECKLIST.md`.

---

## 7. Campaign path (Blocks 1–11 → FINAL)

1. **B1–4:** ST_m3.6 + Nifty + EMA200 core; kill-breadth near-miss  
2. **B5:** Promote kill40+dd (dual-clear lastWF 9.2%)  
3. **B6:** Neighborhood freeze; nifty_mom near-miss → later risk-adj  
4. **B7–8:** Risk-adj promotes (mom → days60) with tied lastWF  
5. **B9:** Anti-overfit → complexity prefers Paper A = B6  
6. **B10:** Operationalize Paper A; sensitivity (exec/cost/slots/mult/univ) — no new gates; mult≈3.5 fragile  
7. **B11:** Shadow 0.08/0.15; days60 live log; BH benchmarks; universe freeze; pine checks  
8. **FINAL (&lt;1h):** Repro confirm; lock this report; align rules/checklist/leaderboard  

---

## 8. How to run

```bash
# From repo root (use project venv)
.venv/bin/python strategies/nifty_edge_paper.py      # Paper A
.venv/bin/python strategies/nifty_edge_best.py       # Research A (monitor)
.venv/bin/python research/nifty_edge_8h/run_block11.py  # hygiene pack (optional)
```

**Pine (TradingView):**
1. Open `pinescript/nifty_edge_paper.pine` (Paper A) or `nifty_edge_best.pine` (Research A)  
2. Apply to a **single** NSE symbol chart — this is an **illustrative ST+EMA proxy only**  
3. Basket gates (breadth, dd, mom, days60) live in **Python only** — documented in pine headers  
4. `process_orders_on_close=false` ≈ next-open intent; TV single-symbol P&amp;L ≠ 5-slot basket OOS  

Artifacts: `results/block10_summary.json`, `results/block11_summary.json`, this file.

---

## 9. Caveats (read before any capital)

- **Not guaranteed profit.** OOS edge is a backtest on Yahoo-adjusted daily data.  
- Live costs, liquidity, gaps, halts, and corp actions can differ; use shadow 0.15% book.  
- **Basket ≠ single-symbol TV** — Pine cannot reproduce breadth/dd/mom/days60 basket logic.  
- Days60 / mom skip samples are **thin**; do not confirm gates on n&lt;20.  
- Tied lastWF + identical late held-out → complexity favors fewer gates (Paper A).  
- ST mult=**3.6** is a local peak; mult≈**3.5** was fragile (lastWF −3.5%) — do not retune mid-paper.  
- No live capital in this campaign. Research paper sleeves only.  
- Do not invent new gates. Do not silently swap `nifty_edge_best.py` into the paper role.

---

## 10. What not to do

- Do not stack more gates without dual-clear lastWF **strictly &gt;** Paper A lastWF.  
- Do not treat days60/mom save-rates as confirmatory while n&lt;20.  
- Do not mid-paper tweak mult, slots, universe, or costs beyond shadow logging.  
- Do not confuse Research A files (`nifty_edge_best.*`) with the paper primary.

---

**FINAL LOCK:** Paper A = `B6_ST_kill40_dd_nifty_mom_m04` · Research A = `B7_ST_kill40_dd_mom_days60` (monitor) · No new gates · Campaign complete.
