"""Demo play must not show on the super-admin's House / Games P&L.

Reported: the breakdown showed 77 tickets / 93,700 revenue after demo accounts
had expired. Measured on production: every one of those bets belonged either to
a live demo account or to an account that no longer exists — the 7-day demo
cleanup deleted demo users and kept their bets, and a bet owned by nobody was
on nobody's demo list, so it counted as real. Only bets of EXISTING, non-demo
users count now, and the cleanup takes the games data with the account.
"""

import asyncio
import pathlib
import types

import pytest
from bson import ObjectId

import app.models.games.bets as bets
from app.api.v1.admin import me

ROOT = pathlib.Path(__file__).resolve().parents[1]

REAL, DEMO, GONE = ObjectId(), ObjectId(), ObjectId()
USERS = {
    REAL: types.SimpleNamespace(id=REAL, is_demo=False),
    DEMO: types.SimpleNamespace(id=DEMO, is_demo=True),
    # GONE: an expired demo — the account was deleted, its bets were not.
}


class _Coll:
    def __init__(self, docs):
        self.docs = docs

    async def distinct(self, field):
        return list({d[field] for d in self.docs})

    def aggregate(self, pipeline):
        match = pipeline[0]["$match"]
        rows = [
            d for d in self.docs
            if d["game_key"] == match["game_key"] and d["user_id"] in match["user_id"]["$in"]
        ]
        out = []
        if rows:
            out = [{"tickets": len(rows), "gross": sum(d["amount"] for d in rows),
                    "payouts": sum(d.get("payout", 0) + d.get("prize", 0) for d in rows)}]

        class _Cur:
            async def to_list(self, n):
                return out

        return _Cur()


def _model(docs):
    return types.SimpleNamespace(get_motor_collection=lambda: _Coll(docs))


@pytest.fixture
def platform(monkeypatch):
    updown = [
        {"user_id": REAL, "game_key": "niftyUpDown", "amount": 600, "payout": 0},
        {"user_id": DEMO, "game_key": "niftyUpDown", "amount": 600, "payout": 1140},
        {"user_id": GONE, "game_key": "niftyUpDown", "amount": 37800, "payout": 46000},
        {"user_id": GONE, "game_key": "btcUpDown", "amount": 15000, "payout": 0},
    ]
    number = [{"user_id": GONE, "game_key": "btcNumber", "amount": 17550, "payout": 9000}]
    monkeypatch.setattr(bets, "UpDownBet", _model(updown))
    monkeypatch.setattr(bets, "NumberBet", _model(number))
    monkeypatch.setattr(bets, "BracketTrade", _model([]))
    monkeypatch.setattr(bets, "JackpotBid", _model([]))

    def find(query):
        if "_id" in query:
            wanted = query["_id"]["$in"]
            rows = [u for oid, u in USERS.items() if oid in wanted and not u.is_demo]
        else:
            rows = []  # the per-admin commission lookup

        class _Q:
            async def to_list(self):
                return rows

        return _Q()

    monkeypatch.setattr(me, "User", types.SimpleNamespace(find=find))


def test_only_bets_of_existing_real_users_count(platform):
    out = asyncio.run(me.games_breakdown(types.SimpleNamespace(id=ObjectId())))
    t = out.data["totals"]
    assert t == {"total_tickets": 1, "total_revenue": 600.0, "total_payouts": 0.0, "house_net": 600.0}
    by_game = {g["game_key"]: g for g in out.data["per_game"]}
    assert by_game["btcUpDown"]["tickets"] == 0      # an expired demo's bets
    assert by_game["btcNumber"]["tickets"] == 0


def test_the_bettor_list_is_an_inclusion_list(platform):
    ids = asyncio.run(me._real_bettors((bets.UpDownBet, bets.NumberBet)))
    assert ids == [REAL]                             # not DEMO, not the deleted one


def test_with_no_real_bettor_nothing_counts(monkeypatch, platform):
    USERS_BACKUP = dict(USERS)
    USERS.pop(REAL)
    try:
        out = asyncio.run(me.games_breakdown(types.SimpleNamespace(id=ObjectId())))
        assert out.data["totals"]["total_tickets"] == 0
    finally:
        USERS.clear()
        USERS.update(USERS_BACKUP)


def test_the_demo_cleanup_takes_the_games_data_with_the_account():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    loop = src[src.index("async def _demo_cleanup_loop") :][:4000]
    for model in ("UpDownBet", "NumberBet", "BracketTrade", "JackpotBid", "GamesWallet"):
        assert model in loop
    # The games ledger is keyed by owner_id, not user_id.
    assert 'GamesWalletLedger.find({"owner_id": uid}).delete()' in loop
