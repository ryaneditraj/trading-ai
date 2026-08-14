"""Offline synthetic snapshot so the radar CLI can run without Binance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd


def build_demo_snapshot(price: float = 97_500.0) -> dict:
    """
    Build a bullish-leaning but mixed tape: trend + VWAP + CVD align,
    funding not crowded, asks slightly heavier above price.
    """
    n = 200
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    # Align to 5m
    end = end - timedelta(minutes=end.minute % 5)

    rows_5 = []
    px = price * 0.985
    for i in range(n):
        t = end - timedelta(minutes=5 * (n - 1 - i))
        drift = (price - px) / max(n - i, 1)
        o = px
        h = o * 1.0012
        low = o * 0.9990
        c = o + drift * 0.7
        vol = 80.0 + (i % 17)
        rows_5.append(
            {
                "open_time": t,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": vol,
                "close_time": t + timedelta(minutes=5) - timedelta(milliseconds=1),
                "quote_volume": vol * c,
                "trades": 100,
                "taker_buy_base": vol * 0.56,
                "taker_buy_quote": vol * c * 0.56,
                "ignore": 0,
            }
        )
        px = c
    k5 = pd.DataFrame(rows_5)
    k5["open_time"] = pd.to_datetime(k5["open_time"], utc=True)
    k5["close_time"] = pd.to_datetime(k5["close_time"], utc=True)

    rows_15 = []
    for i in range(0, n, 3):
        chunk = k5.iloc[i : i + 3]
        rows_15.append(
            {
                "open_time": chunk["open_time"].iloc[0],
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
                "volume": float(chunk["volume"].sum()),
                "close_time": chunk["close_time"].iloc[-1],
                "quote_volume": float(chunk["quote_volume"].sum()),
                "trades": int(chunk["trades"].sum()),
                "taker_buy_base": float(chunk["taker_buy_base"].sum()),
                "taker_buy_quote": float(chunk["taker_buy_quote"].sum()),
                "ignore": 0,
            }
        )
    k15 = pd.DataFrame(rows_15)

    last = k5["open_time"].iloc[-1]
    k1d = pd.DataFrame(
        [
            {
                "open_time": last.normalize() - timedelta(days=d),
                "open": price * (0.99 - d * 0.002),
                "high": price * (1.01 - d * 0.002),
                "low": price * (0.98 - d * 0.002),
                "close": price * (1.0 - d * 0.002),
                "volume": 20_000.0,
                "close_time": last.normalize() - timedelta(days=d - 1) - timedelta(milliseconds=1),
            }
            for d in range(4, -1, -1)
        ]
    )

    mark = float(k5["close"].iloc[-1])
    bids = [[str(mark * (1 - 0.0002 * i)), str(2.0 + i * 0.1)] for i in range(1, 40)]
    asks = [[str(mark * (1 + 0.0002 * i)), str(3.2 + i * 0.15)] for i in range(1, 40)]

    oi_hist = [
        {"sumOpenInterest": 48_000.0},
        {"sumOpenInterest": 48_900.0},
    ]
    taker = [{"buySellRatio": 1.08}, {"buySellRatio": 1.11}, {"buySellRatio": 1.09}, {"buySellRatio": 1.12}]
    ls = [{"longShortRatio": 1.15}]

    return {
        "symbol": "BTCUSDT",
        "fetched_at": last.timestamp(),
        "k5": k5,
        "k15": k15,
        "k1d": k1d,
        "premium": {"markPrice": mark, "lastFundingRate": 0.00008},
        "oi": {"openInterest": 48_900.0},
        "oi_hist": oi_hist,
        "funding_hist": [],
        "long_short": ls,
        "top_long_short": [],
        "taker": taker,
        "depth": {"bids": bids, "asks": asks},
        "force_orders": [],
        "demo": True,
    }
