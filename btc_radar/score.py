"""10-point LONG/SHORT scorer + 100x liquidation distance."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from btc_radar.catalyst import CatalystFeatures
from btc_radar.derivatives import DerivativesFeatures
from btc_radar.liquidity import LiquidityFeatures
from btc_radar.structure import StructureFeatures

# Fire only when one side is clearly stacked. 8/10 is intentionally strict:
# mixed tape should print NO TRADE rather than a coin-flip.
THRESHOLD = 8.0
TARGET_PCT = 1.0


@dataclass
class ScoreBreakdown:
    long_points: dict[str, float] = field(default_factory=dict)
    short_points: dict[str, float] = field(default_factory=dict)

    @property
    def long_total(self) -> float:
        return float(sum(self.long_points.values()))

    @property
    def short_total(self) -> float:
        return float(sum(self.short_points.values()))


@dataclass
class RadarResult:
    price: float
    long_score: float
    short_score: float
    long_pct: float
    short_pct: float
    signal: str  # LONG | SHORT | NO TRADE
    confidence: float
    breakdown: ScoreBreakdown
    structure: StructureFeatures
    derivatives: DerivativesFeatures
    liquidity: LiquidityFeatures
    catalyst: CatalystFeatures
    leverage: float
    liq_distance_pct: float
    risk_usd: float
    max_notional: float
    warnings: list[str]

    def to_dict(self) -> dict:
        """JSON-friendly dump for --json / logging. Enums become strings."""
        return asdict(self)


def liquidation_distance_pct(leverage: float, mmr: float = 0.004) -> float:
    """
    Approximate isolated-margin liquidation distance for a linear perp.
    Rough: 1/leverage - mmr (maintenance margin rate ~0.4% for BTC on many venues).
    """
    if leverage <= 0:
        return 100.0
    dist = (1.0 / leverage) - mmr
    return max(dist, 0.0001) * 100.0  # percent


def score(
    structure: StructureFeatures,
    derivatives: DerivativesFeatures,
    liquidity: LiquidityFeatures,
    catalyst: CatalystFeatures,
    leverage: float = 100.0,
    risk_usd: float = 100.0,
    force: bool = False,
) -> RadarResult:
    bd = ScoreBreakdown()

    # --- LONG ---
    if structure.trend_bullish:
        bd.long_points["trend_bullish"] = 2.0
    if structure.above_vwap:
        bd.long_points["above_vwap"] = 1.0
    if derivatives.cvd_bullish:
        bd.long_points["cvd_bullish"] = 2.0
    if derivatives.oi_with_price_long:
        bd.long_points["oi_rising_with_price"] = 1.0
    if derivatives.funding_ok_for_long:
        bd.long_points["funding_ok"] = 1.0
    if liquidity.larger_above:
        bd.long_points["liq_cluster_above"] = 2.0
    if catalyst.bullish_bias:
        bd.long_points["macro_bullish"] = 1.0

    # --- SHORT ---
    if structure.trend_bearish:
        bd.short_points["trend_bearish"] = 2.0
    if not structure.above_vwap:
        bd.short_points["below_vwap"] = 1.0
    if derivatives.cvd_bearish:
        bd.short_points["cvd_bearish"] = 2.0
    if derivatives.oi_with_price_short:
        bd.short_points["oi_rising_with_price"] = 1.0
    if derivatives.funding_ok_for_short:
        bd.short_points["funding_ok"] = 1.0
    if liquidity.larger_below:
        bd.short_points["liq_cluster_below"] = 2.0
    if catalyst.bearish_bias:
        bd.short_points["macro_bearish"] = 1.0

    long_score = bd.long_total
    short_score = bd.short_total
    long_pct = min(100.0, long_score / 10.0 * 100.0)
    short_pct = min(100.0, short_score / 10.0 * 100.0)

    warnings: list[str] = []
    liq_pct = liquidation_distance_pct(leverage)

    if liq_pct <= TARGET_PCT:
        warnings.append(
            f"TARGET ±{TARGET_PCT}% ≥ LIQUIDATION DISTANCE ±{liq_pct:.2f}% @ {leverage:.0f}x — "
            "size only with cash you can lose"
        )

    signal = "NO TRADE"
    confidence = 0.0

    if catalyst.force_no_trade and not force:
        signal = "NO TRADE"
        confidence = max(long_score, short_score)
        warnings.append(f"Macro {catalyst.risk_label}: {catalyst.detail}")
    elif long_score >= THRESHOLD and long_score > short_score:
        signal = "LONG"
        confidence = long_score
    elif short_score >= THRESHOLD and short_score > long_score:
        signal = "SHORT"
        confidence = short_score
    else:
        signal = "NO TRADE"
        confidence = max(long_score, short_score)
        if long_score < THRESHOLD and short_score < THRESHOLD:
            warnings.append(f"Neither side ≥ {THRESHOLD:.0f}/10 — sit out")

    # Max notional such that a full wipe at liq_pct costs ~risk_usd
    # At 100x, notional ≈ risk_usd * leverage if you risk the entire margin.
    max_notional = risk_usd * leverage

    return RadarResult(
        price=structure.price,
        long_score=long_score,
        short_score=short_score,
        long_pct=long_pct,
        short_pct=short_pct,
        signal=signal,
        confidence=confidence,
        breakdown=bd,
        structure=structure,
        derivatives=derivatives,
        liquidity=liquidity,
        catalyst=catalyst,
        leverage=leverage,
        liq_distance_pct=liq_pct,
        risk_usd=risk_usd,
        max_notional=max_notional,
        warnings=warnings,
    )
