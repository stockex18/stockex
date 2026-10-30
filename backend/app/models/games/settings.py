"""GameSettings singleton — the master config for the whole games system.

One document only (enforced by a unique `key` index). `get_settings()` lazily
creates it and AUTO-HEALS any of the 7 known game blocks that are missing, so
adding a game to the schema never 404s an existing install (mirrors
`netting_service.get_global_risk`).

SuperAdmin is the only role that can write these. Hierarchy / referral fields
are stored but UNUSED in v1 (deferred — see plan §Decisions).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from app.models._base import TimestampMixin

# ── Canonical game keys (GameSettings keys, spec §7) ─────────────────────
GAME_KEYS: tuple[str, ...] = (
    "niftyUpDown",
    "btcUpDown",
    "niftyNumber",
    "btcNumber",
    "niftyBracket",
    "niftyJackpot",
    "btcJackpot",
)


class HierarchyShare(BaseModel):
    """Stored but UNUSED in v1 (hierarchy commission deferred)."""

    sub_broker_percent: float = 0.0
    broker_percent: float = 0.0
    admin_percent: float = 0.0


class ReferralDistribution(BaseModel):
    """Stored but UNUSED in v1 (referral rewards deferred)."""

    win_percent: float = 0.0
    first_win_by_tickets: bool = False
    top_ranks_only: bool = False
    top_ranks_count: int = 0


class GameConfig(BaseModel):
    """Per-game config. Superset of every game's levers (spec §2.2–2.3);
    fields not relevant to a given game are simply ignored by that game's
    service. Every field has a safe default so a partially-specified block
    still validates."""

    enabled: bool = True
    min_tickets: int = 1
    max_tickets: int = 500
    win_multiplier: float = 1.95
    brokerage_percent: float = 5.0  # fee on profit (v1: informational)
    ticket_price: float = 300.0
    max_bets_per_round: int = 0  # 0 = unlimited

    # Up/Down window timing
    round_duration: int = 900  # seconds (15m)
    cooldown_between_rounds: int = 0
    start_time: str = "09:15:00"
    end_time: str = "15:45:00"
    max_tickets_up_per_window: int = 0  # 0 = unlimited
    max_tickets_down_per_window: int = 0
    # Up/Down: the most tickets ONE user may hold in ONE window, UP and DOWN
    # counted together, across every bet and modify in that window. 0 =
    # unlimited. Enforced in `services/games/updown_limits.py`. Nifty and BTC
    # are separate games, so each has its own cap. Super-admin editable.
    max_tickets_per_window: int = 5
    # BTC up/down
    allowed_expiry_times: list[int] = Field(default_factory=list)
    default_expiry_time: int = 60

    # Number game
    fixed_profit: float = 0.0  # 0 → use ticket_price × win_multiplier
    bets_per_day: int = 10
    max_tickets_per_number: int = 2
    all_decimals: bool = False  # False → .00–.95 step 5 ; True → .00–.99

    # Result source (number games). True (default) → the winning number is
    # derived from the live broker/Zerodha close at result_time. False → the
    # super-admin types the day's result manually (GameManualResult) and the
    # settler waits for it instead of reading the feed. Surfaced as an "Auto
    # result (Zerodha)" switch in the admin panel — ON = auto, OFF = manual.
    auto_result: bool = True

    # Bracket
    bracket_gap: float = 20.0
    bracket_gap_type: str = "point"  # "point" | "percentage"
    bracket_gap_percent: float = 0.1
    bracket_anchor_to_spot: bool = True
    bracket_session_close_rule: str = "directionVsEntry"  # | "breakPastBands"
    expiry_minutes: int = 5

    # Bidding / result windows (Number, Bracket, Jackpot)
    bidding_start_time: str = "09:15:00"
    bidding_end_time: str = "15:24:00"
    result_time: str = "15:45:00"
    max_bid_time: str = "15:40:00"

    # Jackpot
    top_winners: int = 20
    bids_per_day: int = 100
    max_tickets_per_request: int = 1
    # rank (as string "1".."N") → percent of pool
    prize_percentages: dict[str, float] = Field(default_factory=dict)

    # ── Hierarchy commission (ACTIVE) ────────────────────────────────
    # Up/Down + Bracket use the WIN-BROKERAGE model: T = brokerage_percent%
    # of profit, then split by profit_*_percent (user rebate + SubBroker +
    # Broker + Admin + SuperAdmin remainder), funded from the house.
    profit_user_percent: float = 0.0
    profit_sub_broker_percent: float = 10.0
    profit_broker_percent: float = 20.0
    profit_admin_percent: float = 30.0
    sub_broker_share_to_broker: bool = True
    # Number + Jackpot use the GROSS-PRIZE model: hierarchy takes
    # gross_prize_*_percent of the winner's gross, funded from the house.
    gross_prize_sub_broker_percent: float = 0.0
    gross_prize_broker_percent: float = 0.0
    gross_prize_admin_percent: float = 0.0

    # Referral-per-win: referrer earns referral_win_percent% of one ticket
    # price on the referred user's FIRST win in this game (funded from the
    # house). 0 disables. threshold = min house games-earnings before payout.
    # (DEPRECATED — superseded by the 4-level %-of-win-profit model below;
    # kept for back-compat, no longer used for distribution.)
    referral_win_percent: float = 0.0
    referral_top_ranks_only: bool = False
    referral_top_ranks_count: int = 0

    # ── 4-level %-of-win-profit model (ACTIVE) ───────────────────────
    # On EVERY win, profit = payout − stake (per winning bet, ≥0). Each of the
    # four levels gets a FLAT % of that profit, funded from the house:
    #   Admin/Broker/Sub-broker → HELD (temporary) wallet via the hierarchy
    #     cascade (missing role bubbles up; receives_hierarchy_brokerage gates).
    #   Referrer (player.referred_by, a CLIENT) → their GAMES wallet, every win.
    admin_profit_pct: float = 0.0
    broker_profit_pct: float = 0.0
    sub_broker_profit_pct: float = 0.0
    referrer_profit_pct: float = 0.0
    # Referrer (the CLIENT who shared the code) is paid ONCE per game per
    # referred friend — on the friend's FIRST win in this game — when True
    # (default). False → pay the referrer on EVERY win. Hierarchy (SB/B/Admin)
    # ALWAYS pays on every win regardless. Super-admin editable per game.
    referrer_first_win_only: bool = True

    # Legacy embedded blocks (kept for backward-compat; unused by v2 flow).
    hierarchy: HierarchyShare = Field(default_factory=HierarchyShare)
    referral_distribution: ReferralDistribution = Field(default_factory=ReferralDistribution)


class ProfitDistribution(BaseModel):
    super_admin_percent: float = 40.0
    admin_percent: float = 30.0
    broker_percent: float = 20.0
    sub_broker_percent: float = 10.0


class GameSettings(TimestampMixin):
    # Singleton guard — exactly one row.
    key: str = "GLOBAL"

    # ── Global levers ────────────────────────────────────────────────
    games_enabled: bool = True
    maintenance_mode: bool = False
    maintenance_message: str = "Games are under maintenance. Please check back soon."
    token_value: float = 300.0  # 1 token = 🪙300 (display as "tickets")
    platform_commission: float = 5.0

    profit_distribution: ProfitDistribution = Field(default_factory=ProfitDistribution)

    global_min_tickets: int = 1
    global_max_tickets: int = 1000
    daily_bet_limit: float = 500000.0
    daily_win_limit: float = 1000000.0
    game_position_expiry_grace_seconds: int = 3600

    # Per-game config keyed by GameSettings key (GAME_KEYS).
    games: dict[str, GameConfig] = Field(default_factory=dict)

    class Settings:
        name = "game_settings"
        indexes = [IndexModel([("key", ASCENDING)], unique=True)]

    # ── Singleton accessor ───────────────────────────────────────────
    # NOTE: must NOT be named `get_settings` — Beanie's Document reserves
    # that classmethod (used internally by get_motor_collection()).
    @classmethod
    async def load_singleton(cls) -> "GameSettings":
        """Lazily create the singleton and auto-heal any missing game block."""
        doc = await cls.find_one(cls.key == "GLOBAL")
        if doc is None:
            doc = cls(games={k: GameConfig(**_DEFAULTS[k]) for k in GAME_KEYS})
            try:
                await doc.insert()
            except Exception:
                # Lost a create race with another worker — re-read.
                doc = await cls.find_one(cls.key == "GLOBAL")
                if doc is None:
                    raise
        # Auto-heal newly added game keys.
        healed = False
        for k in GAME_KEYS:
            if k not in doc.games:
                doc.games[k] = GameConfig(**_DEFAULTS[k])
                healed = True
        if healed:
            await doc.save()
        return doc


def _jackpot_prizes() -> dict[str, float]:
    """Top-20 rank → pool % (sums ~100). Rank 1 45%, tapering."""
    return {
        "1": 45.0, "2": 10.0, "3": 8.0, "4": 6.0, "5": 5.0,
        "6": 4.0, "7": 3.5, "8": 3.0, "9": 2.5, "10": 2.0,
        "11": 1.7, "12": 1.5, "13": 1.3, "14": 1.1, "15": 1.0,
        "16": 0.9, "17": 0.8, "18": 0.7, "19": 0.6, "20": 0.4,
    }


# Per-game defaults (spec §2.3). Only the fields that differ from GameConfig
# defaults are listed; the rest fall back to the GameConfig field defaults.
_DEFAULTS: dict[str, dict[str, Any]] = {
    # Incentive (sub_broker/broker/admin_profit_pct) + referrer_profit_pct are a
    # FLAT % of the gross WINNING amount (the full payout/prize), funded from the
    # house. Betting is open only in [start/bidding window], results at result_time.
    "niftyUpDown": {
        # ticket 600 · winning = 600 × 1.66667 = 1000
        "win_multiplier": 1.66667, "round_duration": 900, "brokerage_percent": 5.0,
        "start_time": "09:15:00", "end_time": "15:00:00", "ticket_price": 600.0,
        # incentive on WINNING → SB 5% / B 1% / A 1% · referral 5%
        "sub_broker_profit_pct": 5.0, "broker_profit_pct": 1.0, "admin_profit_pct": 1.0, "referrer_profit_pct": 5.0,
    },
    "btcUpDown": {
        # ticket 600 · winning = 600 × 1.66667 = 1000 · betting 00:00–22:29:59
        "win_multiplier": 1.66667, "round_duration": 900, "brokerage_percent": 5.0,
        "start_time": "00:00:00", "end_time": "22:30:00", "ticket_price": 600.0,
        "allowed_expiry_times": [60, 120, 300, 600, 900], "default_expiry_time": 60,
        "sub_broker_profit_pct": 5.0, "broker_profit_pct": 1.0, "admin_profit_pct": 1.0, "referrer_profit_pct": 5.0,
    },
    "niftyNumber": {
        # ticket 675 · winning = 10000 gross per ticket (675 × 14.81482 ≈ 10000)
        "win_multiplier": 14.81482, "fixed_profit": 10000.0, "ticket_price": 675.0,
        "bets_per_day": 10, "max_tickets_per_number": 2, "all_decimals": False,
        "bidding_start_time": "09:15:00", "bidding_end_time": "15:15:00",
        "result_time": "15:45:00", "max_bid_time": "15:14:00",
        # incentive on WINNING → SB 8% / B 1% / A 1% · referral 10%
        "sub_broker_profit_pct": 8.0, "broker_profit_pct": 1.0, "admin_profit_pct": 1.0, "referrer_profit_pct": 10.0,
    },
    "btcNumber": {
        # ticket 675 · winning = 10000 gross per ticket · betting 00:00–21:00, result 23:00
        "win_multiplier": 14.81482, "fixed_profit": 10000.0, "ticket_price": 675.0,
        "bets_per_day": 10, "max_tickets_per_number": 2, "all_decimals": True,
        "bidding_start_time": "00:00:00", "bidding_end_time": "21:00:00",
        "result_time": "23:00:00", "max_bid_time": "20:59:00",
        "sub_broker_profit_pct": 8.0, "broker_profit_pct": 1.0, "admin_profit_pct": 1.0, "referrer_profit_pct": 10.0,
    },
    "niftyBracket": {
        # ticket 1100 · winning = 1100 × 1.818189 ≈ 2000 · window 09:15–15:29:59,
        # result 15:30:20 — 20 s AFTER the 15:30 close so Zerodha's OFFICIAL
        # closing minute candle is published + the WS feed has stopped, so we
        # settle on the true close (not the lagging live tick).
        "ticket_price": 1100.0, "win_multiplier": 1.818189, "bracket_gap": 20.0,
        "bracket_gap_type": "point", "bracket_anchor_to_spot": True,
        "bracket_session_close_rule": "directionVsEntry", "expiry_minutes": 5,
        "bidding_start_time": "09:15:00", "bidding_end_time": "15:29:59",
        "result_time": "15:30:20", "brokerage_percent": 5.0,
        # incentive on WINNING → SB 2.5% / B 0.5% / A 0.5% · referral 2.5%
        "sub_broker_profit_pct": 2.5, "broker_profit_pct": 0.5, "admin_profit_pct": 0.5, "referrer_profit_pct": 2.5,
    },
    "niftyJackpot": {
        # ticket 1100 · one ticket at once · winning from bank · top 20 winners
        "top_winners": 20, "ticket_price": 1100.0, "bids_per_day": 100,
        "max_tickets_per_request": 1, "bidding_start_time": "09:15:00",
        "bidding_end_time": "15:00:00", "result_time": "15:45:00", "max_bid_time": "14:59:00",
        "prize_percentages": _jackpot_prizes(),
        # incentive on WINNING (prize) → SB 8% / B 1% / A 1% · referral 5% (flat)
        "sub_broker_profit_pct": 8.0, "broker_profit_pct": 1.0, "admin_profit_pct": 1.0, "referrer_profit_pct": 5.0,
    },
    "btcJackpot": {
        # ticket 1100 · betting 00:00–21:00, result 23:00 · top 20 winners
        "top_winners": 20, "ticket_price": 1100.0, "bids_per_day": 200,
        "max_tickets_per_request": 1, "bidding_start_time": "00:00:00",
        "bidding_end_time": "21:00:00", "result_time": "23:00:00", "max_bid_time": "20:59:00",
        "prize_percentages": _jackpot_prizes(),
        "sub_broker_profit_pct": 8.0, "broker_profit_pct": 1.0, "admin_profit_pct": 1.0, "referrer_profit_pct": 5.0,
    },
}
