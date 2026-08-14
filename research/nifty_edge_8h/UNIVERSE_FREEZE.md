# Universe Freeze — Paper A (FINAL)

**Frozen:** 2026-08-04 19:40 UTC (Block 11); confirmed FINAL LOCK 2026-08-05
**Source of truth:** `UNIVERSE` in `research/nifty_edge_8h/run_block1.py`
**n names:** 20
**max_slots:** 5 (do not change mid-paper)
**Report:** `FINAL_REPORT.md`

## Tickers (exact order)

```
RELIANCE.NS
TCS.NS
INFY.NS
HDFCBANK.NS
ICICIBANK.NS
SBIN.NS
BHARTIARTL.NS
ITC.NS
LT.NS
AXISBANK.NS
KOTAKBANK.NS
HINDUNILVR.NS
BAJFINANCE.NS
ASIANPAINT.NS
MARUTI.NS
SUNPHARMA.NS
TITAN.NS
ULTRACEMCO.NS
WIPRO.NS
NESTLEIND.NS
```

One-line: `RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, ICICIBANK.NS, SBIN.NS, BHARTIARTL.NS, ITC.NS, LT.NS, AXISBANK.NS, KOTAKBANK.NS, HINDUNILVR.NS, BAJFINANCE.NS, ASIANPAINT.NS, MARUTI.NS, SUNPHARMA.NS, TITAN.NS, ULTRACEMCO.NS, WIPRO.NS, NESTLEIND.NS`

## Rules
- Do **not** drop/add names mid-paper without a documented held-out dual-clear.
- Block 10 drop sensitivity (WIPRO / BAJFINANCE) was stress-only — default stays 20.
- Index filter: `^NSEI` daily. Bank reference: `^NSEBANK` (RS/breadth only).
