"""Each announcement can have its own strip colour (client request, Nov 2026).

Before, the strip had one colour pair for every line. Now a line may carry its
own `bg_color` / `text_color`; a line without them keeps the strip colours.
Users get the colours per line in `items`; the plain `messages` list stays
for any client that predates this."""

from __future__ import annotations

from types import SimpleNamespace as Namespace

import pytest
from beanie import init_beanie
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError

from app.api.v1.admin import ticker as admin_ticker
from app.api.v1.user import ticker as user_ticker
from app.models.platform_setting import PlatformSetting
from app.models.ticker_message import TickerMessage


def test_line_colours_must_be_hex():
    ok = admin_ticker.TickerPayload(text="Ban scrips today", bg_color="#c0392b", text_color="#FFFFFF")
    assert (ok.bg_color, ok.text_color) == ("#c0392b", "#FFFFFF")
    # Written straight into users' pages as CSS, so nothing looser is accepted.
    for bad in ("red", "#fff", "rgb(1,2,3)", "url(x)", "#12345g"):
        with pytest.raises(ValidationError):
            admin_ticker.TickerPayload(text="x", bg_color=bad)


def test_no_colour_means_the_strip_colours():
    p = admin_ticker.TickerPayload(text="Play Nifty UP/DOWN")
    assert (p.bg_color, p.text_color) == (None, None)


@pytest.fixture
async def db(monkeypatch):
    await init_beanie(
        database=AsyncMongoMockClient()["ticker_colours_test"],
        document_models=[TickerMessage, PlatformSetting],
    )

    async def no_audit(**_k):
        return None

    monkeypatch.setattr(admin_ticker, "log_event", no_audit)


async def test_colours_are_saved_edited_and_cleared(db):
    sa = Namespace(id=ObjectId())
    made = (await admin_ticker.create_ticker(
        admin_ticker.TickerPayload(text="Ban Scrips Today - KAYNES", bg_color="#c0392b"), sa
    )).data
    assert (made["bg_color"], made["text_color"]) == ("#c0392b", None)

    edited = (await admin_ticker.update_ticker(
        made["id"],
        admin_ticker.TickerPayload(
            text="Ban Scrips Today - KAYNES", bg_color="#1e8449", text_color="#000000"
        ),
        sa,
    )).data
    assert (edited["bg_color"], edited["text_color"]) == ("#1e8449", "#000000")

    cleared = (await admin_ticker.update_ticker(
        made["id"], admin_ticker.TickerPayload(text="Ban Scrips Today - KAYNES"), sa
    )).data
    assert (cleared["bg_color"], cleared["text_color"]) == (None, None)


async def test_users_get_each_lines_colours_and_the_old_list(db):
    await TickerMessage(text="Ban Scrips Today - KAYNES", sort_order=1, bg_color="#c0392b").insert()
    await TickerMessage(text="Try Nifty Number Earn 10,000 Coin.", sort_order=2).insert()
    await TickerMessage(text="Off line", sort_order=3, enabled=False, bg_color="#000000").insert()
    await TickerMessage(text="Play Nifty UP/DOWN Win 1000 Coin", sort_order=4,
                        bg_color="#1e8449", text_color="#ffff00").insert()

    data = (await user_ticker.my_ticker(Namespace(id=ObjectId()))).data
    assert data["messages"] == [
        "Ban Scrips Today - KAYNES",
        "Try Nifty Number Earn 10,000 Coin.",
        "Play Nifty UP/DOWN Win 1000 Coin",
    ]
    assert data["items"] == [
        {"text": "Ban Scrips Today - KAYNES", "bg": "#c0392b", "text_color": None},
        {"text": "Try Nifty Number Earn 10,000 Coin.", "bg": None, "text_color": None},
        {"text": "Play Nifty UP/DOWN Win 1000 Coin", "bg": "#1e8449", "text_color": "#ffff00"},
    ]
    assert data["style"] == {"bg": None, "text": None}


async def test_lines_saved_before_this_change_have_no_colours(db):
    # Rows already in the database have no colour fields at all.
    await TickerMessage.get_motor_collection().insert_one(
        {"text": "Old line", "enabled": True, "target_all": True, "admin_ids": [], "sort_order": 1}
    )
    data = (await user_ticker.my_ticker(Namespace(id=ObjectId()))).data
    assert data["items"] == [{"text": "Old line", "bg": None, "text_color": None}]


async def test_nothing_enabled_gives_an_empty_strip(db):
    data = (await user_ticker.my_ticker(Namespace(id=ObjectId()))).data
    assert (data["messages"], data["items"]) == ([], [])
