#!/usr/bin/env python3
"""
BTC 1% Radar — walk-forward backtest
====================================
Measures whether LONG/SHORT signals (≥ threshold) correctly predict which
side first prints a ±1% excursion.

Usage:
  python strategies/btc_1pct_radar_backtest.py
  python strategies/btc_1pct_radar_backtest.py --days 14 --threshold 8
  python strategies/btc_1pct_radar_backtest.py --no-macro --step 2 --csv /tmp/radar_bt.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from btc_radar.backtest import BacktestConfig, format_summary, run_backtest  # noqa: E402
from btc_radar.history import load_history  # noqa: E402
from btc_radar.score import THRESHOLD, TARGET_PCT  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backtest BTC 1% Radar signals")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--days", type=int, default=28, help="Evaluation window (max ~28; Binance deriv hist)")
    p.add_argument("--threshold", type=float, default=THRESHOLD)
    p.add_argument("--target-pct", type=float, default=TARGET_PCT)
    p.add_argument("--leverage", type=float, default=100.0)
    p.add_argument("--step", type=int, default=1, help="Evaluate every Nth 15m bar")
    p.add_argument("--no-macro", action="store_true", help="Disable macro NO TRADE gate")
    p.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Count every 15m bar signal (default collapses consecutive same-side signals)",
    )
    p.add_argument("--csv", type=str, default="", help="Optional path to write trade-level CSV")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = BacktestConfig(
        days=args.days,
        target_pct=args.target_pct,
        threshold=args.threshold,
        leverage=args.leverage,
        step=max(1, args.step),
        use_macro=not args.no_macro,
        dedupe_signals=not args.no_dedupe,
    )
    print(f"Loading Binance history for {args.symbol} (~{cfg.days}d)…", flush=True)
    try:
        hist = load_history(symbol=args.symbol, days=cfg.days)
        df, summary = run_backtest(hist=hist, cfg=cfg, symbol=args.symbol)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print()
    print(format_summary(summary, df))

    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        print(f"\nWrote {len(df)} rows → {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
