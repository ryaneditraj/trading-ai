"""
Runner-up r1: Supertrend basket, conservative mult=3.0
OOS PF≈2.05 tot≈79% n≈119 WF=3/3 (less peaky than mult=3.6)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "strategies"))

# Reuse best engine with overridden mult
import nifty_edge_best as best  # noqa: E402

best.ENTRY_MULT = 3.0


def main():
    print("Running conservative ST mult=3.0 …")
    best.main()


if __name__ == "__main__":
    main()
