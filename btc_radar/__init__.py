"""BTC 1% Radar — short-horizon LONG/SHORT confidence from structure + derivatives."""

from btc_radar.pipeline import run_radar
from btc_radar.score import RadarResult, score

__version__ = "0.1.0"
__all__ = ["RadarResult", "run_radar", "score", "__version__"]
