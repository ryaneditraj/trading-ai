"""
GIFT / Overnight Nifty edge research
====================================
Two sleeves:
  A) OVERNIGHT — capture the move while NSE cash is closed
     Proxy P&L = Nifty open gap (Open[t]/Close[t-1]-1). This is what overnight
     GIFT traders largely monetize (basis aside). Signals use info known by
     prior India close + prior US close (no look-ahead into Asia same morning
     unless labeled as Asia-confirm open sleeve).

  B) OPEN — trade next NSE session using overnight cues
     Enter at open, exit at close (or opposite open).

Data: ^NSEI, ES=F, NQ=F, ^N225, ^HSI, ^INDIAVIX via yfinance.
True GIFT Session II ticks are NOT free on Yahoo — when you have a CSV,
drop it into research/gift_overnight_edge/data/gift_nifty.csv
(columns: datetime, Open, High, Low, Close, Volume) and re-run.

Usage:
  python research/gift_overnight_edge/run_research.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research"))

from india_edge_engine import RESULTS_DIR, time_split, safe_cache_path  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)
GIFT_CSV = Path(__file__).resolve().parent / "data" / "gift_nifty.csv"

RT = 0.0008
RT_STRESS = 0.0015
TRAIN_FRAC = 0.70


def _flat(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def fetch(symbol: str, start: str = "2015-01-01") -> pd.DataFrame:
    cache = safe_cache_path(
        f"gift_{symbol.replace('^', '').replace('=', '_').replace('.', '_')}_1d.parquet"
    )
    if cache.exists():
        df = pd.read_parquet(cache)
        if len(df) > 200:
            return df
    raw = yf.download(symbol, start=start, interval="1d", progress=False, auto_adjust=True)
    raw = _flat(raw)
    if raw.empty:
        raise ValueError(f"No data for {symbol}")
    df = raw.rename(columns=str.title)[["Open", "High", "Low", "Close", "Volume"]].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def load_gift_csv() -> Optional[pd.DataFrame]:
    if not GIFT_CSV.exists():
        return None
    df = pd.read_csv(GIFT_CSV)
    cols = {c.lower(): c for c in df.columns}
    # normalize
    rename = {}
    for want in ("open", "high", "low", "close", "volume"):
        if want in cols:
            rename[cols[want]] = want.title()
    df = df.rename(columns=rename)
    dtcol = None
    for c in df.columns:
        if c.lower() in ("datetime", "date", "time", "timestamp"):
            dtcol = c
            break
    if dtcol is None:
        raise ValueError("gift_nifty.csv needs a datetime/date column")
    df[dtcol] = pd.to_datetime(df[dtcol])
    df = df.set_index(dtcol).sort_index()
    df.index = df.index.tz_localize(None) if df.index.tz is None else df.index.tz_convert(None)
    need = ["Open", "High", "Low", "Close"]
    for c in need:
        if c not in df.columns:
            raise ValueError(f"gift csv missing {c}")
    return df.dropna(subset=need)


def build_frame() -> pd.DataFrame:
    n = fetch("^NSEI")
    es = fetch("ES=F")
    nq = fetch("NQ=F")
    nk = fetch("^N225")
    hs = fetch("^HSI")
    try:
        vx = fetch("^INDIAVIX")
    except Exception:
        vx = None

    o = n.copy()
    o["gap"] = o["Open"] / o["Close"].shift(1) - 1.0  # overnight move (GIFT proxy PnL)
    o["day"] = o["Close"] / o["Open"] - 1.0  # cash session
    o["ret1"] = o["Close"].pct_change()
    o["ret5"] = o["Close"].pct_change(5)
    o["ema20"] = o["Close"].ewm(span=20, adjust=False).mean()
    o["ema50"] = o["Close"].ewm(span=50, adjust=False).mean()
    o["ema200"] = o["Close"].ewm(span=200, adjust=False).mean()
    o["atr"] = (o["High"] - o["Low"]).rolling(14).mean()
    o["atr_pct"] = o["atr"] / o["Close"]
    # prior India session (known before overnight)
    o["india_day_prev"] = o["day"].shift(1)
    o["india_ret1_prev"] = o["ret1"].shift(1)
    o["above_ema200"] = o["Close"] > o["ema200"]
    o["above_ema50"] = o["Close"] > o["ema50"]

    # US: prior session close-to-close (known before India morning; US closes ~02:30 IST next day
    # For India day t open (~09:15), US day t-1 close is known. Use shift(1) on US aligned by date.
    es_c = es["Close"].reindex(o.index, method="ffill")
    nq_c = nq["Close"].reindex(o.index, method="ffill")
    # US return ending on calendar date d is known for India session on d+1 if US closed same calendar day
    # Conservative: use US return from previous calendar row of ES (already date-indexed)
    es_ret = es["Close"].pct_change()
    nq_ret = nq["Close"].pct_change()
    # For India OPEN day t: US close on calendar t-1 is known → es_ret_prev
    o["es_ret_prev"] = es_ret.reindex(o.index).shift(1)
    o["nq_ret_prev"] = nq_ret.reindex(o.index).shift(1)
    # For overnight ENTRY at India CLOSE t-1: US t-1 not finished yet → need US t-2
    o["es_ret_lag2"] = es_ret.reindex(o.index).shift(2)
    o["nq_ret_lag2"] = nq_ret.reindex(o.index).shift(2)
    # Same-calendar US return (ES twin / Session-II overlap PnL)
    o["es_ret_same"] = es_ret.reindex(o.index)
    o["nq_ret_same"] = nq_ret.reindex(o.index)

    # Asia: same calendar date — for India 9:15, Nikkei/HSI have usually opened (Tokyo 5:30 IST)
    # Using same-day Asia open→close would look ahead into India day; use Asia overnight gap instead
    nk = nk.reindex(o.index)
    hs = hs.reindex(o.index)
    o["nk_gap"] = (nk["Open"] / nk["Close"].shift(1) - 1.0)
    o["hs_gap"] = (hs["Open"] / hs["Close"].shift(1) - 1.0)
    # Asia gap on date t is known ~before/at India open — OK for OPEN sleeve, NOT for overnight entry at t-1 close

    if vx is not None:
        o["india_vix"] = vx["Close"].reindex(o.index, method="ffill")
        o["vix_z"] = (o["india_vix"] - o["india_vix"].rolling(60).mean()) / o[
            "india_vix"
        ].rolling(60).std()
    else:
        o["india_vix"] = np.nan
        o["vix_z"] = 0.0

    # Overnight composite proxy (for open sleeve): US prev + Asia gaps
    o["overnight_proxy"] = (
        0.5 * o["es_ret_prev"].fillna(0)
        + 0.2 * o["nq_ret_prev"].fillna(0)
        + 0.15 * o["nk_gap"].fillna(0)
        + 0.15 * o["hs_gap"].fillna(0)
    )

    # True GIFT daily if provided (resample to daily last close)
    gift = load_gift_csv()
    if gift is not None:
        gday = gift.resample("1D").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
        ).dropna(subset=["Close"])
        o["gift_ret"] = gday["Close"].pct_change().reindex(o.index)
        o["gift_gap_vs_nse"] = gday["Close"].reindex(o.index) / o["Close"].shift(1) - 1.0
        print(f"Loaded GIFT CSV: {len(gift)} bars → {len(gday)} days")
    else:
        o["gift_ret"] = np.nan
        o["gift_gap_vs_nse"] = np.nan
        print("No GIFT CSV — overnight PnL proxy = NSE open gap; US twin = ES session.")

    return o.dropna(subset=["gap", "day", "es_ret_prev"]).copy()


# ── Stats helpers ─────────────────────────────────────────────────────────────
def trade_stats(rets: np.ndarray, name: str, split: str) -> dict:
    rets = np.asarray(rets, dtype=float)
    rets = rets[np.isfinite(rets)]
    if len(rets) == 0:
        return {
            "name": name,
            "split": split,
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "total_return": 0.0,
            "max_dd": 0.0,
            "sharpe": 0.0,
        }
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    gp = wins.sum() if len(wins) else 0.0
    gl = -losses.sum() if len(losses) else 0.0
    pf = float(gp / gl) if gl > 1e-12 else (999.0 if gp > 0 else 0.0)
    eq = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    mu, sd = rets.mean(), rets.std(ddof=1) if len(rets) > 1 else 0.0
    # ~1 trade/day when active; ann by sqrt(252 * participation)
    sharpe = float((mu / sd) * np.sqrt(252)) if sd > 1e-12 else 0.0
    return {
        "name": name,
        "split": split,
        "n_trades": int(len(rets)),
        "win_rate": float((rets > 0).mean()),
        "profit_factor": pf,
        "expectancy": float(mu),
        "total_return": float(eq[-1] - 1.0),
        "max_dd": float(dd.min()),
        "sharpe": sharpe,
    }


def eval_signal(
    df: pd.DataFrame,
    side: pd.Series,
    pnl_col: str,
    name: str,
    rt: float = RT,
) -> Dict[str, dict]:
    """side in {-1,0,1}; PnL = side * df[pnl_col] - rt*|side|."""
    train, test = time_split(df, TRAIN_FRAC)
    out = {}
    for split, part in [("IS", train), ("OOS", test)]:
        s = side.reindex(part.index).fillna(0)
        active = s != 0
        if active.sum() == 0:
            out[split] = trade_stats(np.array([]), name, split)
            continue
        rets = (s * part[pnl_col] - rt * s.abs()).loc[active].values
        out[split] = trade_stats(rets, name, split)
    # walk-forward 3 chunks on OOS
    te = test
    n = len(te)
    wf = []
    if n > 60:
        cuts = [0, n // 3, 2 * n // 3, n]
        for i in range(3):
            part = te.iloc[cuts[i] : cuts[i + 1]]
            s = side.reindex(part.index).fillna(0)
            active = s != 0
            rets = (s * part[pnl_col] - rt * s.abs()).loc[active].values if active.any() else np.array([])
            st = trade_stats(rets, name, f"WF{i+1}")
            wf.append(st)
    out["wf"] = wf
    out["wf_pos"] = sum(1 for w in wf if w["expectancy"] > 0)
    out["last_wf_tot"] = wf[-1]["total_return"] if wf else 0.0
    return out


def fmt(s: dict) -> str:
    return (
        f"n={s['n_trades']:4d} WR={s['win_rate']:5.1%} PF={s['profit_factor']:5.2f} "
        f"E={s['expectancy']*100:+.3f}% Tot={s['total_return']*100:+.1f}% "
        f"MDD={s['max_dd']*100:.1f}% Sh={s['sharpe']:.2f}"
    )


def pass_bar(oos: dict, wf_pos: int) -> bool:
    return (
        oos["n_trades"] >= 40
        and oos["profit_factor"] >= 1.3
        and oos["expectancy"] > 0
        and wf_pos >= 2
    )


# ── Prediction diagnostics ────────────────────────────────────────────────────
def predict_study(df: pd.DataFrame) -> dict:
    """How well overnight proxies predict gap and day return (OOS only)."""
    _, te = time_split(df, TRAIN_FRAC)
    rows = {}
    for feat in ["es_ret_prev", "nq_ret_prev", "overnight_proxy", "nk_gap", "hs_gap"]:
        x = te[feat]
        for tgt in ["gap", "day"]:
            y = te[tgt]
            m = x.notna() & y.notna()
            if m.sum() < 30:
                continue
            xv, yv = x[m].values, y[m].values
            # correlation + hit rate same sign
            corr = float(np.corrcoef(xv, yv)[0, 1]) if len(xv) > 2 else 0.0
            hit = float(((xv > 0) == (yv > 0)).mean())
            # R2 from simple regression
            coef = np.polyfit(xv, yv, 1)
            pred = coef[0] * xv + coef[1]
            ss_res = ((yv - pred) ** 2).sum()
            ss_tot = ((yv - yv.mean()) ** 2).sum()
            r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0
            rows[f"{feat}→{tgt}"] = {"corr": corr, "hit_rate": hit, "r2": r2, "n": int(m.sum())}
    # gap → day (does open gap predict cash session?)
    m = te["gap"].notna() & te["day"].notna()
    xv, yv = te.loc[m, "gap"].values, te.loc[m, "day"].values
    corr = float(np.corrcoef(xv, yv)[0, 1])
    hit = float(((xv > 0) == (yv > 0)).mean())
    rows["gap→day"] = {"corr": corr, "hit_rate": hit, "n": int(m.sum())}
    return rows


# ── Strategy builders: return side series in {-1,0,1} ─────────────────────────
SignalBuilder = Callable[[pd.DataFrame, dict], pd.Series]


def sig_overnight_trend_hold(df: pd.DataFrame, p: dict) -> pd.Series:
    """At prior close: if India uptrend, hold long overnight (earn the gap)."""
    above200 = df["above_ema200"].shift(1).fillna(False).astype(bool)
    above50 = (df["Close"].shift(1) > df["ema50"].shift(1)).fillna(False).astype(bool)
    up = above200 & above50
    dn = (~above200) & (~above50)
    side = pd.Series(0.0, index=df.index)
    side = side.mask(up, 1.0)
    if p.get("allow_short", False):
        side = side.mask(dn, -1.0)
    return side


def sig_overnight_mom_trend(df: pd.DataFrame, p: dict) -> pd.Series:
    """Overnight momentum only with EMA200 trend alignment."""
    thr = float(p.get("thr", 0.005))
    prev = df["india_day_prev"]
    uptrend = df["above_ema200"].shift(1).fillna(False).astype(bool)
    side = pd.Series(0.0, index=df.index)
    side = side.mask((prev >= thr) & uptrend, 1.0)
    side = side.mask((prev <= -thr) & (~uptrend), -1.0)
    return side


def sig_overnight_momentum(df: pd.DataFrame, p: dict) -> pd.Series:
    """Ride prior India day into overnight if |day| large."""
    thr = float(p.get("thr", 0.004))
    prev = df["india_day_prev"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(prev >= thr, 1.0)
    side = side.mask(prev <= -thr, -1.0)
    return side


def sig_overnight_fade_day(df: pd.DataFrame, p: dict) -> pd.Series:
    """Fade a large India cash session into the overnight gap."""
    thr = float(p.get("thr", 0.008))
    prev = df["india_day_prev"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(prev >= thr, -1.0)
    side = side.mask(prev <= -thr, 1.0)
    return side


def sig_overnight_us_lead(df: pd.DataFrame, p: dict) -> pd.Series:
    """
    Overnight hold decided at India close using US lag-2 (no look-ahead).
    Earns NSE open gap.
    """
    thr = float(p.get("thr", 0.003))
    us = df["es_ret_lag2"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(us >= thr, 1.0)
    side = side.mask(us <= -thr, -1.0)
    return side


def sig_overnight_us_same_session(df: pd.DataFrame, p: dict) -> pd.Series:
    """
    ES twin: enter from prior ES day momentum, earn same-calendar ES return.
    Proxies trading risk during US hours that overlap GIFT Session II.
    """
    thr = float(p.get("thr", 0.002))
    us = df["es_ret_prev"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(us >= thr, 1.0)
    side = side.mask(us <= -thr, -1.0)
    return side


def sig_open_gap_cont(df: pd.DataFrame, p: dict) -> pd.Series:
    """At open: continue the gap into the cash session."""
    thr = float(p.get("thr", 0.003))
    g = df["gap"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(g >= thr, 1.0)
    side = side.mask(g <= -thr, -1.0)
    return side


def sig_open_gap_fade(df: pd.DataFrame, p: dict) -> pd.Series:
    thr = float(p.get("thr", 0.008))
    g = df["gap"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(g >= thr, -1.0)
    side = side.mask(g <= -thr, 1.0)
    # only in elevated vix
    if p.get("vix_z_min") is not None:
        side = side.where(df["vix_z"] >= float(p["vix_z_min"]), 0.0)
    return side


def sig_open_us_lead(df: pd.DataFrame, p: dict) -> pd.Series:
    """Trade cash session in direction of prior US overnight."""
    thr = float(p.get("thr", 0.004))
    us = df["es_ret_prev"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(us >= thr, 1.0)
    side = side.mask(us <= -thr, -1.0)
    return side


def sig_open_proxy_cont(df: pd.DataFrame, p: dict) -> pd.Series:
    thr = float(p.get("thr", 0.003))
    x = df["overnight_proxy"]
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(x >= thr, 1.0)
    side = side.mask(x <= -thr, -1.0)
    return side


def sig_open_asia_confirm(df: pd.DataFrame, p: dict) -> pd.Series:
    """Continue gap only if Asia gaps agree with US prev."""
    thr = float(p.get("thr", 0.003))
    us = df["es_ret_prev"]
    asia = 0.5 * df["nk_gap"].fillna(0) + 0.5 * df["hs_gap"].fillna(0)
    agree_up = (us > 0) & (asia > 0) & (df["gap"] >= thr)
    agree_dn = (us < 0) & (asia < 0) & (df["gap"] <= -thr)
    side = pd.Series(0, index=df.index, dtype=float)
    side = side.mask(agree_up, 1.0)
    side = side.mask(agree_dn, -1.0)
    return side


def sig_open_disagree_fade(df: pd.DataFrame, p: dict) -> pd.Series:
    """Big overnight proxy but tiny actual gap → fade the proxy (auction disagreement)."""
    pthr = float(p.get("proxy_thr", 0.005))
    gmax = float(p.get("gap_max", 0.002))
    x = df["overnight_proxy"]
    g = df["gap"]
    side = pd.Series(0, index=df.index, dtype=float)
    # proxy said up, open barely moved → short the day
    side = side.mask((x >= pthr) & (g.abs() <= gmax), -1.0)
    side = side.mask((x <= -pthr) & (g.abs() <= gmax), 1.0)
    return side


def main():
    print("=== GIFT / Overnight Nifty research ===\n")
    df = build_frame()
    print(f"Frame: {len(df)} days  {df.index.min().date()} → {df.index.max().date()}")

    pred = predict_study(df)
    print("\n── Prediction study (OOS) ──")
    for k, v in sorted(pred.items(), key=lambda kv: -abs(kv[1].get("corr", 0))):
        print(
            f"  {k:28s}  corr={v.get('corr', 0):+.3f}  hit={v.get('hit_rate', 0):.1%}  "
            f"r2={v.get('r2', float('nan')):.3f}  n={v.get('n')}"
        )

    # Strategy grid
    strategies: List[Tuple[str, str, SignalBuilder, dict, float]] = []
    # sleeve, pnl_col, builder, params, rt
    # OVERNIGHT: earn the gap
    for thr in (0.002, 0.004, 0.006):
        strategies.append(
            (f"ON_mom_day_{thr}", "gap", sig_overnight_momentum, {"thr": thr}, RT)
        )
        strategies.append(
            (f"ON_us_lead_{thr}", "gap", sig_overnight_us_lead, {"thr": thr}, RT)
        )
        strategies.append(
            (f"ON_fade_day_{thr}", "gap", sig_overnight_fade_day, {"thr": thr}, RT)
        )
    strategies.append(
        ("ON_trend_hold_long", "gap", sig_overnight_trend_hold, {"allow_short": False}, RT)
    )
    strategies.append(
        ("ON_trend_hold_both", "gap", sig_overnight_trend_hold, {"allow_short": True}, RT)
    )
    for thr in (0.004, 0.006, 0.008):
        strategies.append(
            (f"ON_mom_trend_{thr}", "gap", sig_overnight_mom_trend, {"thr": thr}, RT)
        )
    # Trade ES as Session-II twin (actual US overnight risk)
    for thr in (0.002, 0.004):
        strategies.append(
            (
                f"ON_ES_twin_{thr}",
                "es_ret_same",
                sig_overnight_us_same_session,
                {"thr": thr},
                0.0004,  # ES cheaper
            )
        )

    # OPEN session
    for thr in (0.002, 0.004, 0.006, 0.008):
        strategies.append((f"OP_gap_cont_{thr}", "day", sig_open_gap_cont, {"thr": thr}, RT))
        strategies.append((f"OP_gap_fade_{thr}", "day", sig_open_gap_fade, {"thr": thr}, RT))
        strategies.append((f"OP_us_lead_{thr}", "day", sig_open_us_lead, {"thr": thr}, RT))
        strategies.append((f"OP_proxy_{thr}", "day", sig_open_proxy_cont, {"thr": thr}, RT))
    strategies.append(
        ("OP_gap_fade_hvix", "day", sig_open_gap_fade, {"thr": 0.008, "vix_z_min": 0.5}, RT)
    )
    strategies.append(
        ("OP_asia_confirm", "day", sig_open_asia_confirm, {"thr": 0.003}, RT)
    )
    strategies.append(
        ("OP_disagree_fade", "day", sig_open_disagree_fade, {"proxy_thr": 0.005, "gap_max": 0.002}, RT)
    )

    # If GIFT daily present, add sleeve
    if df["gift_ret"].notna().sum() > 100:
        strategies.append(
            ("ON_gift_us_lead", "gift_ret", sig_overnight_us_lead, {"thr": 0.003}, RT)
        )

    results = []
    print("\n── Strategy screen ──")
    for name, pnl_col, fn, params, rt in strategies:
        side = fn(df, params)
        ev = eval_signal(df, side, pnl_col, name, rt=rt)
        oos = ev["OOS"]
        ok = pass_bar(oos, ev["wf_pos"])
        row = {
            "name": name,
            "pnl_col": pnl_col,
            "params": params,
            "rt": rt,
            "IS": ev["IS"],
            "OOS": oos,
            "wf_pos": ev["wf_pos"],
            "last_wf_tot": ev["last_wf_tot"],
            "pass": ok,
        }
        results.append(row)
        mark = "PASS" if ok else "fail"
        print(f"  [{mark}] {name:28s} OOS {fmt(oos)}  WF={ev['wf_pos']}/3")

    # Stress survivors / top by OOS expectancy among n>=30
    ranked = sorted(
        results,
        key=lambda r: (
            r["pass"],
            r["OOS"]["expectancy"] if r["OOS"]["n_trades"] >= 30 else -9,
            r["OOS"]["profit_factor"],
        ),
        reverse=True,
    )
    print("\n── TOP 8 by OOS (n≥30 preferred) ──")
    for r in ranked[:8]:
        print(
            f"  {'PASS' if r['pass'] else 'fail':4s} {r['name']:28s} "
            f"{fmt(r['OOS'])} lastWF={r['last_wf_tot']*100:+.1f}%"
        )

    survivors = [r for r in results if r["pass"]]
    # stress cost on survivors
    stress = []
    for r in survivors:
        # rebuild
        name = r["name"]
        # find builder
        for n, pnl_col, fn, params, rt in strategies:
            if n == name:
                side = fn(df, params)
                ev = eval_signal(df, side, pnl_col, name, rt=RT_STRESS)
                stress.append({"name": name, "OOS_stress": ev["OOS"]})
                print(f"\n  STRESS 0.15% {name}: {fmt(ev['OOS'])}")
                break

    verdict = {
        "note": (
            "Overnight sleeve PnL = NSE open gap (GIFT proxy). "
            "ES twin trades US session overlapping GIFT Session II. "
            "Drop real GIFT CSV to research/gift_overnight_edge/data/gift_nifty.csv for Phase 2."
        ),
        "prediction": pred,
        "n_pass": len(survivors),
        "survivors": [
            {"name": r["name"], "params": r["params"], "OOS": r["OOS"], "wf_pos": r["wf_pos"]}
            for r in survivors
        ],
        "top8": [
            {
                "name": r["name"],
                "pass": r["pass"],
                "params": r["params"],
                "pnl_col": r["pnl_col"],
                "OOS": r["OOS"],
                "wf_pos": r["wf_pos"],
                "last_wf_tot": r["last_wf_tot"],
            }
            for r in ranked[:8]
        ],
        "stress": stress,
        "champion": survivors[0]["name"] if survivors else (
            ranked[0]["name"] if ranked else None
        ),
        "champion_pass": bool(survivors),
    }

    print("\n=== VERDICT ===")
    if survivors:
        print(f"EDGE FOUND: {len(survivors)} sleeve(s) clear the bar.")
        for r in survivors:
            print(f"  • {r['name']}  OOS {fmt(r['OOS'])}")
    else:
        best = ranked[0] if ranked else None
        print("No sleeve cleared PF≥1.3 / n≥40 / WF≥2/3.")
        if best:
            print(f"Least-bad: {best['name']}  OOS {fmt(best['OOS'])}")
        print(
            "Interpretation: overnight IS where price discovery happens, but a simple "
            "mechanical edge on free proxies is thin. Next: real GIFT ticks + first-hour exits."
        )

    path = RESULTS_DIR / "gift_overnight_edge.json"
    path.write_text(json.dumps(verdict, indent=2, default=str))
    OUT.joinpath("summary.json").write_text(json.dumps(verdict, indent=2, default=str))
    print(f"\nWrote {path}")
    return verdict


if __name__ == "__main__":
    main()
