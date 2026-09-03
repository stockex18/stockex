"""Ledger books — named accounts with posted lines and a printable statement.

Every book belongs to the admin who keeps it, and every route resolves through
that owner id, so one admin can never read or post into another's books.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.core.dependencies import CurrentAdmin, SuperAdmin
from app.core.exceptions import AppError
from app.schemas.common import APIResponse
from app.services import ledger_book_service as svc

router = APIRouter(prefix="/ledger-books", tags=["admin-ledger-books"])

FIRM_KEY = "ledger_firm_header"


class BookBody(BaseModel):
    name: str
    is_payment_mode: bool = False
    account_type: str = "OTHER"   # CASH / BANK / PARTY / EXPENSE / OTHER
    opening_balance: float = 0
    opening_date: datetime | None = None
    note: str | None = None


class BookPatch(BaseModel):
    name: str | None = None
    is_payment_mode: bool | None = None
    opening_balance: float | None = None
    opening_date: datetime | None = None
    note: str | None = None
    is_archived: bool | None = None


class EntryBody(BaseModel):
    entry_date: datetime
    debit: float = 0
    credit: float = 0
    voucher_type: str = "Jrnl"
    voucher_no: str | None = None
    particulars: str | None = None
    narration: str | None = None


class FirmBody(BaseModel):
    name: str | None = None
    address: str | None = None
    statutory: str | None = None


def _http(e: Exception) -> HTTPException:
    if isinstance(e, AppError):
        return HTTPException(status_code=e.status_code, detail=e.message or str(e))
    return HTTPException(status_code=400, detail=str(e))


# ── The firm header printed on top of every statement ────────────────
async def _get_firm() -> dict:
    from app.models.platform_setting import PlatformSetting

    row = await PlatformSetting.find_one(PlatformSetting.setting_key == FIRM_KEY)
    v = getattr(row, "setting_value", None)
    return v if isinstance(v, dict) else {}


@router.get("/firm", response_model=APIResponse[dict])
async def get_firm(admin: CurrentAdmin):
    return APIResponse(data=await _get_firm())


@router.put("/firm", response_model=APIResponse[dict])
async def set_firm(body: FirmBody, admin: SuperAdmin):
    from app.models.platform_setting import PlatformSetting, SettingType

    val = {k: (v or "") for k, v in body.model_dump().items()}
    row = await PlatformSetting.find_one(PlatformSetting.setting_key == FIRM_KEY)
    if row is None:
        row = PlatformSetting(
            setting_key=FIRM_KEY, setting_value=val, setting_type=SettingType.JSON,
            description="Firm name/address printed on ledger statements", category="general",
        )
        await row.insert()
    else:
        row.setting_value = val
        await row.save()
    return APIResponse(data=val, message="Header saved")


# ── Payment modes ────────────────────────────────────────────────────
@router.get("/payment-modes", response_model=APIResponse[list])
async def payment_modes(admin: CurrentAdmin):
    """The modes the super-admin defined. Every admin tier reads the same list
    so a movement is recorded the same way on both sides of it."""
    return APIResponse(data=await svc.payment_modes())


class VoucherLeg(BaseModel):
    book_id: str
    debit: float = 0
    credit: float = 0
    particulars: str | None = None


class VoucherBody(BaseModel):
    entry_date: datetime
    legs: list[VoucherLeg]
    voucher_type: str = "Jrnl"
    voucher_no: str | None = None
    narration: str | None = None


# ── Double entry ─────────────────────────────────────────────────────
@router.post("/vouchers", response_model=APIResponse[dict])
async def post_voucher(body: VoucherBody, admin: CurrentAdmin):
    """One voucher, two or more accounts, debits equal to credits."""
    try:
        vid = await svc.post_voucher(
            admin.id,
            entry_date=body.entry_date,
            legs=[l.model_dump() for l in body.legs],
            voucher_type=body.voucher_type,
            voucher_no=body.voucher_no or "",
            narration=body.narration or "",
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(data={"voucher_id": vid}, message="Voucher posted")


@router.get("/trial-balance", response_model=APIResponse[dict])
async def trial_balance(admin: CurrentAdmin, as_of: datetime | None = None):
    """Every account's closing balance, and whether the books square."""
    try:
        return APIResponse(data=await svc.trial_balance(admin.id, as_of))
    except Exception as e:
        raise _http(e)


@router.get("/coin-trial-balance", response_model=APIResponse[dict])
async def coin_trial_balance(admin: CurrentAdmin, as_on: datetime | None = None):
    """The coin economy's trial balance.

    A different report from `/trial-balance`, which totals the cash and bank
    BOOKS. This one totals the COINS: what was issued against every wallet
    holding one. It squares by identity rather than by bookkeeping discipline,
    because every coin is in exactly one wallet.
    """
    from app.services import coin_trial_balance as _ctb

    try:
        return APIResponse(data=await _ctb.build(as_on))
    except Exception as e:
        raise _http(e)


