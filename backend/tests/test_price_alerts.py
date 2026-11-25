"""Price alerts fire once the live price reaches the target.

Client request 25 Nov 2026: a notification on the phone when the price is
reached. Before this nothing compared an alert with the market at all (4
alerts on production, none ever triggered).

Pinned here:
  * LTP_ABOVE fires at LTP >= target, LTP_BELOW at LTP <= target;
  * nothing fires while the alert's market is shut, or with no live price;
  * an alert fires ONCE — only the scan that wins the claim notifies;
  * a notification failure never stops the other parts or the scan;
  * the loop runs on the feed leader beside the pending-order poller.
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.alert import AlertType
from app.services import market_data_service, matching_engine
from app.services import price_alert_service as pas

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _alert(aid, token="111", alert_type=AlertType.LTP_ABOVE, target="100", note=None, symbol="GOLD26DECFUT"):
    return SimpleNamespace(
        id=aid,
        user_id="u1",
        instrument=SimpleNamespace(token=token, symbol=symbol, trading_symbol=symbol, segment="MCX_FUT"),
        alert_type=alert_type,
        target_price=target,
        note=note,
    )


# ── The rule ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("kind", "ltp", "target", "expected"),
    [
        ("LTP_ABOVE", "100", "100", True),
        ("LTP_ABOVE", "100.05", "100", True),
        ("LTP_ABOVE", "99.95", "100", False),
        ("LTP_BELOW", "100", "100", True),
        ("LTP_BELOW", "99.95", "100", True),
        ("LTP_BELOW", "100.05", "100", False),
        ("PERCENT_CHANGE", "500", "100", False),
    ],
)
def test_reached(kind, ltp, target, expected):
    assert pas.reached(kind, Decimal(ltp), Decimal(target)) is expected


def test_amounts_use_indian_grouping():
    assert pas._fmt(Decimal("120750")) == "1,20,750"
    assert pas._fmt(Decimal("120762.50")) == "1,20,762.5"
    assert pas._fmt(Decimal("101")) == "101"
    assert pas._fmt(Decimal("12345678.9")) == "1,23,45,678.9"


def test_message_names_the_symbol_target_ltp_and_note():
    a = _alert("a1", alert_type=AlertType.LTP_BELOW, note="Kuch nahi")
    title, body = pas.alert_message(a, Decimal("120650"), Decimal("120640"))
    assert "GOLD26DECFUT" in title
    assert body.startswith("GOLD26DECFUT fell below ₹1,20,650 — LTP ₹1,20,640")
    assert body.endswith("Note: Kuch nahi")


# ── One scan ─────────────────────────────────────────────────────────
@pytest.fixture
def scan(monkeypatch):
    """`scan_once` with the DB, the market gate, prices and notifying faked."""
    st = {
        "rows": [], "closed": set(), "ltp": {}, "claim_ok": True,
        "claimed": [], "notified": [], "query": None,
    }

    class _Find:
        def __init__(self, q):
            st["query"] = q

        async def to_list(self):
            return st["rows"]

    async def gate(rows):
        return lambda a: a.id in st["closed"]

    async def claim(a, ltp):
        st["claimed"].append((a.id, ltp))
        return st["claim_ok"]

    async def notify(a, target, ltp):
        st["notified"].append((a.id, target, ltp))

    monkeypatch.setattr(pas.PriceAlert, "find", staticmethod(lambda q: _Find(q)))
    monkeypatch.setattr(matching_engine, "resting_order_closed_gate", gate)
    monkeypatch.setattr(market_data_service, "get_ltp_live", lambda tok: st["ltp"].get(tok))
    monkeypatch.setattr(pas, "_claim", claim)
    monkeypatch.setattr(pas, "_notify", notify)
    return st


def _run():
    return asyncio.run(pas.scan_once())


def test_only_active_untriggered_price_alerts_are_read(scan):
    _run()
    q = scan["query"]
    assert q["is_active"] is True and q["is_triggered"] is False
    assert set(q["alert_type"]["$in"]) == {"LTP_ABOVE", "LTP_BELOW"}


def test_fires_when_reached_and_not_otherwise(scan):
    scan["rows"] = [
        _alert("up-hit", token="1", target="100"),
        _alert("up-miss", token="2", target="100"),
        _alert("down-hit", token="3", alert_type=AlertType.LTP_BELOW, target="50"),
    ]
    scan["ltp"] = {"1": Decimal("100.5"), "2": Decimal("99"), "3": Decimal("49.95")}
    assert _run() == 2
    assert [n[0] for n in scan["notified"]] == ["up-hit", "down-hit"]
    assert scan["notified"][0][1:] == (Decimal("100"), Decimal("100.5"))


def test_market_closed_never_fires(scan):
    scan["rows"] = [_alert("a1", token="1", target="100")]
    scan["ltp"] = {"1": Decimal("150")}
    scan["closed"] = {"a1"}
    assert _run() == 0
    assert scan["claimed"] == []


@pytest.mark.parametrize("ltp", [None, Decimal("0")])
def test_no_live_price_never_fires(scan, ltp):
    scan["rows"] = [_alert("a1", token="1", alert_type=AlertType.LTP_BELOW, target="100")]
    scan["ltp"] = {"1": ltp}
    assert _run() == 0
    assert scan["claimed"] == []


@pytest.mark.parametrize("target", [None, "0", "junk"])
def test_no_usable_target_never_fires(scan, target):
    scan["rows"] = [_alert("a1", token="1", target=target)]
    scan["ltp"] = {"1": Decimal("150")}
    assert _run() == 0


def test_lost_claim_sends_nothing(scan):
    """Another scan (a leader hand-over) already fired it: no second message."""
    scan["rows"] = [_alert("a1", token="1", target="100")]
    scan["ltp"] = {"1": Decimal("150")}
    scan["claim_ok"] = False
    assert _run() == 0
    assert scan["claimed"] and scan["notified"] == []


def test_one_bad_alert_does_not_stop_the_rest(scan, monkeypatch):
    scan["rows"] = [_alert("bad", token="1", target="100"), _alert("good", token="2", target="100")]
    scan["ltp"] = {"1": Decimal("150"), "2": Decimal("150")}

    async def claim(a, ltp):
        if a.id == "bad":
            raise RuntimeError("db hiccup")
        return True

    monkeypatch.setattr(pas, "_claim", claim)
    assert _run() == 1
    assert [n[0] for n in scan["notified"]] == ["good"]


def test_claim_is_one_conditional_update():
    src = inspect.getsource(pas._claim)
    assert '{"_id": a.id, "is_active": True, "is_triggered": False}' in src
    assert "res.modified_count == 1" in src


# ── Notifying ────────────────────────────────────────────────────────
def test_notify_sends_bell_live_event_and_push_even_if_one_fails(monkeypatch):
    from app.core import redis_client
    from app.models import notification as notif_mod
    from app.services import push_service

    sent: dict = {}

    class _Notif:
        def __init__(self, **kw):
            sent["bell"] = kw

        async def insert(self):
            raise RuntimeError("mongo down")  # bell fails; the rest must still go

    async def publish(channel, payload):
        sent["live"] = (channel, payload)

    async def push(user_id, **kw):
        sent["push"] = (user_id, kw)

    monkeypatch.setattr(notif_mod, "Notification", _Notif)
    monkeypatch.setattr(redis_client, "publish", publish)
    monkeypatch.setattr(push_service, "send_to_user", push)

    a = _alert("a1", target="100")
    asyncio.run(pas._notify(a, Decimal("100"), Decimal("100.5")))
    assert sent["bell"]["type"].value == "PRICE_ALERT"
    channel, payload = sent["live"]
    assert channel == "user:u1:alerts" and payload["type"] == "price_alert"
    assert payload["alert_id"] == "a1" and payload["ltp"] == "100.5"
    user_id, kw = sent["push"]
    assert user_id == "u1" and kw["url"] == "/alerts" and kw["tag"] == "price-alert-a1"


# ── Wiring ───────────────────────────────────────────────────────────
def test_loop_rides_the_feed_leader_beside_the_poller():
    src = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    poller = src.index('"pending_order_poller",\n                        _partial(pending_order_poller')
    alerts = src.index('_supervise("price_alert_loop", _partial(price_alert_loop, interval_sec=1.0))')
    feed_end = src.index('_supervise("feed", _leader_only("feed", _feed_leader_main))')
    assert poller < alerts < feed_end


def test_user_ws_hub_forwards_the_alerts_channel():
    """The hub only forwards topics on its allow-list; "alerts" must be on it
    or the in-app toast never reaches the user."""
    from app.core.ws_hub import user_channel_hub

    assert user_channel_hub._route_keys("user:u1:alerts", {}) == ["u1"]
