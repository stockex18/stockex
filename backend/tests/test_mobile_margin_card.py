"""The mobile trade card shows BOTH sides' margin, not just the one you are on.

Operator: "isme card me intraday me / karke sell ka bhi margin likh, yaha pe
buy ka bas dikh raha hai - red color me sell ka, green color me buy ka, and
carry me bhi same".

It matters most where the two are not alike. On a future they differ only by
the spread:

    CRUDEOIL 21SEP  lot 100  BUY 8900  SELL 8898   intraday 100x  carry 50x
        intraday   S 8,898    B 8,900
        carry      S 17,796   B 17,800

but on an option they are different KINDS of number - a writer posts against
the STRIKE (strike x qty x rate) and a buyer only the premium. Showing one and
letting the trader assume it applies to the other button is how somebody gets a
surprise on the fill.

Checked from the backend suite because there is no frontend runner here; these
read the source.
"""

from __future__ import annotations

import io
import re

SHEET = r"D:\stockex_new\frontend-user\components\trading\TradeDetailSheet.tsx"


def src() -> str:
    return io.open(SHEET, encoding="utf-8", errors="ignore").read()


# ── both sides are resolved, and both are shown ───────────────────────
def test_the_other_sides_settings_are_fetched_too():
    """BUY and SELL resolve to DIFFERENT settings - that is the whole reason
    the two margins differ - so one query cannot answer for both."""
    s = src()
    assert 'const oppSide: "BUY" | "SELL" = side === "BUY" ? "SELL" : "BUY";' in s
    assert "SegmentSettingsAPI.effective(token!, oppSide, productType)" in s


def test_flipping_side_costs_no_network():
    """Same query-key shape as the current side, so the toggle just swaps which
    cached row is 'current'."""
    s = src()
    assert s.count('queryKey: ["segment-settings", token, side, productType]') == 1
    assert s.count('queryKey: ["segment-settings", token, oppSide, productType]') == 1


def test_both_margin_tiles_show_a_pair():
    s = src()
    for a, b in (
        ("sell: formatINRCompact(sellMargins.intraday)", "buy: formatINRCompact(buyMargins.intraday)"),
        ("sellMargins.intraday : sellMargins.carry", "buyMargins.intraday : buyMargins.carry"),
    ):
        assert a in s, a
        assert b in s, b


def test_sell_is_red_and_buy_is_green():
    """The platform's own theme tokens, the same ones the BUY/SELL buttons and
    the price header use - not new colours."""
    s = src()
    i = s.index('["S", pair.sell, "text-sell"]')
    assert '["B", pair.buy, "text-buy"]' in s[i : i + 200]


def test_each_number_is_labelled():
    """Two bare figures in a column would not say which is which."""
    s = src()
    assert '["S", pair.sell' in s and '["B", pair.buy' in s


# ── one formula, used for both sides ──────────────────────────────────
def test_there_is_a_single_shared_per_side_helper():
    """This formula already exists in the backend validator, the carry planner
    and the desktop panel, and every time it has been copied one copy has gone
    stale. The card computes both sides through ONE function."""
    s = src()
    assert "function marginsForSide(" in s
    assert s.count("marginsForSide(") == 3  # the definition plus two call sites


def test_the_old_duplicated_blocks_are_gone():
    s = src()
    assert "const marginPerLot = useMemo" not in s
    assert "const overnightMarginPerLot = useMemo" not in s


def test_option_writing_still_sits_on_the_strike_and_only_on_sell():
    s = src()
    assert 'if (mode === "strike_pct" && r > 0 && sideArg === "SELL" && strike > 0)' in s
    assert "return strike * lotSize * r;" in s


def test_fixed_per_lot_still_wins_where_it_is_set():
    s = src()
    i = s.index('if (mode === "fixed" && f > 0) return f;')
    j = s.index('if (mode === "strike_pct" && r > 0 && sideArg === "SELL"')
    assert j < i, "strike_pct must be tested before the generic paths"


def test_the_segment_default_percentage_survived_the_refactor():
    """Until the settings land there is no `margin_percentage`. Falling back to
    100% instead of the segment shape would flash a margin several times the
    real one on first paint."""
    s = src()
    assert "const defaultMarginPct = isFno ? 0.13 : isCrypto ? 0.2 : isForex ? 0.05 : 1.0;" in s
    assert "? Number(s.margin_percentage) / 100 : defaultPct;" in s


# ── the side being ordered still drives the funds check ───────────────
def test_the_current_side_is_what_the_funds_check_and_the_order_use():
    """The tiles are informational; `intradayMargin` is what blocks an order
    and what is sent with it. It must stay the side actually being traded."""
    s = src()
    assert 'const _sideMargins = side === "BUY" ? buyMargins : sellMargins;' in s
    assert "const intradayMargin = _sideMargins.intraday;" in s
    assert "const carryforwardMargin = _sideMargins.carry;" in s
    assert "if (intradayMargin > 0 && availableMargin < intradayMargin) {" in s


def test_a_typed_limit_still_prices_the_side_being_ordered():
    """`refPrice` honours a typed LIMIT. The other side has no order on it, so
    it is priced at its own quote."""
    s = src()
    assert 'const _buyPx = (side === "BUY" ? refPrice : buyPrice) || ltp || 0;' in s
    assert 'const _sellPx = (side === "SELL" ? refPrice : sellPrice) || ltp || 0;' in s


def test_the_pair_is_stacked_rather_than_slashed_on_one_line():
    """NFO and MCX margins run to six and seven figures (1,60,574 / 2,98,637)
    and a third of a phone width cannot hold that pair without truncating. A
    half-shown margin is worse than none."""
    s = src()
    i = s.index("pair?: { sell: string; buy: string };")
    assert "truncating" in s[i - 400 : i]


def test_crypto_and_forex_still_show_the_same_number_twice():
    """Infoway segments have no separate carry tier - the posted margin is held
    for as long as the position is - so carry equals intraday there."""
    s = src()
    assert "isInfowaySeg ? sellMargins.intraday : sellMargins.carry" in s
    assert "isInfowaySeg ? buyMargins.intraday : buyMargins.carry" in s


def test_the_tooltip_spells_both_out_in_full():
    """The tile is compact by necessity; the long-press / hover value should
    not be."""
    s = src()
    assert re.search(r"Intraday margin · SELL \$\{formatINR\(sellMargins\.intraday\)\}", s)
    assert "· BUY ${formatINR(buyMargins.intraday)}" in s
