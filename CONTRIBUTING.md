# Contributing

Thanks for looking at BTC 1% Radar. Issues and pull requests are welcome, especially when they make a score easier to disagree with or a research result harder to overfit.

## Ground rules

- This is research software. It does not place orders. Please don't send patches that wire in live execution, broker keys, or "just this once" shortcuts around the NO TRADE gate.
- Nothing here is financial advice. Don't market a change as a profit claim.
- Keep secrets out of the diff. No API keys, `.env` files, or account screenshots. See [SECURITY.md](SECURITY.md).

## Setup

```bash
git clone https://github.com/ryaneditraj/trading-ai.git
cd trading-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
python -m btc_radar --demo --macro low
```

Python 3.11 or newer. Tests are offline and must stay that way: do not add a test that calls Binance or Yahoo.

## What to change

| Area | Guidance |
|------|----------|
| `btc_radar/` | Product code. A scoring change needs a unit test that shows the point, the threshold, or the warning. |
| `strategies/nifty_edge_paper.py` and `pinescript/` | Paper sleeve and TradingView ports. Keep them aligned, or say why they diverged. |
| `strategies/nifty_edge_r*.py` | Dated research iterations. Prefer a new file over silently editing an old pass. |
| `research/nifty_edge_8h/` | Locked campaign notes. Don't rewrite history to make a sleeve look cleaner. |

Match the style of the file you touch. There is no formatter gate. Prefer small diffs.

## Pull requests

1. Describe what changed and how you checked it.
2. Run `pytest` and paste the result, or say why you could not.
3. If you changed the ASCII card, run `python -m btc_radar --demo --macro low` and mention it.
4. Screenshots in `docs/screenshots/` must be real runs. Don't draw a mock card.

## Reporting bugs

Use the bug template. Include the command, the Python version, and whether you used `--demo` or the live API. Binance returns HTTP 451 from some regions; that is an eligibility block, not a crash in this repo.

## Code of conduct

Participation is covered by the [Contributor Covenant](CODE_OF_CONDUCT.md).
