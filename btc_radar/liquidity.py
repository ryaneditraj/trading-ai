"""Liquidity proxy: order-book depth clusters + recent force-order levels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


@dataclass
class LiquidityFeatures:
    bid_depth_usd: float  # within band below
    ask_depth_usd: float  # within band above
    cluster_above: float  # price of densest ask cluster
    cluster_below: float  # price of densest bid cluster
    larger_above: bool  # more liquidity / magnet above → favors LONG sweep thesis
    larger_below: bool
    band_pct: float
    note: str


def _depth_usd_in_band(
    levels: list[list[str]],
    mid: float,
    lo: float,
    hi: float,
) -> tuple[float, float]:
    """Return (total_usd, densest_price) for levels with price in [lo, hi]."""
    total = 0.0
    best_px = mid
    best_notional = 0.0
    for row in levels:
        px = _f(row[0])
        qty = _f(row[1])
        if px < lo or px > hi:
            continue
        notional = px * qty
        total += notional
        if notional > best_notional:
            best_notional = notional
            best_px = px
    return total, best_px


def extract_liquidity(snapshot: dict, band_pct: float = 0.015) -> LiquidityFeatures:
    """
    Use Binance book depth within ±band_pct as a liquidity/magnet proxy.
    Larger ask-side depth above price → more fuel above (LONG +2 in score model).
    """
    price = _f(snapshot["premium"]["markPrice"])
    book = snapshot.get("depth") or {}
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    lo = price * (1.0 - band_pct)
    hi = price * (1.0 + band_pct)

    bid_usd, cluster_below = _depth_usd_in_band(bids, price, lo, price)
    ask_usd, cluster_above = _depth_usd_in_band(asks, price, price, hi)

    # Fold in recent force-order price levels as secondary magnets
    forces = snapshot.get("force_orders") or []
    force_above = 0.0
    force_below = 0.0
    for fo in forces:
        px = _f(fo.get("avgPrice") or fo.get("price"), price)
        qty = _f(fo.get("origQty") or fo.get("executedQty"))
        notional = px * qty
        # Force-order notionals are a weaker magnet than resting book depth.
        if price < px <= hi:
            force_above += notional
        elif lo <= px < price:
            force_below += notional

    ask_total = ask_usd + 0.25 * force_above
    bid_total = bid_usd + 0.25 * force_below

    # Need clear imbalance (>15%) to award the liquidity points
    larger_above = ask_total > bid_total * 1.15
    larger_below = bid_total > ask_total * 1.15

    note = "Binance book depth + recent force orders (not multi-exchange heatmap)"

    return LiquidityFeatures(
        bid_depth_usd=bid_total,
        ask_depth_usd=ask_total,
        cluster_above=cluster_above if ask_usd > 0 else price * (1 + band_pct),
        cluster_below=cluster_below if bid_usd > 0 else price * (1 - band_pct),
        larger_above=larger_above,
        larger_below=larger_below,
        band_pct=band_pct,
        note=note,
    )
