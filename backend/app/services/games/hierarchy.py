"""Games hierarchy commission distribution (mirrors D:\\Stockex).

Two models, both FUNDED FROM THE HOUSE (SUPER_ADMIN main wallet):
  • WIN-BROKERAGE (Up/Down, Bracket): T = brokerage_percent% of profit, split
    userRebate + SubBroker + Broker + Admin + SuperAdmin(remainder) by the
    profit_*_percent config.
  • GROSS-PRIZE (Number, Jackpot): gross_prize_*_percent of the winner's gross
    to SubBroker/Broker/Admin.

Cascade: a missing role's share rolls up (SubBroker→Broker→Admin→SuperAdmin),
with the `sub_broker_share_to_broker` toggle. Ineligible admins
(`receives_hierarchy_brokerage=False`) have their share diverted to SuperAdmin
(i.e. it simply stays in the house). Non-SA earnings accrue to the recipient's
TEMPORARY wallet; SA's remainder already sits in the house so no move is made.

New-folder hierarchy is on the single `User` collection:
  admin        = user.assigned_admin_id            (role ADMIN)
  broker       = root broker (top of broker_ancestry, or the sole broker)
  sub_broker   = the immediate broker when nested   (user.assigned_broker_id)
"""

from __future__ import annotations

import logging
from decimal import Decimal

from beanie import PydanticObjectId

from app.models.games.settings import GameConfig
from app.models.user import User
from app.services.games import wallet_service
from app.utils.decimal_utils import ZERO, quantize_money, to_decimal, to_decimal128

logger = logging.getLogger(__name__)


async def _resolve_chain(user: User) -> dict[str, User | None]:
    """Resolve the {sub_broker, broker, admin} User docs above `user`."""
    brokers: list[PydanticObjectId] = []
    if getattr(user, "assigned_broker_id", None):
        brokers.append(user.assigned_broker_id)
    for b in reversed(list(getattr(user, "broker_ancestry", None) or [])):
        if b not in brokers:
            brokers.append(b)  # nearest → root order

    sub_broker_id: PydanticObjectId | None = None
    broker_id: PydanticObjectId | None = None
    if len(brokers) >= 2:
        sub_broker_id = brokers[0]   # nearest broker = sub-broker
        broker_id = brokers[-1]      # root broker = broker
    elif len(brokers) == 1:
        broker_id = brokers[0]       # sole broker = BROKER bucket

    admin_id = getattr(user, "assigned_admin_id", None)

    async def _load(uid: PydanticObjectId | None) -> User | None:
        if not uid:
            return None
        try:
            return await User.get(uid)
        except Exception:
            return None

    return {
        "sub_broker": await _load(sub_broker_id),
        "broker": await _load(broker_id),
        "admin": await _load(admin_id),
    }


def _cascade(
    pct_sb: float, pct_br: float, pct_ad: float,
    *, has_sb: bool, has_br: bool, has_ad: bool, sub_to_broker: bool,
) -> tuple[float, float, float]:
    """Return effective (sb, br, ad) percents after rolling missing roles up.
    SuperAdmin implicitly keeps the remainder (100 − used), which stays in the
    house, so we don't return it."""
    sb, br, ad = pct_sb, pct_br, pct_ad
    if not has_sb:
        if sub_to_broker and has_br:
            br += sb
        elif has_ad:
            ad += sb
        # else → stays with SA
        sb = 0.0
    if not has_br:
        if has_ad:
            ad += br
        # else → SA
        br = 0.0
    if not has_ad:
        # → SA
        ad = 0.0
    return sb, br, ad


async def _pay(role_user: User | None, amount: Decimal, *, game_key: str, role: str, base: Decimal, related_user_id) -> None:
    """Credit one hierarchy recipient's temporary wallet, funded from the
    house. Skips ineligible admins (their share stays in the house)."""
    if role_user is None or amount <= ZERO:
        return
    if not bool(getattr(role_user, "receives_hierarchy_brokerage", True)):
        return  # diverted → stays in house (SA)
    # Move the money out of the house, into the recipient's temp wallet.
    await wallet_service.house_settle(
        -amount, game_key=game_key,
        narration=f"Games commission → {role} ({role_user.user_code})",
        # The player this commission arises from. Every caller already
        # refuses a demo `user` at the top, so this is the second lock on
        # the same door — but it is the only one that still holds if a new
        # caller is added and forgets the first.
        user_id=related_user_id,
    )
    pct = float((amount / base * to_decimal(100))) if base > 0 else 0.0
    await wallet_service.credit_admin_temp(
        role_user.id, amount, game_key=game_key,
        description=f"Games commission — {role} ({pct:.1f}% of {base})",
        meta={"role": role, "base": str(base), "related_user_id": str(related_user_id)},
    )


