from btc_radar.liquidity import extract_liquidity


def test_ask_heavy_book_awards_above_cluster():
    snap = {
        "premium": {"markPrice": 100_000},
        "depth": {
            "bids": [["99900", "1"]],
            "asks": [["100100", "20"], ["100200", "20"]],
        },
        "force_orders": [],
    }
    liq = extract_liquidity(snap)
    assert liq.larger_above is True
    assert liq.larger_below is False


def test_balanced_book_awards_neither_side():
    snap = {
        "premium": {"markPrice": 100_000},
        "depth": {
            "bids": [["99900", "10"]],
            "asks": [["100100", "10"]],
        },
        "force_orders": [],
    }
    liq = extract_liquidity(snap)
    assert liq.larger_above is False
    assert liq.larger_below is False
