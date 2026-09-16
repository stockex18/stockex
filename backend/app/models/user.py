"""User & UserSegment documents.

A single User collection holds clients, dealers, masters, admins, super-admin
— role-based filtering keeps query plans simple. Hierarchical relationships
(master → dealer → client) are modelled via `parent_id`.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from beanie import Indexed, Link, PydanticObjectId
from bson import Decimal128
from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import PermissionLevel, StrEnum, TimestampMixin
from app.models._types import Money
from app.utils.time_utils import now_utc


class UserRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    MASTER = "MASTER"
    DEALER = "DEALER"
    CLIENT = "CLIENT"
    # New tier: a broker sits under an admin and manages their own client
    # pool. Brokers can also create sub-brokers (nested, via broker_ancestry).
    BROKER = "BROKER"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    PENDING = "PENDING"
    CLOSED = "CLOSED"


class AccountType(StrEnum):
    LIVE = "LIVE"
    DEMO = "DEMO"


# ── Embedded sub-documents ──────────────────────────────────────────
class KycInfo(BaseModel):
    pan: str | None = None
    aadhaar: str | None = None  # store hashed/last-4 in production
    dob: date | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    country: str = "India"
    is_verified: bool = False
    verified_at: datetime | None = None


class UserPermissions(BaseModel):
    can_place_orders: bool = True
    can_modify_orders: bool = True
    can_cancel_orders: bool = True
    can_withdraw: bool = True
    can_deposit: bool = True
    can_view_charts: bool = True
    api_access: bool = False
    algo_trading: bool = False


class TradingHours(BaseModel):
    login_start: str = "00:00"  # HH:MM, IST
    login_end: str = "23:59"
    ip_whitelist: list[str] = Field(default_factory=list)


class RiskProfile(BaseModel):
    max_daily_loss: float = 0.0  # 0 = no limit
    max_position_value: float = 0.0
    max_open_positions: int = 0
    auto_squareoff_enabled: bool = True
    m2m_squareoff_percent: float = 80.0  # squareoff at -80% of margin


class CommunicationPrefs(BaseModel):
    email_alerts: bool = True
    sms_alerts: bool = True
    whatsapp_alerts: bool = False
    push_alerts: bool = True


# Section toggles for sub-admins (role == ADMIN). One boolean per admin nav
# section; SUPER_ADMIN ignores this object entirely. Adding a new section
# means: append a field here, gate it in admin endpoints with
# require_admin_permission(<name>), and surface a toggle in the
# `frontend-admin/management` page.
class AdminPermissions(BaseModel):
    users: bool = False
    kyc: bool = False
    deposits: bool = False
    withdrawals: bool = False
    segment_settings: bool = False
    risk: bool = False
    netting: bool = False
    trading_view: bool = False
    ledger: bool = False
    reports: bool = False
    brokerage: bool = False
    # Gates access to /management/brokers — admin needs this ON to create
    # brokers under their pool. Super-admin always has it.
    brokers: bool = False
    # Gates the Bank Accounts tab on the Payments page (list/create/edit/
    # delete of CompanyBankAccount rows in the admin's own pool). Default
    # True so existing admins keep their bank-management capability —
    # super-admin can turn it OFF per sub-admin to lock down.
    banks: bool = True
    # Firing an order into a user's account from Market Watch, approving a
    # pending one, or cancelling a resting one — moving someone else's money
    # by hand. Operator: only the super-admin holds this, and hands it out
    # per admin. So it is the one flag that stays OFF unless granted, and
    # `require_perm` keeps the super-admin above it as always.
    order_execute: bool = False


# Tri-state permissions granted by an admin to a broker (or by a broker to
# a sub-broker). Each key mirrors a section in the admin nav; the level
# decides what the broker sees and can do on that page:
#   OFF  → section hidden from sidebar; backend rejects all calls with 403
#   VIEW → page loads, list/details readable; mutation buttons disabled,
#          backend rejects writes with 403
#   EDIT → full access (read + write)
# The `sub_brokers` key here is the broker-level equivalent of admin's
# `brokers` flag — gates the broker's ability to mint sub-brokers.
class BrokerPermissions(BaseModel):
    users: PermissionLevel = PermissionLevel.OFF
    kyc: PermissionLevel = PermissionLevel.OFF
    deposits: PermissionLevel = PermissionLevel.OFF
    withdrawals: PermissionLevel = PermissionLevel.OFF
    segment_settings: PermissionLevel = PermissionLevel.OFF
    risk: PermissionLevel = PermissionLevel.OFF
    netting: PermissionLevel = PermissionLevel.OFF
    trading_view: PermissionLevel = PermissionLevel.OFF
    ledger: PermissionLevel = PermissionLevel.OFF
    reports: PermissionLevel = PermissionLevel.OFF
    brokerage: PermissionLevel = PermissionLevel.OFF
    sub_brokers: PermissionLevel = PermissionLevel.OFF
    # Bank Accounts tab — VIEW lets broker see existing banks in their pool,
    # EDIT lets them add / update / delete banks for their own users.
    banks: PermissionLevel = PermissionLevel.OFF


class GameReferralStats(BaseModel):
    """Reserved for the deferred games referral-per-win feature (v1 unused).
    `first_win_by_game` maps a GameSettings key → whether the user has already
    had their first win (so a referrer is rewarded at most once per game)."""

    first_win_by_game: dict[str, bool] = Field(default_factory=dict)


class ReferralStats(BaseModel):
    """Rollup of what a user has earned by referring others (mirror of
    Stockex User.referralStats). Bumped whenever a referral reward is paid to
    this user from a referred user's game win / trade."""

    total_referral_earnings: Money = Field(default_factory=lambda: Decimal128("0"))
    total_referrals: int = 0
    active_referrals: int = 0