async def _bump_earnings(user: User, hierarchy_total) -> None:
    """Record the games-segment hierarchy earnings for this user's subtree so
    the referral threshold gate has data. Best-effort; never raises."""
    try:
        from app.services import referral_service

        await referral_service.bump_hierarchy_earnings(
            getattr(user, "assigned_admin_id", None), "games", hierarchy_total
        )
    except Exception:
        logger.exception("games_bump_earnings_failed user=%s", getattr(user, "id", None))


async def distribute_win_brokerage(
    user: User, total_brokerage, game_key: str, cfg: GameConfig, *, skip_user_rebate: bool = True
) -> None:
    """Split win-side brokerage T through the hierarchy (Up/Down, Bracket)."""
    T = quantize_money(to_decimal(total_brokerage))
    if T <= ZERO or getattr(user, "is_demo", False):
        return
    chain = await _resolve_chain(user)
    has_sb, has_br, has_ad = bool(chain["sub_broker"]), bool(chain["broker"]), bool(chain["admin"])
    sb_pct, br_pct, ad_pct = _cascade(
        cfg.profit_sub_broker_percent, cfg.profit_broker_percent, cfg.profit_admin_percent,
        has_sb=has_sb, has_br=has_br, has_ad=has_ad, sub_to_broker=cfg.sub_broker_share_to_broker,
    )
    user_pct = 0.0 if skip_user_rebate else max(0.0, cfg.profit_user_percent)

    user_amt = quantize_money(T * to_decimal(user_pct) / to_decimal(100))
    sb_amt = quantize_money(T * to_decimal(sb_pct) / to_decimal(100))
    br_amt = quantize_money(T * to_decimal(br_pct) / to_decimal(100))
    ad_amt = quantize_money(T * to_decimal(ad_pct) / to_decimal(100))

    if user_amt > ZERO:
        await wallet_service.house_settle(
            -user_amt, game_key=game_key, narration="Games brokerage rebate (user)",
            user_id=user.id,
        )
        await wallet_service.atomic_games_wallet_credit(
            user.id, user_amt, game_key=game_key, description="Brokerage rebate (user share)",
            meta={"kind": "REBATE"},
        )
    await _pay(chain["sub_broker"], sb_amt, game_key=game_key, role="SUB_BROKER", base=T, related_user_id=user.id)
    await _pay(chain["broker"], br_amt, game_key=game_key, role="BROKER", base=T, related_user_id=user.id)
    await _pay(chain["admin"], ad_amt, game_key=game_key, role="ADMIN", base=T, related_user_id=user.id)
    await _bump_earnings(user, sb_amt + br_amt + ad_amt)


async def distribute_profit_split(
    user: User, win_amount, game_key: str, cfg: GameConfig
) -> None:
    """4-level %-of-WINNING model (ACTIVE) — hierarchy leg.

    Each surviving role earns a FLAT % of the gross `win_amount` — the FULL
    winning amount (payout/prize the user receives), NOT payout − stake —
    funded from the house and credited to the recipient's HELD (temporary)
    wallet. Reuses the same cascade as `distribute_win_brokerage` (a missing
    role's share bubbles up, honoring `sub_broker_share_to_broker`) and the
    same eligibility gate (`receives_hierarchy_brokerage=False` → the share
    stays in the house). The referrer leg is handled separately in
    `referral.credit_referral_on_win`."""
    P = quantize_money(to_decimal(win_amount))
    if P <= ZERO or getattr(user, "is_demo", False):
        return
    chain = await _resolve_chain(user)
    has_sb, has_br, has_ad = bool(chain["sub_broker"]), bool(chain["broker"]), bool(chain["admin"])
    sb_pct, br_pct, ad_pct = _cascade(
        cfg.sub_broker_profit_pct, cfg.broker_profit_pct, cfg.admin_profit_pct,
        has_sb=has_sb, has_br=has_br, has_ad=has_ad, sub_to_broker=cfg.sub_broker_share_to_broker,
    )
    sb_amt = quantize_money(P * to_decimal(sb_pct) / to_decimal(100))
    br_amt = quantize_money(P * to_decimal(br_pct) / to_decimal(100))
    ad_amt = quantize_money(P * to_decimal(ad_pct) / to_decimal(100))
    await _pay(chain["sub_broker"], sb_amt, game_key=game_key, role="SUB_BROKER", base=P, related_user_id=user.id)
    await _pay(chain["broker"], br_amt, game_key=game_key, role="BROKER", base=P, related_user_id=user.id)
    await _pay(chain["admin"], ad_amt, game_key=game_key, role="ADMIN", base=P, related_user_id=user.id)
    await _bump_earnings(user, sb_amt + br_amt + ad_amt)


