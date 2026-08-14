#!/usr/bin/env python3
"""
Iterate India price/volume/structure hypotheses with IS/OOS + robustness checks.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from india_edge_engine import (
    DEFAULT_RT_COST,
    DEFAULT_SYMBOLS,
    RESULTS_DIR,
    add_structure_features,
    compute_stats,
    evaluate_strategy,
    fetch_daily,
    fetch_hourly,
    param_perturb,
    run_signal_backtest,
    time_split,
    walk_forward_folds,
)
from india_strategies import DEFAULT_PARAMS, STRATEGIES, h11_hourly_bos_daily_trend

RT_COST = DEFAULT_RT_COST  # 0.08% round-trip


def fmt_stats(s) -> str:
    return (
        f"n={s.n_trades:4d} WR={s.win_rate:5.1%} PF={s.profit_factor:5.2f} "
        f"E={s.expectancy*100:6.3f}% Tot={s.total_return*100:7.1f}% "
        f"MDD={s.max_dd*100:6.1f}% Sh={s.sharpe:5.2f} hold={s.avg_hold:4.1f}d"
    )


def score_candidate(oos) -> float:
    """Higher is better. Penalize low trade count and deep DD."""
    if oos.n_trades < 20:
        return -999.0
    # Prefer positive expectancy, PF>1, enough trades
    score = (
        oos.expectancy * 1000
        + min(oos.profit_factor, 3.0) * 0.5
        + min(oos.n_trades, 200) / 200.0
        + max(oos.max_dd, -0.5) * 2.0  # less negative DD better
        + min(max(oos.sharpe, -2), 3) * 0.3
    )
    if oos.expectancy <= 0:
        score -= 5
    if oos.profit_factor < 1.0:
        score -= 3
    return float(score)


def main():
    symbols = DEFAULT_SYMBOLS
    rows = []
    log_lines = []

    print(f"Round-trip cost assumption: {RT_COST*100:.2f}%")
    print("Fetching / caching daily data...")
    data = {}
    for sym in symbols:
        try:
            df = add_structure_features(fetch_daily(sym))
            data[sym] = df
            print(f"  {sym}: {len(df)} bars {df.index.min().date()} → {df.index.max().date()}")
        except Exception as e:
            print(f"  FAIL {sym}: {e}")

    # ── Pass 1: coarse screen across symbols/params ──────────────────────────
    print("\n=== PASS 1: Coarse hypothesis screen ===")
    for name, builder in STRATEGIES.items():
        for params in DEFAULT_PARAMS[name]:
            for sym, df in data.items():
                try:
                    res = evaluate_strategy(
                        name, sym, df, builder, params, rt_cost=RT_COST, max_hold=30
                    )
                    is_s, oos = res["IS"], res["OOS"]
                    sc = score_candidate(oos)
                    row = {
                        "name": name,
                        "symbol": sym,
                        "params": json.dumps(params),
                        "score": sc,
                        "oos_n": oos.n_trades,
                        "oos_wr": oos.win_rate,
                        "oos_pf": oos.profit_factor,
                        "oos_exp": oos.expectancy,
                        "oos_tot": oos.total_return,
                        "oos_mdd": oos.max_dd,
                        "oos_sharpe": oos.sharpe,
                        "oos_hold": oos.avg_hold,
                        "is_n": is_s.n_trades,
                        "is_exp": is_s.expectancy,
                        "is_pf": is_s.profit_factor,
                    }
                    rows.append(row)
                except Exception:
                    traceback.print_exc()

    screen = pd.DataFrame(rows).sort_values("score", ascending=False)
    screen.to_csv(RESULTS_DIR / "pass1_screen.csv", index=False)
    print("\nTop 25 OOS candidates:")
    print(
        screen.head(25)[
            ["name", "symbol", "params", "oos_n", "oos_exp", "oos_pf", "oos_mdd", "oos_sharpe", "score"]
        ].to_string(index=False)
    )

    log_lines.append("## Pass 1 — coarse screen\n")
    log_lines.append(f"Cost: {RT_COST*100:.2f}% RT | Train 70% / Test 30% | max hold 30 bars\n")
    for _, r in screen.head(15).iterrows():
        log_lines.append(
            f"- **{r['name']}** `{r['symbol']}` params={r['params']} | "
            f"OOS n={r['oos_n']} E={r['oos_exp']*100:.3f}% PF={r['oos_pf']:.2f} "
            f"MDD={r['oos_mdd']*100:.1f}% score={r['score']:.2f}\n"
        )

    # Per-hypothesis summary (best OOS by mean expectancy across liquid names)
    log_lines.append("\n## Per-hypothesis verdict (best symbol OOS)\n")
    for name in STRATEGIES:
        sub = screen[screen["name"] == name]
        if sub.empty:
            continue
        best = sub.iloc[0]
        # Aggregate long-only on indices
        idx_sub = sub[sub["symbol"].isin(["^NSEI", "^NSEBANK", "NIFTYBEES.NS", "BANKBEES.NS"])]
        mean_exp = idx_sub["oos_exp"].mean() if len(idx_sub) else sub["oos_exp"].mean()
        verdict = "PROMISING" if best["oos_exp"] > 0 and best["oos_pf"] > 1.05 and best["oos_n"] >= 40 else "REJECT"
        if best["oos_exp"] > 0 and best["oos_n"] >= 20 and best["oos_pf"] > 1.0:
            verdict = "WEAK/PARTIAL" if verdict == "REJECT" else verdict
        log_lines.append(
            f"- **{name}**: {verdict} — best `{best['symbol']}` OOS E={best['oos_exp']*100:.3f}% "
            f"n={int(best['oos_n'])} PF={best['oos_pf']:.2f}; index mean E={mean_exp*100:.3f}%\n"
        )
        print(f"{name}: {verdict} best={best['symbol']} E={best['oos_exp']*100:.3f}% n={int(best['oos_n'])}")

    # ── Pass 2: refine top families with walk-forward + perturbation ─────────
    print("\n=== PASS 2: Walk-forward + robustness on top candidates ===")
    top_names = (
        screen[screen["oos_n"] >= 30]
        .groupby("name")["score"]
        .max()
        .sort_values(ascending=False)
        .head(6)
        .index.tolist()
    )
    if not top_names:
        top_names = screen.groupby("name")["score"].max().sort_values(ascending=False).head(6).index.tolist()

    refined = []
    for name in top_names:
        builder = STRATEGIES[name]
        # pick best params overall then perturb
        best_row = screen[screen["name"] == name].iloc[0]
        base_params = json.loads(best_row["params"])
        # Also try the default long-biased params
        candidates_params = DEFAULT_PARAMS[name][:2] + [base_params]
        # unique
        uniq = []
        seen = set()
        for p in candidates_params:
            k = tuple(sorted(p.items()))
            if k not in seen:
                seen.add(k)
                uniq.append(p)

        for sym in ["^NSEI", "^NSEBANK", "NIFTYBEES.NS", "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS"]:
            if sym not in data:
                continue
            df = data[sym]
            for params in uniq:
                # Walk-forward
                folds = walk_forward_folds(df, n_folds=5, train_bars=756, test_bars=252)
                oos_stats = []
                for tr, te in folds:
                    # use params as-is (no IS optimization to avoid leak); report OOS folds
                    e, x, side = builder(te, params)
                    trades = run_signal_backtest(te, e, x, side=side, rt_cost=RT_COST, max_hold=30)
                    oos_stats.append(compute_stats(trades, name, sym, "WF", params))

                # Simple IS/OOS
                res = evaluate_strategy(name, sym, df, builder, params, rt_cost=RT_COST, max_hold=30)
                oos = res["OOS"]

                # Perturbation robustness on full OOS window
                train, test = time_split(df, 0.7)
                perturb_keys = [k for k in params if k in ("n", "rvol_min", "gap_min", "squeeze_max", "range_mult", "rvol_max")]
                variants = param_perturb(params, perturb_keys, pct=0.2)
                pert_exps = []
                for vp in variants:
                    e, x, side = builder(test, vp)
                    trds = run_signal_backtest(test, e, x, side=side, rt_cost=RT_COST, max_hold=30)
                    st = compute_stats(trds, name, sym, "PERT", vp)
                    if st.n_trades >= 10:
                        pert_exps.append(st.expectancy)
                frac_pos = float(np.mean([e > 0 for e in pert_exps])) if pert_exps else 0.0
                mean_pert = float(np.mean(pert_exps)) if pert_exps else 0.0

                wf_n = sum(s.n_trades for s in oos_stats)
                wf_rets = []
                for s in oos_stats:
                    # approximate: use expectancy * n as proxy; better re-collect
                    pass
                # Re-run WF collecting all trades
                all_wf_trades = []
                for tr, te in folds:
                    e, x, side = builder(te, params)
                    all_wf_trades.extend(
                        run_signal_backtest(te, e, x, side=side, rt_cost=RT_COST, max_hold=30)
                    )
                wf = compute_stats(all_wf_trades, name, sym, "WF_ALL", params)

                refined.append(
                    {
                        "name": name,
                        "symbol": sym,
                        "params": json.dumps(params),
                        "oos_n": oos.n_trades,
                        "oos_exp": oos.expectancy,
                        "oos_pf": oos.profit_factor,
                        "oos_wr": oos.win_rate,
                        "oos_mdd": oos.max_dd,
                        "oos_sharpe": oos.sharpe,
                        "oos_tot": oos.total_return,
                        "oos_hold": oos.avg_hold,
                        "is_exp": res["IS"].expectancy,
                        "is_pf": res["IS"].profit_factor,
                        "is_n": res["IS"].n_trades,
                        "wf_n": wf.n_trades,
                        "wf_exp": wf.expectancy,
                        "wf_pf": wf.profit_factor,
                        "wf_mdd": wf.max_dd,
                        "wf_sharpe": wf.sharpe,
                        "pert_frac_pos": frac_pos,
                        "pert_mean_exp": mean_pert,
                        "n_folds": len(folds),
                    }
                )
                print(
                    f"{name} {sym} {params} | OOS {fmt_stats(oos)} | "
                    f"WF n={wf.n_trades} E={wf.expectancy*100:.3f}% | pert+={frac_pos:.0%}"
                )

    ref_df = pd.DataFrame(refined).sort_values(
        by=["wf_exp", "oos_exp", "pert_frac_pos"], ascending=False
    )
    ref_df.to_csv(RESULTS_DIR / "pass2_refined.csv", index=False)

    log_lines.append("\n## Pass 2 — walk-forward + ±20% param perturbation\n")
    for _, r in ref_df.head(20).iterrows():
        log_lines.append(
            f"- **{r['name']}** `{r['symbol']}` {r['params']} | "
            f"OOS n={int(r['oos_n'])} E={r['oos_exp']*100:.3f}% PF={r['oos_pf']:.2f} | "
            f"WF n={int(r['wf_n'])} E={r['wf_exp']*100:.3f}% PF={r['wf_pf']:.2f} | "
            f"pert+={r['pert_frac_pos']:.0%} meanE={r['pert_mean_exp']*100:.3f}%\n"
        )

    # ── Pass 3: hourly BOS with daily trend filter ────────────────────────────
    print("\n=== PASS 3: Hourly BOS + daily trend (H11) ===")
    h11_rows = []
    for sym in ["^NSEI", "^NSEBANK", "NIFTYBEES.NS", "RELIANCE.NS", "HDFCBANK.NS"]:
        try:
            daily = data.get(sym) or add_structure_features(fetch_daily(sym))
            hourly = add_structure_features(fetch_hourly(sym))
            # Map daily EMA200 regime onto hourly dates
            d_close = daily[["Close", "ema200"]].copy()
            d_close["trend_long"] = d_close["Close"] > d_close["ema200"]
            # asof merge
            h = hourly.copy()
            h["date"] = pd.to_datetime(h.index.date)
            dtmp = d_close.copy()
            dtmp["date"] = pd.to_datetime(dtmp.index.date)
            h = h.merge(dtmp[["date", "trend_long"]], on="date", how="left")
            h["trend_long"] = h["trend_long"].ffill().fillna(False)
            for rvol_min in (1.3, 1.6, 2.0):
                params = {"rvol_min": rvol_min}
                # Long-only when daily trend long
                h_long = h[h["trend_long"]].copy()
                if len(h_long) < 300:
                    continue
                # Need features on filtered frame — recompute signals on full then mask
                e, x, side = h11_hourly_bos_daily_trend(h, True, params)
                e = e & h["trend_long"]
                train, test = time_split(h, 0.7)
                # Align boolean series
                e_tr, x_tr = e.loc[train.index], x.loc[train.index]
                e_te, x_te = e.loc[test.index], x.loc[test.index]
                tr_trades = run_signal_backtest(train, e_tr, x_tr, side=1, rt_cost=RT_COST, max_hold=24)
                te_trades = run_signal_backtest(test, e_te, x_te, side=1, rt_cost=RT_COST, max_hold=24)
                is_s = compute_stats(tr_trades, "H11_hourly_bos", sym, "IS", params)
                oos = compute_stats(te_trades, "H11_hourly_bos", sym, "OOS", params)
                h11_rows.append(
                    {
                        "name": "H11_hourly_bos",
                        "symbol": sym,
                        "params": json.dumps(params),
                        "oos_n": oos.n_trades,
                        "oos_exp": oos.expectancy,
                        "oos_pf": oos.profit_factor,
                        "oos_wr": oos.win_rate,
                        "oos_mdd": oos.max_dd,
                        "oos_sharpe": oos.sharpe,
                        "is_exp": is_s.expectancy,
                        "is_n": is_s.n_trades,
                    }
                )
                print(f"H11 {sym} {params} | IS {fmt_stats(is_s)} | OOS {fmt_stats(oos)}")
        except Exception:
            traceback.print_exc()

    if h11_rows:
        h11_df = pd.DataFrame(h11_rows).sort_values("oos_exp", ascending=False)
        h11_df.to_csv(RESULTS_DIR / "pass3_hourly.csv", index=False)
        log_lines.append("\n## Pass 3 — Hourly BOS + daily EMA200 trend\n")
        for _, r in h11_df.iterrows():
            log_lines.append(
                f"- `{r['symbol']}` {r['params']} OOS n={int(r['oos_n'])} "
                f"E={r['oos_exp']*100:.3f}% PF={r['oos_pf']:.2f} MDD={r['oos_mdd']*100:.1f}%\n"
            )

    # ── Pass 4: portfolio / multi-symbol for best strategy family ─────────────
    print("\n=== PASS 4: Select winner & multi-symbol OOS ===")
    # Rank: require WF or OOS positive, n>=40 preferred, pert robustness
    if len(ref_df):
        viable = ref_df[
            (ref_df["oos_exp"] > 0)
            & (ref_df["wf_exp"] > 0)
            & (ref_df["oos_n"] >= 25)
            & (ref_df["pert_frac_pos"] >= 0.5)
        ].copy()
        if viable.empty:
            viable = ref_df[(ref_df["oos_exp"] > 0) & (ref_df["oos_n"] >= 20)].copy()
        if viable.empty:
            viable = ref_df.copy()
        winner = viable.iloc[0]
    else:
        winner = screen.iloc[0]

    log_lines.append("\n## Winner selection\n")
    log_lines.append(f"Selected: **{winner['name']}** on `{winner['symbol']}` params={winner['params']}\n")

    # Multi-symbol check for winner family
    w_name = winner["name"]
    w_params = json.loads(winner["params"]) if isinstance(winner["params"], str) else winner["params"]
    builder = STRATEGIES.get(w_name)
    multi = []
    if builder:
        for sym, df in data.items():
            res = evaluate_strategy(w_name, sym, df, builder, w_params, rt_cost=RT_COST, max_hold=30)
            oos = res["OOS"]
            multi.append(
                {
                    "symbol": sym,
                    "oos_n": oos.n_trades,
                    "oos_exp": oos.expectancy,
                    "oos_pf": oos.profit_factor,
                    "oos_wr": oos.win_rate,
                    "oos_mdd": oos.max_dd,
                    "oos_sharpe": oos.sharpe,
                    "is_exp": res["IS"].expectancy,
                }
            )
            print(f"MULTI {w_name} {sym}: OOS {fmt_stats(oos)}")
        multi_df = pd.DataFrame(multi).sort_values("oos_exp", ascending=False)
        multi_df.to_csv(RESULTS_DIR / "winner_multisymbol.csv", index=False)
        pos_frac = (multi_df["oos_exp"] > 0).mean()
        log_lines.append(
            f"\nMulti-symbol OOS positive fraction: {pos_frac:.0%} "
            f"(mean E={multi_df['oos_exp'].mean()*100:.3f}%)\n"
        )
        for _, r in multi_df.iterrows():
            log_lines.append(
                f"- `{r['symbol']}` n={int(r['oos_n'])} E={r['oos_exp']*100:.3f}% "
                f"PF={r['oos_pf']:.2f} MDD={r['oos_mdd']*100:.1f}%\n"
            )

    # Persist research notes fragment
    (RESULTS_DIR / "research_log_fragment.md").write_text("".join(log_lines))
    meta = {
        "rt_cost": RT_COST,
        "winner_name": str(winner["name"]),
        "winner_symbol": str(winner["symbol"]),
        "winner_params": w_params if builder else {},
        "winner_oos_exp": float(winner.get("oos_exp", 0)),
        "winner_oos_n": int(winner.get("oos_n", 0)),
        "winner_wf_exp": float(winner.get("wf_exp", 0)) if "wf_exp" in winner else None,
        "winner_pert_frac": float(winner.get("pert_frac_pos", 0)) if "pert_frac_pos" in winner else None,
    }
    (RESULTS_DIR / "winner_meta.json").write_text(json.dumps(meta, indent=2))
    print("\nWINNER META:", json.dumps(meta, indent=2))
    print(f"Wrote results to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
