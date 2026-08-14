# Days60-Skip Live Log — Research A vs Paper A

**Created:** 2026-08-04 19:40 UTC (Block 11)
**FINAL LOCK:** 2026-08-05 — continue appending live rows until n≥20. See `FINAL_REPORT.md`.
**Purpose:** Record every signal where Paper A would enter but Research A skips
because `nifty_days_since_high > 60`. Accumulate until **n≥20** before treating
save-rate as soft evidence.

**Roles**
- Paper A (trade): `B6_ST_kill40_dd_nifty_mom_m04` — **no** days60 gate
- Research A (monitor): `B7_ST_kill40_dd_mom_days60` — days≤60 gate ON

## How to record (until n≥20)

1. After daily signal pass, list Paper A entry candidates (next-open fills).
2. For each candidate, compute causal `nifty_days_since_high` on signal bar.
3. If days > 60 → Research would skip. Log a row **even if** you still take the
   Paper A fill (you should — Paper A is primary).
4. When the Paper A trade exits, fill `exit_date`, `ret_%`, `W/L`.
5. **Save-rate** = losers among skips / n_skips. Target ≥50% once n≥20.
6. Do **not** flip Research→Paper on thin-n. Do **not** add new gates.

### Row fields
| Field | Meaning |
|-------|---------|
| date_signal | Signal bar (close) that triggered Paper entry |
| symbol | Ticker |
| days_since_high | Causal Nifty days since prior high |
| paper_entry | Next-open fill date |
| paper_exit | Exit date (or open) |
| ret_% | Paper trade return after 0.08% RT |
| W/L | Winner if ret>0 |
| notes | Optional (halt, gap, data issue) |

## Historical OOS skips (thin — provisional)

Hist n=1 save-rate=100% — **n=1 skips — rates provisional; do not treat save-rate as confirmatory until n≥20 live+hist combined.**

| date_signal | symbol | days_since_high | paper_entry | paper_exit | ret_% | W/L | notes |
|-------------|--------|----------------:|-------------|------------|------:|:---:|-------|
| 2022-01-14 | WIPRO.NS | 62 | 2022-01-17 | 2022-01-24 | -10.37% | L | hist OOS |

## Live log (append below)

| date_signal | symbol | days_since_high | paper_entry | paper_exit | ret_% | W/L | notes |
|-------------|--------|----------------:|-------------|------------|------:|:---:|-------|
| YYYY-MM-DD | TICKER.NS | | | | | | |

**Running tally:** hist_n=1 + live_n=0 → combined=**1** (need ≥20).
**Promote Research→Paper only if:** dual-clear lastWF **strictly >** Paper lastWF
OR held-out clear win + ladder + boot — never on skip-rate alone while n<20.