class ReferralEligibility(BaseModel):
    """SUPER_ADMIN-owned gate: a referral is only paid once the referred user's
    hierarchy has earned enough for the house. `threshold_unit`:
    PER_CRORE → total_earnings / 1e7 >= threshold_amount; ABSOLUTE → >=."""

    enabled: bool = True
    threshold_amount: float = 1000.0
    threshold_unit: str = "PER_CRORE"  # "PER_CRORE" | "ABSOLUTE"

    # ── Trading referral THRESHOLD model (super-admin configurable) ──────
    # A referrer earns a ONE-TIME reward once the super-admin's NET brokerage
    # income from the referred user (accrued across all their closed trades)
    # reaches `trading_threshold_amount`. The reward paid is
    # `trading_reward_amount`. Both default 🪙1000. `enabled` gates the feature.
    trading_threshold_amount: float = 1000.0
    trading_reward_amount: float = 1000.0


class ReferralDistributionEnabled(BaseModel):
    """Per-admin toggle of which segments pay referral rewards for their
    subtree. mcx/crypto/forex additionally require the master `trading` flag."""

    games: bool = True
    trading: bool = True
    mcx: bool = True
    crypto: bool = True
    forex: bool = True


class PattiSegmentShare(BaseModel):
    """This admin-tier node's GROSS share of the per-trade house pool for a
    segment (set CUMULATIVELY up the chain). `pnl_pct` = % of the house's P&L
    pool (house gains on a user loss, is debited on a user profit — shared both
    ways); `brokerage_pct` = % of the brokerage charged. At settlement each node
    NETS its own % minus the nearest downline's % (so the chain never exceeds
    100%); the remainder stays with the SUPER_ADMIN house that funds it. Mirrors
    the reference `resolvePattiCascadeCredits`."""

    pnl_pct: float = 0.0
    brokerage_pct: float = 0.0


class PattiSharing(BaseModel):
    """Admin-hierarchy "patti" — a real-time, SUPER_ADMIN-funded cascade of a
    user's trading book result to the admin/broker/sub-broker above them.
    OPT-IN per admin-tier node (default off → no behaviour change). Keep OFF
    for a subtree that already uses the weekly `pnl_sharing` agreement to avoid
    double-counting. `segments` key = "trading"/"mcx"/"crypto"/"forex" or
    "ALL" (fallback)."""

    enabled: bool = False
    applied_to: str = "ALL_TRADES"  # ALL_TRADES | SPECIFIC_CLIENTS (v1: ALL)
    segments: dict[str, PattiSegmentShare] = Field(default_factory=dict)


