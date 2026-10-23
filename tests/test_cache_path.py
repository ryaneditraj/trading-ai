"""Research parquet caches must stay inside research/data."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))

from india_edge_engine import DATA_DIR, safe_cache_path  # noqa: E402


def test_existing_ticker_filenames_stay_the_same():
    """Sanitizing must not rename caches the research scripts already use."""
    cases = {
        "^NSEI": "NSEI_1d.parquet",
        "^NSEBANK": "NSEBANK_1d.parquet",
        "RELIANCE.NS": "RELIANCE_NS_1d.parquet",
        "ES=F": "ES=F_1d.parquet",
    }
    for symbol, name in cases.items():
        path = safe_cache_path(f"{symbol.replace('^', '').replace('.', '_')}_1d.parquet")
        assert path.name == name


def test_nifty_and_gift_names_stay_in_data_dir():
    root = DATA_DIR.resolve()
    daily = safe_cache_path("NSEI_1d.parquet")
    hourly = safe_cache_path("RELIANCE_NS_1h.parquet")
    futures = safe_cache_path("ES=F_1d.parquet")
    gift = safe_cache_path("gift_NQ_F_1d.parquet")
    for path in (daily, hourly, futures, gift):
        assert path.parent == root


@pytest.mark.parametrize(
    "name",
    [
        "../x.parquet",
        "..",
        "a/b.parquet",
        "a\\b.parquet",
        "foo..bar.parquet",
        "",
        "has space.parquet",
        "bad\nname.parquet",
        ".hidden.parquet",
    ],
)
def test_unsafe_cache_names_raise(name):
    with pytest.raises(ValueError):
        safe_cache_path(name)
