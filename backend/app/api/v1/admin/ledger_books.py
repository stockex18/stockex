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
    kind: str = "CUSTOM"
    opening_balance: float = 0
    opening_date: datetime | None = None
    note: str | None = None


class BookPatch(BaseModel):
    name: str | None = None
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


# ── Books ────────────────────────────────────────────────────────────
@router.get("", response_model=APIResponse[list])
async def list_books(admin: CurrentAdmin, include_archived: bool = False):
    return APIResponse(data=await svc.list_books(admin.id, include_archived))


@router.post("", response_model=APIResponse[dict])
async def create_book(body: BookBody, admin: CurrentAdmin):
    try:
        b = await svc.create_book(
            admin.id, body.name, kind=body.kind,
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