# ── User document ───────────────────────────────────────────────────
class User(TimestampMixin):
    user_code: Indexed(str, unique=True)  # type: ignore[valid-type]
    # Short 6-digit referral code shared on Refer & Earn (easier than the full
    # user_code). Unique per user; assigned at creation + backfilled. Indexed
    # for resolve_referrer lookups.
    referral_number: Indexed(str) | None = None  # type: ignore[valid-type]
    # Stored as plain `str` (NOT EmailStr) on purpose: the soft-delete flow
    # rewrites a closed user's email to "<orig>+deleted-<id>" to free the
    # unique index (see /admin/users DELETE). That suffix is not a valid
    # RFC email, so an EmailStr field would raise ValidationError when
    # beanie re-parses the row — crashing any `.to_list()` whose scope
    # includes a closed user (admin Users list, sub-admin drill-in, money
    # / accounts aggregations). Email FORMAT is still validated at the API
    # input layer (register / create-user / create-sub-admin / create-broker
    # request schemas all use EmailStr), so new accounts stay well-formed.
    email: Indexed(str, unique=True)  # type: ignore[valid-type]
    mobile: Indexed(str, unique=True)  # type: ignore[valid-type]
    password_hash: str
    full_name: str
    photo_url: str | None = None

    # Tombstones stamped by /admin/users/{id} DELETE when the row is
    # soft-closed.  email/mobile are rewritten to "<orig>+deleted-<id>"
    # and "DEL<oid-tail>" respectively so the unique index frees up for
    # a future registration with the same contact; the originals are
    # kept here for the audit trail / KYC lookup.
    deleted_email_original: str | None = None
    deleted_mobile_original: str | None = None

    # ── Terms & Conditions (admin-tier writes; cascades to clients) ──
    # Each admin-tier user (SUPER_ADMIN / ADMIN / BROKER) can set their
    # own T&C text + toggle. When `terms_enabled=True`, every CLIENT
    # in their downline sees the T&C modal once after register and
    # again whenever the text changes (acceptance is tracked via
    # `terms_accepted_at` on the client row).
    terms_text: str | None = None
    terms_enabled: bool = False
    # CLIENT-side: timestamp of the last accept click. Reset to None by
    # admin if they update terms_text and want re-acceptance.
    terms_accepted_at: datetime | None = None

    role: UserRole = UserRole.CLIENT
    status: UserStatus = UserStatus.PENDING
    account_type: AccountType = AccountType.LIVE
    is_demo: bool = False
    # Set the moment a demo account (client OR broker) is converted to real.
    # `is_demo` flips False on convert, so this is the ONLY durable marker that
    # a real account STARTED as a demo — the super-admin "Demo" section uses it
    # to split "converted" from "still-demo" (is_demo=True). None = never a demo
    # convert (either a native real account, or still a live demo).
    demo_converted_at: datetime | None = None

    # Session epoch. Stamped into every access token as the `ver` claim;
    # the per-request auth dependency rejects any token whose `ver` doesn't
    # match. Bumping this (on block / admin password reset) instantly
    # invalidates EVERY outstanding access token for the user — they can't
    # ride out the 15-min access-token window or refresh back in, so the
    # account is force-logged-out on its very next request.
    token_version: int = 0

    parent_id: PydanticObjectId | None = None  # hierarchy

    kyc: KycInfo = Field(default_factory=KycInfo)
    permissions: UserPermissions = Field(default_factory=UserPermissions)
    trading_hours: TradingHours = Field(default_factory=TradingHours)
    risk: RiskProfile = Field(default_factory=RiskProfile)
    communication: CommunicationPrefs = Field(default_factory=CommunicationPrefs)

    # Brokerage plan (FK to brokerage_plans, optional → uses default)
    brokerage_plan_id: PydanticObjectId | None = None

    # 2FA
    two_fa_enabled: bool = False
    two_fa_secret: str | None = None
    two_fa_backup_codes: list[str] = Field(default_factory=list)

    # Login telemetry
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    failed_login_count: int = 0
    locked_until: datetime | None = None
    password_changed_at: datetime | None = None
    must_change_password: bool = False

    created_by: PydanticObjectId | None = None

    # Pool transfer telemetry — stamped every time a super-admin /
    # admin / broker moves this user into a new pool via the admin
    # `Transfer User` action. Lets the destination dashboard render a
    # "Transferred" badge so the new owner can spot users that landed
    # in their pool through reassignment vs. ones they personally
    # created. NULL on freshly-created users (the originating admin
    # is `created_by`).
    last_transferred_at: datetime | None = None
    last_transferred_by: PydanticObjectId | None = None

    # Sub-admin ownership (CLIENT/DEALER/MASTER → which ADMIN owns them).
    # NULL ⇒ owned by super-admin (the platform itself).
    assigned_admin_id: PydanticObjectId | None = None

    # Sub-admin profile — only populated for role == ADMIN.
    admin_permissions: AdminPermissions | None = None
    pnl_share_pct: Decimal128 | None = None  # 0..100
    # Separate brokerage-sharing % (how much of THIS admin's brokerage the
    # super-admin takes), independent of the PnL share. None ⇒ the admin
    # inherits `pnl_share_pct` for brokerage too (so existing admins are
    # unchanged). Mirrors `broker_brokerage_share_pct`.
    admin_brokerage_share_pct: Decimal128 | None = None  # 0..100

    # Expiry / option-chain settings lock. By DEFAULT an admin/broker CANNOT
    # edit their own ExpiryOverride — they inherit whatever the super-admin set.
    # The super-admin flips this ON per-admin (3-dot → "Expiry edit") to let that
    # admin override. Super-admin itself is always allowed. Default False = locked.
    can_edit_expiry_settings: bool = False

    # Super-admin master switch for TRADING-REFERRAL income across an ENTIRE
    # admin's client base. Default ON. Flip OFF (sub-admins 3-dot → "Trading
    # referral") and `referral_service.credit_referral_trading_reward` skips all
    # accrual + payout for every client whose owning admin is this row — one
    # switch kills the trading-referral rewards for that admin's whole pool.
    # Only meaningful on an ADMIN / SUPER_ADMIN row; unset = True (legacy).
    trading_referral_enabled: bool = True

    # Immediate broker owner. For BROKER role: their parent broker (NULL for
    # a top-level broker created by an admin/super-admin). For CLIENT role:
    # the broker that minted them (NULL when client belongs to admin pool).
    assigned_broker_id: PydanticObjectId | None = None

    # Materialised broker ancestry, root-first, NOT including self. Lets us
    # scope an entire subtree in O(1) via a single multikey index lookup:
    #     User.find({"broker_ancestry": broker.id})
    # matches every descendant (sub-brokers + their clients) since the array
    # contains the broker.id at any depth. Top broker under an admin: [].
    # Sub-broker: [top_broker.id]. Sub-sub-broker: [top_broker.id, parent.id].
    broker_ancestry: list[PydanticObjectId] = Field(default_factory=list)

    # ── Fixed-brokerage flow ("Account 2") — parallel to the % sharing ──
    # A SEPARATE, opt-in model (does NOT touch the existing pnl/brokerage %
    # sharing). When `is_fixed_brokerage` is set on an ADMIN/BROKER, the node's
    # PARENT takes a FIXED per-lot / per-crore brokerage from this node's whole
    # subtree volume — regardless of what this node charges its own users. The
    # rate here is what the PARENT collects from THIS node.
    #   • ADMIN  → set by the super-admin at create (SA's cut from the admin).
    #   • BROKER → set by the owning admin/broker at create (parent's cut).
    # A fixed-brokerage admin's brokers/sub-brokers are themselves fixed-brokerage.
    is_fixed_brokerage: bool = False
    # "No-brokerage admin" type (3rd admin type). When True, on the admin-book
    # per-trade flow the SA collects 100% of the brokerage from the admin's OWN
    # (direct, assigned_broker_id=None) users, while brokerage from users under
    # the admin's BROKERS stays with the admin. PnL still follows pnl_share_pct.
    # Distinct from admin_brokerage_share_pct=0 (which means SA takes NONE).
    no_self_brokerage: bool = False
    # LEGACY single-rate (pre-2026-07-13). Superseded by per-segment rates
    # below; kept so old rows don't break and Account 2 can fall back.
    fixed_brokerage_unit: str | None = None  # "per_lot" | "per_crore"
    fixed_brokerage_rate: Decimal128 | None = None  # 🪙 per lot / per crore
    # PER-SEGMENT FROZEN fixed-brokerage rate the PARENT takes from THIS node,
    # keyed by admin segment name (SEGMENT_CODES: NSE_STK_OPT, MCX_FUT, CRYPTO…).
    # SNAPSHOTTED the moment the parent sets this node's segment brokerage via the
    # per-node segment editor — so the child later raising what it charges its OWN
    # users (its live SubAdminSegmentOverride commission) never changes what the
    # parent collects. Shape: { seg_name: {"commission": float, "commissionType":
    # "per_lot"|"per_crore"} }. Account 2 reads THIS.
    fixed_brokerage_rates: dict[str, dict] = Field(default_factory=dict)

    # Broker profile — only meaningful when role == BROKER.
    broker_permissions: BrokerPermissions | None = None
    broker_pnl_share_pct: Decimal128 | None = None  # 0..100
    # Separate brokerage-sharing %, independent of the PnL share. None on
    # brokers created before the split — those inherit broker_pnl_share_pct
    # everywhere, so their settlement math stays byte-identical to before.
    broker_brokerage_share_pct: Decimal128 | None = None  # 0..100

    # Broker's PUBLIC city/place — set by the broker themselves. Powers the
    # signup broker-picker's place-wise search. Only meaningful for role==BROKER
    # but stored top-level + indexed for a fast search; NULL until the broker
    # sets it. Distinct from the private `kyc.city`.
    city: str | None = None

    # Per-user "auto settle" toggle (default ON). When True (default),
    # `wallet_service.adjust()` floors any debit that would push
    # available_balance below 0 and books the overflow into
    # settlement_outstanding automatically — that's the existing
    # 21-May floor-at-0 behaviour every legacy user runs.
    #
    # When False (admin opt-out via the user-detail toggle), the
    # wallet is allowed to go NEGATIVE. The same path queues a
    # pending `SettlementRequest` instead so the admin can manually
    # approve from the Payments → Settlement Requests tab. While a
    # PENDING request exists the order validator refuses new-opening
    # orders (closing trades still pass through via the existing
    # `is_reducing` exemption).
    auto_settlement: bool = True

    # ADMIN-level bulk switch for the above. On an ADMIN / SUPER_ADMIN row this
    # is the "Auto-settlement" state shown on their Payments page. Default ON.
    # When the admin flips it OFF, EVERY user in their pool is bulk-set to
    # `auto_settlement = False` at once (so all their outstanding goes to
    # negative balance + manual SettlementRequest), and NEW signups under them
    # inherit it. Purely the pool default/toggle state — the per-user
    # `auto_settlement` above is still what wallet_service reads per debit.
    pool_auto_settlement: bool = True

    # Per-SEGMENT-WALLET auto-settlement override, on an ADMIN / SUPER_ADMIN row.
    # Keys are wallet kinds ("NSE_BSE" / "MCX" / "CRYPTO" / "FOREX"); an absent
    # key = True (default ON = floor that segment wallet at 0 + book to
    # settlement_outstanding). Set a kind to False and that segment wallet is
    # allowed to go NEGATIVE (mines) on a shortfall for every user in the pool,
    # instead of flooring. Read live in `segment_wallet_service.adjust` (only on
    # the below-zero path), so it applies to all current + future users at once.
    pool_auto_settlement_kinds: dict[str, bool] = Field(default_factory=dict)

    # Per-admin support WhatsApp number, shown to that admin's downstream
    # users on the "Add funds → Support" button and any other Contact-
    # support affordance in the apk/user web. Cascade resolution: when a
    # user requests their support number, we walk up the parent_id chain
    # (CLIENT → DEALER/MASTER/BROKER → ADMIN → SUPER_ADMIN) and return
    # the first non-empty value. Falls back to the global
    # `platform.support_whatsapp` PlatformSetting if nothing is set
    # anywhere in the chain. Only meaningful for admin-tier roles
    # (SUPER_ADMIN / ADMIN / BROKER); CLIENT rows leave this NULL.
    # Stored as a free-form string so country code + spacing + the
    # leading `+` survive round-trips — the apk's `buildWhatsappUrl`
    # strips non-digits before composing the wa.me link.
    support_whatsapp: str | None = None

    # ── White-label branding (Phase 1: schema-only, gated by
    # `settings.BRANDING_ENABLED`). All optional, default `None`, so
    # existing 10k user rows behave exactly as today on read. Only
    # meaningful when role == ADMIN, except `signup_origin` which is
    # stamped on every newly-registered user post-rollout. None for any
    # legacy user is treated as "PLATFORM" by the resolution logic, so
    # zero backfill is needed.
    #
    # Why these fields can ship invisibly:
    #   * Pydantic/Beanie auto-fills missing keys with `None` on read.
    #   * The unique index on `custom_domain` below is *sparse* — rows
    #     with `None` are simply not indexed, so the existing 10k rows
    #     contribute zero index entries and zero write overhead.
    #   * No code path consumes these fields until BRANDING_ENABLED
    #     flips on (Phase 2+) and the public `/branding/*` endpoints
    #     ship.
    brand_name: str | None = None
    logo_url: str | None = None  # "/uploads/logos/logo-<admin_id>-<ts>.png"

    # Custom domain (sparse-unique — see Settings.indexes). Stored
    # lowercased, no scheme: "mybroker.com".
    custom_domain: str | None = None

    # Lifecycle state machine for `custom_domain` provisioning.
    #   PENDING_DNS  → admin saved domain, hasn't verified yet
    #   DNS_VERIFIED → backend confirmed A records point to platform IP
    #   PROVISIONING → certbot Celery task running
    #   READY        → cert installed, nginx reloaded — domain live
    #   FAILED       → cert issuance failed (last_error populated)
    custom_domain_status: str | None = None
    custom_domain_last_error: str | None = None
    custom_domain_verified_at: datetime | None = None

    # ── Games subsystem ────────────────────────────────────────────────
    # Referral tracking (first-win-per-game gate for referral rewards).
    game_referral: GameReferralStats | None = None
    # Referrer link (mirrors Stockex User.referredBy). Set at signup when a
    # user joins via a referral; default None → no referral. Additive.
    referred_by: PydanticObjectId | None = None
    # What THIS user has earned by referring others (rollup). Additive.
    referral_stats: ReferralStats | None = None
    # ── Admin/broker-tier referral config (SUPER_ADMIN / ADMIN only) ────
    # Which segments pay referral rewards for this admin's subtree, and the
    # house-earnings threshold gate. Only meaningful on admin-tier users;
    # None on clients → defaults apply. Additive.
    referral_distribution_enabled: ReferralDistributionEnabled | None = None
    referral_eligibility: ReferralEligibility | None = None
    # Admin-hierarchy patti (trading P&L cascade). Only meaningful on
    # admin-tier users; None → this node takes no patti. Additive, opt-in.
    patti_sharing: PattiSharing | None = None
    # Kuber funding-plan flags (used by kuber_service.resolve_funding_plan).
    is_franchise_root: bool = False
    patti_child_pct: float | None = None

    # ── Multi-wallet (per-segment trading wallets — wallet.md) ──────────
    # The user's PRIMARY trading wallet — drives the default Market/trade view.
    # Default NSE_BSE. Additive; existing users default to NSE_BSE on read.
    primary_wallet_kind: str = "NSE_BSE"
    # Hierarchy-commission eligibility (mirrors Stockex Admin.receivesHierarchyBrokerage).
    # When False, this admin/broker's games commission share is diverted to the
    # super-admin. Default True → everyone eligible. Only meaningful for
    # ADMIN/BROKER-tier users.
    receives_hierarchy_brokerage: bool = True

    # How this user originally signed up — drives the post-login
    # cross-origin redirect gate. `None` ≡ "PLATFORM" (the default for
    # every existing legacy user, hence no backfill).
    #   PLATFORM         : signed up at stockex.com/register (or pre-rollout)
    #   BRANDED_REFERRAL : signed up via /r/<admin_user_code>/signup or ?ref=
    #   CUSTOM_DOMAIN    : signed up directly on admin's custom_domain host
    signup_origin: str | None = None

    # ── Per-admin platform maintenance settings (ADMIN-tier users) ───────
    # An ADMIN configures these for THEIR OWN downstream users (super-admin
    # doesn't touch them). Both default OFF; the daily maintenance sweep is a
    # no-op until an admin turns one on.
    #   • platform_charge_*  — a DAILY per-user platform fee. When enabled, the
    #     sweep debits `platform_charge_amount` from each of the admin's ACTIVE
    #     users' MAIN wallet once per IST day and credits it to the admin.
    #   • zero_balance_autoclose_enabled — when enabled, a user of this admin
    #     whose whole balance has sat at 🪙0 for ≥7 days is soft-closed
    #     (status → CLOSED, recoverable — NOT hard-deleted).
    platform_charge_enabled: bool = False
    platform_charge_amount: Money = Field(default_factory=lambda: Decimal128("0"))
    zero_balance_autoclose_enabled: bool = False

    # ── Per-user maintenance tracking (CLIENT-tier users) ────────────────
    # IST day-string ("YYYY-MM-DD") of the last daily platform charge, so the
    # sweep never double-charges within a day and self-heals across restarts.
    last_platform_charge_day: str | None = None
    # First moment the sweep observed this user's total balance at 🪙0; cleared
    # the moment any balance returns. `now - zero_balance_since ≥ 7d` → close.
    zero_balance_since: datetime | None = None

    class Settings:
        name = "users"
        use_state_management = True
        indexes = [
            IndexModel([("email", ASCENDING)], unique=True),
            IndexModel([("mobile", ASCENDING)], unique=True),
            IndexModel([("user_code", ASCENDING)], unique=True),
            IndexModel([("parent_id", ASCENDING)]),
            IndexModel([("role", ASCENDING), ("status", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            IndexModel([("kyc.pan", ASCENDING)]),
            IndexModel([("assigned_admin_id", ASCENDING), ("role", ASCENDING)]),
            IndexModel([("assigned_broker_id", ASCENDING), ("role", ASCENDING)]),
            # Broker place-wise search for the signup broker-picker.
            IndexModel([("role", ASCENDING), ("city", ASCENDING)]),
            # Multikey index — Mongo creates one entry per element of the
            # array, so {"broker_ancestry": <id>} matches in O(log n).
            IndexModel([("broker_ancestry", ASCENDING)]),
            # White-label custom domain — partial + unique. `sparse=True`
            # was wrong: MongoDB sparse only skips MISSING fields, not
            # explicit `null` values, and Beanie/Pydantic always serializes
            # the field (default None) so every user row had `custom_domain: null`,
            # collapsing the unique constraint to "at most one row with null".
            # `partialFilterExpression` correctly indexes only rows that
            # actually have a string custom_domain set.
            IndexModel(
                [("custom_domain", ASCENDING)],
                unique=True,
                partialFilterExpression={"custom_domain": {"$type": "string"}},
                name="custom_domain_unique_partial",
            ),
        ]

    def is_admin(self) -> bool:
        # BROKER role is considered admin-tier for purposes of the admin
        # login endpoint + admin-side JWT audience. Permission gating then
        # narrows behavior down via require_admin_permission /
        # require_broker_permission.
        return self.role in {
            UserRole.SUPER_ADMIN,
            UserRole.ADMIN,
            UserRole.BROKER,
        }

    def is_internal(self) -> bool:
        return self.role in {
            UserRole.SUPER_ADMIN,
            UserRole.ADMIN,
            UserRole.BROKER,
            UserRole.MASTER,
            UserRole.DEALER,
        }

    def record_successful_login(self, ip: str) -> None:
        self.last_login_at = now_utc()
        self.last_login_ip = ip
        self.failed_login_count = 0
        self.locked_until = None


# ── User segment toggle (which segments this user may even *see*) ────
class UserSegment(TimestampMixin):
    user_id: PydanticObjectId
    segment: str  # SegmentType.value
    enabled: bool = True

    class Settings:
        name = "user_segments"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("segment", ASCENDING)], unique=True),
        ]
