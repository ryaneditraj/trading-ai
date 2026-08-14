from btc_radar.catalyst import MacroMode
from btc_radar.demo import build_demo_snapshot
from btc_radar.pipeline import run_radar
from btc_radar.structure import session_vwap


def test_demo_snapshot_has_session_vwap():
    snap = build_demo_snapshot()
    vwap = session_vwap(snap["k5"])
    assert vwap == vwap  # not NaN
    assert vwap > 0


def test_demo_pipeline_scores_without_network():
    result, text = run_radar(macro=MacroMode.LOW, snapshot=build_demo_snapshot())
    assert result.price > 0
    assert result.signal in {"LONG", "SHORT", "NO TRADE"}
    assert "NEXT 1% CONFIDENCE" in text
    assert result.long_score >= 0
