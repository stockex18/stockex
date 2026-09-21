"""The coin trial balance has to square, and has to square for the right reason.

Every coin that exists is sitting in exactly one wallet, so the two sides are
the same quantity counted twice — once as "what was issued", once as "where it
is now". That is why this squares to the paisa where a voucher-built trial
balance does not always.

Which makes the totals matching worthless as evidence on its own: it is an
identity, it cannot fail. So what is worth pinning is that nothing is LEFT OUT
of the count — a wallet field the sum forgets is a coin the report cannot see,
and the total would still match itself while being wrong.
"""

from __future__ import annotations

import inspect

from app.services import coin_trial_balance as ctb


SRC = inspect.getsource(ctb)


# ── nothing that holds a coin may be left out ─────────────────────────
def test_every_balance_field_on_the_wallet_is_counted():
    """`available_balance` alone would miss margin locked in a position and
    commission held back — both hold real money today."""
    for field in (
        "available_balance",
        "used_margin",
        "temporary_balance",
        "settlement_outstanding",
    ):
        assert field in SRC, field


def test_the_kuber_pool_is_outside_the_totals_but_not_hidden():
    """It is a separate house pool with its own funding route. Carrying 98
    crore of it through a sheet that follows the MAIN wallet's issuance would
    swamp every other line — but a pool that size going unmentioned would be
    the more misleading choice, so it is a memo."""
    src = inspect.getsource(ctb.build)
    assert '"kuber_pool"' in src
    # never a row, on either side
    assert '"account": "Kuber Pool"' not in src


def test_the_capital_line_names_the_main_wallet_as_the_source():
    src = inspect.getsource(ctb.build)
    assert "Main Wallet - total coins issued" in src


def test_segment_wallets_are_counted():
    """Most of the user money on this platform sits in segment wallets, not
    the main one. Counting only `wallets` would miss it."""
    assert "segment_wallets" in SRC
    src = inspect.getsource(ctb.build)
    i = src.index("segment_wallets")
    assert "available_balance" in src[i : i + 300]
    assert "used_margin" in src[i : i + 300]


def test_security_money_is_counted():
    assert "admin_securities" in SRC


def test_the_security_and_payable_accounts_are_always_listed():
    """A trial balance lists the ACCOUNT. One that disappears when it happens
    to be empty cannot be checked — "is security money in this sheet at all?"
    has to be answerable by looking."""
    src = inspect.getsource(ctb.build)
    i = src.index("credit_rows: list")
    block = src[i : i + 500]
    assert "Security Money held" in block
    assert "Payable to Admins" in block
    assert "if security:" not in src
    assert "if payable:" not in src


# ── the sides are the right way round ─────────────────────────────────
def test_security_money_sits_on_the_credit_side():
    """Collateral an admin lodged is money the platform HOLDS but does not
    own. Putting it on the asset side would double-count it."""
    src = inspect.getsource(ctb.build)
    i = src.index("Security Money held")
    assert '"credit": security' in src[i - 200 : i + 200]


def test_settlement_outstanding_reduces_the_asset_side():
    """It is not a coin anyone holds — it is a coin paid out and never
    covered. Adding it would invent money that does not exist."""
    src = inspect.getsource(ctb.build)
    i = src.index("Settlement Outstanding")
    assert '"debit": -outstanding' in src[i - 200 : i + 200]


def test_the_capital_account_is_what_makes_it_square():
    src = inspect.getsource(ctb.build)
    assert "circulation = total_debit - liabilities" in src
    assert "total_credit = liabilities + circulation" in src


def test_each_admin_gets_its_own_line():
    """The operator asked for exactly this — what went to which admin, one row
    each, not a single lumped figure. Keyed by id, because two admins can
    share a name and their coins must not merge into one row."""
    src = inspect.getsource(ctb.build)
    assert "per_admin" in src
    assert 'per_admin[u["_id"]]' in src
    assert "for name, amt in sorted(per_admin.values()" in src


# ── the classification of movements ───────────────────────────────────
def test_only_issue_and_withdraw_change_the_total():
    """Trading, brokerage, P&L, patti, wallet transfers — every one of those
    moves a coin between two wallets, so it cancels across the sheet. If any
    of them were treated as minting, the reconciliation would drift by the
    whole volume of trading."""
    for t in ("TRADE", "PNL", "BROKERAGE", "WALLET_TRANSFER", "ADMIN_TRANSFER"):
        assert t not in ctb.MINT_TYPES, t
        assert t not in ctb.BURN_TYPES, t
    assert "KUBER_TOPUP" in ctb.MINT_TYPES
    assert "DEPOSIT" in ctb.MINT_TYPES
    assert "WITHDRAWAL" in ctb.BURN_TYPES


