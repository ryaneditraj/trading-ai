# Security policy

BTC 1% Radar is a local command-line tool and a research lab. It is not a hosted service. It does not take API keys, and it does not place orders.

## Reporting a vulnerability

Open a [private GitHub security advisory](https://github.com/ryaneditraj/trading-ai/security/advisories/new).

Please do not file a public issue for a vulnerability, and do not paste keys, session cookies, or account identifiers. A report that includes a failing test or a minimal traceback is enough.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x on `main` | Yes |

## Secrets

No API keys, tokens, or passwords are required. The Binance client calls public market-data endpoints only. `.env` is gitignored. `.env.example` documents that the commented base-URL and calendar variables are **not read**, so a local env file cannot point the client at another host.

If you fork the project and add credentials, keep them in the environment or in `.env`, never in source. This repository does not rewrite git history. If a secret is ever committed, rotate it at the provider. As of the audit on 23 October 2026, no secret was found in the tree or in git history.

## Hardening already in the client

- Symbol, kline interval, and `/futures/data` paths are allow-listed before a request is sent.
- HTTP redirects are not followed.
- HTTP 451 (Binance's restricted-location response) raises a clear error and points at `--demo`.
- The public liquidation WebSocket rejects frame lengths above 64 KiB and buffers above 256 KiB, and it only dials `fstream.binance.com` over TLS with certificate verification.
- Order-book rows and force-order payloads that are not the expected shape are skipped.
- Nifty and GIFT research caches can only be written as a single filename inside `research/data/`.

## Dependency audit

`pip-audit` reported no known vulnerabilities on 23 October 2026 for `requirements.txt` and for a fresh install of that file (requests 2.34.2, urllib3 2.8.0, yfinance 1.7.0, pandas 3.1.0, numpy 2.5.4, pyarrow 26.0.0). Versions in `requirements.txt` are minimums, not a lockfile. GitHub Actions runs `pip-audit` on pull requests, and Dependabot opens update PRs.

## Residual risk

- Binance and Yahoo Finance are third parties. Their responses are treated as market data, not as instructions. TLS is verified. A proxy or CA that **you** installed can still see traffic; the client does not send credentials.
- The liquidation client is a small sampler, not a full WebSocket stack. It does not reassemble fragmented messages and it does not answer pings. Those misses show up as a quiet liquidation line, not as a fabricated print.
- `--watch` hits public endpoints on every refresh. Keep the interval in seconds, not a tight loop.
- `--csv` writes the path you pass. Point it at a file you meant to create.
- Research code reads parquet caches it previously wrote. Do not drop untrusted `.parquet` files into `research/data/` (a malicious parquet is a parser problem, not a ticker).
- `macro_events.json` is a hand-maintained estimate of CPI, NFP, and FOMC windows. It is not an official calendar and it is not a secret.
- There is no web UI, so there is no XSS surface in this repository. There is no SQL database and no `eval` / `pickle` / `shell=True` path.

Signals are research output. A bug in the scorer can still be wrong about the market. That is a model risk, and it belongs in a normal issue unless it is a security bug.
