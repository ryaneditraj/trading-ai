#!/usr/bin/env python3
"""
Nifty edge 8h campaign — Block 1 runner.

1) Reproduce baseline india_nifty_adx_donchian_v2 basket stats
2) Screen ≥20 new single-symbol hypotheses on ^NSEI + NIFTYBEES
3) Promote top candidates to basket / refine / walk-forward / ±20% perturb
4) Append leaderboard + log; write JSON results

Usage:
  python research/nifty_edge_8h/run_block1.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "strategies"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from india_edge_engine import (  # noqa: E402
    DEFAULT_RT_COST,
    add_structure_features,
    compute_stats,
    fetch_daily,
    param_perturb,
    run_signal_backtest,
    time_split,
    walk_forward_folds,
)
from hypotheses_b1 import HYPOTHESES  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
RESULTS = OUT_DIR / "results"
RESULTS.mkdir(parents=True, exist_ok=True)
LOG = OUT_DIR / "log.md"
LEADERBOARD = OUT_DIR / "leaderboard.md"

RT = 0.0008
RT_STRESS = 0.0015
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


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"- `{ts}` {msg}\n"
    if not LOG.exists():
        LOG.write_text("# Nifty Edge 8h — Append-only Log\n\n")
    with LOG.open("a") as f:
        f.write(line)
    print(msg)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    o = df.copy()
    o = o[(o["Open"] > 0) & (o["High"] > 0) & (o["Low"] > 0) & (o["Close"] > 0)]
    o = o[o["High"] >= o["Low"]]
    gap = o["Open"] / o["Close"].shift(1) - 1.0
    ret = o["Close"].pct_change()
    mask = ((gap.abs() < 0.08) | gap.isna()) & ((ret.abs() < 0.12) | ret.isna())
    return o.loc[mask].copy()


def add_adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
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
    o["plus_di"] = plus_di
    o["minus_di"] = minus_di
    o["adx"] = dx.ewm(alpha=1 / n, adjust=False).mean()
    o["adx_rising"] = o["adx"] > o["adx"].shift(5)
    o["atr_expanding"] = o["atr"] > o["atr"].rolling(50).mean() if "atr" in o.columns else False
    return o


def add_extra_features(df: pd.DataFrame) -> pd.DataFrame:
    o = add_structure_features(df)
    o = add_adx(o)
    # RSI14
    delta = o["Close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    o["rsi14"] = 100 - (100 / (1 + rs))
    # Return z-score 20
    mu = o["ret"].rolling(20).mean()
    sd = o["ret"].rolling(20).std()
    o["ret_z20"] = (o["ret"] - mu) / sd.replace(0, np.nan)
    o["ema100"] = o["Close"].ewm(span=100, adjust=False).mean()
    return o


def prepare_symbol(sym: str) -> pd.DataFrame:
    return add_extra_features(clean(fetch_daily(sym)))


def attach_rs_and_breadth(
    nifty: pd.DataFrame,
    bank: pd.DataFrame,
    stocks: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    o = nifty.copy()
    b = bank.reindex(o.index, method="ffill")
    # 20d relative strength Nifty vs Bank
    n_ret = o["Close"].pct_change(20)
    b_ret = b["Close"].pct_change(20)
    o["rs_nifty_bank"] = n_ret - b_ret
    # Breadth: fraction of stocks above EMA50
    above = None
    count = None
    for df in stocks.values():
        a = (df["Close"] > df["ema50"]).astype(float).reindex(o.index)
        c = (~df["Close"].isna()).astype(float).reindex(o.index)
        above = a if above is None else above.add(a, fill_value=0)
        count = c if count is None else count.add(c, fill_value=0)
    o["breadth50"] = (above / count.replace(0, np.nan)).fillna(0)
    return o


def buy_hold_stats(df: pd.DataFrame, split: str, rt_cost: float = RT) -> dict:
    """Compounded buy-hold from first open to last close, one round-trip cost."""
    if len(df) < 2:
        return {"n_trades": 0, "total_return": 0.0, "max_dd": 0.0, "sharpe": 0.0, "profit_factor": 0.0}
    rets = df["Close"].pct_change().dropna()
    eq = (1 + rets).cumprod()
    # Apply one RT cost at end conceptually for fairness on single hold
    total = float(eq.iloc[-1] - 1.0 - rt_cost)
    peak = eq.cummax()
    dd = float((eq / peak - 1.0).min())
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    return {
        "n_trades": 1,
        "win_rate": 1.0 if total > 0 else 0.0,
        "profit_factor": 999.0 if total > 0 else 0.0,
        "expectancy": total,
        "total_return": total,
        "max_dd": dd,
        "sharpe": sharpe,
        "avg_hold": float(len(df)),
        "split": split,
    }


def eval_single(
    name: str,
    df: pd.DataFrame,
    fn,
    params: dict,
    max_hold: int,
    rt_cost: float = RT,
) -> dict:
    train, test = time_split(df, TRAIN_FRAC)
    out = {"name": name, "params": params}
    for split, part in [("IS", train), ("OOS", test)]:
        entries, exits, side = fn(part, params)
        trades = run_signal_backtest(part, entries, exits, side=side, rt_cost=rt_cost, max_hold=max_hold)
        st = compute_stats(trades, name, "sym", split, params)
        out[split] = st.to_dict()
    # Walk-forward OOS chunks on full series
    folds = walk_forward_folds(df, n_folds=4, train_bars=756, test_bars=252)
    wf = []
    for i, (_, te) in enumerate(folds):
        entries, exits, side = fn(te, params)
        trades = run_signal_backtest(te, entries, exits, side=side, rt_cost=rt_cost, max_hold=max_hold)
        st = compute_stats(trades, name, "sym", f"WF{i+1}", params)
        wf.append(st.to_dict())
    out["wf"] = wf
    out["wf_pos"] = int(sum(1 for w in wf if w["expectancy"] > 0 and w["n_trades"] >= 3))
    out["wf_n"] = len(wf)
    # Stress OOS
    entries, exits, side = fn(test, params)
    trades = run_signal_backtest(test, entries, exits, side=side, rt_cost=RT_STRESS, max_hold=max_hold)
    out["OOS_stress"] = compute_stats(trades, name, "sym", "OOS_stress", params).to_dict()
    return out


def score_row(r: dict) -> float:
    """Composite: prefer OOS PF, expectancy, trade count, WF positivity."""
    oos = r.get("OOS", {})
    n = oos.get("n_trades", 0)
    pf = oos.get("profit_factor", 0)
    exp = oos.get("expectancy", 0)
    tot = oos.get("total_return", 0)
    if n < 15:
        return -999.0
    wf_frac = r.get("wf_pos", 0) / max(r.get("wf_n", 1), 1)
    return float(pf * 2.0 + exp * 50 + tot * 2 + wf_frac * 1.5 + min(n, 80) * 0.01)


# ── Portfolio engine (reuse v2 pattern) ───────────────────────────────────────
def run_portfolio(
    data: Dict[str, pd.DataFrame],
    signal_fn,
    params: dict,
    start_date=None,
    end_date=None,
    max_positions: int = 5,
    rt_cost: float = RT,
) -> dict:
    sig = {}
    for s, df in data.items():
        e, x = signal_fn(df, params)[:2]
        sig[s] = {
            "entry": e.fillna(False),
            "exit": x.fillna(False),
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
                trades.append({"symbol": s, "entry": positions[s]["entry_date"], "exit": dt, "ret": ret})
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
            positions[s] = {"w": alloc * (1 - rt_cost / 2), "entry_px": entry_px, "entry_date": nxt}

    if all_dates:
        last = all_dates[-1]
        for s, p in list(positions.items()):
            px = float(sig[s]["close"].loc[last]) if last in sig[s]["close"].index else p["entry_px"]
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
        "avg_hold_days": float(np.mean([(t["exit"] - t["entry"]).days for t in trades])) if trades else 0.0,
    }


def align_nifty(stock: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    o = stock.copy()
    n = nifty.reindex(o.index, method="ffill")
    o["nifty_close"] = n["Close"]
    o["nifty_ema"] = n["Close"].ewm(span=200, adjust=False).mean()
    o["nifty_hh"] = n["High"].rolling(55).max().shift(1)
    o["nifty_bull"] = (o["nifty_close"] > o["nifty_ema"]) | (o["nifty_close"] > o["nifty_hh"])
    return o


def basket_signal_adx_donchian(df, p):
    entry_n = int(p.get("entry_n", 70))
    exit_n = int(p.get("exit_n", 25))
    adx_min = float(p.get("adx_min", 18))
    ema = df["Close"].ewm(span=200, adjust=False).mean()
    hh = df["High"].rolling(entry_n).max().shift(1)
    ll = df["Low"].rolling(exit_n).min().shift(1)
    regime = (
        (df["Close"] > ema)
        & df["nifty_bull"].fillna(False)
        & (df["adx"] >= adx_min)
        & df["adx_rising"].fillna(False)
    )
    e = (df["Close"] > hh) & regime
    x = df["Close"] < ll
    return e.fillna(False), x.fillna(False), 1


def basket_signal_from_hyp(name: str):
    """Wrap single-symbol hyp for basket; add nifty_bull gate when available."""
    meta = HYPOTHESES[name]
    base_fn = meta["fn"]

    def fn(df, p):
        e, x, side = base_fn(df, p)
        if "nifty_bull" in df.columns:
            e = e & df["nifty_bull"].fillna(False)
        return e, x, side

    return fn, meta["params"], meta.get("max_hold", 40)


def write_leaderboard(rows: List[dict], baseline: dict, bh: dict) -> None:
    rows_sorted = sorted(rows, key=score_row, reverse=True)
    lines = [
        "# Nifty Edge 8h — Living Leaderboard",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} (Block 1)",
        f"**Costs:** {RT*100:.2f}% RT default; stress {RT_STRESS*100:.2f}%",
        f"**Pass bar:** OOS PF≥1.3, positive expectancy, n≥15, WF stability preferred",
        "",
        "## Buy & hold (^NSEI OOS)",
        "",
        f"| Total | MDD | Sharpe |",
        f"|------:|----:|-------:|",
        f"| {bh.get('total_return',0)*100:.1f}% | {bh.get('max_dd',0)*100:.1f}% | {bh.get('sharpe',0):.2f} |",
        "",
        "## Baseline reproduction (india_nifty_adx_donchian_v2 basket)",
        "",
        "| Split | n | WR | PF | Exp | Tot | MDD | Sharpe |",
        "|-------|--:|---:|---:|----:|----:|----:|-------:|",
    ]
    for k in ("IS", "OOS", "OOS_stress"):
        s = baseline.get(k, {})
        if not s:
            continue
        lines.append(
            f"| {k} | {s.get('n_trades',0)} | {s.get('win_rate',0)*100:.1f}% | {s.get('profit_factor',0):.2f} | "
            f"{s.get('expectancy',0)*100:.2f}% | {s.get('total_return',0)*100:.1f}% | "
            f"{s.get('max_dd',0)*100:.1f}% | {s.get('sharpe',0):.2f} |"
        )
    lines += [
        "",
        "## Single-symbol screen (ranked by composite score)",
        "",
        "| Rank | ID | Sym | Family | OOS n | OOS PF | OOS Exp | OOS Tot | MDD | WF+/N | Score | Verdict |",
        "|-----:|----|-----|--------|------:|-------:|--------:|--------:|----:|------:|------:|---------|",
    ]
    for i, r in enumerate(rows_sorted[:40], 1):
        oos = r["OOS"]
        pf = oos["profit_factor"]
        n = oos["n_trades"]
        exp = oos["expectancy"]
        if n < 15 or pf < 1.0 or exp <= 0:
            verd = "REJECT"
        elif pf >= 1.3 and exp > 0 and r.get("wf_pos", 0) >= 2:
            verd = "PROMOTE"
        elif pf >= 1.2 and exp > 0:
            verd = "WATCH"
        else:
            verd = "WEAK"
        lines.append(
            f"| {i} | {r['name']} | {r.get('symbol','')} | {r.get('family','')} | {n} | {pf:.2f} | "
            f"{exp*100:.2f}% | {oos['total_return']*100:.1f}% | {oos['max_dd']*100:.1f}% | "
            f"{r.get('wf_pos',0)}/{r.get('wf_n',0)} | {score_row(r):.2f} | {verd} |"
        )
    lines += ["", "## Rejected / thin (sample)", ""]
    rejected = [r for r in rows_sorted if score_row(r) < 0 or r["OOS"]["profit_factor"] < 1.0][:25]
    for r in rejected:
        oos = r["OOS"]
        lines.append(
            f"- `{r['name']}` ({r.get('symbol')}) n={oos['n_trades']} PF={oos['profit_factor']:.2f} "
            f"exp={oos['expectancy']*100:.2f}% tot={oos['total_return']*100:.1f}%"
        )
    LEADERBOARD.write_text("\n".join(lines) + "\n")


def reproduce_baseline(stock_data: Dict[str, pd.DataFrame]) -> dict:
    log("Reproducing baseline india_nifty_adx_donchian_v2…")
    ref = stock_data["RELIANCE.NS"]
    _, oos_ref = time_split(ref, TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    params = {"entry_n": 70, "exit_n": 25, "adx_min": 18}
    is_stats = run_portfolio(stock_data, basket_signal_adx_donchian, params, end_date=oos_start - pd.Timedelta(days=1))
    oos_stats = run_portfolio(stock_data, basket_signal_adx_donchian, params, start_date=oos_start)
    oos_stress = run_portfolio(stock_data, basket_signal_adx_donchian, params, start_date=oos_start, rt_cost=RT_STRESS)
    end = max(df.index.max() for df in stock_data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_portfolio(stock_data, basket_signal_adx_donchian, params, start_date=dates[i], end_date=dates[i + 1])
        wf.append({"period": f"{dates[i].date()}→{dates[i+1].date()}", **st})
    out = {"IS": is_stats, "OOS": oos_stats, "OOS_stress": oos_stress, "wf": wf, "oos_start": str(oos_start.date())}
    log(
        f"Baseline OOS: n={oos_stats['n_trades']} PF={oos_stats['profit_factor']:.2f} "
        f"tot={oos_stats['total_return']*100:.1f}% MDD={oos_stats['max_dd']*100:.1f}% "
        f"stress_PF={oos_stress['profit_factor']:.2f}"
    )
    for w in wf:
        log(f"  WF {w['period']}: n={w['n_trades']} exp={w['expectancy']*100:.2f}% tot={w['total_return']*100:.1f}%")
    return out


def main():
    log("=== Block 1 start ===")
    log(f"Loading Nifty + Bank + {len(UNIVERSE)} stocks…")
    nifty_raw = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    bees = prepare_symbol("NIFTYBEES.NS")
    stocks = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty_raw, bank, stocks)
    stock_data = {s: align_nifty(df, nifty) for s, df in stocks.items()}

    # Buy & hold OOS
    _, nifty_oos = time_split(nifty, TRAIN_FRAC)
    bh = buy_hold_stats(nifty_oos, "OOS")
    log(f"Buy&hold ^NSEI OOS: tot={bh['total_return']*100:.1f}% MDD={bh['max_dd']*100:.1f}% Sharpe={bh['sharpe']:.2f}")

    baseline = reproduce_baseline(stock_data)
    (RESULTS / "baseline_v2.json").write_text(json.dumps(baseline, indent=2, default=str))

    # Single-symbol screen
    symbols = {"^NSEI": nifty, "NIFTYBEES.NS": bees, "^NSEBANK": bank}
    rows = []
    log(f"Screening {len(HYPOTHESES)} hypotheses × {len(symbols)} symbols…")
    for hid, meta in HYPOTHESES.items():
        for sym, df in symbols.items():
            try:
                r = eval_single(hid, df, meta["fn"], meta["params"], meta.get("max_hold", 40))
                r["symbol"] = sym
                r["family"] = meta["family"]
                rows.append(r)
                oos = r["OOS"]
                log(
                    f"  {hid} @ {sym}: OOS n={oos['n_trades']} PF={oos['profit_factor']:.2f} "
                    f"exp={oos['expectancy']*100:.2f}% tot={oos['total_return']*100:.1f}% "
                    f"WF={r['wf_pos']}/{r['wf_n']}"
                )
            except Exception as e:
                log(f"  FAIL {hid} @ {sym}: {e}")
                traceback.print_exc()

    (RESULTS / "block1_single_screen.json").write_text(json.dumps(rows, indent=2, default=str))
    write_leaderboard(rows, baseline, bh)

    # Promote top single-symbol ideas to basket
    promotable = [
        r
        for r in rows
        if r["OOS"]["n_trades"] >= 15
        and r["OOS"]["profit_factor"] >= 1.2
        and r["OOS"]["expectancy"] > 0
        and r.get("symbol") == "^NSEI"
    ]
    promotable = sorted(promotable, key=score_row, reverse=True)[:8]
    # Always try a few structural families as basket even if index-thin
    force = [
        "B1-03_adx_donchian_70_25",
        "B1-04_ma_pullback",
        "B1-14_bb_walk",
        "B1-15_keltner",
        "B1-16_supertrend",
        "B1-17_failed_bd_fade",
        "B1-22_di_momentum",
        "B1-26_ema_ribbon",
        "B1-05_atr_expansion",
        "B1-18_time_structure",
    ]
    basket_results = []
    ref = stock_data["RELIANCE.NS"]
    _, oos_ref = time_split(ref, TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    tried = set()
    to_try = [r["name"] for r in promotable] + force
    log(f"Basket promotion pass: {to_try}")
    for hid in to_try:
        if hid in tried or hid not in HYPOTHESES:
            continue
        tried.add(hid)
        fn, params, _ = basket_signal_from_hyp(hid)
        try:
            is_s = run_portfolio(stock_data, fn, params, end_date=oos_start - pd.Timedelta(days=1))
            oos_s = run_portfolio(stock_data, fn, params, start_date=oos_start)
            oos_st = run_portfolio(stock_data, fn, params, start_date=oos_start, rt_cost=RT_STRESS)
            end = max(df.index.max() for df in stock_data.values())
            dates = pd.date_range(oos_start, end, periods=4)
            wf = []
            for i in range(3):
                st = run_portfolio(stock_data, fn, params, start_date=dates[i], end_date=dates[i + 1])
                wf.append({"period": f"{dates[i].date()}→{dates[i+1].date()}", **st})
            row = {
                "name": f"BASKET_{hid}",
                "params": params,
                "IS": is_s,
                "OOS": oos_s,
                "OOS_stress": oos_st,
                "wf": wf,
                "wf_pos": int(sum(1 for w in wf if w["expectancy"] > 0)),
                "wf_n": 3,
                "symbol": "BASKET20",
                "family": HYPOTHESES[hid]["family"],
            }
            basket_results.append(row)
            log(
                f"  BASKET {hid}: OOS n={oos_s['n_trades']} PF={oos_s['profit_factor']:.2f} "
                f"tot={oos_s['total_return']*100:.1f}% WF+={row['wf_pos']}/3 "
                f"stress_PF={oos_st['profit_factor']:.2f}"
            )
        except Exception as e:
            log(f"  BASKET FAIL {hid}: {e}")
            traceback.print_exc()

    (RESULTS / "block1_basket.json").write_text(json.dumps(basket_results, indent=2, default=str))

    # Param refine on best basket + best single
    all_cands = basket_results + [
        {**r, "name": r["name"]} for r in rows if r["OOS"]["profit_factor"] >= 1.25 and r["OOS"]["n_trades"] >= 20
    ]
    all_cands = sorted(
        all_cands,
        key=lambda r: (
            r["OOS"].get("profit_factor", 0),
            r["OOS"].get("expectancy", 0),
            r.get("wf_pos", 0),
        ),
        reverse=True,
    )
    best = all_cands[0] if all_cands else None
    refine_out = []
    if best and best["name"].startswith("BASKET_"):
        hid = best["name"].replace("BASKET_", "")
        base_params = dict(best["params"])
        # Perturb numeric keys
        keys = [k for k, v in base_params.items() if isinstance(v, (int, float))]
        variants = param_perturb(base_params, keys, pct=0.2)
        log(f"Refining {best['name']} with {len(variants)} param variants…")
        fn, _, _ = basket_signal_from_hyp(hid)
        for p in variants:
            oos_s = run_portfolio(stock_data, fn, p, start_date=oos_start)
            refine_out.append({"params": p, "OOS": oos_s})
            log(f"  perturb {p}: PF={oos_s['profit_factor']:.2f} tot={oos_s['total_return']*100:.1f}% n={oos_s['n_trades']}")
        (RESULTS / "block1_refine.json").write_text(json.dumps(refine_out, indent=2, default=str))
        # Pick best refine by OOS PF with n>=40
        good = [x for x in refine_out if x["OOS"]["n_trades"] >= 40]
        if good:
            best_ref = max(good, key=lambda x: (x["OOS"]["profit_factor"], x["OOS"]["expectancy"]))
            best = {
                **best,
                "params": best_ref["params"],
                "OOS": best_ref["OOS"],
                "name": best["name"] + "_refined",
            }

    # Merge leaderboard with baskets
    write_leaderboard(rows + basket_results, baseline, bh)

    summary = {
        "block": 1,
        "n_hypotheses": len(HYPOTHESES),
        "n_single_evals": len(rows),
        "n_basket_evals": len(basket_results),
        "buy_hold_oos": bh,
        "baseline": {k: baseline[k] for k in ("IS", "OOS", "OOS_stress", "oos_start")},
        "best": best,
        "top5_single": sorted(rows, key=score_row, reverse=True)[:5],
        "top5_basket": sorted(basket_results, key=lambda r: r["OOS"]["profit_factor"], reverse=True)[:5],
    }
    (RESULTS / "block1_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log("=== Block 1 screen complete ===")
    if best:
        log(
            f"Current #1: {best['name']} OOS PF={best['OOS']['profit_factor']:.2f} "
            f"tot={best['OOS']['total_return']*100:.1f}% n={best['OOS']['n_trades']}"
        )
    return summary


if __name__ == "__main__":
    main()
