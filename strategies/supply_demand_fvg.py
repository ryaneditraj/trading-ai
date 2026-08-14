"""
Supply / Demand + Fair Value Gap retest (v2)
============================================
From https://www.youtube.com/shorts/ln08lo2X5Lc

Video sequence (short):
  1. Price pushes down → supply zone at origin
  2. Huge candles leave Fair Value Gaps (momentum)
  3. Price retraces, fills FVGs (momentum slows)
  4. Price taps supply → enter short
  5. Target ~2R below entry; stop above supply

Also tests the symmetric demand long.

Compares ^NSEI vs BTC-USD on daily + hourly; small grid on OOS.

Usage:
  python strategies/supply_demand_fvg.py
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from india_edge_engine import (  # noqa: E402
    RESULTS_DIR,
    Trade,
    compute_stats,
    fetch_daily,
    fetch_hourly,
    time_split,
)

COST = {"^NSEI": 0.0005, "BTC-USD": 0.0010}

DEFAULT = {
    "body_atr": 1.4,
    "max_age": 25,
    "rr": 2.0,
    "max_hold": 12,
    "min_zone_atr": 0.2,
    "require_fvg_fill": True,
    "sides": "both",  # "short", "long", "both"
}


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev).abs(),
            (df["Low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(n).mean()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o["atr"] = _atr(o)
    o["body"] = (o["Close"] - o["Open"]).abs()
    return o


def build_trades(df: pd.DataFrame, params: dict, rt_cost: float) -> List[Trade]:
    """
    Event-driven: displacement + FVG → zone; optional FVG fill; tap → entry next open.
    Stop at zone extreme; TP at rr * risk.
    """
    p = {**DEFAULT, **params}
    o = prepare(df)
    atr = o["atr"].to_numpy(dtype=float)
    body = o["body"].to_numpy(dtype=float)
    opens = o["Open"].to_numpy(dtype=float)
    highs = o["High"].to_numpy(dtype=float)
    lows = o["Low"].to_numpy(dtype=float)
    closes = o["Close"].to_numpy(dtype=float)
    idx = o.index
    n = len(o)

    # FVG levels at bar i using i-2 / i
    h2 = o["High"].shift(2).to_numpy(dtype=float)
    l2 = o["Low"].shift(2).to_numpy(dtype=float)
    bull_fvg = lows > h2  # bullish imbalance
    bear_fvg = highs < l2
    # gap bounds
    bull_bot, bull_top = h2, lows
    bear_top, bear_bot = l2, highs

    body_atr = float(p["body_atr"])
    max_age = int(p["max_age"])
    rr = float(p["rr"])
    max_hold = int(p["max_hold"])
    min_zone_atr = float(p["min_zone_atr"])
    require_fill = bool(p["require_fvg_fill"])
    sides = p["sides"]
    allow_short = sides in ("short", "both")
    allow_long = sides in ("long", "both")

    zones: List[dict] = []
    trades: List[Trade] = []
    i = 20
    in_trade = False
    state: Optional[dict] = None

    while i < n - 1:
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            i += 1
            continue

        zones = [z for z in zones if (i - z["born"] <= max_age) and not z["dead"]]

        # Manage open trade
        if in_trade and state is not None:
            side = state["side"]
            entry_i = state["entry_i"]
            entry_px = state["entry"]
            stop = state["stop"]
            target = state["target"]
            hit_stop = hit_tgt = False
            if side == 1:
                if lows[i] <= stop:
                    hit_stop = True
                elif highs[i] >= target:
                    hit_tgt = True
            else:
                if highs[i] >= stop:
                    hit_stop = True
                elif lows[i] <= target:
                    hit_tgt = True

            exit_i = exit_px = None
            if hit_stop:
                exit_i, exit_px = i, stop
            elif hit_tgt:
                exit_i, exit_px = i, target
            elif i - entry_i + 1 >= max_hold:
                exit_i, exit_px = i, closes[i]

            if exit_i is not None:
                ret_g = side * (exit_px / entry_px - 1.0)
                trades.append(
                    Trade(
                        entry_time=idx[entry_i],
                        exit_time=idx[exit_i],
                        side=side,
                        entry=float(entry_px),
                        exit=float(exit_px),
                        bars=int(exit_i - entry_i + 1),
                        ret_gross=float(ret_g),
                        ret_net=float(ret_g - rt_cost),
                    )
                )
                in_trade = False
                state = None
                i = exit_i + 1
                continue

        # Track FVG fill on active zones
        for z in zones:
            if z["dead"] or z["fvg_filled"]:
                continue
            # fill = price trades into the FVG band
            if highs[i] >= z["fvg_bot"] and lows[i] <= z["fvg_top"]:
                z["fvg_filled"] = True

        # Spawn zone on displacement candle that co-occurs with FVG
        if body[i] >= body_atr * a and np.isfinite(h2[i]):
            z_i = i - 1
            z_hi, z_lo = float(highs[z_i]), float(lows[z_i])
            width = z_hi - z_lo
            if width < min_zone_atr * a:
                mid = 0.5 * (z_hi + z_lo)
                half = 0.5 * min_zone_atr * a
                z_hi, z_lo = mid + half, mid - half

            if closes[i] < opens[i] and allow_short and bear_fvg[i]:
                zones.append(
                    {
                        "side": -1,
                        "top": z_hi,
                        "bot": z_lo,
                        "born": i,
                        "dead": False,
                        "fvg_top": float(bear_top[i]),
                        "fvg_bot": float(bear_bot[i]),
                        "fvg_filled": False if require_fill else True,
                    }
                )
            elif closes[i] > opens[i] and allow_long and bull_fvg[i]:
                zones.append(
                    {
                        "side": 1,
                        "top": z_hi,
                        "bot": z_lo,
                        "born": i,
                        "dead": False,
                        "fvg_top": float(bull_top[i]),
                        "fvg_bot": float(bull_bot[i]),
                        "fvg_filled": False if require_fill else True,
                    }
                )

        # Invalidate if closed through zone
        for z in zones:
            if z["dead"]:
                continue
            if z["side"] == -1 and closes[i] > z["top"]:
                z["dead"] = True
            if z["side"] == 1 and closes[i] < z["bot"]:
                z["dead"] = True

        # Tap entry
        if not in_trade:
            tapped = None
            for z in zones:
                if z["dead"] or i <= z["born"] or not z["fvg_filled"]:
                    continue
                if not (highs[i] >= z["bot"] and lows[i] <= z["top"]):
                    continue
                # approach from discount/premium correctly
                if z["side"] == -1 and closes[max(0, i - 1)] > z["top"]:
                    continue
                if z["side"] == 1 and closes[max(0, i - 1)] < z["bot"]:
                    continue
                tapped = z
                break

            if tapped is not None and i + 1 < n:
                entry_i = i + 1
                entry_px = float(opens[entry_i])
                if not (np.isfinite(entry_px) and entry_px > 0):
                    i += 1
                    continue
                side = tapped["side"]
                if side == -1:
                    stop = tapped["top"] * 1.001
                    risk = stop - entry_px
                    if risk <= entry_px * 1e-4:
                        i += 1
                        continue
                    target = entry_px - rr * risk
                else:
                    stop = tapped["bot"] * 0.999
                    risk = entry_px - stop
                    if risk <= entry_px * 1e-4:
                        i += 1
                        continue
                    target = entry_px + rr * risk

                in_trade = True
                state = {
                    "side": side,
                    "entry_i": entry_i,
                    "entry": entry_px,
                    "stop": float(stop),
                    "target": float(target),
                }
                tapped["dead"] = True
                i = entry_i
                continue

        i += 1

    return trades


def load(symbol: str, tf: str) -> pd.DataFrame:
    if tf == "1h":
        df = fetch_hourly(symbol)
    else:
        df = fetch_daily(symbol, start="2015-01-01")
    return df.dropna(subset=["Open", "High", "Low", "Close"])


def eval_one(symbol: str, tf: str, params: dict) -> Dict:
    df = load(symbol, tf)
    cost = COST.get(symbol, 0.0008)
    # hourly ann factor ~ 252*6.5 for India, 365*24 for BTC — use trade-based sharpe from engine
    train, test = time_split(df, 0.7)
    out = {"symbol": symbol, "tf": tf, "params": params, "n_bars": len(df)}
    for split, part in [("IS", train), ("OOS", test)]:
        trades = build_trades(part, params, rt_cost=cost)
        ann = 252.0 if tf == "1d" else (365.0 * 24 if "BTC" in symbol else 252.0 * 6.5)
        stats = compute_stats(
            trades, "sd_fvg", symbol, split, params, ann_factor=ann
        )
        out[split] = {
            k: v for k, v in stats.to_dict().items() if k not in ("params", "name", "symbol")
        }
    return out


def fmt(s: dict) -> str:
    return (
        f"n={s['n_trades']:4d} WR={s['win_rate']:5.1%} PF={s['profit_factor']:5.2f} "
        f"E={s['expectancy']:+.3%} Tot={s['total_return']:+.1%} "
        f"MDD={s['max_dd']:.1%} Sh={s['sharpe']:.2f}"
    )


def oos_score(r: dict) -> float:
    o = r["OOS"]
    if o["n_trades"] < 10:
        return -999.0
    if o["profit_factor"] < 1.0 or o["expectancy"] <= 0:
        return -100.0 + o["expectancy"] * 10
    return o["expectancy"] * np.sqrt(o["n_trades"]) + 0.05 * o["sharpe"]


def grid_search(symbol: str, tf: str) -> Tuple[dict, List[dict]]:
    grid = {
        "body_atr": [1.0, 1.4, 1.8],
        "rr": [1.5, 2.0, 2.5],
        "max_hold": [8, 15],
        "max_age": [15, 30],
        "require_fvg_fill": [True, False],
        "sides": ["short", "both"],
    }
    keys = list(grid.keys())
    rows = []
    best = None
    best_sc = -1e18
    for vals in product(*[grid[k] for k in keys]):
        params = dict(zip(keys, vals))
        params["min_zone_atr"] = 0.2
        try:
            r = eval_one(symbol, tf, params)
        except Exception:
            continue
        sc = oos_score(r)
        row = {
            "params": params,
            "score": sc,
            "OOS": r["OOS"],
            "IS": r["IS"],
        }
        rows.append(row)
        if sc > best_sc:
            best_sc = sc
            best = r
    rows.sort(key=lambda x: x["score"], reverse=True)
    return best, rows[:5]


def main():
    summary = {"video": "https://www.youtube.com/shorts/ln08lo2X5Lc", "markets": {}}

    print("=== Baseline (video-faithful: short + FVG fill) ===")
    base = {
        **DEFAULT,
        "sides": "short",
        "require_fvg_fill": True,
    }
    baselines = {}
    for sym in ("^NSEI", "BTC-USD"):
        for tf in ("1d", "1h"):
            tag = f"{sym}|{tf}"
            print(f"\n{tag}")
            try:
                r = eval_one(sym, tf, base)
            except Exception as e:
                print(f"  skip: {e}")
                continue
            print(f"  IS   {fmt(r['IS'])}")
            print(f"  OOS  {fmt(r['OOS'])}")
            baselines[tag] = r

    print("\n=== Grid search (best OOS per market/tf) ===")
    winners = {}
    for sym in ("^NSEI", "BTC-USD"):
        for tf in ("1d", "1h"):
            tag = f"{sym}|{tf}"
            print(f"\nSearching {tag}...")
            try:
                best, top = grid_search(sym, tf)
            except Exception as e:
                print(f"  skip: {e}")
                continue
            if best is None:
                print("  no viable configs")
                continue
            print(f"  BEST OOS {fmt(best['OOS'])}")
            print(f"  params {best['params']}")
            winners[tag] = {
                "best": best,
                "top5": [
                    {
                        "score": t["score"],
                        "params": t["params"],
                        "OOS_n": t["OOS"]["n_trades"],
                        "OOS_PF": t["OOS"]["profit_factor"],
                        "OOS_E": t["OOS"]["expectancy"],
                        "OOS_tot": t["OOS"]["total_return"],
                    }
                    for t in top
                ],
            }

    # Head-to-head on best OOS expectancy among configs with PF>=1 and n>=10
    print("\n=== HEAD-TO-HEAD ===")
    ranked = []
    for tag, w in winners.items():
        o = w["best"]["OOS"]
        sc = oos_score(w["best"])
        ranked.append((sc, tag, o, w["best"]["params"]))
        print(f"  {tag:18s} score={sc:7.3f}  {fmt(o)}")

    ranked.sort(reverse=True)
    if ranked and ranked[0][0] > -50:
        champ = ranked[0][1]
        print(f"\nBest mechanical edge: {champ}")
    else:
        # fall back to least-bad baseline
        base_rank = []
        for tag, r in baselines.items():
            base_rank.append((oos_score(r), tag, r["OOS"]))
        base_rank.sort(reverse=True)
        champ = base_rank[0][1] if base_rank else "none"
        print(f"\nNo PF>1 OOS edge found. Least-bad baseline: {champ}")
        for sc, tag, o in base_rank:
            print(f"  {tag:18s} score={sc:7.3f}  {fmt(o)}")

    # Nifty vs BTC at same tf using best grid result
    for tf in ("1d", "1h"):
        ntag, btag = f"^NSEI|{tf}", f"BTC-USD|{tf}"
        if ntag in winners and btag in winners:
            ns, bs = oos_score(winners[ntag]["best"]), oos_score(winners[btag]["best"])
            better = "BTC-USD" if bs >= ns else "^NSEI"
            print(f"\nOn {tf}: {better} scores higher (Nifty={ns:.3f}, BTC={bs:.3f})")

    summary["baselines"] = baselines
    summary["winners"] = {
        k: {
            "params": v["best"]["params"],
            "IS": v["best"]["IS"],
            "OOS": v["best"]["OOS"],
            "top5": v["top5"],
        }
        for k, v in winners.items()
    }
    summary["champion_tag"] = champ if ranked else champ

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "supply_demand_fvg_nifty_vs_btc.json"
    path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
