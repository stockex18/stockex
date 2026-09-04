"""Margin on the positions screen is priced at the market, not at the entry.

Three things the operator reported, all traced to one place:

    Futures CF        correct       times mode on entry notional
    Buy call/put      wrong         "calculating on entry price, then 2X for cf"
    Sell call/put     wrong         "qty multiply by entry price"

The sell case was the worst. The admin had Strike % configured — verified live,
the resolver returns `strike_pct 0.04 / 0.08` — but the display had no branch
for that mode, so it fell through to the generic path where the resolver's
100% / 1x for strike_pct reduce to `qty x price`: the PREMIUM, which is what a
buyer pays, not what a writer posts.

    COPPER26SEP1390PE   qty 1080  strike 1390
      showed   1080 x 28.83          =   31,136.40
      correct  1080 x 1390 x 0.08    = 1,20,096.00
"""

from __future__ import annotations

import inspect
import re

from app.api.v1.user import positions as api

SRC = inspect.getsource(api.list_active_trades)


def _blocks() -> list[str]:
    """The two margin computations in this endpoint — one per tab. They must
    agree, or the same position reads differently depending on which tab you
    are looking at."""
    return [m for m in re.findall(r"mode = s\.get\(.margin_calc_mode.\).*?used_margin_inr = round\(used_native, 2\)",
                                  SRC, re.S)]


def test_there_are_two_of_them_and_both_were_changed():
    assert len(_blocks()) == 2, "one tab was left on the old formula"


# ── priced at the market ──────────────────────────────────────────────
def test_both_price_the_requirement_at_the_current_market():
    """Entry price is a fact about the past. What this column answers — what
    it costs to hold this leg — is a question about now."""
    for b in _blocks():
        assert "mark = ltp if ltp > 0 else price" in b or "qty * mark" in b


def test_the_entry_price_survives_only_as_a_fallback():
    """Better a stale number than a blank one when the feed is down."""
    assert SRC.count("mark = ltp if ltp > 0 else price") == 2


# ── option writing sits on the strike ─────────────────────────────────
def test_both_have_a_strike_pct_branch():
    """Without it a strike_pct row falls through to the generic path, where
    the resolver's 100% / 1x reduce it to the premium."""
    for b in _blocks():
        assert 'mode == "strike_pct"' in b


def test_the_strike_branch_uses_strike_notional_not_premium():
    for b in _blocks():
        assert "qty * _strike * _strike_rate" in b   # carry-forward
        assert "qty * _strike * intra_rate" in b     # intraday


def test_it_refuses_to_guess_when_the_strike_is_unknown():
    """A strike of 0 would compute a margin of 0 and let a writer sell for
    nothing. Falling through to the generic path is wrong too, but it is at
    least a positive number — and the lookup failure is logged."""
    for b in _blocks():
        assert "_strike > 0" in b
        assert "_strike_rate > 0" in b or "intra_rate > 0" in b


def test_the_strike_is_looked_up_once_for_the_whole_response():
    """`InstrumentRef` carries no strike, so it has to be fetched — but per
    row on a page of positions would be a query each."""
    assert '{"token": {"$in": _opt_tokens}}' in SRC
    assert "strike_by_token" in SRC


def test_a_failed_strike_lookup_is_logged_not_swallowed():
    """Silently falling back to premium margin on every option is exactly the
    bug being fixed; it must not come back invisibly."""
    i = SRC.index("holding_margin_strike_lookup_failed")
    assert "warning" in SRC[i - 120 : i + 40]


# ── the modes that already worked keep working ────────────────────────
def test_fixed_per_lot_still_wins_where_it_is_set():
    for b in _blocks():
        assert 'mode == "fixed"' in b
        assert b.index('mode == "fixed"') < b.index('mode == "strike_pct"')


def test_times_mode_is_still_the_fallthrough():
    """Futures were correct and must stay correct — the operator confirmed
    that half."""
    for b in _blocks():
        assert "ovn_pct / ovn_lev" in b or "pct / lev" in b


def test_usd_conversion_still_skips_fixed_per_lot():
    """A rupee-per-lot figure the admin typed is already in rupees."""
    assert SRC.count('if is_usd and not (mode == "fixed" and ovn_fixed > 0)') == 2
    assert SRC.count('if is_usd and not (mode == "fixed" and intra_fixed > 0)') == 2


# ── the wallet is not touched ─────────────────────────────────────────
def test_this_only_changes_what_is_displayed():
    """The wallet still holds what was locked at entry. Re-marking the real
    lock is a separate decision with real consequences — it can push a live
    position into shortfall as the price moves."""
    for word in ("block_margin", "release_margin", "wallet.used_margin ="):
        assert word not in SRC, word


def test_used_follows_the_positions_own_product_type():
    """An NRML leg is HELD overnight, so the overnight numbers ARE its margin.
    Reading the intraday pair for it showed half the real figure on every
    carry-forward position — LEAD26SEPFUT read 53,053.34 against a wallet
    holding 1,06,106.69."""
    for b in _blocks():
        assert '_carry = str(p.product_type.value).upper() != "MIS"' in b
        assert "overnight_leverage" in b and "overnight_strike_margin_rate" in b


def test_a_MIS_leg_still_reads_the_intraday_pair():
    for b in _blocks():
        assert "else s.get(\"strike_margin_rate\")" in b
        assert "else s.get(\"leverage\")" in b


def test_the_locked_figure_remains_the_fallback():
    """A leg whose settings will not resolve still shows a real number rather
    than zero."""
    assert "used_margin_inr = round(pos_margin * trade_share, 2)" in SRC
    assert "holding_margin_inr = used_margin_inr" in SRC
