"""Referral-per-win reward (mirrors D:\\Stockex referralPerWin).

On the referred user's FIRST win in a given game, the referrer earns
`referral_win_percent%` of ONE ticket price, funded from the house and
credited to the referrer's games wallet. Gated once per (user, game) via
`User.game_referral.first_win_by_game`.
"""

from __future__ import annotations

import logging

from app.models.games.settings import GameConfig
from app.models.user import User
from app.services.games import wallet_service
from app.utils.decimal_utils import ZERO, quantize_money, to_decimal

logger = logging.getLogger(__name__)


async def credit_referral_on_win(user: User, win_amount, cfg: GameConfig, *, game_key: str) -> None:
    """4-level %-of-WINNING model (ACTIVE) — referrer leg.

    The CLIENT who referred the player (`player.referred_by`) earns
    `referrer_profit_pct%` of the gross `win_amount` (the FULL winning amount —
    payout/prize, NOT payout − stake), funded from the house → the referrer's
    GAMES wallet.

    ONE-TIME by default: `cfg.referrer_first_win_only=True` (super-admin
    editable per game) pays the referrer only on the referred friend's FIRST
    win in THIS game — gated via `User.game_referral.first_win_by_game[game_key]`
    — so up to once per game per friend. Set it False to pay on EVERY win.
    The HIERARCHY leg (SubBroker/Broker/Admin in `distribute_profit_split`) is
    UNAFFECTED and always pays on every win. Best-effort: wrapped so it can
    never break settlement."""
    try:
        from app.services import referral_service

        referred_by = getattr(user, "referred_by", None)
        if not referred_by:
            return
        pct = float(cfg.referrer_profit_pct or 0)
        if pct <= 0:
            return

        # One-time-per-game gate (default ON). Once the referrer has been paid
        # for this friend's first win in this game, further wins pay only the
        # hierarchy, not the referrer.
        first_win_only = bool(getattr(cfg, "referrer_first_win_only", True))
        stats = getattr(user, "game_referral", None)
        if first_win_only and bool(stats and stats.first_win_by_game.get(game_key)):
            return

        reward = quantize_money(to_decimal(win_amount) * to_decimal(pct) / to_decimal(100))
        if reward <= ZERO:
            return

        # Funded from the house → referrer's games wallet.
        await wallet_service.house_settle(
            -reward, game_key=game_key,
            narration=f"Referral reward (referrer of {user.user_code})",
            user_id=user.id,
        )
        await wallet_service.atomic_games_wallet_credit(
            referred_by, reward, game_key=game_key,
            description=f"Referral reward — {user.user_code}'s {game_key} win",
            meta={"kind": "REFERRAL", "referred_user": str(user.id)},
        )

        # Mark the first-win gate so the referrer isn't paid again for this
        # game (only when first-win-only is on).
        if first_win_only:
            from app.models.user import GameReferralStats

            if stats is None:
                user.game_referral = GameReferralStats(first_win_by_game={game_key: True})
            else:
                stats.first_win_by_game[game_key] = True
                user.game_referral = stats
            await user.save()

        # Rollup on the Referral doc + referrer stats (Refer&Earn page).
        await referral_service.record_referral_earning(
            referred_by, user.id, reward, game=game_key
        )
    except Exception:  # noqa: BLE001 — referral must never break settlement
        logger.exception(
            "games_referral_on_win_failed user=%s game=%s",
            getattr(user, "id", None), game_key,
        )


