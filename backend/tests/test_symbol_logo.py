"""Symbol logos: validation, SVG safety, the exact-match rule, and the cache."""

import asyncio
import os
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import market_public
from app.services import symbol_logo_service as logo

TV_FILE = (
    b'<!-- by TradingView --><svg width="18" height="18" xmlns="http://www.w3.org/2000/svg">'
    b'<path fill="#F0B90B" d="M0 0h18v18H0z"/></svg>'
)


# ── symbol validation ────────────────────────────────────────────────────


@pytest.mark.parametrize("sym", ["M&M", "BAJAJ-AUTO", "RELIANCE", "NIFTY 50", "nifty bank", "3MINDIA"])
def test_real_symbols_are_accepted(sym):
    assert logo.normalize(sym) is not None


@pytest.mark.parametrize(
    "sym", ["../etc/passwd", "..", "a/b", "A\\B", "RELIANCE.svg", "", "X" * 25, "NIFTY%2F", "A\x00B"]
)
def test_anything_that_could_walk_the_filesystem_is_rejected(sym):
    assert logo.normalize(sym) is None


def test_a_bad_symbol_never_touches_the_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(logo, "CACHE_DIR", tmp_path / "cache")

    async def boom(_):
        raise AssertionError("must not fetch")

    monkeypatch.setattr(logo, "_fetch", boom)
    body, _ = asyncio.run(logo.get_logo("../etc/passwd"))
    assert body is None
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize(
    ("sym", "key"),
    [
        ("NIFTY25OCTFUT", "NIFTY"),
        ("NIFTY25OCT25000CE", "NIFTY"),
        ("SENSEX26O0169800CE", "SENSEX"),       # weekly: year, month letter, day
        ("BANKNIFTY2510950000PE", "BANKNIFTY"),
        ("M&M25OCTFUT", "M&M"),
        ("NIFTYNXT5025OCTFUT", "NIFTYNXT50"),    # an underlying with digits in it
        ("GOLDM25DECFUT", "GOLDM"),
        ("BTC-260922-76000-C", "BTCUSD"),
        ("NIFTY 50", "NIFTY50"),
        ("RELIANCE", "RELIANCE"),
    ],
)
def test_every_contract_shares_its_underlyings_logo(sym, key):
    assert logo.normalize(sym) == key


# ── things that are not companies ────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "logoid"),
    [
        ("NIFTY", "indices/nifty-50"),
        ("NIFTY50", "indices/nifty-50"),
        ("NIFTYBANK", "indices/nifty-bank-index"),
        ("BANKNIFTY", "indices/nifty-bank-index"),
        ("SENSEX", "indices/bse-sensex"),
        ("GOLD", "metal/gold"),
        ("XAUUSD", "metal/gold"),
        ("CRUDEOIL", "crude-oil"),
        ("EURUSD", "country/EU"),
        ("USDINR", "country/US"),
        ("BTCUSD", "crypto/XTVCBTC"),
        ("ETHUSDT", "crypto/XTVCETH"),
        ("NAS100", "indices/nasdaq-100"),
    ],
)
def test_indices_metals_currencies_and_coins_are_mapped_by_hand(key, logoid):
    assert logo.fixed_logoid(key) == logoid


@pytest.mark.parametrize("key", ["RELIANCE", "HDFCBANK", "M&M", "GOLDBEES", "TCS"])
def test_a_company_is_not_mapped_by_hand(key):
    assert logo.fixed_logoid(key) is None


def test_an_index_never_reaches_a_stock_source(monkeypatch):
    seen = []

    class FakeClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, **_):
            seen.append(url)
            return httpx.Response(200, content=TV_FILE)

    monkeypatch.setattr(logo.httpx, "AsyncClient", FakeClient)
    assert asyncio.run(logo._fetch("NIFTY")) == TV_FILE
    assert seen == ["https://s3-symbol-logo.tradingview.com/indices/nifty-50.svg"]


# ── SVG safety ───────────────────────────────────────────────────────────


def test_a_tradingview_file_with_its_leading_comment_is_safe():
    assert logo.is_safe_svg(TV_FILE)


def test_an_xml_prolog_is_allowed():
    assert logo.is_safe_svg(b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="x"></svg>')


@pytest.mark.parametrize(
    "body",
    [
        b'<svg xmlns="x"><script>alert(1)</script></svg>',
        b'<svg xmlns="x"><svg:script>alert(1)</svg:script></svg>',
        b'<svg xmlns="x" onload="alert(1)"></svg>',
        b'<svg/onload=alert(1)>',
        b'<svg xmlns="x"><a href="javascript:alert(1)"><path/></a></svg>',
        b'<svg xmlns="x"><foreignObject><div/></foreignObject></svg>',
        b'<svg xmlns="x"><iframe src="x"/></svg>',
        b'<svg xmlns="x"><embed src="x"/></svg>',
        b'<svg xmlns="x"><object data="x"/></svg>',
    ],
)
def test_anything_that_can_run_is_rejected(body):
    assert not logo.is_safe_svg(body)


def test_an_oversized_file_is_rejected():
    big = b'<svg xmlns="x"><path d="' + b"M0 0" * 60_000 + b'"/></svg>'
    assert len(big) > logo.MAX_SVG_BYTES
    assert not logo.is_safe_svg(big)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<html><svg></svg></html>",
        b'<!DOCTYPE svg [<!ENTITY x "y">]><svg></svg>',
        b"<?xml version='1.0'?><Error><Code>AccessDenied</Code></Error>",
        b"\xff\xfe<svg></svg>",
    ],
)
def test_a_file_that_is_not_an_svg_at_its_root_is_rejected(body):
    assert not logo.is_safe_svg(body)


