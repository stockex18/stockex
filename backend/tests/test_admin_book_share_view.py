"""An admin on a 90/10 split sees their own 10% per trade.

JKM, 23 Nov (super admin 90%, admin 10%): the user made 17,100 and paid
249.48 + 252.90 brokerage. The wallet shows the whole result and the whole
brokerage and then the super admin's share coming back, so no line said
"your 10%". /me/book-share puts the admin's own cut on one line per trade."""

import asyncio
import types

from bson import Decimal128, ObjectId

from app.api.v1.admin import me
from app.models import admin_book_entry
from app.models.user import UserRole

ADMIN, USER = ObjectId(), ObjectId()


def _entry(house, brok, sa_pnl, sa_bkg, admin_net):
    return types.SimpleNamespace(
        id=ObjectId(), user_id=USER, instrument_symbol="GOLDM26DECFUT", booked_at=None, created_at=None,
        house_pnl_inr=Decimal128(house), brokerage_inr=Decimal128(brok),
        sa_pnl_share_inr=Decimal128(sa_pnl), sa_bkg_share_inr=Decimal128(sa_bkg),
        admin_net_inr=Decimal128(admin_net), pnl_pct_snapshot=Decimal128("90.00"),
    )


def test_the_admin_sees_ten_percent_of_the_loss_and_of_the_brokerage(monkeypatch):
    rows = [
        _entry("-17100.00", "252.90", "-15390.00", "227.61", "-1684.71"),  # close: user profit
        _entry("0", "249.48", "0.00", "224.53", "24.95"),  # open: brokerage only
    ]

    class _Q:
        def __init__(self, data):
            self.data = data

        def sort(self, *_a):
            return self

        def limit(self, *_a):
            return self

        async def to_list(self):
            return self.data

    monkeypatch.setattr(admin_book_entry, "AdminBookEntry",
                        types.SimpleNamespace(admin_id=None, find=lambda *_a, **_k: _Q(rows)))
    monkeypatch.setattr(me, "User", types.SimpleNamespace(
        find=lambda *_a, **_k: _Q([types.SimpleNamespace(id=USER, user_code="CL97486914")])))

    admin = types.SimpleNamespace(id=ADMIN, role=UserRole.ADMIN)
    out = asyncio.run(me.my_book_share(admin, limit=100)).data

    close, opened = out
    assert close["user_code"] == "CL97486914"
    assert (close["house_pnl"], close["my_pnl_pct"], close["my_pnl"]) == (-17100.0, 10.0, -1710.0)
    assert (close["brokerage"], close["my_brokerage"], round(close["my_brokerage_pct"], 2)) == (252.9, 25.29, 10.0)
    assert close["my_net"] == -1684.71
    assert (opened["my_pnl"], opened["my_brokerage"], opened["my_net"]) == (0.0, 24.95, 24.95)
    assert round(sum(r["my_net"] for r in out), 2) == -1659.76  # the admin's whole 10%


def test_only_an_admin_gets_rows():
    sa = types.SimpleNamespace(id=ADMIN, role=UserRole.SUPER_ADMIN)
    assert asyncio.run(me.my_book_share(sa, limit=10)).data == []
