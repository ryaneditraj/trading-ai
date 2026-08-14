#!/usr/bin/env python3
"""
Block 2 — beat / stress-test Block-1 #1 (ST mult=3.6 + Nifty + EMA200).

1) Reproduce #1 exactly; note drift
2) Bootstrap / holdout / CI on mult=3.6 vs sleeve 3.0–3.8
3) ≥15 NEW variants (breadth×ST, kill-switch, ATR+ST exit, RS, heat, delay, RVOL, hybrid)
4) Update leaderboard + append log; overwrite best ONLY if clearly better
5) Save runners-up as nifty_edge_r4+.py

Usage:
  python research/nifty_edge_8h/run_block2.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from india_edge_engine import time_split  # noqa: E402
from run_block1 import (  # noqa: E402
    LEADERBOARD,
    LOG,
    RESULTS,
    RT,
    RT_STRESS,
    TRAIN_FRAC,
    UNIVERSE,
    align_nifty,
    attach_rs_and_breadth,
    buy_hold_stats,
    log,
    prepare_symbol,
    run_portfolio,
)
from run_block1b import (  # noqa: E402
    portfolio_eval,
    sig_atr_exp,
    sig_supertrend,
    supertrend_bands,
)

OUT_STRAT = ROOT / "strategies"
OUT_PINE = ROOT / "pinescript"
DEADLINE_FILE = Path(__file__).resolve().parent / "deadline_unix.txt"

# Reference #1 from Block 1 (for drift check)
REF_OOS = {
    "n_trades": 75,
    "profit_factor": 3.90,
    "expectancy": 0.0553,
    "total_return": 1.102,
    "max_dd": -0.148,
    "sharpe": 1.10,
}


def past_deadline() -> bool:
    if not DEADLINE_FILE.exists():
        return False
    raw = DEADLINE_FILE.read_text().strip().splitlines()[0]
    try:
        return int(datetime.now(timezone.utc).timestamp()) > int(raw.strip())
    except ValueError:
        return False


def attach_market_to_stocks(
    stocks: Dict[str, pd.DataFrame],
    nifty: pd.DataFrame,
    bank: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """Align nifty bull, breadth, bank RS onto each stock frame (no look-ahead)."""
    out = {}
    n = nifty
    b = bank.reindex(n.index, method="ffill")
    bank_ret20 = b["Close"].pct_change(20)
    nifty_ret20 = n["Close"].pct_change(20)
    for s, df in stocks.items():
        o = align_nifty(df, nifty)
        ni = n.reindex(o.index, method="ffill")
        bi = b.reindex(o.index, method="ffill")
        o["breadth50"] = ni["breadth50"] if "breadth50" in ni.columns else 0.0
        o["rs_nifty_bank"] = ni["rs_nifty_bank"] if "rs_nifty_bank" in ni.columns else 0.0
        # Stock RS vs Bank / Nifty (20d) — lag-safe: uses completed 20d returns
        s_ret20 = o["Close"].pct_change(20)
        o["rs_vs_bank"] = s_ret20 - bi["Close"].pct_change(20)
        o["rs_vs_nifty"] = s_ret20 - ni["Close"].pct_change(20)
        o["nifty_ema50"] = ni["Close"].ewm(span=50, adjust=False).mean()
        o["nifty_above_ema50"] = o["nifty_close"] > o["nifty_ema50"]
        # ATR expansion flag
        o["atr_exp_flag"] = o["atr"] > o["atr"].rolling(20).mean() * 1.2
        out[s] = o
    return out


# ── Extended portfolio (delay / heat / trade list) ────────────────────────────
def run_portfolio_ext(
    data: Dict[str, pd.DataFrame],
    signal_fn,
    params: dict,
    start_date=None,
    end_date=None,
    max_positions: int = 5,
    rt_cost: float = RT,
    entry_delay: int = 0,
    heat_cap: Optional[float] = None,
    return_trades: bool = False,
) -> dict:
    """
    Like run_portfolio but supports:
      - entry_delay: wait N bars after signal before next-open entry
      - heat_cap: max fraction of equity in positions (default = max_positions * slot)
      - return_trades: include trade list for bootstrap
    """
    delay = int(params.get("entry_delay", entry_delay))
    max_pos = int(params.get("max_positions", max_positions))
    heat = params.get("heat_cap", heat_cap)
    if heat is None:
        heat = 1.0
    heat = float(heat)

    sig = {}
    pending: Dict[str, int] = {}  # symbol -> bars left before eligible
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
    slot = 1.0 / max_pos
    # delayed candidates: symbol -> first eligible date index
    delayed: Dict[str, int] = {}

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
        free = max_pos - len(positions)
        if free <= 0 or cash <= 1e-8:
            # Still age/expire delay queue so we don't carry stale signals
            if delay > 0:
                for s, elig_i in list(delayed.items()):
                    if i > elig_i + 5:  # expire after a few days unfilled
                        del delayed[s]
            continue

        ranked = []
        if delay <= 0:
            # Exact Block-1 behavior: same-bar signal → next open only
            for s in data:
                if s in positions:
                    continue
                if dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                    continue
                if nxt not in sig[s]["open"].index:
                    continue
                if dt not in data[s].index:
                    continue
                strength = float(data[s].loc[dt, "Close"] / data[s].loc[dt, "ema200"] - 1.0)
                ranked.append((strength, s))
        else:
            # Register new signals into delay queue
            for s in data:
                if s in positions or s in delayed:
                    continue
                if dt not in sig[s]["entry"].index or not bool(sig[s]["entry"].loc[dt]):
                    continue
                delayed[s] = i + delay

            for s, elig_i in list(delayed.items()):
                if s in positions:
                    del delayed[s]
                    continue
                if i < elig_i:
                    continue
                if dt not in data[s].index or dt not in sig[s]["exit"].index:
                    continue
                if bool(sig[s]["exit"].loc[dt]):
                    del delayed[s]
                    continue
                if i > elig_i + 5:
                    del delayed[s]
                    continue
                if nxt not in sig[s]["open"].index:
                    continue
                strength = float(data[s].loc[dt, "Close"] / data[s].loc[dt, "ema200"] - 1.0)
                ranked.append((strength, s))
        ranked.sort(reverse=True)

        invested = equity - cash
        for _, s in ranked[:free]:
            # heat: don't exceed heat_cap of equity in positions
            if invested / max(equity, 1e-12) >= heat - 1e-9:
                break
            alloc = min(cash, equity * slot, equity * heat - invested)
            if alloc <= 1e-8:
                break
            entry_px = float(sig[s]["open"].loc[nxt])
            cash -= alloc
            invested += alloc
            positions[s] = {
                "w": alloc * (1 - rt_cost / 2),
                "entry_px": entry_px,
                "entry_date": nxt,
            }
            delayed.pop(s, None)

    if all_dates:
        last = all_dates[-1]
        for s, p in list(positions.items()):
            px = float(sig[s]["close"].loc[last]) if last in sig[s]["close"].index else p["entry_px"]
            ret = px / p["entry_px"] - 1.0 - rt_cost
            cash += p["w"] * (1.0 + ret)
            trades.append({"symbol": s, "entry": p["entry_date"], "exit": last, "ret": ret})

    eq = pd.Series({d: e for d, e, _ in equity_curve})
    rets = eq.pct_change().dropna()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    tr = np.array([t["ret"] for t in trades], dtype=float) if trades else np.array([])
    wins = tr[tr > 0]
    losses = tr[tr <= 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) and -losses.sum() > 0 else 0.0
    out = {
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
    if return_trades:
        out["trades"] = trades
        out["trade_rets"] = tr.tolist()
        out["equity"] = eq
    return out


def collect_trade_rets(
    data: Dict[str, pd.DataFrame],
    signal_fn,
    params: dict,
    start_date=None,
    end_date=None,
    max_positions: int = 5,
    rt_cost: float = RT,
) -> List[float]:
    """Same fill rules as run_portfolio; return list of trade returns for bootstrap."""
    # Reuse portfolio_ext with delay=0 / full heat — after calendar fix
    out = run_portfolio_ext(
        data,
        signal_fn,
        params,
        start_date=start_date,
        end_date=end_date,
        max_positions=max_positions,
        rt_cost=rt_cost,
        entry_delay=0,
        heat_cap=1.0,
        return_trades=True,
    )
    return list(out.get("trade_rets", []))


def portfolio_eval_ext(name, data, fn, params, oos_start, **kw) -> dict:
    is_s = run_portfolio_ext(data, fn, params, end_date=oos_start - pd.Timedelta(days=1), **kw)
    oos_s = run_portfolio_ext(data, fn, params, start_date=oos_start, **kw)
    oos_st = run_portfolio_ext(data, fn, params, start_date=oos_start, rt_cost=RT_STRESS, **kw)
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    wf = []
    for i in range(3):
        st = run_portfolio_ext(data, fn, params, start_date=dates[i], end_date=dates[i + 1], **kw)
        wf.append({"period": f"{dates[i].date()}→{dates[i+1].date()}", **{k: st[k] for k in st if k not in ("trades", "trade_rets")}})
    return {
        "name": name,
        "params": params,
        "IS": is_s if "trades" not in is_s else {k: v for k, v in is_s.items() if k not in ("trades", "trade_rets")},
        "OOS": {k: v for k, v in oos_s.items() if k not in ("trades", "trade_rets")},
        "OOS_stress": {k: v for k, v in oos_st.items() if k not in ("trades", "trade_rets")},
        "wf": wf,
        "wf_pos": int(sum(1 for w in wf if w["expectancy"] > 0)),
        "wf_n": 3,
        "symbol": "BASKET20",
        "last_wf_tot": wf[-1]["total_return"] if wf else 0.0,
    }


# ── Signal variants ───────────────────────────────────────────────────────────
def sig_st_breadth(df, p):
    e, x, side = sig_supertrend(df, p)
    thr = float(p.get("breadth_min", 0.65))
    if "breadth50" in df.columns:
        e = e & (df["breadth50"] >= thr)
    return e, x, side


def sig_st_kill_breadth(df, p):
    """Soft kill-switch: no new entries when breadth < floor (don't force exits)."""
    e, x, side = sig_supertrend(df, p)
    floor = float(p.get("breadth_floor", 0.40))
    if "breadth50" in df.columns:
        e = e & (df["breadth50"] >= floor)
    return e, x, side


def sig_st_kill_nifty_ema50(df, p):
    """Kill entries when Nifty below EMA50 (softer than EMA200 bull gate alone)."""
    e, x, side = sig_supertrend(df, p)
    if "nifty_above_ema50" in df.columns:
        e = e & df["nifty_above_ema50"].fillna(False)
    return e, x, side


def sig_atr_entry_st_exit(df, p):
    """ATR expansion Donchian-style entry + Supertrend exit."""
    look = int(p.get("lookback", 25))
    ratio = float(p.get("atr_ratio", 0.2))
    mult = float(p.get("mult", 3.6))
    atr_ma = df["atr"].rolling(look).mean()
    expanding = df["atr"] > atr_ma * (1.0 + ratio)
    hh = df["High"].rolling(20).max().shift(1)
    regime = df["Close"] > df["ema200"]
    if p.get("use_nifty", True) and "nifty_bull" in df.columns:
        regime = regime & df["nifty_bull"].fillna(False)
    e = expanding & (df["Close"] > hh) & regime
    st = supertrend_bands(df, mult)
    x = df["Close"] < st
    return e.fillna(False), x.fillna(False), 1


def sig_st_rs_bank(df, p):
    e, x, side = sig_supertrend(df, p)
    min_rs = float(p.get("min_rs", 0.0))
    if "rs_vs_bank" in df.columns:
        e = e & (df["rs_vs_bank"] > min_rs)
    return e, x, side


def sig_st_rs_nifty(df, p):
    e, x, side = sig_supertrend(df, p)
    min_rs = float(p.get("min_rs", 0.0))
    if "rs_vs_nifty" in df.columns:
        e = e & (df["rs_vs_nifty"] > min_rs)
    return e, x, side


def sig_st_rvol(df, p):
    e, x, side = sig_supertrend(df, p)
    min_rvol = float(p.get("min_rvol", 1.2))
    if "rvol" in df.columns:
        e = e & (df["rvol"] >= min_rvol)
    return e, x, side


def sig_st_hybrid_breadth_rvol(df, p):
    e, x, side = sig_supertrend(df, p)
    thr = float(p.get("breadth_min", 0.55))
    min_rvol = float(p.get("min_rvol", 1.1))
    if "breadth50" in df.columns:
        e = e & (df["breadth50"] >= thr)
    if "rvol" in df.columns:
        e = e & (df["rvol"] >= min_rvol)
    return e, x, side


def sig_st_atr_expand(df, p):
    e, x, side = sig_supertrend(df, p)
    if "atr_exp_flag" in df.columns:
        e = e & df["atr_exp_flag"].fillna(False)
    return e, x, side


def sig_st_delay_base(df, p):
    """Base ST; delay handled in portfolio_ext via params['entry_delay']."""
    return sig_supertrend(df, p)


def pf_from_rets(rets: np.ndarray) -> float:
    if len(rets) == 0:
        return 0.0
    wins = rets[rets > 0].sum()
    losses = -rets[rets <= 0].sum()
    if losses <= 0:
        return 999.0 if wins > 0 else 0.0
    return float(wins / losses)


def bootstrap_pf(trade_rets: List[float], n_boot: int = 2000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    rets = np.asarray(trade_rets, dtype=float)
    if len(rets) < 10:
        return {"n": len(rets), "pf": pf_from_rets(rets), "ci_lo": None, "ci_hi": None, "mean_pf": None}
    boots = []
    for _ in range(n_boot):
        sample = rng.choice(rets, size=len(rets), replace=True)
        boots.append(pf_from_rets(sample))
    boots = np.array(boots)
    return {
        "n": int(len(rets)),
        "pf": pf_from_rets(rets),
        "mean_pf": float(boots.mean()),
        "ci_lo": float(np.percentile(boots, 2.5)),
        "ci_hi": float(np.percentile(boots, 97.5)),
        "p5": float(np.percentile(boots, 5)),
        "p50": float(np.percentile(boots, 50)),
        "p95": float(np.percentile(boots, 95)),
    }


def clearly_better(challenger: dict, champion: dict) -> bool:
    """
    Promote only if clearly better on OOS — not vanity PF spikes.
    Require: WF≥ champion WF, last WF not worse by much, and
    (PF≥champ OR tot≥champ) with no large MDD blowup, n≥40 preferred.
    """
    c, h = challenger["OOS"], champion["OOS"]
    if c["n_trades"] < 30:
        return False
    if challenger.get("wf_pos", 0) < champion.get("wf_pos", 0):
        return False
    # Don't kill 2024-26: last WF must stay non-negative if champ was positive
    c_last = challenger.get("last_wf_tot", 0)
    h_last = champion.get("last_wf_tot", 0)
    if h_last > 0 and c_last < -0.02:
        return False
    if c["max_dd"] < h["max_dd"] - 0.05:  # much worse DD
        return False
    # Composite: need meaningful improvement on PF+tot or tot+sharpe with solid PF
    pf_ok = c["profit_factor"] >= h["profit_factor"] * 0.95 and c["total_return"] > h["total_return"] * 1.05
    tot_ok = c["total_return"] >= h["total_return"] and c["profit_factor"] > h["profit_factor"] * 1.05
    robust_ok = (
        c["profit_factor"] >= 2.0
        and c["total_return"] >= h["total_return"] * 0.95
        and challenger.get("wf_pos", 0) == 3
        and c["n_trades"] >= h["n_trades"] * 1.2
        and c["profit_factor"] >= h["profit_factor"] * 0.85
        and challenger["OOS_stress"]["profit_factor"] >= champion["OOS_stress"]["profit_factor"] * 0.9
    )
    # Vanity guard: tiny n with huge PF vs champ does not win
    if c["n_trades"] < 50 and c["profit_factor"] > h["profit_factor"] and c["total_return"] < h["total_return"] * 0.9:
        return False
    return bool(pf_ok or tot_ok or (robust_ok and c["sharpe"] >= h["sharpe"]))


def write_runner_up(idx: int, row: dict, fn_import: str) -> Path:
    path = OUT_STRAT / f"nifty_edge_r{idx}.py"
    oos = row["OOS"]
    code = f'''"""
Runner-up r{idx}: {row["name"]}
Params: {json.dumps(row["params"])}
OOS n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} WF+={row.get("wf_pos")}/{row.get("wf_n")}
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks, run_portfolio_ext, {fn_import}

PARAMS = {json.dumps(row["params"], indent=2)}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    oos = run_portfolio_ext(data, {fn_import}, PARAMS, start_date=oos_start)
    print(json.dumps({{"name": {json.dumps(row["name"])}, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
    path.write_text(code)
    return path


def append_leaderboard_block2(
    champ: dict,
    rows: List[dict],
    boot: dict,
    sleeve: List[dict],
    promoted: bool,
    bh: dict,
) -> None:
    """Append Block 2 section; keep prior content."""
    prev = LEADERBOARD.read_text() if LEADERBOARD.exists() else ""
    # Strip trailing old Block2 if re-run
    marker = "\n## Block 2"
    if marker in prev:
        prev = prev.split(marker)[0].rstrip() + "\n"

    o = champ["OOS"]
    lines = [
        "",
        "## Block 2 — Reproduce, bootstrap CI, beat attempt",
        "",
        f"**Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**#1 still leads:** {'YES' if not promoted else 'NO — new champion promoted'}",
        "",
        "### Reproduced #1 (ST_m3.6_n1_e1)",
        "",
        f"| Metric | Block1 ref | Block2 | Drift |",
        f"|--------|----------:|-------:|------:|",
        f"| n | {REF_OOS['n_trades']} | {o['n_trades']} | {o['n_trades']-REF_OOS['n_trades']:+d} |",
        f"| PF | {REF_OOS['profit_factor']:.2f} | {o['profit_factor']:.2f} | {o['profit_factor']-REF_OOS['profit_factor']:+.2f} |",
        f"| Tot | {REF_OOS['total_return']*100:.1f}% | {o['total_return']*100:.1f}% | {(o['total_return']-REF_OOS['total_return'])*100:+.1f}pp |",
        f"| MDD | {REF_OOS['max_dd']*100:.1f}% | {o['max_dd']*100:.1f}% | {(o['max_dd']-REF_OOS['max_dd'])*100:+.1f}pp |",
        f"| Sharpe | {REF_OOS['sharpe']:.2f} | {o['sharpe']:.2f} | {o['sharpe']-REF_OOS['sharpe']:+.2f} |",
        "",
        "### Bootstrap CI (OOS trade PF, 2000 resamples)",
        "",
        "| Mult | n | PF | boot mean | 95% CI |",
        "|-----:|--:|---:|----------:|--------|",
    ]
    for m, b in sorted(boot.items(), key=lambda x: float(x[0])):
        ci = f"[{b['ci_lo']:.2f}, {b['ci_hi']:.2f}]" if b.get("ci_lo") is not None else "n/a"
        mean = f"{b['mean_pf']:.2f}" if b.get("mean_pf") is not None else "n/a"
        lines.append(f"| {m} | {b['n']} | {b['pf']:.2f} | {mean} | {ci} |")

    lines += [
        "",
        "### Sleeve robustness (mult 3.0–3.8, n1 e1)",
        "",
        "| Mult | n | PF | Tot | MDD | WF+ | Last WF tot |",
        "|-----:|--:|---:|----:|----:|----:|------------:|",
    ]
    for r in sleeve:
        oos = r["OOS"]
        lines.append(
            f"| {r['params']['mult']} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['total_return']*100:.1f}% | {oos['max_dd']*100:.1f}% | "
            f"{r['wf_pos']}/{r['wf_n']} | {r['last_wf_tot']*100:.1f}% |"
        )

    top = sorted(
        rows,
        key=lambda r: (
            r.get("wf_pos", 0),
            r["OOS"]["profit_factor"],
            r["OOS"]["total_return"],
            r["OOS"]["sharpe"],
        ),
        reverse=True,
    )[:20]
    lines += [
        "",
        "### Block 2 new variants (top 20 by WF+ / PF / tot)",
        "",
        "| Rank | Name | n | PF | Exp | Tot | MDD | Stress PF | WF+ | LastWF |",
        "|-----:|------|--:|---:|----:|----:|----:|----------:|----:|-------:|",
    ]
    for i, r in enumerate(top, 1):
        oos = r["OOS"]
        lines.append(
            f"| {i} | {r['name']} | {oos['n_trades']} | {oos['profit_factor']:.2f} | "
            f"{oos['expectancy']*100:.2f}% | {oos['total_return']*100:.1f}% | "
            f"{oos['max_dd']*100:.1f}% | {r['OOS_stress']['profit_factor']:.2f} | "
            f"{r['wf_pos']}/{r['wf_n']} | {r['last_wf_tot']*100:.1f}% |"
        )

    lines += [
        "",
        f"**Champion after Block 2:** `{champ['name']}` — OOS PF={o['profit_factor']:.2f} "
        f"tot={o['total_return']*100:.1f}% n={o['n_trades']} WF={champ['wf_pos']}/{champ['wf_n']}",
        f"**B&H ^NSEI OOS:** tot={bh['total_return']*100:.1f}% Sharpe={bh['sharpe']:.2f}",
        "",
        "### Honesty",
        "- Bootstrap: if 3.6 CI sits well above neighbors → local peak but real; if overlaps heavily with 3.0 → prefer robust sleeve.",
        "- No fake futures; universe = ^NSEI + 20 NSE large-caps.",
        "- Costs 0.08% / stress 0.15% RT.",
        "",
    ]
    LEADERBOARD.write_text(prev + "\n".join(lines))


def main():
    if past_deadline():
        log("DEADLINE PASSED — Block 2 should not invent; run FINAL synthesis instead")
        print("PAST_DEADLINE")
        return

    log("=== Block 2 start ===")
    log("Loading Nifty + Bank + 20 stocks…")
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {s: prepare_symbol(s) for s in UNIVERSE}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)

    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos_start = oos_ref.index[0]
    end = max(df.index.max() for df in data.values())
    dates = pd.date_range(oos_start, end, periods=4)
    holdout_start = dates[2]  # last ~1/3 of OOS as holdout (aligns with last WF)

    bh_oos = buy_hold_stats(nifty.loc[nifty.index >= oos_start], "OOS")
    log(f"Buy&hold ^NSEI OOS: tot={bh_oos['total_return']*100:.1f}% Sharpe={bh_oos['sharpe']:.2f}")

    # ── 1) Reproduce #1 (exact engine from Block 1) ───────────────────────────
    log("Reproducing #1 ST_m3.6_n1_e1…")
    champ_params = {"mult": 3.6, "use_nifty": True, "use_ema200": True}
    champ = portfolio_eval("ST_m3.6_n1_e1", data, sig_supertrend, champ_params, oos_start)
    champ["last_wf_tot"] = champ["wf"][-1]["total_return"] if champ["wf"] else 0.0
    o = champ["OOS"]
    drift_pf = o["profit_factor"] - REF_OOS["profit_factor"]
    log(
        f"  REPRO n={o['n_trades']} PF={o['profit_factor']:.2f} tot={o['total_return']*100:.1f}% "
        f"MDD={o['max_dd']*100:.1f}% Sharpe={o['sharpe']:.2f} stressPF={champ['OOS_stress']['profit_factor']:.2f} "
        f"WF={champ['wf_pos']}/{champ['wf_n']} lastWF={champ['last_wf_tot']*100:.1f}% "
        f"drift_PF={drift_pf:+.2f}"
    )
    for w in champ["wf"]:
        log(f"  WF {w['period']}: n={w['n_trades']} exp={w['expectancy']*100:.2f}% tot={w['total_return']*100:.1f}%")

    # ── 2) Bootstrap / sleeve CI ──────────────────────────────────────────────
    log("Bootstrap + sleeve CI on mult 3.0–3.8…")
    sleeve_mults = [3.0, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8]
    boot: Dict[str, dict] = {}
    sleeve_rows: List[dict] = []
    for m in sleeve_mults:
        p = {"mult": m, "use_nifty": True, "use_ema200": True}
        row = portfolio_eval(f"ST_m{m}_n1_e1", data, sig_supertrend, p, oos_start)
        row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
        # holdout = last WF window
        hold = run_portfolio(data, sig_supertrend, p, start_date=holdout_start)
        row["holdout"] = hold
        # Trade list for bootstrap
        trets = collect_trade_rets(data, sig_supertrend, p, start_date=oos_start)
        b = bootstrap_pf(trets, n_boot=2000, seed=42 + int(m * 10))
        boot[str(m)] = b
        sleeve_rows.append(row)
        log(
            f"  sleeve m={m}: PF={row['OOS']['profit_factor']:.2f} n={row['OOS']['n_trades']} "
            f"tot={row['OOS']['total_return']*100:.1f}% WF={row['wf_pos']}/3 "
            f"lastWF={row['last_wf_tot']*100:.1f}% holdPF={hold['profit_factor']:.2f} "
            f"bootCI=[{b.get('ci_lo')}, {b.get('ci_hi')}]"
        )

    # Fragility verdict
    b36 = boot["3.6"]
    b30 = boot["3.0"]
    fragile = False
    prefer_mult = 3.6
    if b36.get("ci_lo") is not None and b30.get("ci_lo") is not None:
        # If 3.6 CI lower bound below 3.0 mean and 3.0 has more trades + WF 3/3 → prefer robust
        overlap = b36["ci_lo"] < b30["mean_pf"] < b36["ci_hi"]
        if overlap and b36["ci_lo"] < 2.0:
            fragile = True
            prefer_mult = 3.0
            log("  VERDICT: mult=3.6 looks like a FRAGILE spike (CI overlaps robust sleeve); prefer mult=3.0 for promotion conservatism")
        elif b36["ci_lo"] > b30["ci_hi"]:
            log("  VERDICT: mult=3.6 CI sits above 3.0 CI — peak is elevated but separated; keep 3.6 as #1 with caveat")
        else:
            log("  VERDICT: mult=3.6 elevated; neighborhood still strong — keep #1, track 3.0 as conservative")
    # Prefer robust param for *sleeve tracking* if last WF worse
    robust_candidates = [r for r in sleeve_rows if r["wf_pos"] == 3 and r["OOS"]["profit_factor"] >= 1.8]
    if robust_candidates:
        # Prefer higher lower-CI then more trades
        def robust_key(r):
            m = str(r["params"]["mult"])
            lo = boot[m].get("ci_lo") or 0
            return (lo, r["OOS"]["n_trades"], r["last_wf_tot"])

        robust_best = max(robust_candidates, key=robust_key)
        log(
            f"  Robust sleeve pick by boot CI_lo: mult={robust_best['params']['mult']} "
            f"PF={robust_best['OOS']['profit_factor']:.2f} CI_lo={boot[str(robust_best['params']['mult'])].get('ci_lo')}"
        )

    # ── 3) ≥15 NEW variants ───────────────────────────────────────────────────
    log("Screening ≥15 NEW Block-2 variants…")
    variants: List[Tuple[str, Callable, dict]] = [
        # Breadth × Supertrend
        ("B2_ST_breadth65_m3.6", sig_st_breadth, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_min": 0.65}),
        ("B2_ST_breadth70_m3.6", sig_st_breadth, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_min": 0.70}),
        ("B2_ST_breadth55_m3.0", sig_st_breadth, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "breadth_min": 0.55}),
        ("B2_ST_breadth60_m3.8", sig_st_breadth, {"mult": 3.8, "use_nifty": True, "use_ema200": True, "breadth_min": 0.60}),
        # Regime kill-switch (soft)
        ("B2_ST_kill_breadth40_m3.6", sig_st_kill_breadth, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.40}),
        ("B2_ST_kill_breadth45_m3.0", sig_st_kill_breadth, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "breadth_floor": 0.45}),
        ("B2_ST_kill_nifty_ema50_m3.6", sig_st_kill_nifty_ema50, {"mult": 3.6, "use_nifty": True, "use_ema200": True}),
        # ATR expansion entry + ST exit
        ("B2_ATRin_STout_25_0.2_m3.6", sig_atr_entry_st_exit, {"lookback": 25, "atr_ratio": 0.2, "mult": 3.6, "use_nifty": True}),
        ("B2_ATRin_STout_20_0.3_m3.0", sig_atr_entry_st_exit, {"lookback": 20, "atr_ratio": 0.3, "mult": 3.0, "use_nifty": True}),
        ("B2_ATRin_STout_40_0.2_m3.6", sig_atr_entry_st_exit, {"lookback": 40, "atr_ratio": 0.2, "mult": 3.6, "use_nifty": True}),
        # RS vs Bank / Nifty
        ("B2_ST_rs_bank_m3.6", sig_st_rs_bank, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "min_rs": 0.0}),
        ("B2_ST_rs_bank_m3.0", sig_st_rs_bank, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "min_rs": 0.02}),
        ("B2_ST_rs_nifty_m3.6", sig_st_rs_nifty, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "min_rs": 0.0}),
        # Heat / position caps (via params)
        ("B2_ST_heat3_m3.6", sig_st_delay_base, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "max_positions": 3, "heat_cap": 0.75}),
        ("B2_ST_heat4_m3.6", sig_st_delay_base, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "max_positions": 4, "heat_cap": 0.85}),
        ("B2_ST_heat3_m3.0", sig_st_delay_base, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "max_positions": 3, "heat_cap": 0.75}),
        # Entry delays
        ("B2_ST_delay1_m3.6", sig_st_delay_base, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "entry_delay": 1}),
        ("B2_ST_delay2_m3.6", sig_st_delay_base, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "entry_delay": 2}),
        ("B2_ST_delay1_m3.0", sig_st_delay_base, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "entry_delay": 1}),
        # RVOL filters
        ("B2_ST_rvol1.2_m3.6", sig_st_rvol, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "min_rvol": 1.2}),
        ("B2_ST_rvol1.5_m3.6", sig_st_rvol, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "min_rvol": 1.5}),
        ("B2_ST_rvol1.2_m3.0", sig_st_rvol, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "min_rvol": 1.2}),
        # Hybrid filters
        ("B2_ST_hyb_br55_rv1.1_m3.6", sig_st_hybrid_breadth_rvol, {"mult": 3.6, "use_nifty": True, "use_ema200": True, "breadth_min": 0.55, "min_rvol": 1.1}),
        ("B2_ST_hyb_br60_rv1.2_m3.0", sig_st_hybrid_breadth_rvol, {"mult": 3.0, "use_nifty": True, "use_ema200": True, "breadth_min": 0.60, "min_rvol": 1.2}),
        ("B2_ST_atr_exp_gate_m3.6", sig_st_atr_expand, {"mult": 3.6, "use_nifty": True, "use_ema200": True}),
        ("B2_ST_atr_exp_gate_m3.0", sig_st_atr_expand, {"mult": 3.0, "use_nifty": True, "use_ema200": True}),
        # Extra: plain atr_exp basket with nifty (control)
        ("B2_ATREXP_n25_r0.2", sig_atr_exp, {"n": 25, "rank_max": 0.2, "use_nifty": True}),
    ]

    needs_ext = {"entry_delay", "max_positions", "heat_cap"}
    new_rows: List[dict] = []
    fn_map = {}
    for name, fn, params in variants:
        try:
            if needs_ext & set(params.keys()):
                row = portfolio_eval_ext(name, data, fn, params, oos_start)
            else:
                row = portfolio_eval(name, data, fn, params, oos_start)
                row["last_wf_tot"] = row["wf"][-1]["total_return"] if row["wf"] else 0.0
            new_rows.append(row)
            fn_map[name] = fn.__name__
            log(
                f"  {name}: n={row['OOS']['n_trades']} PF={row['OOS']['profit_factor']:.2f} "
                f"tot={row['OOS']['total_return']*100:.1f}% MDD={row['OOS']['max_dd']*100:.1f}% "
                f"WF={row['wf_pos']}/3 lastWF={row['last_wf_tot']*100:.1f}% "
                f"stressPF={row['OOS_stress']['profit_factor']:.2f}"
            )
        except Exception as ex:
            log(f"  FAIL {name}: {ex}")

    log(f"Screened {len(new_rows)} new variants")

    # ── 4) Beat check ─────────────────────────────────────────────────────────
    contenders = [r for r in new_rows if r["OOS"]["n_trades"] >= 30 and r["OOS"]["profit_factor"] >= 1.3]
    contenders = sorted(
        contenders,
        key=lambda r: (r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"]),
        reverse=True,
    )
    promoted = False
    new_champ = champ
    for c in contenders:
        if clearly_better(c, champ):
            log(
                f"  BEAT: {c['name']} clearly better than #1 "
                f"(PF {c['OOS']['profit_factor']:.2f} vs {champ['OOS']['profit_factor']:.2f}, "
                f"tot {c['OOS']['total_return']*100:.1f}% vs {champ['OOS']['total_return']*100:.1f}%)"
            )
            new_champ = c
            promoted = True
            break
    if not promoted:
        log("  #1 ST_m3.6_n1_e1 REMAINS best — no challenger clearly better on OOS/WF/robustness")

    # Save runners-up r4, r5, r6 from best new variants that aren't the champ
    pool = [r for r in contenders if r["name"] != new_champ["name"]][:3]
    # Also include robust sleeve 3.0 if not already
    sleeve30 = next((r for r in sleeve_rows if r["params"]["mult"] == 3.0), None)
    saved = []
    for i, r in enumerate(pool, start=4):
        fn_name = fn_map.get(r["name"], "sig_supertrend")
        path = write_runner_up(i, r, fn_name)
        saved.append(str(path))
        log(f"  Saved {path.name}: {r['name']} PF={r['OOS']['profit_factor']:.2f}")

    # If we have a strong robust sleeve insight and didn't save 3.0 variant, note it
    if sleeve30 and fragile:
        log(f"  Conservative twin remains strategies/nifty_edge_r1.py (mult=3.0) — CI prefers robustness")

    # Only overwrite best if promoted
    if promoted:
        log("  Overwriting nifty_edge_best.py/.pine with new champion")
        oos = new_champ["OOS"]
        stress = new_champ["OOS_stress"]
        params = new_champ["params"]
        fn_name = fn_map.get(new_champ["name"], "sig_supertrend")
        py = f'''"""
Nifty Edge Best — Block 2 champion
==================================
{new_champ["name"]}
Params: {json.dumps(params)}

OOS: n={oos["n_trades"]} PF={oos["profit_factor"]:.2f} tot={oos["total_return"]*100:.1f}%
MDD={oos["max_dd"]*100:.1f}% Sharpe={oos["sharpe"]:.2f} stressPF={stress["profit_factor"]:.2f}
WF={new_champ["wf_pos"]}/{new_champ["wf_n"]} lastWF={new_champ["last_wf_tot"]*100:.1f}%

Usage:
  python strategies/nifty_edge_best.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "research" / "nifty_edge_8h"))
from india_edge_engine import time_split
from run_block1 import UNIVERSE, TRAIN_FRAC, prepare_symbol, attach_rs_and_breadth
from run_block2 import attach_market_to_stocks, run_portfolio_ext, {fn_name}

PARAMS = {json.dumps(params, indent=2)}

def main():
    nifty = prepare_symbol("^NSEI")
    bank = prepare_symbol("^NSEBANK")
    stocks_raw = {{s: prepare_symbol(s) for s in UNIVERSE}}
    nifty = attach_rs_and_breadth(nifty, bank, stocks_raw)
    data = attach_market_to_stocks(stocks_raw, nifty, bank)
    _, oos_ref = time_split(data["RELIANCE.NS"], TRAIN_FRAC)
    oos = run_portfolio_ext(data, {fn_name}, PARAMS, start_date=oos_ref.index[0])
    print(json.dumps({{"name": {json.dumps(new_champ["name"])}, "OOS": oos}}, indent=2, default=str))

if __name__ == "__main__":
    main()
'''
        (OUT_STRAT / "nifty_edge_best.py").write_text(py)
        log(f"  Wrote {OUT_STRAT / 'nifty_edge_best.py'}")
    else:
        log("  Kept strategies/nifty_edge_best.py unchanged (Block1 #1 still leads)")

    # ── Persist results + leaderboard ─────────────────────────────────────────
    summary = {
        "repro": champ,
        "bootstrap": boot,
        "sleeve": [{k: v for k, v in r.items() if k != "IS"} for r in sleeve_rows],
        "new_variants": [{k: v for k, v in r.items() if k != "IS"} for r in new_rows],
        "promoted": promoted,
        "champion": new_champ["name"],
        "fragile_36": fragile,
        "prefer_mult": prefer_mult,
        "runners_up": saved,
        "bh_oos": bh_oos,
    }
    # JSON-safe
    path = RESULTS / "block2_summary.json"

    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items() if k not in ("trades", "trade_rets")}
        if isinstance(obj, list):
            return [_clean(x) for x in obj]
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (pd.Timestamp, datetime)):
            return str(obj)
        return obj

    path.write_text(json.dumps(_clean(summary), indent=2, default=str))
    log(f"Wrote {path}")

    append_leaderboard_block2(new_champ, new_rows, boot, sleeve_rows, promoted, bh_oos)
    log(f"Updated {LEADERBOARD}")

    # Top 5 summary
    top5 = sorted(
        new_rows,
        key=lambda r: (r["wf_pos"], r["OOS"]["profit_factor"], r["OOS"]["total_return"]),
        reverse=True,
    )[:5]
    log("--- Block 2 top 5 new ---")
    for r in top5:
        log(
            f"  {r['name']}: PF={r['OOS']['profit_factor']:.2f} tot={r['OOS']['total_return']*100:.1f}% "
            f"n={r['OOS']['n_trades']} WF={r['wf_pos']}/3"
        )
    log(
        f"=== Block 2 complete === champion={new_champ['name']} "
        f"PF={new_champ['OOS']['profit_factor']:.2f} promoted={promoted} fragile_36={fragile}"
    )
    log(
        "Next Block 3: futures/point costs if data appears; hourly ORB on stocks; "
        "ensemble ST 3.0+3.6 sleeve; volatility targeting; sector-neutral heat"
    )


if __name__ == "__main__":
    main()