# ── the exact-match rule ─────────────────────────────────────────────────


def test_only_the_exact_symbol_is_taken_never_the_first_fuzzy_hit():
    payload = {
        "symbols": [
            {"symbol": "<em>TATAMOTORS</em>DVR", "logoid": "tata-motors-dvr"},
            {"symbol": "<em>TATAMOTORS</em>", "logoid": "tata-motors"},
        ]
    }
    assert logo.pick_logoid(payload, "TATAMOTORS") == "tata-motors"


def test_a_delisted_ticker_gets_nothing_rather_than_someone_elses_logo():
    payload = {"symbols": [{"symbol": "<em>HDFC</em>BANK", "logoid": "hdfc-bank"}]}
    assert logo.pick_logoid(payload, "HDFC") is None


def test_tradingviews_placeholder_flag_is_not_a_logo():
    payload = {"symbols": [{"symbol": "SNXT50", "logoid": "country/IN"}]}
    assert logo.pick_logoid(payload, "SNXT50") is None


@pytest.mark.parametrize("payload", [None, [], {}, {"symbols": None}, {"symbols": ["x", 1]}])
def test_a_malformed_search_reply_gives_nothing(payload):
    assert logo.pick_logoid(payload, "TCS") is None


def test_a_logoid_that_could_steer_the_url_is_refused():
    payload = {"symbols": [{"symbol": "TCS", "logoid": "../../evil?x="}]}
    assert logo.pick_logoid(payload, "TCS") is None


# ── the cache ────────────────────────────────────────────────────────────


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(logo, "CACHE_DIR", tmp_path)
    calls = []

    def use(result):
        async def fake(key):
            calls.append(key)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(logo, "_fetch", fake)

    return tmp_path, calls, use


def test_a_found_logo_is_fetched_once_and_then_served_from_disk(cache):
    path, calls, use = cache
    use(TV_FILE)
    assert asyncio.run(logo.get_logo("NIFTY25OCTFUT")) == (TV_FILE, logo.MAX_AGE_SEC)
    assert asyncio.run(logo.get_logo("NIFTY25OCT25000CE")) == (TV_FILE, logo.MAX_AGE_SEC)
    assert asyncio.run(logo.get_logo("NIFTY")) == (TV_FILE, logo.MAX_AGE_SEC)
    assert calls == ["NIFTY"]
    assert (path / "NIFTY.svg").read_bytes() == TV_FILE
    assert not list(path.glob("*.partial"))


def test_a_miss_is_remembered_for_a_day(cache):
    path, calls, use = cache
    use(None)
    assert asyncio.run(logo.get_logo("ZZZNOPE")) == (None, logo.MAX_AGE_SEC)
    assert asyncio.run(logo.get_logo("ZZZNOPE")) == (None, logo.MAX_AGE_SEC)
    assert calls == ["ZZZNOPE"]
    assert (path / "ZZZNOPE.missing").is_file()


def test_a_day_old_miss_is_asked_again(cache):
    path, calls, use = cache
    use(None)
    asyncio.run(logo.get_logo("ZZZNOPE"))
    old = time.time() - logo.MAX_AGE_SEC - 5
    os.utime(path / "ZZZNOPE.missing", (old, old))
    use(TV_FILE)
    assert asyncio.run(logo.get_logo("ZZZNOPE"))[0] == TV_FILE
    assert not (path / "ZZZNOPE.missing").exists()


def test_an_unreachable_vendor_is_retried_in_minutes_not_a_day(cache):
    path, calls, use = cache
    use(httpx.ConnectTimeout("slow"))
    assert asyncio.run(logo.get_logo("TCS")) == (None, logo.RETRY_AFTER_SEC)
    age_left = logo.MAX_AGE_SEC - (time.time() - (path / "TCS.missing").stat().st_mtime)
    assert 0 < age_left <= logo.RETRY_AFTER_SEC + 1


# ── the endpoint ─────────────────────────────────────────────────────────


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(market_public.router, prefix="/api/v1")
    return TestClient(app)


def test_the_endpoint_serves_svg_with_a_sandbox_and_a_day_of_cache(client, monkeypatch):
    async def found(_):
        return TV_FILE, logo.MAX_AGE_SEC

    monkeypatch.setattr(logo, "get_logo", found)
    r = client.get("/api/v1/market/logo/M%26M")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/svg+xml"
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_missing_logo_is_a_cached_404(client, monkeypatch):
    async def missing(_):
        return None, logo.MAX_AGE_SEC

    monkeypatch.setattr(logo, "get_logo", missing)
    r = client.get("/api/v1/market/logo/ZZZNOPE")
    assert r.status_code == 404
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert "sandbox" in r.headers["content-security-policy"]
