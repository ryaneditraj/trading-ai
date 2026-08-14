from btc_radar.score import THRESHOLD, liquidation_distance_pct, score

from tests.fakes import catalyst_elevated, catalyst_low, derivatives, liquidity, structure


def test_liquidation_distance_100x_is_under_one_percent():
    # 1/100 - 0.4% MMR = 0.6%
    dist = liquidation_distance_pct(100.0)
    assert 0.5 < dist < 0.7


def test_zero_leverage_does_not_blow_up():
    assert liquidation_distance_pct(0) == 100.0


def test_aligned_long_clears_threshold():
    result = score(structure(bullish=True), derivatives(long_side=True), liquidity(larger_above=True), catalyst_low())
    assert result.long_score >= THRESHOLD
    assert result.signal == "LONG"
    assert result.short_score < result.long_score


def test_mixed_tape_is_no_trade():
    result = score(
        structure(bullish=True, above_vwap=False),
        derivatives(long_side=False),
        liquidity(larger_above=True),
        catalyst_low(),
    )
    assert result.signal == "NO TRADE"
    assert any("sit out" in w for w in result.warnings)


def test_macro_gate_blocks_even_when_score_is_full():
    result = score(
        structure(bullish=True),
        derivatives(long_side=True),
        liquidity(larger_above=True),
        catalyst_elevated(),
        force=False,
    )
    assert result.signal == "NO TRADE"
    assert any("Macro" in w for w in result.warnings)


def test_force_bypasses_macro_gate():
    result = score(
        structure(bullish=True),
        derivatives(long_side=True),
        liquidity(larger_above=True),
        catalyst_elevated(),
        force=True,
    )
    assert result.signal == "LONG"