async def _unpay(
    role_user: User | None, amount: Decimal, *, game_key: str, role: str,
    related_user_id=None,
) -> None:
    """Reverse one `_pay`: pull `amount` back from the recipient's temporary
    (HELD) wallet into the house. Best-effort — floors temp at 0 (if the
    commission was already released to main, only what remains is clawed)."""
    if role_user is None or amount <= ZERO:
        return
    if not bool(getattr(role_user, "receives_hierarchy_brokerage", True)):
        return
    try:
        from app.models.wallet import Wallet

        w = await Wallet.find_one(Wallet.user_id == role_user.id)
        if w is not None:
            new_temp = to_decimal(w.temporary_balance) - amount
            if new_temp < ZERO:
                new_temp = ZERO
            w.temporary_balance = to_decimal128(new_temp)
            if hasattr(w, "temporary_total_earned"):
                new_tot = to_decimal(getattr(w, "temporary_total_earned", 0) or 0) - amount
                if new_tot < ZERO:
                    new_tot = ZERO
                w.temporary_total_earned = to_decimal128(new_tot)
            w.version = (w.version or 0) + 1
            await w.save()
    except Exception:
        logger.exception("hierarchy_unpay_temp_failed role=%s", role)
    # Return the money to the house.
    await wallet_service.house_settle(
        amount, game_key=game_key,
        narration=f"Reverse games commission ← {role} ({role_user.user_code})",
        # A reversal must be skipped on exactly the accounts the forward pay
        # was skipped on, or the house keeps money it never handed out.
        user_id=related_user_id,
    )


async def reverse_profit_split(
    user: User, win_amount, game_key: str, cfg: GameConfig
) -> None:
    """Reverse ``distribute_profit_split`` for a mis-declared win — mirrors the
    forward split exactly (config is unchanged on a same-session reversal), then
    claws each role's share back from its HELD wallet into the house."""
    P = quantize_money(to_decimal(win_amount))
    if P <= ZERO or getattr(user, "is_demo", False):
        return
    chain = await _resolve_chain(user)
    has_sb, has_br, has_ad = bool(chain["sub_broker"]), bool(chain["broker"]), bool(chain["admin"])
    sb_pct, br_pct, ad_pct = _cascade(
        cfg.sub_broker_profit_pct, cfg.broker_profit_pct, cfg.admin_profit_pct,
        has_sb=has_sb, has_br=has_br, has_ad=has_ad, sub_to_broker=cfg.sub_broker_share_to_broker,
    )
    sb_amt = quantize_money(P * to_decimal(sb_pct) / to_decimal(100))
    br_amt = quantize_money(P * to_decimal(br_pct) / to_decimal(100))
    ad_amt = quantize_money(P * to_decimal(ad_pct) / to_decimal(100))
    await _unpay(chain["sub_broker"], sb_amt, game_key=game_key, role="SUB_BROKER", related_user_id=user.id)
    await _unpay(chain["broker"], br_amt, game_key=game_key, role="BROKER", related_user_id=user.id)
    await _unpay(chain["admin"], ad_amt, game_key=game_key, role="ADMIN", related_user_id=user.id)


async def distribute_gross_hierarchy(
    user: User, gross_prize, game_key: str, cfg: GameConfig
) -> None:
    """Split gross_prize_*_percent of a winner's gross through the hierarchy
    (Number, Jackpot). Funded from the house; winner keeps the full gross."""
    G = quantize_money(to_decimal(gross_prize))
    if G <= ZERO or getattr(user, "is_demo", False):
        return
    if (cfg.gross_prize_sub_broker_percent + cfg.gross_prize_broker_percent + cfg.gross_prize_admin_percent) <= 0:
        return
    chain = await _resolve_chain(user)
    has_sb, has_br, has_ad = bool(chain["sub_broker"]), bool(chain["broker"]), bool(chain["admin"])
    sb_pct, br_pct, ad_pct = _cascade(
        cfg.gross_prize_sub_broker_percent, cfg.gross_prize_broker_percent, cfg.gross_prize_admin_percent,
        has_sb=has_sb, has_br=has_br, has_ad=has_ad, sub_to_broker=cfg.sub_broker_share_to_broker,
    )
    sb_amt = quantize_money(G * to_decimal(sb_pct) / to_decimal(100))
    br_amt = quantize_money(G * to_decimal(br_pct) / to_decimal(100))
    ad_amt = quantize_money(G * to_decimal(ad_pct) / to_decimal(100))
    await _pay(chain["sub_broker"], sb_amt, game_key=game_key, role="SUB_BROKER", base=G, related_user_id=user.id)
    await _pay(chain["broker"], br_amt, game_key=game_key, role="BROKER", base=G, related_user_id=user.id)
    await _pay(chain["admin"], ad_amt, game_key=game_key, role="ADMIN", base=G, related_user_id=user.id)
    await _bump_earnings(user, sb_amt + br_amt + ad_amt)
