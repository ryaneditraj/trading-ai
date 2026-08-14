# GIFT Nifty data (optional Phase 2)

Yahoo does not provide clean GIFT Nifty history. To upgrade overnight research from the NSE open-gap proxy to real Session II futures:

1. Export OHLC from your broker / NSE IX / data vendor.
2. Save as `gift_nifty.csv` in this folder.

Required columns (case-insensitive):

```
datetime,Open,High,Low,Close,Volume
```

Timezone: IST preferred (naive timestamps treated as IST/exchange local).

Then re-run:

```bash
python research/gift_overnight_edge/run_research.py
```
