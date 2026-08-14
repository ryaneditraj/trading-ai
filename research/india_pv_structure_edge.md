# India Price / Volume / Structure Edge Search

**Date:** 2026-08-04  
**Branch:** `main` (no commit)  
**Data:** yfinance daily (2008→2026) + hourly (~2y) for NSE indices/stocks  
**Costs:** default **0.08% round-trip** (broker + taxes + slippage ballpark); also stressed 0.03–0.15%  
**Split:** 70% in-sample / 30% out-of-sample; walk-forward folds; ±20% param perturbation  

## Verdict (updated after Round 2)

| Question | Answer |
|----------|--------|
| User: is prior Donchian profitable? | **No** — OOS PF 1.17 / +9% / MDD −21% is not a usable edge |
| Round-2 edge after costs on OOS? | **Yes (conditional)** — Nifty+ADX Donchian 70/25 |
| Best candidate | **India Nifty+ADX Donchian Basket v2** |
| Paths | `strategies/india_nifty_adx_donchian_v2.py`, `pinescript/india_nifty_adx_donchian_v2.pine` |
| Secondary sleeve | Failed-breakdown fade — `strategies/india_failed_breakdown_fade_v2.py` |

### Round-2 winner — portfolio OOS (honest)

Universe: 20 liquid NSE large-caps, max **5** slots, Daily, long-only. Costs **0.08% RT** (stress 0.15%).

| Metric | IS | OOS (2021-01 → 2026-08) | OOS @ 0.15% RT |
|--------|----|-------------------------|----------------|
| Trades | 145 | **74** | 74 |
| Win rate | 47.6% | **48.6%** | 48.6% |
| Expectancy (net) | +7.81%/trade | **+2.58%/trade** | +2.51% |
| Profit factor | 3.17 | **1.86** | **1.83** |
| Total return | +528% | **+38.7%** | +36.7% |
| Max DD | −25.8% | **−14.4%** | −14.9% |
| Sharpe (daily eq) | 1.04 | **0.59** | 0.57 |
| Avg hold | ~111d | ~92d | ~92d |

**Walk-forward OOS chunks:**

| Period | n | Expectancy | Total | MDD |
|--------|---|------------|-------|-----|
| 2021-01 → 2022-11 | 29 | **+1.95%** | **+10.7%** | −12.7% |
| 2022-11 → 2024-09 | 26 | **+7.80%** | **+42.5%** | −6.8% |
| 2024-09 → 2026-08 | 23 | **−1.61%** | **−7.3%** | −9.8% |

**Param ±20%:** all tested variants of entry/exit/ADX floor kept OOS PF ≥ 1.37 and 2/3 WF chunks green. Not a single-point fluke.

### Rules (v2 winner)

1. Universe: liquid NSE large-caps (see strategy file).  
2. **Nifty bull:** `^NSEI` close > EMA200 **or** close > prior 55-day high.  
3. **Stock ADX:** ADX(14) ≥ 18 **and** ADX > ADX from 5 bars ago.  
4. **Entry:** Daily close > prior **70**-day high **and** close > EMA200.  
5. **Exit:** Daily close < prior **25**-day low.  
6. **Portfolio:** max 5 names; ~20% equity/slot; rank by Close/EMA200.  
7. **Costs:** ≥ 0.08% RT; stress-tested at 0.15%. **Long-only** (shorts failed costs).

### Why prior “partial edge” failed the user

| Failure mode | Evidence |
|--------------|----------|
| OOS barely above noise | PF **1.17**, Sharpe **0.19**, +9% over ~5.5y with −21% MDD |
| 2021–22 chop | WF chunk −11.2% — buy-the-dip bull bias vanished |
| Single-symbol Pine vs basket | Pine is 1 name; research edge was **basket diversification** |
| Fill model mismatch | Python = next-day open; Pine `process_orders_on_close` = close fill |
| Shorts | Failed-BU short sleeve OOS PF **0.79** — leave OFF |
| Gap / overnight / MR | Large n, negative after 0.08% RT |

Baseline kept only for reproduction: `strategies/india_donchian_trend_basket.py`.

---

## User rejected — unprofitable; round 2

**Date:** 2026-08-04 (same day continuation)  
**Belief:** User said not profitable at all → prior Partial treated as **FAILED**.  
**Loop:** 28 candidates in pass A + 25 refine/perturb in pass B (≥10 new families beyond research log).  
**Scripts:** `research/run_india_edge_round2.py`, `research/run_india_edge_round2b.py`  
**Artifacts:** `research/results/india_round2_results.json`, `india_round2b_refine.json`

### Round-2 hypotheses (measured)

