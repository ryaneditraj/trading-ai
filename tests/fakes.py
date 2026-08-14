"""Shared dummy features for scorer tests."""

from __future__ import annotations

from btc_radar.catalyst import CatalystFeatures, MacroMode
from btc_radar.derivatives import DerivativesFeatures
from btc_radar.liquidity import LiquidityFeatures
from btc_radar.structure import StructureFeatures


def structure(*, bullish: bool = True, above_vwap: bool | None = None) -> StructureFeatures:
    above = bullish if above_vwap is None else above_vwap
    return StructureFeatures(
        price=100_000.0,
        vwap=99_500.0 if above else 100_500.0,
        above_vwap=above,
        pdh=101_000.0,
        pdl=98_000.0,
        session_high=100_800.0,
        session_low=99_200.0,
        ema20_5m=99_800.0 if bullish else 100_200.0,
        ema50_5m=99_000.0 if bullish else 101_000.0,
        ema20_15m=99_700.0 if bullish else 100_300.0,
        ema50_15m=98_900.0 if bullish else 101_100.0,
        trend_bullish=bullish,
        trend_bearish=not bullish,
        near_support=False,
        near_resistance=False,
        label="bullish" if bullish and above else ("bearish" if not bullish and not above else "mixed"),
    )


def derivatives(*, long_side: bool = True) -> DerivativesFeatures:
    return DerivativesFeatures(
        oi=50_000.0,
        oi_prev=49_000.0,
        oi_rising=True,
        oi_arrow="↑",
        price_up=long_side,
        oi_with_price_long=long_side,
        oi_with_price_short=not long_side,
        funding=0.00005,
        funding_label="neutral",
        funding_ok_for_long=True,
        funding_ok_for_short=True,
        long_short_ratio=1.1,
        taker_buy_sell_ratio=1.12 if long_side else 0.88,
        cvd_bullish=long_side,
        cvd_bearish=not long_side,
        cvd_arrow="↑" if long_side else "↓",
        liq_long_usd=0.0,
        liq_short_usd=0.0,
        liq_label="quiet (live WS sample)",
    )


def liquidity(*, larger_above: bool = True) -> LiquidityFeatures:
    return LiquidityFeatures(
        bid_depth_usd=1_000_000.0,
        ask_depth_usd=2_000_000.0 if larger_above else 500_000.0,
        cluster_above=100_800.0,
        cluster_below=99_200.0,
        larger_above=larger_above,
        larger_below=not larger_above,
        band_pct=0.015,
        note="test",
    )


def catalyst_low() -> CatalystFeatures:
    return CatalystFeatures(
        mode=MacroMode.LOW,
        risk_label="LOW",
        force_no_trade=False,
        bullish_bias=False,
        bearish_bias=False,
        next_event="(override)",
        hours_to_event=None,
        detail="Macro override: LOW",
    )


def catalyst_elevated() -> CatalystFeatures:
    return CatalystFeatures(
        mode=MacroMode.ELEVATED,
        risk_label="ELEVATED",
        force_no_trade=True,
        bullish_bias=False,
        bearish_bias=False,
        next_event="(override)",
        hours_to_event=None,
        detail="Macro override: ELEVATED — prefer NO TRADE",
    )
