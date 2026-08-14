"""
Walk-forward backtest of the BTC 1% Radar score.

At each 15m bar close (after warmup), rebuild features with no lookahead,
emit LONG/SHORT/NO TRADE, then label which side first reaches ±target_pct
on subsequent 5m bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from btc_radar.catalyst import MacroMode, extract_catalyst
from btc_radar.derivatives import FUNDING_HIGH, FUNDING_LOW, DerivativesFeatures
from btc_radar.history import HistoryBundle, load_history
from btc_radar.liquidity import LiquidityFeatures
from btc_radar.score import THRESHOLD, TARGET_PCT, liquidation_distance_pct, score
from btc_radar.structure import StructureFeatures, _ema, session_vwap


@dataclass
class BacktestConfig:
    days: int = 28
    target_pct: float = TARGET_PCT
    threshold: float = THRESHOLD
    leverage: float = 100.0
    step: int = 1  # evaluate every Nth 15m bar
    max_horizon_bars_5m: int = 96 * 7  # 7 days of 5m bars
    warmup_15m: int = 60
    use_macro: bool = True
    dedupe_signals: bool = True  # collapse consecutive identical LONG/SHORT into one trade


def _asof_value(df: pd.DataFrame, ts: pd.Timestamp, col: str, default: float = np.nan) -> float:
    if df is None or df.empty or col not in df.columns:
        return float(default)
    tcol = "timestamp" if "timestamp" in df.columns else ("fundingTime" if "fundingTime" in df.columns else None)
    if tcol is None:
        return float(default)
    sub = df[df[tcol] <= ts]
    if sub.empty:
        return float(default)
    return float(sub[col].iloc[-1])


def _asof_series_tail(
    df: pd.DataFrame, ts: pd.Timestamp, col: str, n: int
) -> list[float]:
    if df is None or df.empty or col not in df.columns:
        return []
    tcol = "timestamp" if "timestamp" in df.columns else None
    if tcol is None:
        return []
    sub = df[df[tcol] <= ts]
    if sub.empty:
        return []
    return [float(x) for x in sub[col].tail(n).tolist()]


def _structure_at(hist: HistoryBundle, i15: int) -> StructureFeatures:
    k15 = hist.k15.iloc[: i15 + 1]
    t = k15["open_time"].iloc[-1]
    price = float(k15["close"].iloc[-1])

    k5 = hist.k5[hist.k5["open_time"] <= t]
    if len(k5) < 50:
        # insufficient
        raise ValueError("warmup")

    k1d = hist.k1d[hist.k1d["open_time"] <= t]
    vwap = session_vwap(k5)
    above_vwap = price > vwap

    if len(k1d) >= 2:
        # last completed daily = previous calendar day if today's bar incomplete
        completed = k1d[k1d["close_time"] < t]
        if len(completed) >= 1:
            prev = completed.iloc[-1]
        else:
            prev = k1d.iloc[-2] if len(k1d) >= 2 else k1d.iloc[-1]
        pdh, pdl = float(prev["high"]), float(prev["low"])
    else:
        pdh = float(k5["high"].max())
        pdl = float(k5["low"].min())

    last_day = k5["open_time"].dt.floor("D").iloc[-1]
    sess = k5[k5["open_time"].dt.floor("D") == last_day]
    if sess.empty:
        sess = k5.tail(48)
    session_high = float(sess["high"].max())
    session_low = float(sess["low"].min())

    e20_5 = float(_ema(k5["close"], 20).iloc[-1])
    e50_5 = float(_ema(k5["close"], 50).iloc[-1])
    e20_15 = float(_ema(k15["close"], 20).iloc[-1])
    e50_15 = float(_ema(k15["close"], 50).iloc[-1])

    bull_5 = price > e20_5 > e50_5
    bear_5 = price < e20_5 < e50_5
    bull_15 = price > e20_15 > e50_15
    bear_15 = price < e20_15 < e50_15
    trend_bullish = bull_5 and bull_15
    trend_bearish = bear_5 and bear_15

    thr = price * 0.0035
    near_support = min(abs(price - pdl), abs(price - session_low)) <= thr
    near_resistance = min(abs(price - pdh), abs(price - session_high)) <= thr

    if trend_bullish and above_vwap:
        label = "bullish"
    elif trend_bearish and not above_vwap:
        label = "bearish"
    else:
        label = "mixed"

    return StructureFeatures(
        price=price,
        vwap=vwap,
        above_vwap=above_vwap,
        pdh=pdh,
        pdl=pdl,
        session_high=session_high,
        session_low=session_low,
        ema20_5m=e20_5,
        ema50_5m=e50_5,
        ema20_15m=e20_15,
        ema50_15m=e50_15,
        trend_bullish=trend_bullish,
        trend_bearish=trend_bearish,
        near_support=near_support,
        near_resistance=near_resistance,
        label=label,
    )


def _derivatives_at(hist: HistoryBundle, i15: int) -> DerivativesFeatures:
    k15 = hist.k15.iloc[: i15 + 1]
    t = k15["open_time"].iloc[-1]
    price = float(k15["close"].iloc[-1])

    oi = _asof_value(hist.oi, t, "sumOpenInterest", default=np.nan)
    oi_vals = _asof_series_tail(hist.oi, t, "sumOpenInterest", 2)
    if len(oi_vals) >= 2:
        oi_prev, oi = oi_vals[-2], oi_vals[-1]
    elif len(oi_vals) == 1:
        oi_prev, oi = oi_vals[0], oi_vals[0]
    else:
        oi_prev, oi = (oi if np.isfinite(oi) else 0.0), (oi if np.isfinite(oi) else 0.0)

    oi_rising = oi > oi_prev * 1.001
    oi_falling = oi < oi_prev * 0.999

    if len(k15) >= 3:
        price_up = float(k15["close"].iloc[-1]) > float(k15["close"].iloc[-3])
    else:
        price_up = True

    funding = _asof_value(hist.funding, t, "fundingRate", default=0.0)
    if not np.isfinite(funding):
        funding = 0.0

    if funding >= FUNDING_HIGH:
        funding_label = "excessively_pos"
        funding_ok_for_long = False
        funding_ok_for_short = True
    elif funding <= FUNDING_LOW:
        funding_label = "excessively_neg"
        funding_ok_for_long = True
        funding_ok_for_short = False
    else:
        funding_label = "neutral"
        funding_ok_for_long = True
        funding_ok_for_short = True

    ls = _asof_value(hist.long_short, t, "longShortRatio", default=1.0)
    if not np.isfinite(ls):
        ls = 1.0

    taker_tail = _asof_series_tail(hist.taker, t, "buySellRatio", 4)
    if taker_tail:
        avg = sum(taker_tail) / len(taker_tail)
    else:
        # Fallback: kline taker buy ratio on last 4 15m bars
        if "taker_buy_base" in k15.columns and len(k15) >= 4:
            tail = k15.tail(4)
            buy = float(tail["taker_buy_base"].sum())
            vol = float(tail["volume"].sum())
            sell = max(vol - buy, 1e-12)
            avg = buy / sell
        else:
            avg = 1.0

    cvd_bullish = avg >= 1.05
    cvd_bearish = avg <= 0.95
    if cvd_bullish:
        cvd_arrow = "↑↑" if avg >= 1.15 else "↑"
    elif cvd_bearish:
        cvd_arrow = "↓↓" if avg <= 0.85 else "↓"
    else:
        cvd_arrow = "→"

    return DerivativesFeatures(
        oi=float(oi),
        oi_prev=float(oi_prev),
        oi_rising=oi_rising,
        oi_arrow="↑" if oi_rising else ("↓" if oi_falling else "→"),
        price_up=price_up,
        oi_with_price_long=oi_rising and price_up,
        oi_with_price_short=oi_rising and not price_up,
        funding=float(funding),
        funding_label=funding_label,
        funding_ok_for_long=funding_ok_for_long,
        funding_ok_for_short=funding_ok_for_short,
        long_short_ratio=float(ls),
        taker_buy_sell_ratio=float(avg),
        cvd_bullish=cvd_bullish,
        cvd_bearish=cvd_bearish,
        cvd_arrow=cvd_arrow,
        liq_long_usd=0.0,
        liq_short_usd=0.0,
        liq_label="n/a (backtest)",
    )


def _liquidity_proxy_at(hist: HistoryBundle, i15: int, band_pct: float = 0.015) -> LiquidityFeatures:
    """
    Historical proxy for book magnets: volume traded near ±band over prior 5m bars.
    Not the same as live L2 depth — labeled accordingly.
    """
    k15 = hist.k15.iloc[: i15 + 1]
    t = k15["open_time"].iloc[-1]
    price = float(k15["close"].iloc[-1])
    k5 = hist.k5[hist.k5["open_time"] <= t].tail(96)  # ~8h
    if k5.empty:
        return LiquidityFeatures(
            bid_depth_usd=0,
            ask_depth_usd=0,
            cluster_above=price * (1 + band_pct),
            cluster_below=price * (1 - band_pct),
            larger_above=False,
            larger_below=False,
            band_pct=band_pct,
            note="volume-near-price proxy (backtest)",
        )

    mid = (k5["high"] + k5["low"]) / 2.0
    notional = mid * k5["volume"]
    above = ((mid >= price) & (mid <= price * (1 + band_pct))).astype(float) * notional
    below = ((mid <= price) & (mid >= price * (1 - band_pct))).astype(float) * notional
    ask_usd = float(above.sum())
    bid_usd = float(below.sum())

    # densest bar in each band
    above_mask = (mid >= price) & (mid <= price * (1 + band_pct))
    below_mask = (mid <= price) & (mid >= price * (1 - band_pct))
    if above_mask.any():
        cluster_above = float(mid[above_mask].iloc[notional[above_mask].values.argmax()])
    else:
        cluster_above = price * (1 + band_pct)
    if below_mask.any():
        cluster_below = float(mid[below_mask].iloc[notional[below_mask].values.argmax()])
    else:
        cluster_below = price * (1 - band_pct)

    larger_above = ask_usd > bid_usd * 1.15
    larger_below = bid_usd > ask_usd * 1.15

    return LiquidityFeatures(
        bid_depth_usd=bid_usd,
        ask_depth_usd=ask_usd,
        cluster_above=cluster_above,
        cluster_below=cluster_below,
        larger_above=larger_above,
        larger_below=larger_below,
        band_pct=band_pct,
        note="volume-near-price proxy (backtest; not L2 book)",
    )


def _label_first_hit(
    k5: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry_price: float,
    target_pct: float,
    max_bars: int,
) -> dict:
    """Which side first hits ±target_pct after entry_time (exclusive)."""
    fut = k5[k5["open_time"] > entry_time].head(max_bars)
    up = entry_price * (1 + target_pct / 100.0)
    dn = entry_price * (1 - target_pct / 100.0)
    if fut.empty:
        return {
            "first": "NONE",
            "bars": None,
            "hit_up": False,
            "hit_dn": False,
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
        }

    first = "NONE"
    bars = None
    mfe = 0.0
    mae = 0.0
    for j, row in enumerate(fut.itertuples(index=False), start=1):
        hi = float(row.high)
        lo = float(row.low)
        mfe = max(mfe, (hi - entry_price) / entry_price * 100.0)
        mae = min(mae, (lo - entry_price) / entry_price * 100.0)
        hit_up = hi >= up
        hit_dn = lo <= dn
        if hit_up and hit_dn:
            # Same bar: use which extreme is farther from entry (conservative tie-break: adverse first for 100x)
            # Prefer path that hit first by proximity of open
            o = float(row.open)
            if abs(o - up) <= abs(o - dn):
                first = "UP"
            else:
                first = "DOWN"
            bars = j
            break
        if hit_up:
            first = "UP"
            bars = j
            break
        if hit_dn:
            first = "DOWN"
            bars = j
            break

    return {
        "first": first,
        "bars": bars,
        "hit_up": first == "UP",
        "hit_dn": first == "DOWN",
        "mfe_pct": float(mfe),
        "mae_pct": float(mae),
    }


def run_backtest(
    hist: HistoryBundle | None = None,
    cfg: BacktestConfig | None = None,
    symbol: str = "BTCUSDT",
) -> tuple[pd.DataFrame, dict]:
    cfg = cfg or BacktestConfig()
    hist = hist or load_history(symbol=symbol, days=cfg.days)

    if hist.k15.empty or hist.k5.empty:
        raise RuntimeError("No kline history returned from Binance")

    # Evaluation window: last `days` (exclude pure warmup)
    t_min = hist.k15["open_time"].iloc[-1] - pd.Timedelta(days=cfg.days)
    rows: list[dict] = []

    start_i = max(cfg.warmup_15m, 50)
    last_trade_signal: str | None = None
    last_trade_time: pd.Timestamp | None = None
    dedupe_gap = pd.Timedelta(hours=6)

    for i in range(start_i, len(hist.k15) - 1, max(1, cfg.step)):
        t = hist.k15["open_time"].iloc[i]
        if t < t_min:
            continue
        try:
            structure = _structure_at(hist, i)
            derivatives = _derivatives_at(hist, i)
            liquidity = _liquidity_proxy_at(hist, i)
        except ValueError:
            continue

        if cfg.use_macro:
            now = t.to_pydatetime()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            catalyst = extract_catalyst(override=MacroMode.AUTO, now=now, force=False)
        else:
            catalyst = extract_catalyst(override=MacroMode.LOW, force=False)

        result = score(
            structure,
            derivatives,
            liquidity,
            catalyst,
            leverage=cfg.leverage,
            force=False,
        )

        # Re-gate with cfg.threshold (score() uses module default THRESHOLD).
        if catalyst.force_no_trade:
            signal = "NO TRADE"
        elif result.long_score >= cfg.threshold and result.long_score > result.short_score:
            signal = "LONG"
        elif result.short_score >= cfg.threshold and result.short_score > result.long_score:
            signal = "SHORT"
        else:
            signal = "NO TRADE"

        is_entry = False
        if signal in ("LONG", "SHORT"):
            if cfg.dedupe_signals and last_trade_signal == signal and last_trade_time is not None:
                if (t - last_trade_time) <= dedupe_gap:
                    # Same-side cluster — keep bar for coverage, not a new trade
                    pass
                else:
                    is_entry = True
            else:
                is_entry = True
            if is_entry:
                last_trade_signal = signal
                last_trade_time = t

        lab = _label_first_hit(
            hist.k5,
            entry_time=t,
            entry_price=structure.price,
            target_pct=cfg.target_pct,
            max_bars=cfg.max_horizon_bars_5m,
        )

        liq_pct = liquidation_distance_pct(cfg.leverage)
        trade_signal = signal if is_entry else "NO TRADE"
        if trade_signal == "LONG":
            if lab["first"] == "UP":
                win = True
            elif lab["first"] == "DOWN":
                win = False
            else:
                win = None
        elif trade_signal == "SHORT":
            if lab["first"] == "DOWN":
                win = True
            elif lab["first"] == "UP":
                win = False
            else:
                win = None
        else:
            win = None

        rows.append(
            {
                "time": t,
                "price": structure.price,
                "long_score": result.long_score,
                "short_score": result.short_score,
                "signal": trade_signal,
                "raw_signal": signal,
                "is_entry": is_entry,
                "macro": catalyst.risk_label,
                "first_1pct": lab["first"],
                "bars_to_hit": lab["bars"],
                "mfe_pct": lab["mfe_pct"],
                "mae_pct": lab["mae_pct"],
                "win": win,
                "liq_distance_pct": liq_pct,
                "likely_liquidated": bool(win is False) if is_entry else False,
                "structure": structure.label,
                "cvd": derivatives.cvd_arrow,
                "oi": derivatives.oi_arrow,
            }
        )

    df = pd.DataFrame(rows)
    summary = summarize(df, cfg)
    summary["symbol"] = hist.symbol
    summary["n_k5"] = len(hist.k5)
    summary["n_k15"] = len(hist.k15)
    summary["oi_points"] = len(hist.oi)
    summary["taker_points"] = len(hist.taker)
    summary["funding_points"] = len(hist.funding)
    return df, summary


def summarize(df: pd.DataFrame, cfg: BacktestConfig) -> dict:
    if df.empty:
        return {"n_bars": 0, "error": "no evaluation rows"}

    traded = df[df["signal"].isin(["LONG", "SHORT"])]
    n = len(df)
    n_traded = len(traded)
    coverage = n_traded / n if n else 0.0

    def hit_rate(sub: pd.DataFrame) -> float | None:
        if sub.empty or sub["win"].isna().all():
            return None
        w = sub["win"].dropna()
        return float(w.mean()) if len(w) else None

    # Baseline: always predict the majority first-hit side of all bars
    vc = df["first_1pct"].value_counts(normalize=True)
    baseline_up = float(vc.get("UP", 0.0))
    baseline_dn = float(vc.get("DOWN", 0.0))
    # Always-long hit rate among all labeled bars
    labeled = df[df["first_1pct"].isin(["UP", "DOWN"])]
    always_long = float((labeled["first_1pct"] == "UP").mean()) if len(labeled) else None
    always_short = float((labeled["first_1pct"] == "DOWN").mean()) if len(labeled) else None

    longs = traded[traded["signal"] == "LONG"]
    shorts = traded[traded["signal"] == "SHORT"]

    # Side-aware: if we said LONG and first was UP → win
    return {
        "n_bars": n,
        "n_signals": n_traded,
        "coverage": coverage,
        "threshold": cfg.threshold,
        "target_pct": cfg.target_pct,
        "leverage": cfg.leverage,
        "hit_rate_all_signals": hit_rate(traded),
        "hit_rate_long": hit_rate(longs),
        "hit_rate_short": hit_rate(shorts),
        "n_long": len(longs),
        "n_short": len(shorts),
        "baseline_always_long": always_long,
        "baseline_always_short": always_short,
        "pct_first_up": baseline_up,
        "pct_first_down": baseline_dn,
        "avg_bars_to_hit_signals": float(traded["bars_to_hit"].dropna().mean())
        if n_traded and traded["bars_to_hit"].notna().any()
        else None,
        "liq_rate_at_leverage": float(traded["likely_liquidated"].mean()) if n_traded else None,
        "no_trade_share": float((df["signal"] == "NO TRADE").mean()),
        "start": str(df["time"].iloc[0]),
        "end": str(df["time"].iloc[-1]),
    }


def format_summary(summary: dict, df: pd.DataFrame | None = None) -> str:
    lines = [
        "BTC 1% RADAR BACKTEST",
        f"Symbol:     {summary.get('symbol', '?')}",
        f"Window:     {summary.get('start', '?')} → {summary.get('end', '?')}",
        f"Bars eval:  {summary.get('n_bars', 0)}  |  signals: {summary.get('n_signals', 0)}  "
        f"({100 * summary.get('coverage', 0):.1f}% coverage)",
        f"Threshold:  {summary.get('threshold', THRESHOLD):.0f}/10  |  target ±{summary.get('target_pct', TARGET_PCT)}%",
        "",
        f"Hit rate (signals):  {_pct(summary.get('hit_rate_all_signals'))}",
        f"  LONG  n={summary.get('n_long', 0):>4}  hit={_pct(summary.get('hit_rate_long'))}",
        f"  SHORT n={summary.get('n_short', 0):>4}  hit={_pct(summary.get('hit_rate_short'))}",
        "",
        f"Baseline always LONG:  {_pct(summary.get('baseline_always_long'))}",
        f"Baseline always SHORT: {_pct(summary.get('baseline_always_short'))}",
        f"First-hit mix: UP {100 * summary.get('pct_first_up', 0):.1f}% / "
        f"DOWN {100 * summary.get('pct_first_down', 0):.1f}%",
        "",
        f"Avg bars to ±1% (signals): {summary.get('avg_bars_to_hit_signals')}",
        f"Likely liq @{summary.get('leverage', 100):.0f}x before target: "
        f"{_pct(summary.get('liq_rate_at_leverage'))}",
        f"NO TRADE share: {100 * summary.get('no_trade_share', 0):.1f}%",
        "",
        f"Data: k5={summary.get('n_k5')} k15={summary.get('n_k15')} "
        f"oi={summary.get('oi_points')} taker={summary.get('taker_points')} "
        f"funding={summary.get('funding_points')}",
        "Note: liquidity pillar uses volume-near-price proxy (not live L2). "
        "Derivatives hist ≈30d Binance limit.",
    ]
    if df is not None and not df.empty:
        recent = df[df["signal"].isin(["LONG", "SHORT"])].tail(8)
        if not recent.empty:
            lines.append("")
            lines.append("Recent signals:")
            for r in recent.itertuples(index=False):
                w = "WIN" if r.win else ("LOSS" if r.win is False else "?")
                lines.append(
                    f"  {r.time}  {r.signal:<5}  L{r.long_score:.0f}/S{r.short_score:.0f}  "
                    f"first={r.first_1pct:<4}  {w}"
                )
    return "\n".join(lines)


def _pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{100 * x:.1f}%"
