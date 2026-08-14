"""BTC 1% Radar CLI — live Binance snapshot or offline --demo."""

from __future__ import annotations

import argparse
import json
import sys
import time
from enum import Enum

from btc_radar.catalyst import MacroMode
from btc_radar.demo import build_demo_snapshot
from btc_radar.pipeline import run_radar
from btc_radar.score import RadarResult


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="btc-radar",
        description="BTC 1% Radar — signal-only score of which side is likelier to print ±1% first",
    )
    p.add_argument("--symbol", default="BTCUSDT", help="Binance USD-M symbol")
    p.add_argument("--leverage", type=float, default=100.0, help="Assumed leverage for liq warning")
    p.add_argument("--risk-usd", type=float, default=100.0, help="Cash risk reminder (print-only)")
    p.add_argument(
        "--macro",
        choices=[m.value for m in MacroMode],
        default=MacroMode.AUTO.value,
        help="Macro risk override",
    )
    p.add_argument("--force", action="store_true", help="Allow signal even if macro elevated")
    p.add_argument(
        "--liq-listen",
        type=float,
        default=1.0,
        help="Seconds to sample Binance liquidation websocket (0=skip)",
    )
    p.add_argument(
        "--watch",
        type=float,
        default=0,
        metavar="SECONDS",
        help="Refresh every N seconds (0 = once)",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Score a synthetic snapshot (no network). Use --macro low to skip the calendar gate.",
    )
    p.add_argument("--json", action="store_true", help="Print RadarResult as JSON instead of the ASCII card")
    return p.parse_args(argv)


def _json_default(obj: object) -> object:
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Not serializable: {type(obj)}")


def _emit(result: RadarResult, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), default=_json_default, indent=2))
        return
    print(text)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    macro = MacroMode(args.macro)
    snapshot = build_demo_snapshot() if args.demo else None

    def once() -> None:
        try:
            result, text = run_radar(
                symbol=args.symbol,
                leverage=args.leverage,
                risk_usd=args.risk_usd,
                macro=macro,
                force=args.force,
                liq_listen_seconds=0.0 if args.demo else max(0.0, args.liq_listen),
                snapshot=snapshot,
            )
            if args.demo and not args.json:
                print("(demo snapshot — not live Binance data)\n")
            _emit(result, text, args.json)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            raise

    if args.watch and args.watch > 0:
        while True:
            print("\033[2J\033[H", end="")
            print(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
            print()
            try:
                once()
            except Exception:
                pass
            print(f"\n— refresh in {args.watch:.0f}s (Ctrl+C to quit) —")
            try:
                time.sleep(args.watch)
            except KeyboardInterrupt:
                print("\nStopped.")
                return 0
    else:
        try:
            once()
        except Exception:
            return 1
    return 0
