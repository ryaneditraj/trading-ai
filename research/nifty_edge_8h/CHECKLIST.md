# Paper A vs Research A — Live Divergence Checklist

**Updated:** 2026-08-05 (FINAL LOCK)
**Status:** FINAL — monitoring research paper sleeves. No look-ahead. No live capital.
**Report:** `FINAL_REPORT.md` · **Paper A = B6** · Research A = B7 monitor only.

| Role | ID | Code |
|------|----|------|
| **PAPER A (primary)** | `B6_ST_kill40_dd_nifty_mom_m04` | `strategies/nifty_edge_paper.py` |
| **RESEARCH A (monitor)** | `B7_ST_kill40_dd_mom_days60` | `strategies/nifty_edge_best.py` / `r29.py` |
| Tertiary | `B5_ST_kill40_dd07` | `strategies/nifty_edge_b5_prior.py` |

**Rules:** `PAPER_TRADE_RULES.md`  
**Shadow:** `SHADOW.md` · **Days60 log:** `DAYS60_SKIP_LOG.md` · **Universe:** `UNIVERSE_FREEZE.md`  
**Pine:** `nifty_edge_paper.pine` = Paper A; `nifty_edge_best.pine` = Research A (monitor)

OOS: Paper n=64 PF=4.73 tot=124.3% lastWF=9.2%  
vs Research n=63 PF=5.17 tot=129.4% lastWF=9.2%

---

## What should differ

| Gate | Paper A | Research A |
|------|:-------:|:----------:|
| Breadth50 ≥ 0.40 | YES | YES |
| Nifty dd ≥ −7% | YES | YES |
| Nifty ret20 ≥ −0.04 | YES | YES |
| Days-since-high ≤ 60 | **NO** | YES |
| ST 3.6 + Nifty bull + EMA200 | YES | YES |

---

## Shadow P&L hygiene (Block 11)

| Book | n | PF | Tot | MDD | Weekly mean |
|------|--:|---:|----:|----:|------------:|
| 0.08% RT (primary) | 64 | 4.73 | 124.3% | -13.0% | 0.2927286323039515pp |
| 0.15% RT (shadow) | — | — | see SHADOW.md | — | 0.28857286343243416pp |

Assumptions documented in `SHADOW.md` (next-open fill, equal 1/5 slots, frozen 20-name univ).

### Benchmarks same OOS

| Sleeve | Tot | MDD | Sharpe |
|--------|----:|----:|-------:|
| Paper A 0.08% | 124.3% | -13.0% | 1.24 |
| ^NSEI BH | 70.5% | -17.2% | 0.76 |
| EW basket BH | 99.5% | -16.3% | 1.02 |

---

## Days60-skip (Research-only vs Paper) — thin-n honesty

Hist OOS: n=1 save-rate=100% — **provisional until n≥20**. Live template: `DAYS60_SKIP_LOG.md`.

---

## Pine conceptual check (Block 11)

| File | core_ok |
|------|:-------:|
| `nifty_edge_paper.pine` | True |
| `nifty_edge_best.pine` | True |

Both are single-symbol ST+EMA proxies; basket gates live in Python only.

---

## Daily divergence log

| Date | Paper entries | Research entries | Research-only skips | Notes |
|------|-------------:|-----------------:|---------------------|-------|
| YYYY-MM-DD | | | days60 / — | |

## Weekly review

1. If Research lags Paper by >2pp for 3 weeks — expected if days60 over-filters; do not auto-promote Research to paper.
2. Days60-skip save-rate target ≥50% once n≥20.
3. **No new gate stacking.** No mid-paper param tweak.
4. Promote Research→Paper only if dual-clear lastWF **strictly >** Paper lastWF OR held-out clear win + ladder + boot.
5. Shadow 0.15% book: review Friday equity in `SHADOW.md`; flag only if stress flips narrative.

## Honesty (FINAL)

- Paper A preferred via complexity (drop thin days60). Research files kept labeled.
- Shadow + skip log complete — **no new gates**. Campaign FINAL locked.
