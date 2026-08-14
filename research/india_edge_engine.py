"""
India price/volume/structure edge research engine.

Walk-forward + cost-aware backtests on NSE indices/stocks via yfinance.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent / "data"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
DATA_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# India equity round-trip cost assumption (broker+taxes+slippage ballpark)
DEFAULT_RT_COST = 0.0008  # 0.08% round-trip
DEFAULT_SYMBOLS = [
    "^NSEI",
    "^NSEBANK",
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "NIFTYBEES.NS",
    "BANKBEES.NS",
]


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def fetch_daily(symbol: str, start: str = "2008-01-01") -> pd.DataFrame:
    cache = DATA_DIR / f"{symbol.replace('^', '').replace('.', '_')}_1d.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        if len(df) > 200:
            return df
    raw = yf.download(symbol, start=start, interval="1d", progress=False, auto_adjust=True)
    raw = _flatten_columns(raw)
    if raw.empty:
        raise ValueError(f"No data for {symbol}")
    df = raw.rename(columns=str.title)[["Open", "High", "Low", "Close", "Volume"]].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.to_parquet(cache)
    return df


def fetch_hourly(symbol: str) -> pd.DataFrame:
    cache = DATA_DIR / f"{symbol.replace('^', '').replace('.', '_')}_1h.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        if len(df) > 200:
            return df
    raw = yf.download(symbol, period="730d", interval="1h", progress=False, auto_adjust=True)
    raw = _flatten_columns(raw)
    if raw.empty:
        raise ValueError(f"No hourly data for {symbol}")
    df = raw.rename(columns=str.title)[["Open", "High", "Low", "Close", "Volume"]].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
    df.to_parquet(cache)
    return df


def add_structure_features(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o["ret"] = o["Close"].pct_change()
    o["range"] = o["High"] - o["Low"]
    o["body"] = (o["Close"] - o["Open"]).abs()
    o["atr14"] = (o["High"] - o["Low"]).rolling(14).mean()  # simple ATR proxy
    # True ATR
    prev_c = o["Close"].shift(1)
    tr = pd.concat(
        [
            o["High"] - o["Low"],
            (o["High"] - prev_c).abs(),
            (o["Low"] - prev_c).abs(),
        ],
        axis=1,
    ).max(axis=1)
    o["atr"] = tr.rolling(14).mean()
    o["atr_pct"] = o["atr"] / o["Close"]
    o["vol_ma20"] = o["Volume"].rolling(20).mean()
    o["rvol"] = o["Volume"] / o["vol_ma20"]
    o["ema20"] = o["Close"].ewm(span=20, adjust=False).mean()
    o["ema50"] = o["Close"].ewm(span=50, adjust=False).mean()
    o["ema200"] = o["Close"].ewm(span=200, adjust=False).mean()
    o["sma20"] = o["Close"].rolling(20).mean()
    o["hh20"] = o["High"].rolling(20).max().shift(1)
    o["ll20"] = o["Low"].rolling(20).min().shift(1)
    o["hh55"] = o["High"].rolling(55).max().shift(1)
    o["ll55"] = o["Low"].rolling(55).min().shift(1)
    o["hh10"] = o["High"].rolling(10).max().shift(1)
    o["ll10"] = o["Low"].rolling(10).min().shift(1)
    o["prior_high"] = o["High"].shift(1)
    o["prior_low"] = o["Low"].shift(1)
    o["prior_close"] = o["Close"].shift(1)
    o["gap"] = o["Open"] / o["prior_close"] - 1.0
    o["nr7"] = o["range"] == o["range"].rolling(7).min()
    # Inside bar
    o["inside"] = (o["High"] < o["prior_high"]) & (o["Low"] > o["prior_low"])
    # Rolling VWAP proxy (anchored to rolling window)
    tp = (o["High"] + o["Low"] + o["Close"]) / 3.0
    o["vwap20"] = (tp * o["Volume"]).rolling(20).sum() / o["Volume"].rolling(20).sum()
    # Swing highs/lows (5-bar fractal)
    o["swing_high"] = (
        (o["High"].shift(2) > o["High"].shift(4))
        & (o["High"].shift(2) > o["High"].shift(3))
        & (o["High"].shift(2) > o["High"].shift(1))
        & (o["High"].shift(2) > o["High"])
    )
    o["swing_low"] = (
        (o["Low"].shift(2) < o["Low"].shift(4))
        & (o["Low"].shift(2) < o["Low"].shift(3))
        & (o["Low"].shift(2) < o["Low"].shift(1))
        & (o["Low"].shift(2) < o["Low"])
    )
    o["last_swing_high"] = o["High"].shift(2).where(o["swing_high"]).ffill()
    o["last_swing_low"] = o["Low"].shift(2).where(o["swing_low"]).ffill()
    # ATR percentile
    o["atr_rank"] = o["atr"].rolling(100).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x.dropna()) else np.nan,
        raw=False,
    )
    return o


SignalFn = Callable[[pd.DataFrame, dict], pd.Series]


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: int
    entry: float
    exit: float
    bars: int
    ret_gross: float
    ret_net: float


@dataclass
class Stats:
    name: str
    symbol: str
    split: str
    n_trades: int
    win_rate: float
    profit_factor: float
    expectancy: float
    total_return: float
    max_dd: float
    sharpe: float
    sortino: float
    avg_hold: float
    avg_win: float
    avg_loss: float
    params: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        return d


def _empty_stats(name, symbol, split, params) -> Stats:
    return Stats(
        name=name,
        symbol=symbol,
        split=split,
        n_trades=0,
        win_rate=0.0,
        profit_factor=0.0,
        expectancy=0.0,
        total_return=0.0,
        max_dd=0.0,
        sharpe=0.0,
        sortino=0.0,
        avg_hold=0.0,
        avg_win=0.0,
        avg_loss=0.0,
        params=params,
    )


def run_signal_backtest(
    df: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    side: int = 1,
    rt_cost: float = DEFAULT_RT_COST,
    max_hold: int = 40,
) -> List[Trade]:
    """
    Next-bar open entry on signal at bar t close; exit on exit signal or max_hold.
    No overlapping positions.
    """
    entries = entries.fillna(False).astype(bool)
    exits = exits.fillna(False).astype(bool)
    opens = df["Open"].values
    closes = df["Close"].values
    idx = df.index
    n = len(df)
    trades: List[Trade] = []
    i = 1
    while i < n - 1:
        if not entries.iloc[i]:
            i += 1
            continue
        # Enter next open
        entry_i = i + 1
        if entry_i >= n:
            break
        entry_px = opens[entry_i]
        if not np.isfinite(entry_px) or entry_px <= 0:
            i += 1
            continue
        exit_i = None
        for j in range(entry_i, min(n, entry_i + max_hold)):
            # exit signal evaluated on bar j close -> exit next open, or same close for simplicity use close
            if j > entry_i and exits.iloc[j]:
                exit_i = j
                break
        if exit_i is None:
            exit_i = min(n - 1, entry_i + max_hold - 1)
        exit_px = closes[exit_i]
        bars = exit_i - entry_i + 1
        ret_g = side * (exit_px / entry_px - 1.0)
        ret_n = ret_g - rt_cost
        trades.append(
            Trade(
                entry_time=idx[entry_i],
                exit_time=idx[exit_i],
                side=side,
                entry=float(entry_px),
                exit=float(exit_px),
                bars=int(bars),
                ret_gross=float(ret_g),
                ret_net=float(ret_n),
            )
        )
        i = exit_i + 1
    return trades


def compute_stats(
    trades: List[Trade],
    name: str,
    symbol: str,
    split: str,
    params: dict,
    ann_factor: float = 252.0,
) -> Stats:
    if not trades:
        return _empty_stats(name, symbol, split, params)
    rets = np.array([t.ret_net for t in trades], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    win_rate = float((rets > 0).mean())
    gp = wins.sum() if len(wins) else 0.0
    gl = -losses.sum() if len(losses) else 0.0
    pf = float(gp / gl) if gl > 1e-12 else (999.0 if gp > 0 else 0.0)
    expectancy = float(rets.mean())
    # Equity curve compounding trade returns
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak) - 1.0
    max_dd = float(dd.min()) if len(dd) else 0.0
    # Trade-level sharpe annualized roughly by avg hold
    avg_hold = float(np.mean([t.bars for t in trades]))
    trades_per_year = ann_factor / max(avg_hold, 1.0)
    mu = rets.mean()
    sd = rets.std(ddof=1) if len(rets) > 1 else 0.0
    sharpe = float((mu / sd) * np.sqrt(trades_per_year)) if sd > 1e-12 else 0.0
    downside = rets[rets < 0]
    dsd = downside.std(ddof=1) if len(downside) > 1 else 0.0
    sortino = float((mu / dsd) * np.sqrt(trades_per_year)) if dsd > 1e-12 else 0.0
    return Stats(
        name=name,
        symbol=symbol,
        split=split,
        n_trades=int(len(trades)),
        win_rate=win_rate,
        profit_factor=pf,
        expectancy=expectancy,
        total_return=float(eq[-1] - 1.0),
        max_dd=max_dd,
        sharpe=sharpe,
        sortino=sortino,
        avg_hold=avg_hold,
        avg_win=float(wins.mean()) if len(wins) else 0.0,
        avg_loss=float(losses.mean()) if len(losses) else 0.0,
        params=params,
    )


def time_split(
    df: pd.DataFrame, train_frac: float = 0.7
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    cut = int(len(df) * train_frac)
    cut = max(200, min(cut, len(df) - 100))
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def walk_forward_folds(
    df: pd.DataFrame, n_folds: int = 4, train_bars: int = 756, test_bars: int = 252
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    folds = []
    start = 0
    while True:
        tr_end = start + train_bars
        te_end = tr_end + test_bars
        if te_end > len(df):
            break
        folds.append((df.iloc[start:tr_end].copy(), df.iloc[tr_end:te_end].copy()))
        start += test_bars
        if len(folds) >= n_folds:
            break
    return folds


def param_perturb(base: dict, keys: List[str], pct: float = 0.2) -> List[dict]:
    variants = [base]
    for k in keys:
        if k not in base or not isinstance(base[k], (int, float)):
            continue
        v = base[k]
        for mult in (1.0 - pct, 1.0 + pct):
            nv = dict(base)
            if isinstance(v, int):
                nv[k] = max(1, int(round(v * mult)))
            else:
                nv[k] = float(v * mult)
            variants.append(nv)
    # dedupe
    uniq = []
    seen = set()
    for p in variants:
        key = tuple(sorted(p.items()))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def evaluate_strategy(
    name: str,
    symbol: str,
    df: pd.DataFrame,
    signal_builder: Callable[[pd.DataFrame, dict], Tuple[pd.Series, pd.Series, int]],
    params: dict,
    rt_cost: float = DEFAULT_RT_COST,
    max_hold: int = 40,
    train_frac: float = 0.7,
) -> Dict[str, Stats]:
    train, test = time_split(df, train_frac)
    out = {}
    for split, part in [("IS", train), ("OOS", test)]:
        entries, exits, side = signal_builder(part, params)
        trades = run_signal_backtest(part, entries, exits, side=side, rt_cost=rt_cost, max_hold=max_hold)
        out[split] = compute_stats(trades, name, symbol, split, params)
    return out


def robustness_score(oos_stats: List[Stats]) -> Tuple[float, float]:
    """Return (mean expectancy, fraction positive expectancy)."""
    if not oos_stats:
        return 0.0, 0.0
    exps = [s.expectancy for s in oos_stats if s.n_trades >= 5]
    if not exps:
        return 0.0, 0.0
    return float(np.mean(exps)), float(np.mean([e > 0 for e in exps]))
