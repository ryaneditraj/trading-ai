"""Binance USD-M futures public REST client (no auth)."""

from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd
import requests

FAPI = "https://fapi.binance.com"
DATA = "https://fapi.binance.com/futures/data"
WS_FORCE = "wss://fstream.binance.com/ws/!forceOrder@arr"
DEFAULT_SYMBOL = "BTCUSDT"
TIMEOUT = 15


class BinancePublic:
    def __init__(self, symbol: str = DEFAULT_SYMBOL, session: requests.Session | None = None):
        self.symbol = symbol.upper()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "btc-1pct-radar/0.1"})

    def _get(self, base: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{base}{path}"
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params or {}, timeout=TIMEOUT)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                last_err = exc
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise
        if last_err:
            raise last_err
        raise RuntimeError(f"GET {url} failed")

    @staticmethod
    def _klines_df(raw: list) -> pd.DataFrame:
        cols = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ]
        df = pd.DataFrame(raw, columns=cols)
        for c in ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        return df

    def klines(
        self,
        interval: str,
        limit: int = 200,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {"symbol": self.symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return self._klines_df(self._get(FAPI, "/fapi/v1/klines", params))

    def klines_range(self, interval: str, start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
        """Paginate klines from start_ms to end_ms (or now)."""
        chunks: list[pd.DataFrame] = []
        cursor = start_ms
        end = end_ms or int(time.time() * 1000)
        while cursor < end:
            df = self.klines(interval, limit=1500, start_ms=cursor, end_ms=end)
            if df.empty:
                break
            chunks.append(df)
            last = int(df["open_time"].iloc[-1].value // 10**6)  # ns → ms
            nxt = last + 1
            if nxt <= cursor:
                break
            cursor = nxt
            if len(df) < 1500:
                break
            time.sleep(0.05)
        if not chunks:
            return self._klines_df([])
        out = pd.concat(chunks, ignore_index=True)
        out = out.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
        return out

    def funding_rate_range(self, start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
        """Paginate funding rate history."""
        rows: list[dict[str, Any]] = []
        cursor = start_ms
        end = end_ms or int(time.time() * 1000)
        while cursor < end:
            batch = self._get(
                FAPI,
                "/fapi/v1/fundingRate",
                {"symbol": self.symbol, "startTime": cursor, "endTime": end, "limit": 1000},
            )
            if not batch:
                break
            rows.extend(batch)
            last = int(batch[-1]["fundingTime"])
            nxt = last + 1
            if nxt <= cursor:
                break
            cursor = nxt
            if len(batch) < 1000:
                break
            time.sleep(0.05)
        if not rows:
            return pd.DataFrame(columns=["fundingTime", "fundingRate", "markPrice"])
        df = pd.DataFrame(rows)
        df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
        if "markPrice" in df.columns:
            df["markPrice"] = pd.to_numeric(df["markPrice"], errors="coerce")
        return df.drop_duplicates(subset=["fundingTime"]).sort_values("fundingTime").reset_index(drop=True)

    def futures_data_hist(self, path: str, period: str = "15m", limit: int = 500) -> pd.DataFrame:
        """Fetch /futures/data/* series (Binance keeps ~30 days)."""
        raw = self._get(
            DATA,
            path,
            {"symbol": self.symbol, "period": period, "limit": limit},
        )
        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for c in df.columns:
            if c in ("timestamp", "symbol", "pair", "contractType"):
                continue
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values("timestamp").reset_index(drop=True) if "timestamp" in df.columns else df

    def premium_index(self) -> dict[str, Any]:
        return self._get(FAPI, "/fapi/v1/premiumIndex", {"symbol": self.symbol})

    def funding_rate_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._get(
            FAPI,
            "/fapi/v1/fundingRate",
            {"symbol": self.symbol, "limit": limit},
        )

    def open_interest(self) -> dict[str, Any]:
        return self._get(FAPI, "/fapi/v1/openInterest", {"symbol": self.symbol})

    def open_interest_hist(self, period: str = "15m", limit: int = 30) -> list[dict[str, Any]]:
        return self._get(
            DATA,
            "/openInterestHist",
            {"symbol": self.symbol, "period": period, "limit": limit},
        )

    def global_long_short_ratio(self, period: str = "15m", limit: int = 30) -> list[dict[str, Any]]:
        return self._get(
            DATA,
            "/globalLongShortAccountRatio",
            {"symbol": self.symbol, "period": period, "limit": limit},
        )

    def top_long_short_position_ratio(self, period: str = "15m", limit: int = 30) -> list[dict[str, Any]]:
        return self._get(
            DATA,
            "/topLongShortPositionRatio",
            {"symbol": self.symbol, "period": period, "limit": limit},
        )

    def taker_long_short_ratio(self, period: str = "15m", limit: int = 30) -> list[dict[str, Any]]:
        return self._get(
            DATA,
            "/takerlongshortRatio",
            {"symbol": self.symbol, "period": period, "limit": limit},
        )

    def depth(self, limit: int = 100) -> dict[str, Any]:
        return self._get(FAPI, "/fapi/v1/depth", {"symbol": self.symbol, "limit": limit})

    def force_orders(self, listen_seconds: float = 1.5) -> list[dict[str, Any]]:
        """
        Sample public liquidation stream briefly.
        REST /fapi/v1/allForceOrders is gone (404); WS !forceOrder@arr is public.
        Returns normalized dicts: side, avgPrice, origQty, symbol, time.
        """
        import base64
        import os
        import socket
        import ssl
        from urllib.parse import urlparse

        out: list[dict[str, Any]] = []
        parsed = urlparse(WS_FORCE)
        host = parsed.hostname or "fstream.binance.com"
        path = parsed.path or "/ws/!forceOrder@arr"
        key = base64.b64encode(os.urandom(16)).decode()

        try:
            ctx = ssl.create_default_context()
            sock = socket.create_connection((host, 443), timeout=10)
            ssock = ctx.wrap_socket(sock, server_hostname=host)
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"\r\n"
            )
            ssock.sendall(req.encode())
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = ssock.recv(4096)
                if not chunk:
                    break
                buf += chunk
            if b"101" not in buf.split(b"\r\n", 1)[0]:
                ssock.close()
                return out

            ssock.settimeout(0.35)
            deadline = time.time() + listen_seconds
            acc = b""
            while time.time() < deadline:
                try:
                    chunk = ssock.recv(8192)
                    if not chunk:
                        break
                    acc += chunk
                except socket.timeout:
                    continue
                except Exception:
                    break

                i = 0
                while i + 2 <= len(acc):
                    b1, b2 = acc[i], acc[i + 1]
                    opcode = b1 & 0x0F
                    masked = bool(b2 & 0x80)
                    ln = b2 & 0x7F
                    j = i + 2
                    if ln == 126:
                        if j + 2 > len(acc):
                            break
                        ln = int.from_bytes(acc[j : j + 2], "big")
                        j += 2
                    elif ln == 127:
                        if j + 8 > len(acc):
                            break
                        ln = int.from_bytes(acc[j : j + 8], "big")
                        j += 8
                    if masked:
                        if j + 4 > len(acc):
                            break
                        mask = acc[j : j + 4]
                        j += 4
                    else:
                        mask = b""
                    if j + ln > len(acc):
                        break
                    payload = bytearray(acc[j : j + ln])
                    if mask:
                        for k in range(len(payload)):
                            payload[k] ^= mask[k % 4]
                    i = j + ln
                    if opcode == 0x8:  # close
                        acc = acc[i:]
                        ssock.close()
                        return out
                    if opcode != 0x1:
                        continue
                    try:
                        raw = json.loads(payload.decode())
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    o = raw.get("o") or raw
                    sym = (o.get("s") or "").upper()
                    if sym and sym != self.symbol:
                        continue
                    out.append(
                        {
                            "symbol": sym or self.symbol,
                            "side": o.get("S"),
                            "avgPrice": o.get("ap") or o.get("p"),
                            "origQty": o.get("q"),
                            "time": o.get("T"),
                        }
                    )
                acc = acc[i:]
            ssock.close()
        except Exception:
            return out
        return out

    def mark_price(self) -> float:
        pi = self.premium_index()
        return float(pi["markPrice"])

    def fetch_snapshot(self, liq_listen_seconds: float = 1.5) -> dict[str, Any]:
        """One coherent market snapshot for scoring."""
        k5 = self.klines("5m", 200)
        k15 = self.klines("15m", 200)
        k1d = self.klines("1d", 5)
        premium = self.premium_index()
        oi = self.open_interest()
        oi_hist = self.open_interest_hist("15m", 30)
        funding_hist = self.funding_rate_history(20)
        ls = self.global_long_short_ratio("15m", 30)
        top_ls = self.top_long_short_position_ratio("15m", 30)
        taker = self.taker_long_short_ratio("15m", 30)
        book = self.depth(100)
        forces = self.force_orders(listen_seconds=liq_listen_seconds)
        return {
            "symbol": self.symbol,
            "fetched_at": time.time(),
            "k5": k5,
            "k15": k15,
            "k1d": k1d,
            "premium": premium,
            "oi": oi,
            "oi_hist": oi_hist,
            "funding_hist": funding_hist,
            "long_short": ls,
            "top_long_short": top_ls,
            "taker": taker,
            "depth": book,
            "force_orders": forces,
        }
