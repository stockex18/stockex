"""Per-game bet/bid records, published results, and the settlement
idempotency guard. All additive collections.

`game_key` on every row is the GameSettings key (spec §7), e.g. "niftyUpDown".
`bet_date` / `settlement_day` are IST day strings ("YYYY-MM-DD") so day-scoped
queries and idempotency are timezone-stable.
"""

from __future__ import annotations

from datetime import datetime

from beanie import PydanticObjectId
from bson import Decimal128
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.models._base import StrEnum, TimestampMixin
from app.models._types import Money


def _zero() -> Decimal128:
    return Decimal128("0")


class GameBetStatus(StrEnum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    TIE = "TIE"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class UpDownPrediction(StrEnum):
    UP = "UP"
    DOWN = "DOWN"


class WindowResult(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    TIE = "TIE"


# ── Published results (per window / per day) ─────────────────────────────
class GameResult(TimestampMixin):
    game_key: str
    day: str  # IST "YYYY-MM-DD"
    window_number: int | None = None  # up/down only
    open_price: Money = Field(default_factory=_zero)
    close_price: Money = Field(default_factory=_zero)
    result: str = ""  # "UP"/"DOWN"/"TIE" (up/down) OR stringified number/price
    result_number: int | None = None  # number games
    locked_price: Money | None = None  # jackpot lock
    price_source: str = ""
    result_declared: bool = True

    class Settings:
        name = "game_results"
        indexes = [
            IndexModel(
                [("game_key", ASCENDING), ("day", ASCENDING), ("window_number", ASCENDING)],
                unique=True,
                name="game_result_unique_window",
            ),
            IndexModel([("game_key", ASCENDING), ("created_at", DESCENDING)]),
        ]


# ── Admin manual result override (number games) ──────────────────────────
class GameManualResult(TimestampMixin):
    """A super-admin-typed daily result for a number game.

    Only consulted when the game's `auto_result` toggle is OFF (manual mode).
    One row per (game_key, day). `close_price` is the price the admin typed
    (e.g. NIFTY 24072.75); `result_number` is the winning two-digit number
    derived from it (75). Storing both keeps the user display — which shows
    the closing price AND the number — consistent with the auto path.

    Settlement reads this instead of the Zerodha close. It is NOT the
    published result on its own: the settler still writes the usual
    `GameResult` row from it at result_time, so the existing user endpoints
    and the "show at 3:45" gating work unchanged.
    """

    game_key: str
    day: str  # IST "YYYY-MM-DD"
    result_number: int
    close_price: Money | None = None
    set_by: PydanticObjectId | None = None

    class Settings:
        name = "game_manual_results"
        indexes = [
            IndexModel(
                [("game_key", ASCENDING), ("day", ASCENDING)],
                unique=True,
                name="game_manual_result_unique_day",
            ),
        ]


# ── Idempotency guard — the double-credit backstop ───────────────────────
class UpDownWindowSettlement(TimestampMixin):
    """One row per (user, game, window, day). Unique index makes a window
    bet impossible to credit twice — insert-then-credit; a duplicate insert
    throws DuplicateKeyError → the settler skips."""

    user_id: PydanticObjectId
    game_key: str
    window_number: int
    settlement_day: str

    class Settings:
        name = "updown_window_settlements"
        indexes = [
            IndexModel(
                [
                    ("user_id", ASCENDING),
                    ("game_key", ASCENDING),
                    ("window_number", ASCENDING),
                    ("settlement_day", ASCENDING),
                ],
                unique=True,
                name="updown_settlement_unique",
            ),
        ]


# ── Up/Down bet (Nifty + BTC share this shape) ───────────────────────────
class UpDownBet(TimestampMixin):
    user_id: PydanticObjectId
    game_key: str  # "niftyUpDown" | "btcUpDown"
    prediction: UpDownPrediction
    amount: Money = Field(default_factory=_zero)  # stake
    # Tickets in this bet (amount ÷ ticket price at placement). Stored so the
    # referrer's one-ticket share stays right even if the ticket price changes
    # before settlement. None on bets placed before this field existed.
    tickets: int | None = None
    entry_price: Money = Field(default_factory=_zero)
    window_number: int
    settlement_day: str
    status: GameBetStatus = GameBetStatus.PENDING
    payout: Money = Field(default_factory=_zero)
    result_price: Money | None = None

    class Settings:
        name = "game_updown_bets"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel(
                [("game_key", ASCENDING), ("settlement_day", ASCENDING), ("window_number", ASCENDING)]
            ),
            IndexModel([("status", ASCENDING)]),
        ]


# ── Number bet (Nifty + BTC) ─────────────────────────────────────────────
class NumberBet(TimestampMixin):
    user_id: PydanticObjectId
    game_key: str  # "niftyNumber" | "btcNumber"
    selected_number: int  # 0..99 (or step-5 for nifty)
    quantity: int = 1
    amount: Money = Field(default_factory=_zero)  # total stake
    ticket_price: Money = Field(default_factory=_zero)
    bet_date: str  # IST day
    status: GameBetStatus = GameBetStatus.PENDING
    result_number: int | None = None
    payout: Money = Field(default_factory=_zero)

    class Settings:
        name = "game_number_bets"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("game_key", ASCENDING), ("bet_date", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
        ]


# ── Bracket trade (Nifty) ────────────────────────────────────────────────
class BracketPrediction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class BracketTrade(TimestampMixin):
    user_id: PydanticObjectId
    game_key: str = "niftyBracket"
    prediction: BracketPrediction
    amount: Money = Field(default_factory=_zero)
    # Tickets in this trade (amount ÷ ticket price at placement) -- same reason
    # as UpDownBet.tickets. None on trades placed before this field existed.
    tickets: int | None = None
    entry_price: Money = Field(default_factory=_zero)
    spot_at_order: Money = Field(default_factory=_zero)
    upper_target: Money = Field(default_factory=_zero)
    lower_target: Money = Field(default_factory=_zero)
    expires_at: datetime
    bet_date: str
    status: GameBetStatus = GameBetStatus.PENDING
    payout: Money = Field(default_factory=_zero)
    result_price: Money | None = None

    class Settings:
        name = "game_bracket_trades"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("status", ASCENDING), ("expires_at", ASCENDING)]),
            IndexModel([("bet_date", ASCENDING)]),
        ]


# ── Jackpot bids (Nifty + BTC) ───────────────────────────────────────────
class JackpotBid(TimestampMixin):
    user_id: PydanticObjectId
    game_key: str  # "niftyJackpot" | "btcJackpot"
    amount: Money = Field(default_factory=_zero)
    ticket_count: int = 1
    predicted_price: Money = Field(default_factory=_zero)  # niftyPriceAtBid / predictedBtc
    bet_date: str
    status: GameBetStatus = GameBetStatus.PENDING
    rank: int | None = None
    prize: Money = Field(default_factory=_zero)

    class Settings:
        name = "game_jackpot_bids"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("game_key", ASCENDING), ("bet_date", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
        ]


class JackpotBank(TimestampMixin):
    """Per-day pool/bank for a jackpot game. One row per (game_key, bet_date)."""

    game_key: str
    bet_date: str
    total_stake: Money = Field(default_factory=_zero)
    bids_count: int = 0
    locked_price: Money | None = None
    result_declared: bool = False

    class Settings:
        name = "game_jackpot_banks"
        indexes = [
            IndexModel(
                [("game_key", ASCENDING), ("bet_date", ASCENDING)],
                unique=True,
                name="jackpot_bank_unique",
            ),
        ]
