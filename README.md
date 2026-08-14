# BTC 1% Radar + systematic trading lab

**A Bitcoin futures radar that scores which side is likelier to print a ±1% move first, plus a walk-forward Nifty / NSE research notebook that refuses to promote overfit sleeves.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Stack](https://img.shields.io/badge/stack-pandas%20%7C%20Binance%20public%20API%20%7C%20Pine%20v5-lightgrey.svg)](#tech-stack)

> Not financial advice. Signals are research output. High leverage can liquidate you before the 1% target prints.

## Problem it solves

Most crypto “signal bots” either spam entries or hide a black box. This repo is the opposite: a **BTC perpetual futures 1% move scorer** that reads public Binance USD-M data (structure, open interest, funding, taker CVD proxy, order-book depth) and prints an honest **LONG / SHORT / NO TRADE** card. A 100x liquidation-distance warning is first-class, because a ±1% target at 100x is inside the wipeout zone.

The second half of the repo is a **systematic Nifty / India equity backtest lab**: Supertrend sleeves on a frozen NSE large-cap basket, with walk-forward splits, cost ladders, bootstrap gates, and an explicit paper-vs-research champion so filter-stacking does not quietly become the live book.

## Why I built this

I wanted a trading stack I would actually trust: public data only, no API keys for the radar, a score I can disagree with because every point is labeled, and a research process that can say “this extra gate smells like overfit — keep it on monitor, trade the simpler twin.” Recruiters: this is how I think about markets and software — measure, gate, refuse the cute parameter.

## Key features

- **BTC 1% Radar CLI** — ASCII scorecard from Binance public futures REST + a short liquidation websocket sample
- **Strict 8/10 threshold** — mixed tape prints `NO TRADE` instead of a coin-flip
- **Macro calendar gate** — estimated CPI / NFP / FOMC windows in `btc_radar/macro_events.json` (override with `--macro`)
- **Walk-forward radar backtest** — did the signal correctly pick which side hit ±1% first?
- **Offline `--demo`** — synthetic snapshot so you can run the CLI with no network
- **Nifty paper sleeve** — locked Paper A in `strategies/nifty_edge_paper.py` + TradingView Pine ports
- **Anti-overfit research log** — `research/nifty_edge_8h/` (blocks, leaderboard, final report)

## Screenshot / GIF

<!-- Drop a terminal capture here after you run: python -m btc_radar --demo --macro low -->
```
BTC: $97,488

NEXT 1% CONFIDENCE (score-derived, not win-rate)

LONG  █████████░  90%   (9.0/10)
SHORT █░░░░░░░░░  10%   (1.0/10)

SIGNAL: LONG
CONFIDENCE: 9.0/10

100x: liq≈±0.60%  |  target ±1.0%
WARNING: TARGET ±1.0% ≥ LIQUIDATION DISTANCE ±0.60% @ 100x
```

Replace this block with `docs/radar-demo.gif` (live `--watch 60` loop is the interesting clip).

## Tech stack

| Layer | Choice |
|--------|--------|
| Language | Python 3.11+ |
| Radar data | Binance USD-M public REST (`fapi.binance.com`) + `!forceOrder@arr` websocket |
| Research data | Yahoo Finance via `yfinance` (NSE / GIFT overnight studies) |
| Numerics | pandas, numpy |
| Charts | TradingView Pine Script v5 |
| Tests | pytest (no live network) |

No broker keys. No LLM in the loop. The “AI” in the folder name is the research process, not a chat model placing trades.

## Quickstart

```bash
git clone https://github.com/ryaneditraj/trading-ai.git
cd trading-ai
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

1. **Offline demo** (no Binance): `python -m btc_radar --demo --macro low`
2. **Live radar**: `python -m btc_radar`  (or `--watch 60`, `--json`, `--leverage 100`)
3. **Radar backtest** (~28d Binance hist): `python strategies/btc_1pct_radar_backtest.py --days 14`
4. **Unit tests**: `pytest`
5. **Nifty paper sleeve** (downloads Yahoo data): `python strategies/nifty_edge_paper.py`

Copy `.env.example` to `.env` only if you later add authenticated venues. The radar does not need keys.

Same CLI also lives at `python strategies/btc_1pct_radar.py`.

## Architecture overview

```
Binance public snapshot
        │
        ▼
 structure │ derivatives │ liquidity │ catalyst
        │
        ▼
   10-point score  →  LONG / SHORT / NO TRADE  →  ASCII or JSON
```

| Path | What it is |
|------|------------|
| `btc_radar/` | Product: fetch, features, score, render, backtest, demo |
| `strategies/` | Runnable sleeves (`btc_1pct_radar.py`, `nifty_edge_paper.py`, …). `nifty_edge_r*.py` are dated research iterations, not the live champion |
| `research/` | Walk-forward engine, India edge search, locked 8h campaign |
| `pinescript/` | TradingView ports of Turtle / Nifty / paper sleeves |

Scoring pillars (max 10): trend + VWAP, CVD, OI-with-price, funding not crowded, liquidity cluster, optional macro bias. Liquidation distance ≈ `1/leverage − maintenance margin`.

## Roadmap

- [ ] Refresh `macro_events.json` from an official calendar instead of estimates
- [ ] Multi-exchange depth / liquidation heatmap (radar currently uses Binance book only)
- [ ] Persist radar cards and hit-rate over a rolling week
- [ ] Split research archives into a `lab/` git submodule if the main repo should stay radar-only

## License

[MIT](LICENSE) — use it, fork it, argue with the score. Do not treat output as a trade instruction.

Past backtests ≠ future results. Nifty OOS stats in `research/nifty_edge_8h/FINAL_REPORT.md` are research paper numbers with assumed costs, not a live audited track record.