| ID | Thesis | OOS n | OOS PF | OOS Tot | WF+/3 | Verdict |
|----|--------|------:|-------:|--------:|------:|---------|
| R2-01 | Regime ADX+ATR expand | 86 | 1.26 | +12% | 2 | Weak — below PF 1.3 |
| R2-02 | Nifty bull filter 55/20 | 110 | 1.30 | +18% | 2 | Borderline |
| **R2-02c** | **Nifty + 70/25** | 88 | **1.46** | **+25%** | 2 | Pass |
| R2-03 | RVOL≥1.5 breakout | 103 | 1.28 | +20% | 2 | Soft pass only |
| R2-03b | RVOL≥1.2 | 107 | 1.32 | +21% | 2 | Pass; WF1 ugly |
| R2-04 | Nifty+RVOL+ADX combo | 83 | 1.32 | +19% | 2 | Pass |
| R2-05 | Failed BD fade long | 61 | **1.59** | +11% | 2 | **Secondary sleeve** |
| R2-06 | Failed BU fade SHORT | 43 | 0.79 | −4% | — | **Reject shorts** |
| R2-07 | Gap continuation + RVOL | 157 | 0.85 | −11% | — | Reject |
| R2-08 | EMA pullback dry-up | 303 | 1.07 | +2% | 1 | Reject |
| R2-09 | Pullback thrust | 154 | 1.15 | +6% | 3 | Thin |
| R2-10 | Breadth ≥55/65% | 96–108 | 1.16–1.22 | +7–10% | 1 | Reject |
| R2-11 | Slow Turtle 100/50 | 58 | 1.30 | +14% | 1 | Borderline |
| R2-12 | ATR trail exit | 182 | 1.15 | +11% | 2 | Reject |
| R2-13 | Nifty/Bank index only | 7–24 | mixed | thin n | — | n too low |
| R2-15 | Nifty HH55 only (strict) | 72 | 0.54 | −22% | — | Reject |
| R2-16 | Dual MA + RVOL | 164 | 1.22 | +13% | 1 | Reject |
| **R2b** | **Nifty+ADX 70/25** | **74** | **1.86** | **+39%** | **2** | **WINNER** |
| R2b | Nifty+ADX 80/30 | 69 | 1.62 | +26% | 2 | Alt params |
| R2b | Combo slow 70/25 | 74 | 1.51 | +24% | 2 | Near-winner |
| R2b | Hybrid trend+fade | 267 | 0.96 | −9% | 1 | **Do not merge** |
| R2b | FailBD n=15/20 | 61–138 | 1.40–1.59 | +11–16% | 2 | Secondary |

### Least-bad alternatives if v2 is still “not enough”

1. **Failed-breakdown fade** alone — better MDD (−7.5%), lower return.  
2. **True NSE futures continuous** (Nifty/Bank) with point-value costs — cash index n too thin.  
3. **Intraday (1m/5m) volume structure** — yfinance hourly index volume is zero/useless.  
4. Do **not** expect single-stock TradingView to match basket OOS; size as 20% of a 5-slot book.

---

## Research log — rejected / weak ideas

Hypotheses below were implemented in Python, measured IS/OOS (and usually WF + perturbation), then rejected or demoted.

### Pass 1 — single-symbol daily screen (9 symbols)

| ID | Thesis | Result | Why rejected |
|----|--------|--------|--------------|
| H1 | Donchian + RVOL + EMA200 | Negative OOS on most names | Volume filter on indices unreliable; too few trades/symbol |
| H2 | NR7 expansion breakout + RVOL | Sparse, negative | NR7 breakouts chop in India daily |
| H3 | Gap fade (weak RVOL) | Spurious green on NIFTYBEES | **Bad ETF prints** (Open=0, gap −100%/+900%); after clean, fades lose after costs |
| H4 | Swing BOS + volume | Low n, negative | Structure breaks without trend filter = noise |
| H5 | Inside-bar break + RVOL | Very few trades | Not tradeable sample |
| H6 | ATR-squeeze Donchian | Tiny n | Over-filtered |
| H7 | Prior-day high + RVOL momentum | Occasional single-name green (INFY) | Does not generalize; IS≠OOS |
| H8 | EMA20 pullback reclaim | Almost no trades | Rules too tight |
| H9 | Volume climax reversal | n&lt;10 | Insufficient |
| H10 | VWAP20 reclaim | Weak / low n | Unstable |
| H12 | Range contraction → thrust | Near-zero trades | — |

### Pass 2 — refined daily + hourly

| ID | Thesis | Result | Why rejected |
|----|--------|--------|--------------|
| H3b/c | Gap fade only with/against EMA200 | Still negative pooled | Gap MR dead after 0.08% RT |
| H1b/c | Classic Donchian longer hold | Single-name INFY looks good | Survivorship / low n; needs basket |
| H13 | Failed breakout fade | n≈5 OOS | Vanity PF |
| H14 | Hourly ORB + RVOL | Stocks mixed; **index volume = 0** on yfinance | ORB fails pooled after costs |
| H15–H18 | Down-streak rev, dry-up thrust, EMA ribbon, range-close BO | Low n or non-general | Reject |