@router.get("/coin-trial-balance/pdf")
async def coin_trial_balance_pdf(admin: CurrentAdmin, as_on: datetime | None = None):
    from fastapi.responses import Response

    from app.services import coin_trial_balance as _ctb
    from app.services import ledger_pdf_service as _pdf

    try:
        data = await _ctb.build(as_on)
        firm = await _get_firm()
        pdf = _pdf.build_coin_trial_balance_pdf(data, firm)
    except Exception as e:
        raise _http(e)
    stamp = (as_on or datetime.now()).strftime("%Y%m%d")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="trial-balance-coins-{stamp}.pdf"'
        },
    )


@router.get("/day-book", response_model=APIResponse[list])
async def day_book(admin: CurrentAdmin, start: datetime | None = None,
                   end: datetime | None = None, limit: int = 500):
    """Every voucher in the period — one row per voucher, with its legs."""
    try:
        return APIResponse(data=await svc.day_book(admin.id, start, end, min(limit, 2000)))
    except Exception as e:
        raise _http(e)


# ── Party (per-admin) accounts ───────────────────────────────────────
@router.get("/parties", response_model=APIResponse[list])
async def parties(admin: CurrentAdmin):
    """Everyone you have actually moved money with, from the posted lines."""
    return APIResponse(data=await svc.parties(admin.id))


@router.get("/parties/{code}/statement", response_model=APIResponse[dict])
async def party_statement(code: str, admin: CurrentAdmin,
                          start: datetime | None = None, end: datetime | None = None):
    """One admin's account with you, across every ledger."""
    try:
        return APIResponse(data=await svc.party_statement(admin.id, code, start, end))
    except Exception as e:
        raise _http(e)


@router.get("/parties/{code}/pdf")
async def party_pdf(code: str, admin: CurrentAdmin,
                    start: datetime | None = None, end: datetime | None = None):
    from app.services.ledger_pdf_service import build_ledger_pdf

    try:
        data = await svc.party_statement(admin.id, code, start, end)
        pdf = build_ledger_pdf(data, await _get_firm())
    except Exception as e:
        raise _http(e)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="ledger-' + code + '.pdf"'},
    )


# ── Books ────────────────────────────────────────────────────────────
@router.get("", response_model=APIResponse[list])
async def list_books(admin: CurrentAdmin, include_archived: bool = False):
    return APIResponse(data=await svc.list_books(admin.id, include_archived))


@router.post("", response_model=APIResponse[dict])
async def create_book(body: BookBody, admin: CurrentAdmin):
    try:
        b = await svc.create_book(
            admin.id, body.name, is_payment_mode=body.is_payment_mode,
            account_type=body.account_type,
            opening_balance=body.opening_balance,
            opening_date=body.opening_date, note=body.note or "",
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(data={"id": str(b.id), "name": b.name}, message="Ledger created")


@router.patch("/{book_id}", response_model=APIResponse[dict])
async def update_book(book_id: str, body: BookPatch, admin: CurrentAdmin):
    try:
        b = await svc.update_book(
            admin.id, book_id, name=body.name, opening_balance=body.opening_balance,
            opening_date=body.opening_date, note=body.note, is_archived=body.is_archived,
            is_payment_mode=body.is_payment_mode,
        )
    except Exception as e:
        raise _http(e)
    return APIResponse(data={"id": str(b.id), "name": b.name}, message="Ledger updated")


@router.delete("/{book_id}", response_model=APIResponse[dict])
async def delete_book(book_id: str, admin: CurrentAdmin):
    try:
        n = await svc.delete_book(admin.id, book_id)
    except Exception as e:
        raise _http(e)
    return APIResponse(data={"deleted_entries": n}, message="Ledger deleted")


# ── Entries + statement ──────────────────────────────────────────────
@router.get("/{book_id}/statement", response_model=APIResponse[dict])
async def statement(book_id: str, admin: CurrentAdmin,
                    start: datetime | None = None, end: datetime | None = None):
    try:
        return APIResponse(data=await svc.statement(admin.id, book_id, start, end))
    except Exception as e:
        raise _http(e)


@router.post("/{book_id}/entries", response_model=APIResponse[dict])
async def add_entry(book_id: str, body: EntryBody, admin: CurrentAdmin):
    try:
        e = await svc.add_entry(
            admin.id, book_id, entry_date=body.entry_date,
            debit=body.debit, credit=body.credit,
            voucher_type=body.voucher_type, voucher_no=body.voucher_no or "",
            particulars=body.particulars or "", narration=body.narration or "",
        )
    except Exception as exc:
        raise _http(exc)
    return APIResponse(data={"id": str(e.id)}, message="Entry posted")


@router.delete("/entries/{entry_id}", response_model=APIResponse[dict])
async def delete_entry(entry_id: str, admin: CurrentAdmin):
    try:
        await svc.delete_entry(admin.id, entry_id)
    except Exception as e:
        raise _http(e)
    return APIResponse(data={"ok": True}, message="Entry removed")


@router.get("/{book_id}/pdf")
async def statement_pdf(book_id: str, admin: CurrentAdmin,
                        start: datetime | None = None, end: datetime | None = None):
    from app.services.ledger_pdf_service import build_ledger_pdf

    try:
        data = await svc.statement(admin.id, book_id, start, end)
        pdf = build_ledger_pdf(data, await _get_firm())
    except Exception as e:
        raise _http(e)
    fname = "ledger-" + str(data["book"]["name"]).replace(" ", "-").lower() + ".pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="' + fname + '"'},
    )
