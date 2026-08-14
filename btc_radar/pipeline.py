"""Orchestrate fetch → features → score → render."""

from __future__ import annotations

from btc_radar.binance import BinancePublic
from btc_radar.catalyst import MacroMode, extract_catalyst
from btc_radar.derivatives import extract_derivatives
from btc_radar.liquidity import extract_liquidity
from btc_radar.render import render
from btc_radar.score import RadarResult, score
from btc_radar.structure import extract_structure


def run_radar(
    symbol: str = "BTCUSDT",
    leverage: float = 100.0,
    risk_usd: float = 100.0,
    macro: MacroMode = MacroMode.AUTO,
    force: bool = False,
    liq_listen_seconds: float = 1.0,
    client: BinancePublic | None = None,
    snapshot: dict | None = None,
) -> tuple[RadarResult, str]:
    """Fetch (or accept) a snapshot, score it, and render the ASCII card."""
    if snapshot is None:
        client = client or BinancePublic(symbol=symbol)
        snapshot = client.fetch_snapshot(liq_listen_seconds=liq_listen_seconds)
    structure = extract_structure(snapshot)
    derivatives = extract_derivatives(snapshot)
    liquidity = extract_liquidity(snapshot)
    catalyst = extract_catalyst(override=macro, force=force)
    result = score(
        structure,
        derivatives,
        liquidity,
        catalyst,
        leverage=leverage,
        risk_usd=risk_usd,
        force=force,
    )
    return result, render(result)