async def reverse_referral_on_win(user: User, win_amount, cfg: GameConfig, *, game_key: str) -> dict:
    """Reverse ``credit_referral_on_win`` for a mis-declared win.

    Claws the reward back from the referrer's games wallet (best-effort — if the
    referrer already spent it, only reports the shortfall), returns the money to
    the house, and RESETS the ``first_win_by_game`` gate so a corrected
    re-declare can pay the referrer again. Returns a small report dict."""
    report = {"reward": "0", "clawed": True}
    try:
        referred_by = getattr(user, "referred_by", None)
        if not referred_by:
            return report
        pct = float(cfg.referrer_profit_pct or 0)
        if pct <= 0:
            return report
        reward = quantize_money(to_decimal(win_amount) * to_decimal(pct) / to_decimal(100))

        # Reset the first-win gate so a corrected re-declare pays again.
        stats = getattr(user, "game_referral", None)
        if stats is not None and stats.first_win_by_game.get(game_key):
            stats.first_win_by_game[game_key] = False
            user.game_referral = stats
            await user.save()

        if reward <= ZERO:
            return report
        report["reward"] = str(reward)

        # Claw back from the referrer's games wallet (best-effort).
        try:
            await wallet_service.atomic_games_wallet_debit(
                referred_by, reward, game_key=game_key,
                description=f"Reverse referral reward — {user.user_code}'s {game_key} win",
                meta={"kind": "REFERRAL_REVERSE", "referred_user": str(user.id)},
            )
            await wallet_service.house_settle(
                reward, game_key=game_key,
                narration=f"Reverse referral reward (referrer of {user.user_code})",
                user_id=user.id,
            )
        except Exception:
            report["clawed"] = False  # referrer already spent it — reported

        # Best-effort undo the rollup (stats only).
        try:
            from app.services import referral_service

            await referral_service.record_referral_earning(
                referred_by, user.id, -reward, game=game_key
            )
        except Exception:
            pass
        return report
    except Exception:  # noqa: BLE001
        logger.exception(
            "games_referral_reverse_failed user=%s game=%s",
            getattr(user, "id", None), game_key,
        )
        return report


async def credit_referral_on_first_win(
    user: User, game_key: str, cfg: GameConfig, *, is_top_rank: bool = True,
    referral_base: float | int | str | None = None,
) -> None:
    """Credit the referrer once for `user`'s first win in `game_key`.

    `referral_base` (the % base) differs per game (refles.md B.2):
      • Up/Down, Number → one ticket price (default when base not passed)
      • Jackpot         → the pool/bank (caller passes it)
      • Bracket         → the user's session stake (caller passes it)
    """
    try:
        from app.services import referral_service

        win_pct = float(cfg.referral_win_percent or 0)
        if win_pct <= 0:
            return
        referred_by = getattr(user, "referred_by", None)
        if not referred_by:
            return
        # Jackpot games may gate the reward to top ranks only.
        if cfg.referral_top_ranks_only and not is_top_rank:
            return

        # First-win-per-game gate.
        stats = getattr(user, "game_referral", None)
        if bool(stats and stats.first_win_by_game.get(game_key)):
            return

        base = to_decimal(referral_base) if referral_base is not None else to_decimal(cfg.ticket_price)
        reward = quantize_money(base * to_decimal(win_pct) / to_decimal(100))
        if reward <= ZERO:
            return

        # Shared eligibility gate (segment enabled + 1-month window + house
        # earnings threshold). Held → skip WITHOUT consuming the first-win gate
        # so it can pay on a later eligible win.
        if not await referral_service.process_conditional_referral_payout(user, reward, "games"):
            return

        # Funded from the house → referrer's games wallet.
        await wallet_service.house_settle(
            -reward, game_key=game_key, narration=f"Referral reward (referrer of {user.user_code})",
            user_id=user.id,
        )
        await wallet_service.atomic_games_wallet_credit(
            referred_by, reward, game_key=game_key,
            description=f"Referral reward — {user.user_code}'s first {game_key} win",
            meta={"kind": "REFERRAL", "referred_user": str(user.id)},
        )

        # Mark the first-win gate (at most once per game per referred user).
        from app.models.user import GameReferralStats

        if stats is None:
            user.game_referral = GameReferralStats(first_win_by_game={game_key: True})
        else:
            stats.first_win_by_game[game_key] = True
            user.game_referral = stats
        await user.save()

        # Rollup on the Referral doc + referrer stats.
        await referral_service.record_referral_earning(
            referred_by, user.id, reward, game=game_key
        )
    except Exception:  # noqa: BLE001 — referral must never break settlement
        logger.exception("games_referral_failed user=%s game=%s", getattr(user, "id", None), game_key)
