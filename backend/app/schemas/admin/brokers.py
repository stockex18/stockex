"""Request / response schemas for the broker-management surface.

All grants use the tri-state `BrokerPermissions` (OFF / VIEW / EDIT).
Validation against the caller's own cap happens in the service layer
via `max_grantable_perms(actor)` — the schema itself only enforces
shape/types.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from beanie import PydanticObjectId
from pydantic import BaseModel, EmailStr, Field

from app.models.user import BrokerPermissions


class CreateBrokerRequest(BaseModel):
    full_name: str
    email: EmailStr
    mobile: str
    password: str = Field(min_length=8)
    permissions: BrokerPermissions = Field(default_factory=BrokerPermissions)
    pnl_share_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    brokerage_share_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    # Fixed-brokerage flow (Account 2) — the parent's fixed cut from this broker.
    is_fixed_brokerage: bool = False
    fixed_brokerage_unit: str | None = None  # "per_lot" | "per_crore"
    fixed_brokerage_rate: Decimal | None = Field(default=None, ge=0)
    # Super-admin only: pin the new broker to a specific admin's pool.
    # When omitted, super-admin creates a top-level broker in the platform
    # pool (assigned_admin_id = None). Admin/broker callers MUST leave this
    # null — service layer rejects mismatch with their natural chain.
    assigned_admin_id: PydanticObjectId | None = None
    # Optional opening float given by the creator (SA → kuber/main, admin →
    # own float) at creation. Credits the new broker's Wallet.available_balance
    # (the float they dispense to users when ADMIN_FLOAT_ENABLED). 0 → none.
    opening_fund: Decimal = Field(default=Decimal("0"), ge=0)
    # The name this broker trades under, shown to clients choosing a broker.
    # Optional: a broker without one is shown under their own name.
    brand_name: str | None = Field(default=None, max_length=64)


class UpdateBrokerRequest(BaseModel):
    full_name: str | None = None


class UpdateBrokerPermissionsRequest(BaseModel):
    permissions: BrokerPermissions


class UpdateBrokerPnlShareRequest(BaseModel):
    pct: Decimal = Field(ge=0, le=100)
    # Optional separate brokerage-sharing %. Omit to leave it unchanged.
    brokerage_pct: Decimal | None = Field(default=None, ge=0, le=100)


class UpdateBrokerFixedBrokerageRequest(BaseModel):
    is_fixed_brokerage: bool = False
    fixed_brokerage_unit: str | None = None  # "per_lot" | "per_crore"
    fixed_brokerage_rate: Decimal | None = Field(default=None, ge=0)


class AssignUserToBrokerRequest(BaseModel):
    broker_id: str | None = None  # None ⇒ return user to admin pool


class BulkAssignToBrokerRequest(BaseModel):
    user_ids: list[str] = Field(min_length=1)
    broker_id: str | None = None


class RecomputeBrokerSettlementRequest(BaseModel):
    week_start: date
    broker_id: str | None = None


class MarkPaidBrokerRequest(BaseModel):
    notes: str | None = None


class BrokerDTO(BaseModel):
    id: str
    user_code: str
    full_name: str
    email: str
    mobile: str
    status: str
    permissions: BrokerPermissions | None = None
    pnl_share_pct: str
    brokerage_share_pct: str = "0"
    is_fixed_brokerage: bool = False
    fixed_brokerage_unit: str | None = None
    fixed_brokerage_rate: str | None = None
    user_count: int = 0
    subtree_user_count: int = 0
    broker_ancestry: list[str] = Field(default_factory=list)
    assigned_admin_id: str | None = None
    assigned_broker_id: str | None = None
    brand_name: str | None = None
    created_at: datetime | None = None


class BrokerSettlementDTO(BaseModel):
    id: str
    broker_id: str
    broker_name: str | None = None
    broker_code: str | None = None
    period_start: datetime
    period_end: datetime
    user_count: int
    gross_user_loss_inr: str
    gross_user_profit_inr: str
    total_brokerage_inr: str
    net_house_pnl_inr: str
    pnl_share_pct_snapshot: str
    broker_share_inr: str
    status: str
    finalized_at: datetime | None = None
    paid_at: datetime | None = None
    notes: str | None = None
    frozen: bool = False


class MaxGrantableDTO(BaseModel):
    """Returned by GET /brokers/max-grantable so the create/edit form
    can grey out levels above the actor's cap."""

    cap: dict[str, str]  # perm_name → "OFF" | "VIEW" | "EDIT"
