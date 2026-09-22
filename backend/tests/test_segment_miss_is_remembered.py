"""A token we have no instrument for is remembered too.

The quote overlay asks for a token's segment on every token on every tick,
and the session-freeze check asks again. The answer was cached — unless it
was "we don't have that instrument", which was thrown away every time on the
reasoning that the row might appear on the next call.

That reasoning held while the collection carried every instrument and a miss
was rare. It stopped holding when the feed streamed more tokens than the
collection knew: every overlay then paid a Redis round-trip plus a Mongo
query to be told "no" again. One worker sat at 92% CPU, the box at load 4.7
on two cores, and every page in both apps felt slow.
"""

from __future__ import annotations

import inspect

from app.services import market_data_service as md


def test_a_miss_is_written_to_the_memo():
    s = inspect.getsource(md._segment_for_token)
    assert "_seg_memo[token] = (_t.time(), None)" in s
    # And it is written BEFORE returning, or nothing is remembered.
    assert s.index("_seg_memo[token] = (_t.time(), None)") < s.index(
        "        return None"
    ) + len(s)


def test_a_miss_expires_sooner_than_a_hit():
    """A miss is the answer most likely to change — instrument rows are
    mirrored in lazily on first use."""
    assert md._SEGMENT_MISS_TTL < md._SEGMENT_FOR_TOKEN_TTL
    assert 0 < md._SEGMENT_MISS_TTL <= 60


def test_the_two_lifetimes_are_told_apart_on_read():
    s = inspect.getsource(md._segment_for_token)
    assert "ttl = _SEGMENT_FOR_TOKEN_TTL if memo[1] is not None else _SEGMENT_MISS_TTL" in s


def test_the_memo_can_hold_a_miss():
    ann = inspect.getsource(md).split("_seg_memo: ")[1].split("\n")[0]
    assert "None" in ann, "the memo's type must admit a miss"


def test_a_remembered_miss_short_circuits_before_redis():
    """The whole point: no round-trip at all on the second ask."""
    s = inspect.getsource(md._segment_for_token)
    assert s.index("memo = _seg_memo.get(token)") < s.index("cache_get")
    assert s.index("return memo[1]") < s.index("cache_get")


def test_the_session_check_goes_through_the_same_memo():
    s = inspect.getsource(md._session_over)
    assert "await _segment_for_token(token)" in s
