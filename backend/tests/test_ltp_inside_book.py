"""A last-traded price is never published outside the book.

The overlays hold the previous `ltp` when a packet carries none, so the
screen never blanks to 0. The hold has no time limit, so a run of such
packets leaves the price frozen while the depth in the same packets moves on.

OFSS26SEPFUT, 28 Sept: ltp stuck at 10,915 for two minutes while the book
fell to 10,870 / 10,883 and volume climbed the whole way. The positions table
read the held price, the trade panel read the fresh depth, and the same
instrument showed thirty points apart -- both drawing the same impossible
quote correctly.

These are the real numbers from that window.
"""

from app.services.market_data_service import _reconcile_ltp_to_book


def test_a_frozen_ltp_above_the_offer_is_pulled_to_it():
    q = _reconcile_ltp_to_book({"ltp": 10915.0, "bid": 10870.0, "ask": 10883.0})
    assert q["ltp"] == 10883.0
    # The book itself is untouched -- only the stale side moves.
    assert q["bid"] == 10870.0 and q["ask"] == 10883.0


def test_a_frozen_ltp_below_the_bid_is_pulled_to_it():
    q = _reconcile_ltp_to_book({"ltp": 10800.0, "bid": 10870.0, "ask": 10883.0})
    assert q["ltp"] == 10870.0


def test_a_price_inside_the_book_is_left_exactly_alone():
    src = {"ltp": 10875.0, "bid": 10870.0, "ask": 10883.0}
    assert _reconcile_ltp_to_book(src) is src


def test_on_the_touch_counts_as_inside():
    for ltp in (10870.0, 10883.0):
        src = {"ltp": ltp, "bid": 10870.0, "ask": 10883.0}
        assert _reconcile_ltp_to_book(src) is src


def test_no_depth_means_no_opinion():
    # A 0 side is "no real depth". Synthesising against it is exactly what
    # the bid/ask resolution refuses to do, so this must not either.
    for q in (
        {"ltp": 10915.0, "bid": 0.0, "ask": 10883.0},
        {"ltp": 10915.0, "bid": 10870.0, "ask": 0.0},
        {"ltp": 10915.0, "bid": 0.0, "ask": 0.0},
    ):
        assert _reconcile_ltp_to_book(q) is q


def test_a_crossed_book_is_not_trusted_to_correct_anything():
    # bid above ask is a broken quote in its own right; clamping to it would
    # move the price on the strength of data we already know is wrong.
    q = {"ltp": 10915.0, "bid": 10890.0, "ask": 10880.0}
    assert _reconcile_ltp_to_book(q) is q


def test_a_missing_or_junk_price_is_left_for_the_holders_to_handle():
    for q in ({"bid": 10870.0, "ask": 10883.0}, {"ltp": 0.0, "bid": 1.0, "ask": 2.0}):
        assert _reconcile_ltp_to_book(q) is q
