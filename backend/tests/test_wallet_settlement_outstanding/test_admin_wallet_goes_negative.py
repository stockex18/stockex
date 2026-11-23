"""An admin's wallet is their book: a client's profit is a minus balance.

JKM, 23 Nov: wallet 249.48, the client made 17,100, and the admin-book P&L
debit floored the wallet at 0 and parked 16,850.52 in settlement_outstanding,
so the card read +15,896.09 next to "16,850.52 outstanding". Operator: the
balance itself must go minus, in red, and the outstanding goes away."""

from __future__ import annotations

from decimal import Decimal

import pytest
from bson import Decimal128

from app.models.transaction import TransactionType
from app.models.user import User, UserRole, UserStatus
from app.models.wallet import Wallet
from app.services import wallet_service


@pytest.mark.asyncio
async def test_an_admin_book_loss_takes_the_admin_wallet_below_zero(db):
    admin = User(
        user_code="ADMTEST01", email="adm_neg@example.com", mobile="9999900301",
        full_name="Admin", password_hash="x", role=UserRole.ADMIN, status=UserStatus.ACTIVE,
    )
    await admin.insert()
    await Wallet(user_id=admin.id, available_balance=Decimal128("249.48")).insert()

    await wallet_service.adjust(
        admin.id, Decimal("-17100"), transaction_type=TransactionType.ADMIN_BOOK_PNL,
        narration="Admin-book P&L", reference_type="ADMIN_BOOK", reference_id="t1",
    )
    await wallet_service.adjust(
        admin.id, Decimal("15390"), transaction_type=TransactionType.SA_PNL_SHARE,
        narration="SA PnL share 90%", reference_type="ADMIN_BOOK", reference_id="t1",
    )

    w = await Wallet.find_one(Wallet.user_id == admin.id)
    assert Decimal(str(w.available_balance)) == Decimal("-1460.52")  # 249.48 - 1,710
    assert Decimal(str(w.settlement_outstanding)) == Decimal("0")


@pytest.mark.asyncio
async def test_a_client_still_floors_at_zero(db, user, wallet):
    await wallet_service.adjust(
        user.id, Decimal("-1500"), transaction_type=TransactionType.PNL,
        narration="loss", reference_type="ORDER", reference_id="t2",
    )
    w = await Wallet.find_one(Wallet.user_id == user.id)
    assert Decimal(str(w.available_balance)) == Decimal("0")
    assert Decimal(str(w.settlement_outstanding)) == Decimal("500")
