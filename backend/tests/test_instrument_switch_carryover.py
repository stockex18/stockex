"""Switching instrument must not carry the last one's price with it.

Reported, exactly: "TCS pe tha, SBI pe gaya, SBI me TCS ka price dikha — aur
order us par lag gaya."

The trade sheet renders its whole body from an inner component that was not
keyed on the token:

    if (!props.open || !props.token) return null;
    return <TradeDetailSheetInner {...props} />;      // no key

Its lazy-mount tears state down when the sheet CLOSES — but swapping
instrument never closes it. `onSwap` and a second tap on the list both change
`token` in place, so React keeps the same instance and every useState and
useRef inside survives: the sticky price cells, the seeded quote, and the typed
limit / stop / target. The previous instrument's numbers stay on screen until
the new one's quote lands, and an order placed in that window is priced off
them.

The desktop order panel had the same shape, holding the typed limit price,
stop, target and lot count.

Checked from the backend suite because there is no frontend runner here; these
read the source, which is enough to stop the key being dropped again.
"""

from __future__ import annotations

import io

SHEET = r"D:\stockex_new\frontend-user\components\trading\TradeDetailSheet.tsx"
TERMINAL = r"D:\stockex_new\frontend-user\app\(terminal)\terminal\page.tsx"
LAYOUT = r"D:\stockex_new\frontend-user\app\(terminal)\layout.tsx"


def src(p: str) -> str:
    return io.open(p, encoding="utf-8", errors="ignore").read()


def test_the_trade_sheet_is_keyed_on_its_token():
    assert "<TradeDetailSheetInner key={props.token}" in src(SHEET)


def test_the_order_panel_is_keyed_on_its_instrument():
    s = src(TERMINAL)
    i = s.index("<OrderPanel")
    assert "key={instrument?.token" in s[i : i + 500]


def test_the_reason_is_recorded_where_the_key_lives():
    """A `key` looks removable to anyone who does not know what it is holding
    back. Both carry the report that produced them."""
    assert "TCS" in src(SHEET) and "SBI" in src(SHEET)
    s = src(TERMINAL)
    i = s.index("<OrderPanel")
    assert "TCS" in s[i : i + 500]


def test_swapping_still_does_not_close_the_sheet():
    """The key is what makes an in-place swap safe. If swapping ever starts
    closing the sheet instead, this test should be revisited — but until then
    the key is the only thing resetting that state."""
    assert "onSwap={(tok) => setSheetToken(tok)}" in src(LAYOUT)


def test_the_sheet_still_renders_nothing_when_closed():
    """The lazy-mount is a separate concern and still wanted: a permanently
    mounted sheet ran a websocket for an instrument nobody was looking at."""
    assert "if (!props.open || !props.token) return null;" in src(SHEET)


def test_the_panel_state_the_key_protects_is_still_there():
    """If these ever move out to the parent the key stops mattering — and this
    test starts pointing at the wrong thing."""
    s = src(r"D:\stockex_new\frontend-user\components\trading\OrderPanel.tsx")
    for name in ("[price, setPrice]", "[stopLoss, setStopLoss]", "[target, setTarget]"):
        assert name in s, name
