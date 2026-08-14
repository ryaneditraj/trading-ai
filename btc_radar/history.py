"""Historical data bundle for BTC 1% Radar backtests."""

from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd

from btc_radar.binance import BinancePublic


@dataclass
class HistoryBundle:
    symbol: str
    k5: pd.DataFrame
    k15: pd.DataFrame
    k1d: pd.DataFrame
    funding: pd.DataFrame
    oi: pd.DataFrame
    taker: pd.DataFrame
    long_short: pd.DataFrame
    fetched_at: float


def load_history(
    symbol: str = "BTCUSDT",
    days: int = 28,
    client: BinancePublic | None = None,
) -> HistoryBundle:
    """
    Load overlapping klines + derivatives.

    Binance /futures/data/* only retains ~30 days, so `days` is capped at 28 by default.
    """
    days = max(3, min(int(days), 28))
    client = client or BinancePublic(symbol=symbol)
    end_ms = int(time.time() * 1000)
    # Extra warmup for EMA50 on 15m (~2 days) and session VWAP
    start_ms = end_ms - int((days + 3) * 86400 * 1000)
    start_daily = end_ms - int((days + 10) * 86400 * 1000)

    k5 = client.klines_range("5m", start_ms, end_ms)
    k15 = client.klines_range("15m", start_ms, end_ms)
    k1d = client.klines_range("1d", start_daily, end_ms)
    funding = client.funding_rate_range(start_ms, end_ms)
    oi = client.futures_data_hist("/openInterestHist", period="15m", limit=500)
    taker = client.futures_data_hist("/takerlongshortRatio", period="15m", limit=500)
    long_short = client.futures_data_hist("/globalLongShortAccountRatio", period="15m", limit=500)

    return HistoryBundle(
        symbol=client.symbol,
        k5=k5,
        k15=k15,
        k1d=k1d,
        funding=funding,
        oi=oi,
        taker=taker,
        long_short=long_short,
        fetched_at=time.time(),
    )
