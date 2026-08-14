"""ASCII radar scorecard renderer."""

from __future__ import annotations

from btc_radar.score import RadarResult, TARGET_PCT


def _bar(pct: float, width: int = 10) -> str:
    filled = int(round(max(0.0, min(100.0, pct)) / 100.0 * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _usd(n: float) -> str:
    if abs(n) >= 1e6:
        return f"${n/1e6:,.1f}M"
    if abs(n) >= 1e3:
        return f"${n/1e3:,.1f}K"
    return f"${n:,.0f}"


def _price(p: float) -> str:
    return f"${p:,.0f}" if p >= 1000 else f"${p:,.2f}"


def render(result: RadarResult) -> str:
    s = result.structure
    d = result.derivatives
    liq = result.liquidity
    c = result.catalyst

    funding_disp = {
        "excessively_pos": "excessively +",
        "excessively_neg": "excessively −",
        "neutral": "neutral",
    }.get(d.funding_label, d.funding_label)

    lines = [
        f"BTC: {_price(result.price)}",
        "",
        "NEXT 1% CONFIDENCE (score-derived, not win-rate)",
        "",
        f"LONG  {_bar(result.long_pct)}  {result.long_pct:.0f}%   ({result.long_score:.1f}/10)",
        f"SHORT {_bar(result.short_pct)}  {result.short_pct:.0f}%   ({result.short_score:.1f}/10)",
        "",
        f"OI              {d.oi_arrow}",
        f"Funding         {funding_disp}  ({d.funding * 100:.4f}%)",
        f"Spot CVD        {d.cvd_arrow}  (taker buy/sell {d.taker_buy_sell_ratio:.2f})",
        f"Liquidations    {d.liq_label}",
        f"VWAP            {'bullish' if s.above_vwap else 'bearish'}  ({_price(s.vwap)})",
        f"Structure       {s.label}",
        f"Liquidity       {_price(liq.cluster_above)} ↑  ({_usd(liq.ask_depth_usd)} asks)",
        f"                {_price(liq.cluster_below)} ↓  ({_usd(liq.bid_depth_usd)} bids)",
        f"                [{liq.note}]",
        "",
        f"MACRO RISK      {c.risk_label}",
        f"                {c.detail}",
        "",
        f"SIGNAL: {result.signal}",
        f"CONFIDENCE: {result.confidence:.1f}/10",
        "",
        f"{result.leverage:.0f}x: liq≈±{result.liq_distance_pct:.2f}%  |  target ±{TARGET_PCT:.1f}%",
        f"Risk reminder: ${result.risk_usd:,.0f} margin risk → ~{_usd(result.max_notional)} notional @ {result.leverage:.0f}x",
    ]

    if result.warnings:
        lines.append("")
        for w in result.warnings:
            lines.append(f"WARNING: {w}")

    # Compact breakdown
    lines.append("")
    lines.append("LONG pts:  " + (", ".join(f"{k}+{v:g}" for k, v in result.breakdown.long_points.items()) or "—"))
    lines.append("SHORT pts: " + (", ".join(f"{k}+{v:g}" for k, v in result.breakdown.short_points.items()) or "—"))

    return "\n".join(lines)
