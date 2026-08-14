"""
India Donchian Trend Basket
==========================
Market-structure thesis: In liquid NSE large-caps, a close above the prior
55-day high while price is above the 200-EMA is a break of range acceptance
in a bullish auction. Exit on a close below the prior 20-day low (Turtle-style
channel exit). Trade as a small basket (max 5 names) with equal slot weight.

SUPERSEDED for live research by strategies/india_nifty_adx_donchian_v2.py
(round-2): bare 55/20 OOS PF≈1.17 / +9% failed the user's profitability bar.
Kept for reproduction of the failure baseline.

Usage:
  python strategies/india_donchian_trend_basket.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from india_edge_engine import (  # noqa: E402
    RESULTS_DIR,
    add_structure_features,
    fetch_daily,
    time_split,
)

# ── Defaults (research-selected) ─────────────────────────────────────────────
ENTRY_N = 55
EXIT_N = 20
EMA_LEN = 200
MAX_POSITIONS = 5
RT_COST = 0.0008  # 0.08% round-trip (broker + taxes + slippage ballpark)
TRAIN_FRAC = 0.7

UNIVERSE = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "ITC.NS",
    "LT.NS",
    "AXISBANK.NS",
    "KOTAKBANK.NS",
    "HINDUNILVR.NS",
    "BAJFINANCE.NS",
    "ASIANPAINT.NS",
    "MARUTI.NS",
    "SUNPHARMA.NS",
    "TITAN.NS",
    "ULTRACEMCO.NS",
    "WIPRO.NS",
    "NESTLEIND.NS",
]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    gap = o["Open"] / o["Close"].shift(1) - 1.0
    ret = o["Close"].pct_change()
    mask = ((gap.abs() < 0.08) | gap.isna()) & ((ret.abs() < 0.12) | ret.isna())
    return add_structure_features(o.loc[mask].copy())


def entry_exit_signals(
    df: pd.DataFrame,
    entry_n: int = ENTRY_N,
    exit_n: int = EXIT_N,
    ema_len: int = EMA_LEN,
) -> tuple[pd.Series, pd.Series]:
    ema = df["Close"].ewm(span=ema_len, adjust=False).mean()
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    entries = (df["Close"] > hh) & (df["Close"] > ema)
    exits = df["Close"] < ll
    return entries.fillna(False), exits.fillna(False)


def run_portfolio(
    data: dict[str, pd.DataFrame],
    start_date=None,
    end_date=None,
    entry_n: int = ENTRY_N,
    exit_n: int = EXIT_N,
    max_positions: int = MAX_POSITIONS,
    rt_cost: float = RT_COST,
) -> dict:
    """Equal-slot basket: up to max_positions concurrent longs, ~1/max equity each."""
    sig = {}
    for s, df in data.items():
        e, x = entry_exit_signals(df, entry_n=entry_n, exit_n=exit_n)
        sig[s] = {"entry": e, "exit": x, "open": df["Open"], "close": df["Close"], "ema200": df["ema200"]}

    all_dates = sorted(set().union(*[set(df.index) for df in data.values()]))
    all_dates = [
        d
        for d in all_dates
        if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)
    ]

    cash = 1.0
    positions: dict = {}
    equity_curve = []
    trades = []
    slot = 1.0 / max_positions

    for i, dt in enumerate(all_dates):
        equity = cash
        for s, p in positions.items():
            if dt in sig[s]["close"].index:
                equity += p["w"] * (float(sig[s]["close"].loc[dt]) / p["entry_px"])
            else:
                equity += p["w"]

        for s in list(positions):
            if dt in sig[s]["exit"].index and bool(sig[s]["exit"].loc[dt]):
                px = float(sig[s]["close"].loc[dt])
                ret = px / positions[s]["entry_px"] - 1.0 - rt_cost
                cash += positions[s]["w"] * (1.0 + ret)
                trades.append(
                    {
                        "symbol": s,
                        "entry": positions[s]["entry_date"],
                        "exit": dt,
                        "ret": ret,
                    }
                )
                del positions[s]

        equity = cash + sum(
            p["w"]
            * (
                float(sig[s]["close"].loc[dt]) / p["entry_px"]
                if dt in sig[s]["close"].index
                else 1.0
            )
            for s, p in positions.items()
        )
        equity_curve.append((dt, equity, len(positions)))

        if i + 1 >= len(all_dates):
            continue
        nxt = all_dates[i + 1]
        free = max_positions - len(positions)
        if free <= 0 or cash <= 1e-8:
            continue

        ranked = []
        for s in data:
            if s in positions:
                continue
            if dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                continue
            if nxt not in sig[s]["open"].index:
                continue
            strength = float(data[s].loc[dt, "Close"] / data[s].loc[dt, "ema200"] - 1.0)
            ranked.append((strength, s))
        ranked.sort(reverse=True)

        for _, s in ranked[:free]:
            alloc = min(cash, equity * slot)
            if alloc <= 0:
                break
            entry_px = float(sig[s]["open"].loc[nxt])
            cash -= alloc
            positions[s] = {
                "w": alloc * (1 - rt_cost / 2),
                "entry_px": entry_px,
                "entry_date": nxt,
            }

    if all_dates:
        last = all_dates[-1]
        for s, p in list(positions.items()):
            px = (
                float(sig[s]["close"].loc[last])
                if last in sig[s]["close"].index
                else p["entry_px"]
            )
            ret = px / p["entry_px"] - 1.0 - rt_cost
            cash += p["w"] * (1.0 + ret)
            trades.append({"symbol": s, "entry": p["entry_date"], "exit": last, "ret": ret})
            del positions[s]

    eq = pd.Series({d: e for d, e, _ in equity_curve})
    rets = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    tr = np.array([t["ret"] for t in trades], dtype=float) if trades else np.array([])
    wins = tr[tr > 0]
    losses = tr[tr <= 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and -losses.sum() > 0 else 0.0

    return {
        "n_trades": int(len(trades)),
        "win_rate": float((tr > 0).mean()) if len(tr) else 0.0,
        "profit_factor": pf,
        "expectancy": float(tr.mean()) if len(tr) else 0.0,
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0,
        "max_dd": float(dd.min()) if len(dd) else 0.0,
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(252))
        if len(rets) > 2 and rets.std() > 0
        else 0.0,
        "avg_hold_days": float(np.mean([(t["exit"] - t["entry"]).days for t in trades]))
        if trades
        else 0.0,
        "trades": trades,
        "equity": eq,
    }


def main():
    print(f"Fetching {len(UNIVERSE)} symbols...")
    data = {s: clean(fetch_daily(s)) for s in UNIVERSE}
    ref = data["RELIANCE.NS"]
    _, oos_ref = time_split(ref, TRAIN_FRAC)
    oos_start = oos_ref.index[0]

    is_stats = run_portfolio(data, end_date=oos_start - pd.Timedelta(days=1))
    oos_stats = run_portfolio(data, start_date=oos_start)

    def strip(d):
        return {k: v for k, v in d.items() if k not in ("trades", "equity")}

    print("\n=== In-sample (portfolio, max 5 slots) ===")
    print(json.dumps(strip(is_stats), indent=2))
    print("\n=== Out-of-sample (portfolio, max 5 slots) ===")
    print(json.dumps(strip(oos_stats), indent=2))
    print(f"\nOOS start: {oos_start.date()}")
    print(f"Costs: {RT_COST*100:.2f}% round-trip assumed")
    print("Rules: Long close > 55d high & close > EMA200; exit close < 20d low.")

    out = {
        "params": {
            "entry_n": ENTRY_N,
            "exit_n": EXIT_N,
            "ema": EMA_LEN,
            "max_positions": MAX_POSITIONS,
            "rt_cost": RT_COST,
        },
        "universe": UNIVERSE,
        "IS": strip(is_stats),
        "OOS": strip(oos_stats),
        "oos_start": str(oos_start.date()),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "india_donchian_trend_basket_stats.json").write_text(json.dumps(out, indent=2))
    print(f"\nWrote {RESULTS_DIR / 'india_donchian_trend_basket_stats.json'}")


if __name__ == "__main__":
    main()