# ── the honest part ───────────────────────────────────────────────────
def test_the_log_is_reconciled_against_but_not_used_as_the_credit_side():
    """`wallet_transactions` records 200 crore of KUBER_TOPUP against a pool
    holding 98 crore — seeded balances were never journalled. Building the
    credit side from it would show a hundred-crore hole that is an artefact of
    seeding, not a missing coin."""
    src = inspect.getsource(ctb.build)
    assert '"unreconciled"' in src
    # the capital figure comes from the balances, never from the log
    assert "circulation = total_debit" in src
    assert "circulation = minted" not in src


def test_a_broken_reconciliation_does_not_take_the_sheet_down():
    """The note is a nicety. The sheet is the report."""
    src = inspect.getsource(ctb.build)
    i = src.index("coin_trial_balance_recon_failed")
    assert "except Exception" in src[i - 200 : i]


def test_the_difference_is_reported_even_though_it_should_be_zero():
    """If it is ever non-zero the arithmetic changed and the page is lying."""
    assert '"difference"' in inspect.getsource(ctb.build)


# ── it is a report, not a mutation ────────────────────────────────────
def test_it_never_writes():
    """Naming the DB methods, not the word "insert" — `credit_rows.insert(0,…)`
    is a list operation and would trip a looser check."""
    for word in (
        "insert_one", "insert_many", "update_one", "update_many",
        "delete_one", "delete_many", ".save()", "$set", "replace_one",
    ):
        assert word not in SRC, word


def test_a_junk_amount_cannot_break_the_sum():
    """One Decimal128 the driver hands back oddly must not take out the whole
    report."""
    assert ctb._dec(None) == 0
    assert ctb._dec("not a number") == 0
    assert ctb._dec("12.50") == 12.5


# ── wiring ────────────────────────────────────────────────────────────
def test_the_endpoints_exist_and_are_separate_from_the_cash_one():
    from app.api.v1.admin.ledger_books import router

    paths = {r.path for r in router.routes}
    assert "/ledger-books/coin-trial-balance" in paths
    assert "/ledger-books/coin-trial-balance/pdf" in paths
    assert "/ledger-books/trial-balance" in paths, "the cash-book report must survive"


def test_the_pdf_builder_takes_this_shape():
    from app.services import ledger_pdf_service as pdf

    src = inspect.getsource(pdf.build_coin_trial_balance_pdf)
    assert "debit_rows" in src and "credit_rows" in src
    assert "reconciliation" in src


def test_the_pdf_columns_fit_the_page():
    """Same 186 mm printable width the other reports in that file assert to."""
    from app.services import ledger_pdf_service as pdf

    assert "assert sum(widths) == 186 * mm" in inspect.getsource(
        pdf.build_coin_trial_balance_pdf
    )


# ── the per-admin drill-down ──────────────────────────────────────────
def test_the_breakdown_finds_ledger_lines_by_the_admins_code():
    """The cash books are shared payment modes (Cash, HDFC, UPI, Cheque), not
    per-party accounts — every `party_user_id` on them is null. The admin is
    named on the LINE, in `particulars`, so that is the only thing that can
    link an entry to them."""
    src = inspect.getsource(ctb.admin_breakdown)
    assert '{"particulars": user_code}' in src
    assert "party_user_id" not in src


def test_it_reads_all_three_sources():
    """Money reaches an admin by three different routes; no one of them
    answers "how did it get here"."""
    src = inspect.getsource(ctb.admin_breakdown)
    for coll in ("ledger_book_entries", "wallet_transactions", "admin_securities"):
        assert coll in src, coll


def test_coin_movements_are_grouped_but_keep_their_count():
    """A hundred brokerage lines should read as one figure — with the hundred
    still visible, or the row looks like a single large transfer."""
    src = inspect.getsource(ctb.admin_breakdown)
    assert '"$group"' in src
    assert '"count": r["n"]' in src


def test_a_missing_admin_is_an_answer_not_a_crash():
    src = inspect.getsource(ctb.admin_breakdown)
    assert 'return {"error": "not found"' in src


def test_the_breakdown_never_writes():
    src = inspect.getsource(ctb.admin_breakdown)
    for word in ("insert_one", "update_one", "delete_one", ".save()", "$set"):
        assert word not in src, word


def test_the_endpoint_is_registered():
    from app.api.v1.admin.ledger_books import router

    assert "/ledger-books/coin-trial-balance/admin/{user_code}" in {
        r.path for r in router.routes
    }
