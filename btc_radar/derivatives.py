"""Derivatives features: OI, funding, L/S, taker CVD proxy, liquidations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


@dataclass
class DerivativesFeatures:
    oi: float
    oi_prev: float
    oi_rising: bool
    oi_arrow: str  # ↑ ↓ →
    price_up: bool
    oi_with_price_long: bool  # OI↑ + price↑
    oi_with_price_short: bool  # OI↑ + price↓
    funding: float
    funding_label: str  # excessively_pos / neutral / excessively_neg
    funding_ok_for_long: bool
    funding_ok_for_short: bool
    long_short_ratio: float
    taker_buy_sell_ratio: float
    cvd_bullish: bool
    cvd_bearish: bool
    cvd_arrow: str
    liq_long_usd: float
    liq_short_usd: float
    liq_label: str


# Funding thresholds (~8h rate). Crowded positive funding is a long crowded-trade
# flag: longs pay shorts, so the model withholds the long "funding_ok" point.
FUNDING_HIGH = 0.0005  # +0.05%
FUNDING_LOW = -0.0005


def extract_derivatives(snapshot: dict) -> DerivativesFeatures:
    premium = snapshot["premium"]
    price = _f(premium["markPrice"])
    funding = _f(premium.get("lastFundingRate"), 0.0)

    oi = _f(snapshot["oi"].get("openInterest"))
    oi_hist = snapshot.get("oi_hist") or []
    if len(oi_hist) >= 2:
        oi_prev = _f(oi_hist[-2].get("sumOpenInterest"), oi)
        # Prefer value if present for direction
        oi_now = _f(oi_hist[-1].get("sumOpenInterest"), oi)
        oi = oi_now
    else:
        oi_prev = oi

    oi_rising = oi > oi_prev * 1.001  # >0.1% rise
    oi_falling = oi < oi_prev * 0.999

    k15 = snapshot["k15"]
    if len(k15) >= 3:
        price_up = float(k15["close"].iloc[-1]) > float(k15["close"].iloc[-3])
    else:
        price_up = True

    oi_with_price_long = oi_rising and price_up
    oi_with_price_short = oi_rising and not price_up

    if oi_rising:
        oi_arrow = "↑"
    elif oi_falling:
        oi_arrow = "↓"
    else:
        oi_arrow = "→"

    if funding >= FUNDING_HIGH:
        funding_label = "excessively_pos"
        funding_ok_for_long = False
        funding_ok_for_short = True
    elif funding <= FUNDING_LOW:
        funding_label = "excessively_neg"
        funding_ok_for_long = True
        funding_ok_for_short = False
    else:
        funding_label = "neutral"
        funding_ok_for_long = True
        funding_ok_for_short = True

    ls = snapshot.get("long_short") or []
    long_short_ratio = _f(ls[-1].get("longShortRatio"), 1.0) if ls else 1.0

    taker = snapshot.get("taker") or []
    if taker:
        recent = [_f(x.get("buySellRatio"), 1.0) for x in taker[-4:]]
        # Score on recent average so one noisy bar does not flip CVD
        taker_buy_sell_ratio = sum(recent) / len(recent)
    else:
        taker_buy_sell_ratio = 1.0

    avg = taker_buy_sell_ratio
    cvd_bullish = avg >= 1.05
    cvd_bearish = avg <= 0.95
    if cvd_bullish:
        cvd_arrow = "↑↑" if avg >= 1.15 else "↑"
    elif cvd_bearish:
        cvd_arrow = "↓↓" if avg <= 0.85 else "↓"
    else:
        cvd_arrow = "→"

    forces = snapshot.get("force_orders") or []
    liq_long_usd = 0.0
    liq_short_usd = 0.0
    for fo in forces:
        # side SELL = long liquidated; BUY = short liquidated
        qty = _f(fo.get("origQty") or fo.get("executedQty"))
        px = _f(fo.get("avgPrice") or fo.get("price"), price)
        notional = qty * px
        side = (fo.get("side") or "").upper()
        if side == "SELL":
            liq_long_usd += notional
        elif side == "BUY":
            liq_short_usd += notional

    if liq_long_usd + liq_short_usd < 1:
        liq_label = "quiet (live WS sample)"
    else:
        liq_label = f"${liq_long_usd/1e6:.2f}M longs / ${liq_short_usd/1e6:.2f}M shorts (live WS)"

    return DerivativesFeatures(
        oi=oi,
        oi_prev=oi_prev,
        oi_rising=oi_rising,
        oi_arrow=oi_arrow,
        price_up=price_up,
        oi_with_price_long=oi_with_price_long,
        oi_with_price_short=oi_with_price_short,
        funding=funding,
        funding_label=funding_label,
        funding_ok_for_long=funding_ok_for_long,
        funding_ok_for_short=funding_ok_for_short,
        long_short_ratio=long_short_ratio,
        taker_buy_sell_ratio=taker_buy_sell_ratio,
        cvd_bullish=cvd_bullish,
        cvd_bearish=cvd_bearish,
        cvd_arrow=cvd_arrow,
        liq_long_usd=liq_long_usd,
        liq_short_usd=liq_short_usd,
        liq_label=liq_label,
    )