**Data note:** `^NSEI` / `^NSEBANK` hourly **volume is always 0** on yfinance → any RVOL rule on cash indices is invalid. Prefer stocks/ETFs for volume, or price-only on indices.

### Pass 3 — pooled portfolios

| ID | Thesis | OOS n | OOS E | Verdict |
|----|--------|------:|------:|---------|
| Gap fade uptrend (all) | Fade gap-down in bull | 147–396 | −0.3% to −0.6% | Reject — costs kill MR |
| Donchian idx 20/10 | Trend on Nifty/Bank | 48 | +0.12% | Thin; WF fragile |
| **Donchian stocks 55/20** | Trend on 5 names | 54 | +0.26% | **Partial seed** |
| NR7 / inside / 2-day rev / pullback50 | Structure variants | 200+ | negative | Reject |
| Hourly VWAP MR | 2-down + reclaim | ~0–1 | — | No signals |
| Hourly ORB pool | OR high break | 85–131 | −0.24% | Reject |

### Pass 4 — filters / MR alternatives

| ID | Result |
|----|--------|
| Donchian + ATR trail / Nifty filter / strength proxy | Still ~breakeven–weak; DD large if sequential |
| Relative strength breakout | Negative OOS |
| Expansion breakout | Negative WF |
| Washout MR / ATR-band fade / up-frac MR | High trade count, **negative after costs** |

### Pass 5 — overnight, gap-and-go, cost stress

| ID | Result |
|----|--------|
| Gap-and-go | OOS negative |
| Overnight / open→close long bias | Large n, negative after 0.03–0.08% RT |
| Index Donchian @ 0.03% RT | Mildly positive, n&lt;80 |
| Stock Donchian 55/20 | Survives 0.03–0.10% RT at 5-name pool |

### Pass 6 — wide universe (20 stocks) + portfolio engine

Sequential pooled trades overstated DD (−60%). **Portfolio engine** (max 5 slots) is the fair test:

- OOS n=124, E=+0.62%, PF=1.17, MDD≈−21%, Sharpe≈0.19  
- Pert expectancy robust; **WF chunk 1 failed**  
- → **Partial edge**, closest robust candidate  

---

## What would make this a full “Yes”

1. **More regimes:** include 2008–09 / 2013 / 2015 / 2018 explicitly in WF (need careful corp-action data).  
2. **True NSE futures/options costs** and point-value sizing (Nifty/Bank Nifty continuous).  
3. **Intraday structure** with real volume (NSE tick/1m), not yfinance hourly.  
4. **Risk overlay:** ATR stop / heat cap to cut 2021–22 damage without erasing 2023–24 trend capture.  
5. **Breadth filter:** only take breakouts when &gt;X% of universe above EMA50 (not tested rigorously here).  

---

## How to verify

```bash
cd /Users/ryaneditraj/trading-ai
python3 -m venv .venv && source .venv/bin/activate
pip install yfinance pandas numpy pyarrow
# Round-2 winner (ship this):
python strategies/india_nifty_adx_donchian_v2.py
# Secondary sleeve:
python strategies/india_failed_breakdown_fade_v2.py
# Reproduce prior failure baseline:
python strategies/india_donchian_trend_basket.py
# Full round-2 research loops:
python research/run_india_edge_round2.py
python research/run_india_edge_round2b.py
```

**TradingView:** paste `pinescript/india_nifty_adx_donchian_v2.pine` on a liquid `.NS` daily chart; commission 0.04%/side; enable Nifty filter (set `NSE:NIFTY` or your feed). Judge basket-level expectancy via Python — single-symbol Pine will not match the 20-name max-5 book.

---

## Honest caveats

- yfinance adjusts/OHLCV quality varies; ETFs had corrupt gaps — cleaned but not institutional-grade.  
- Index cash volume incomplete/zero → volume edges on `^NSEI` are not trustworthy.  
- Survivorship: universe is today’s liquid large-caps.  
- Long-only bull bias in 2008–2026 India equities inflates IS vs OOS.  
- **v2 still lost the 2024-09→2026-08 WF chunk (−7%)** — trend sleeves can go flat/negative for ~1–2 years.  
- No guaranteed profit; paper-trade the basket before capital.

## Hypotheses tried

**≥ 25** rule families in passes 1–6, then **≥ 28** new round-2 candidates + refine grid. Winner = **Nifty+ADX Donchian 70/25** (replaces Partial 55/20).
