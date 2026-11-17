"""Super-admin lot sizes: how many shares / units are in one lot.

    GET    /api/v1/admin/lot-sizes          -> super-admin rows + built-in table
    PUT    /api/v1/admin/lot-sizes          { market, underlying, lot_size, note? }
    DELETE /api/v1/admin/lot-sizes/{id}     -> back to the built-in value

Super-admin only. A row wins over the coded tables and the Zerodha CSV
(services/lot_overrides.py); saving or deleting it rewrites the matching
Instrument rows at once. Open positions keep the lot they were filled at.
Every change is written to the audit log.
"""

from __future__ import annotations

from typing import Any

from beanie import PydanticObjectId
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.dependencies import SuperAdmin
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.audit_log import AuditAction
from app.models.lot_size_override import LotMarket, LotSizeOverride
from app.schemas.common import APIResponse
from app.services import lot_overrides
from app.services.audit_service import log_event

router = APIRouter(prefix="/lot-sizes", tags=["admin-lot-sizes"])


class LotSizeIn(BaseModel):
    market: str = Field(max_length=20)
    underlying: str = Field(max_length=40)
    lot_size: int
    note: str = Field(default="", max_length=200)


def _out(r: LotSizeOverride) -> dict[str, Any]:
    market = getattr(r.market, "value", r.market)
    return {
        "id": str(r.id),
        "market": market,
        "underlying": r.underlying,
        "lot_size": r.lot_size,
        "builtin_lot_size": lot_overrides.builtin_lot(market, r.underlying),
        "note": r.note,
        "updated_at": r.updated_at,
    }


@router.get("", response_model=APIResponse[dict])
async def list_lot_sizes(admin: SuperAdmin):
    rows = await LotSizeOverride.find_all().sort("market", "underlying").to_list()
    return APIResponse(data={
        "overrides": [_out(r) for r in rows],
        "builtin": lot_overrides.builtin_table(),
    })


@router.put("", response_model=APIResponse[dict])
async def set_lot_size(payload: LotSizeIn, admin: SuperAdmin):
    market = payload.market.strip().upper()
    if market not in LotMarket.__members__:
        raise ValidationFailedError("Choose Indian or International.", details={"field": "market"})
    u = lot_overrides.clean_underlying(payload.underlying)
    if not lot_overrides.UNDERLYING_RE[market].match(u):
        hint = (
            "the contract name before the expiry, e.g. NIFTY, BANKNIFTY, RELIANCE, GOLDM"
            if market == "INDIAN"
            else "the symbol, e.g. EURUSD, XAUUSD, BTCUSD (BTC for BTC options)"
        )
        raise ValidationFailedError(f"Enter {hint}.", details={"field": "underlying"})
    if not 1 <= payload.lot_size <= lot_overrides.LOT_SIZE_MAX:
        raise ValidationFailedError(
            f"Lot size must be a whole number from 1 to {lot_overrides.LOT_SIZE_MAX:,}.",
            details={"field": "lot_size"},
        )

    row = await LotSizeOverride.find_one({"market": market, "underlying": u})
    old = row.lot_size if row else None
    if row is None:
        row = LotSizeOverride(market=LotMarket(market), underlying=u, lot_size=payload.lot_size)
    row.lot_size = payload.lot_size
    row.note = payload.note.strip()
    row.updated_by = admin.id
    await row.save()

    lot_overrides.set_local(market, u, payload.lot_size)
    changed = await lot_overrides.apply_to_instruments(market, u)
    await log_event(
        action=AuditAction.SETTING_CHANGE,
        entity_type="lot_size",
        entity_id=row.id,
        actor_id=admin.id,
        old_values={"lot_size": old},
        new_values={"lot_size": payload.lot_size},
        metadata={"market": market, "underlying": u, "instruments_updated": changed},
    )
    out = _out(row)
    out["instruments_updated"] = changed
    return APIResponse(data=out, message=f"{u}: 1 lot = {payload.lot_size:,}")


@router.delete("/{row_id}", response_model=APIResponse[dict])
async def delete_lot_size(row_id: str, admin: SuperAdmin):
    try:
        row = await LotSizeOverride.get(PydanticObjectId(row_id))
    except Exception:
        row = None
    if row is None:
        raise NotFoundError("Lot size not found")
    market = getattr(row.market, "value", row.market)
    await row.delete()

    lot_overrides.set_local(market, row.underlying, None)
    changed = await lot_overrides.apply_to_instruments(market, row.underlying)
    await log_event(
        action=AuditAction.SETTING_CHANGE,
        entity_type="lot_size",
        entity_id=row.id,
        actor_id=admin.id,
        old_values={"lot_size": row.lot_size},
        new_values={"lot_size": None},
        metadata={"market": market, "underlying": row.underlying, "instruments_updated": changed},
    )
    return APIResponse(
        data={"instruments_updated": changed},
        message=f"{row.underlying}: back to the built-in lot size",
    )
