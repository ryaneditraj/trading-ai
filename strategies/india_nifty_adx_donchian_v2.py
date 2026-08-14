"""
India Nifty+ADX Donchian Trend Basket v2
========================================
Round-2 replacement for the weak 55/20 Donchian basket.

Thesis (price + structure + regime):
  Take stock breakouts only when (1) Nifty is bullish (above EMA200 or
  making a 55-day HH), (2) the stock's ADX is above a floor and rising
  (trend present, not chop), and (3) close > EMA200. Entry = close above
  prior 70-day high. Exit = close below prior 25-day low.

Why this replaces v1:
  v1 OOS PF≈1.17 / +9% / MDD−21% (failed the 2021–22 chop). This sleeve
  fixed 2021–22 (+11% WF chunk), OOS PF≈1.86 / +39% after 0.08% RT,
  stress PF≈1.83 at 0.15% RT, n=74 OOS, params stable ±20%.

Caveat: 2024-09→2026-08 WF chunk still lost (~−7%). Not regime-proof forever.

Usage:
  python strategies/india_nifty_adx_donchian_v2.py
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

# ── Defaults (round-2 selected) ──────────────────────────────────────────────
ENTRY_N = 70
EXIT_N = 25
EMA_LEN = 200
ADX_N = 14
ADX_MIN = 18
ADX_RISE_BARS = 5
NIFTY_EMA = 200
NIFTY_HH = 55
MAX_POSITIONS = 5
RT_COST = 0.0008
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


def add_adx(df: pd.DataFrame, n: int = ADX_N) -> pd.DataFrame:
    o = df.copy()
    up = o["High"].diff()
    down = -o["Low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat(
        [
            o["High"] - o["Low"],
            (o["High"] - o["Close"].shift(1)).abs(),
            (o["Low"] - o["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=o.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=o.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    o["adx"] = dx.ewm(alpha=1 / n, adjust=False).mean()
    o["adx_rising"] = o["adx"] > o["adx"].shift(ADX_RISE_BARS)
    return o


def align_nifty(stock: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    o = stock.copy()
    n = nifty.reindex(o.index, method="ffill")
    o["nifty_close"] = n["Close"]
    o["nifty_ema"] = n["Close"].ewm(span=NIFTY_EMA, adjust=False).mean()
    o["nifty_hh"] = n["High"].rolling(NIFTY_HH).max().shift(1)
    o["nifty_bull"] = (o["nifty_close"] > o["nifty_ema"]) | (o["nifty_close"] > o["nifty_hh"])
    return o


def entry_exit_signals(
    df: pd.DataFrame,
    entry_n: int = ENTRY_N,
    exit_n: int = EXIT_N,
    adx_min: float = ADX_MIN,
) -> tuple[pd.Series, pd.Series]:
    ema = df["Close"].ewm(span=EMA_LEN, adjust=False).mean()
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    regime = (
        (df["Close"] > ema)
        & df["nifty_bull"].fillna(False)
        & (df["adx"] >= adx_min)
        & df["adx_rising"].fillna(False)
    )
    entries = (df["Close"] > hh) & regime
    exits = df["Close"] < ll
    return entries.fillna(False), exits.fillna(False)


def run_portfolio(
    data: dict[str, pd.DataFrame],
    start_date=None,
    end_date=None,
    entry_n: int = ENTRY_N,
    exit_n: int = EXIT_N,
    adx_min: float = ADX_MIN,
    max_positions: int = MAX_POSITIONS,
    rt_cost: float = RT_COST,
) -> dict:
    sig = {}
    for s, df in data.items():
        e, x = entry_exit_signals(df, entry_n=entry_n, exit_n=exit_n, adx_min=adx_min)
        sig[s] = {
            "entry": e,
            "exit": x,
            "open": df["Open"],
            "close": df["Close"],
            "ema200": df["ema200"],
        }

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
    print(f"Fetching Nifty + {len(UNIVERSE)} symbols...")
    nifty = add_adx(clean(fetch_daily("^NSEI")))
    data = {s: align_nifty(add_adx(clean(fetch_daily(s))), nifty) for s in UNIVERSE}
    ref = data["RELIANCE.NS"]
    _, oos_ref = time_split(ref, TRAIN_FRAC)
    oos_start = oos_ref.index[0]

    def strip(d):
        return {k: v for k, v in d.items() if k not in ("trades", "equity")}

    is_stats = run_portfolio(data, end_date=oos_start - pd.Timedelta(days=1))
    oos_stats = run_portfolio(data, start_date=oos_start)
    oos_stress = run_portfolio(data, start_date=oos_start, rt_cost=0.0015)
    full = run_portfolio(data)

    # WF chunks
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_portfolio(data, start_date=dates[i], end_date=dates[i + 1])
        wf.append({"period": f"{dates[i].date()}→{dates[i+1].date()}", **strip(st)})

    print("\n=== In-sample ===")
    print(json.dumps(strip(is_stats), indent=2))
    print("\n=== Out-of-sample ===")
    print(json.dumps(strip(oos_stats), indent=2))
    print("\n=== OOS stress 0.15% RT ===")
    print(json.dumps(strip(oos_stress), indent=2))
    print("\n=== Full period ===")
    print(json.dumps(strip(full), indent=2))
    print("\n=== Walk-forward OOS chunks ===")
    print(json.dumps(wf, indent=2))
    print(f"\nOOS start: {oos_start.date()}")
    print(
        f"Rules: Long close > {ENTRY_N}d high & >EMA200 & Nifty bull "
        f"& ADX>={ADX_MIN} rising; exit close < {EXIT_N}d low."
    )
    print(f"Costs: {RT_COST*100:.2f}% RT (stress 0.15%)")

    out = {
        "params": {
            "entry_n": ENTRY_N,
            "exit_n": EXIT_N,
            "ema": EMA_LEN,
            "adx_min": ADX_MIN,
            "max_positions": MAX_POSITIONS,
            "rt_cost": RT_COST,
        },
        "universe": UNIVERSE,
        "IS": strip(is_stats),
        "OOS": strip(oos_stats),
        "OOS_stress_0.15": strip(oos_stress),
        "FULL": strip(full),
        "wf": wf,
        "oos_start": str(oos_start.date()),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "india_nifty_adx_donchian_v2_stats.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
