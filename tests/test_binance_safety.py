"""Guards for the public Binance client. No network."""

import requests

import pytest

from btc_radar.binance import (
    BinancePublic,
    WebSocketProtocolError,
    _MAX_WS_BUFFER,
    _absorb_ws,
    _pop_ws_frames,
)


class _Resp:
    def __init__(self, status: int, body=None):
        self.status_code = status
        self._body = {} if body is None else body
        self.headers = {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Session:
    def __init__(self, response: _Resp):
        self.headers: dict = {}
        self.response = response
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None, allow_redirects=True):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        return self.response


def _frame(payload: bytes, masked: bool = False) -> bytes:
    mask_bit = 0x80 if masked else 0
    length = len(payload)
    if length < 126:
        header = bytes([0x81, mask_bit | length])
    else:
        header = bytes([0x81, mask_bit | 126]) + length.to_bytes(2, "big")
    if not masked:
        return header + payload
    mask = b"\x01\x02\x03\x04"
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return header + mask + body


def test_symbol_is_normalized():
    client = BinancePublic(" btcusdt ")
    assert client.symbol == "BTCUSDT"


@pytest.mark.parametrize("symbol", ["BTC/USDT", "../BTCUSDT", "BTCUSDT;id", "", "A" * 31])
def test_symbol_rejects_unexpected_characters(symbol):
    with pytest.raises(ValueError):
        BinancePublic(symbol)


def test_get_refuses_redirects_and_does_not_follow_them():
    session = _Session(_Resp(302, {"ok": False}))
    client = BinancePublic(session=session)
    with pytest.raises(RuntimeError, match="redirect"):
        client.premium_index()
    assert session.calls[0]["allow_redirects"] is False


def test_get_explains_http_451():
    session = _Session(_Resp(451, {"code": 0, "msg": "restricted"}))
    client = BinancePublic(session=session)
    with pytest.raises(RuntimeError, match="451"):
        client.premium_index()


def test_get_returns_json_body():
    session = _Session(_Resp(200, {"markPrice": "1"}))
    client = BinancePublic(session=session)
    assert client.premium_index()["markPrice"] == "1"


def test_klines_reject_unknown_interval_before_request():
    session = _Session(_Resp(200, []))
    client = BinancePublic(session=session)
    with pytest.raises(ValueError, match="interval"):
        client.klines("1m;drop")
    assert session.calls == []


@pytest.mark.parametrize("path", ["../admin", "https://evil.example", "/openInterestHist?x=1", "openInterestHist"])
def test_futures_data_path_is_a_single_segment(path):
    session = _Session(_Resp(200, []))
    client = BinancePublic(session=session)
    with pytest.raises(ValueError):
        client.futures_data_hist(path)
    assert session.calls == []


def test_known_futures_path_is_allowed():
    session = _Session(_Resp(200, []))
    client = BinancePublic(session=session)
    frame = client.futures_data_hist("/openInterestHist")
    assert frame.empty
    assert session.calls[0]["url"].endswith("/openInterestHist")


def test_text_frame_round_trip_masked_and_plain():
    payload = b'{"o":{"s":"BTCUSDT","S":"SELL","ap":"100","q":"0.1","T":1}}'
    for masked in (False, True):
        frames, rest = _pop_ws_frames(_frame(payload, masked=masked))
        assert rest == b""
        assert frames == [(0x1, payload)]


def test_incomplete_frame_is_kept():
    payload = b'{"e":"forceOrder"}'
    raw = _frame(payload)
    frames, rest = _pop_ws_frames(raw[:4])
    assert frames == []
    assert rest == raw[:4]


def test_declared_length_above_cap_raises_without_a_body():
    short = bytes([0x81, 126]) + (2_000).to_bytes(2, "big")
    with pytest.raises(WebSocketProtocolError):
        _pop_ws_frames(short, max_payload=1_000)
    huge = bytes([0x81, 127]) + (70_000).to_bytes(8, "big")
    with pytest.raises(WebSocketProtocolError):
        _pop_ws_frames(huge)


def test_buffer_cap_raises():
    with pytest.raises(WebSocketProtocolError):
        _absorb_ws(b"x" * _MAX_WS_BUFFER, b"y")
