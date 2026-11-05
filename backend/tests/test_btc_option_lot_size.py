"""BTC options are 1 unit per lot. The order panel showed 1 lot = 1 unit while
order placement sized them with the crypto-coin default (100 units / lot), so
an order went in at 100× the premium and margin on screen. Both now ask
`btc_option_lot_size` first; other crypto keeps its own lot."""

from app.services.infoway_lots import btc_option_lot_size, get_infoway_lot_size

SEG = "CRYPTO_OPTION_BUY"


def test_btc_call_and_put_are_one_unit():
    assert btc_option_lot_size("BTC-261106-73000-C", SEG) == 1
    assert btc_option_lot_size("BTC-261127-100000-P", SEG) == 1
    assert btc_option_lot_size("btc-261106-73000-c", SEG) == 1


def test_only_btc_options():
    # Other crypto options and coins are left to the existing rules.
    assert btc_option_lot_size("ETH-261106-3000-C", SEG) is None
    assert btc_option_lot_size("BTCUSD", "CRYPTO") is None
    assert btc_option_lot_size("BTCUSDT", "CRYPTO") is None
    # A non-crypto segment never matches, whatever the symbol looks like.
    assert btc_option_lot_size("BTC-261106-73000-C", "NSE_INDEX_OPTION_BUY") is None
    assert btc_option_lot_size(None, SEG) is None


def test_crypto_coin_lots_unchanged():
    # The coin table / default this change routes around is untouched.
    assert get_infoway_lot_size("ETHUSD", "CRYPTO") == 100
    assert get_infoway_lot_size("BTC-261106-73000-C", SEG) == 100  # why the check runs first
