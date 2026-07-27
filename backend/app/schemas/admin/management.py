"""Request / response schemas for the super-admin management surface."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.models.user import AdminPermissions


class CreateSubAdminRequest(BaseModel):
    full_name: str
    email: EmailStr
    mobile: str
    password: str = Field(min_length=8)
    permissions: AdminPermissions = Field(default_factory=AdminPermissions)
    pnl_share_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    # Separate brokerage-sharing % the super-admin takes from THIS admin's
    # brokerage (None → inherits pnl_share_pct for brokerage too).
    brokerage_share_pct: Decimal | None = Field(default=None, ge=0, le=100)
    # Fixed-brokerage flow (Account 2) — opt-in, parallel to the % sharing.
    is_fixed_brokerage: bool = False
    fixed_brokerage_unit: str | None = None  # "per_lot" | "per_crore"
    fixed_brokerage_rate: Decimal | None = Field(default=None, ge=0)
    # No-brokerage admin type: SA takes 100% of the admin's OWN (direct) users'
    # brokerage; broker-mediated users' brokerage stays with the admin.
    no_self_brokerage: bool = False
    # Optional opening float given by the super-admin at creation. Credits the
    # new sub-admin's Wallet.available_balance (the float they dispense to users
    # when ADMIN_FLOAT_ENABLED). 0 → no opening fund.
    opening_fund: Decimal = Field(default=Decimal("0"), ge=0)


class UpdateSubAdminRequest(BaseModel):
    full_name: str | None = None


class UpdatePermissionsRequest(BaseModel):
    permissions: AdminPermissions


class UpdatePnlShareRequest(BaseModel):
    pct: Decimal = Field(ge=0, le=100)
    # Optional — update the admin's separate brokerage share % in the same call.
    brokerage_share_pct: Decimal | None = Field(default=None, ge=0, le=100)


class UpdateFixedBrokerageRequest(BaseModel):
    is_fixed_brokerage: bool = False
    fixed_brokerage_unit: str | None = None  # "per_lot" | "per_crore"
    fixed_brokerage_rate: Decimal | None = Field(default=None, ge=0)


class AssignUserRequest(BaseModel):
    sub_admin_id: str | None = None  # None → return user to super-admin pool


class BulkAssignRequest(BaseModel):
    user_ids: list[str] = Field(min_length=1)
    sub_admin_id: str | None = None


class RecomputeSettlementRequest(BaseModel):
    week_start: date  # IST Monday (any date inside the week also accepted by service)
    sub_admin_id: str | None = None  # None → recompute for every sub-admin


class MarkPaidRequest(BaseModel):
    notes: str | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class SubAdminDTO(BaseModel):
    id: str
    user_code: str
    full_name: str
    email: str
    mobile: str
    status: str
    permissions: AdminPermissions | None = None
    pnl_share_pct: str
    brokerage_share_pct: str | None = None  # None ⇒ inherits pnl_share_pct
    is_fixed_brokerage: bool = False
    fixed_brokerage_unit: str | None = None
    fixed_brokerage_rate: str | None = None
    can_edit_expiry_settings: bool = False  # SA-granted expiry-edit unlock
    trading_referral_enabled: bool = True  # SA master switch, whole-pool trading referral
    no_self_brokerage: bool = False  # No-brokerage admin type (self users' brokerage → SA)
    user_count: int = 0  # active trading clients (CLOSED + broker rows excluded)
    broker_count: int = 0  # broker + sub-broker login accounts under this admin
    created_at: datetime | None = None


class SettlementDTO(BaseModel):
    id: str
    sub_admin_id: str
    sub_admin_name: str | None = None
    sub_admin_code: str | None = None
    period_start: datetime
    period_end: datetime
    user_count: int
    gross_user_loss_inr: str
    gross_user_profit_inr: str
    total_brokerage_inr: str
    net_house_pnl_inr: str
    pnl_share_pct_snapshot: str
    sub_admin_share_inr: str
    status: str
    finalized_at: datetime | None = None
    paid_at: datetime | None = None
    notes: str | None = None
    frozen: bool = False
