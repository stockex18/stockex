"""The broker demo is a screen of its own, not a form at the foot of sign-in.

Two screenshots from the operator: tap "Try a Broker Demo" and the form opened
at the BOTTOM of the broker login page — under the sign-in form, the "Install
web app" card and the "Register as a broker" card — with the browser scrolled
down to it, and "Not a broker? Admin login" underneath. Everything on the page
was still there and none of it was about the demo.

Also visible in those shots: the Email field already reading admin@stockex.in
and the password filled in. That was the browser autofilling its saved ADMIN
login into a signup form — a demo for a stranger, pre-loaded with credentials
that open the real panel. It is switched off here, not worked around.

This is layout, so the checks are on the source: the project has no browser
test harness, and what matters is which view owns which block.
"""

from __future__ import annotations

import pathlib

_PAGE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend-admin" / "app" / "broker" / "login" / "page.tsx"
)


def _s() -> str:
    return _PAGE.read_text(encoding="utf-8", errors="ignore")


def _panel() -> str:
    s = _s()
    return s[s.index("function DemoPanel(") :]


def _signin_view() -> str:
    """Everything that renders when the demo is NOT open."""
    s = _s()
    start = s.index("{demoOpen ? (")
    return s[start : s.index("function DemoPanel(")]


# ── the demo replaces the sign-in view ───────────────────────────────
def test_opening_the_demo_swaps_the_whole_card_for_its_own_screen():
    s = _s()
    assert "{demoOpen ? (" in s
    assert "<DemoPanel" in s
    assert s.index("<DemoPanel") < s.index("{/* Card */}")


def test_the_signin_form_the_install_card_and_register_are_all_in_the_other_branch():
    """Everything the operator saw sitting around the demo form."""
    after_panel = _signin_view().split("<DemoPanel", 1)[1]
    for marker in ('id="broker-app"', "Register as a broker", "Sign in", "Broker access only"):
        assert marker in after_panel, marker


def test_the_footer_goes_with_the_signin_view():
    s = _s()
    i = s.index("Not a broker?")
    assert "{!demoOpen && (" in s[i - 400 : i]


def test_the_tagline_goes_too_so_only_the_logo_remains():
    s = _s()
    i = s.index("Manage your clients, positions and payments.")
    assert "{!demoOpen && (" in s[i - 200 : i]


def test_the_inline_form_at_the_foot_of_the_page_is_gone():
    s = _s()
    assert "Create broker demo" not in s
    # The demo's fields are registered by DemoPanel, through its `form` prop.
    # A `demoForm.register` or `demoForm.handleSubmit` in the page body would
    # mean a second, inline copy of the form had crept back.
    assert "demoForm.register" not in s
    assert "demoForm.handleSubmit" not in s
    assert "form={demoForm}" in s


def test_the_way_in_is_still_a_button_on_the_signin_page():
    s = _s()
    assert "Try a Broker Demo" in s
    assert "onClick={() => setDemoOpen(true)}" in s


# ── getting in and out cleanly ───────────────────────────────────────
def test_opening_it_scrolls_to_the_top():
    """The page used to land the browser at the foot of a long scroll."""
    s = _s()
    assert "if (demoOpen) window.scrollTo({ top: 0 });" in s


def test_going_back_clears_what_was_typed():
    s = _s()
    i = s.index("onBack={() => {")
    block = s[i : i + 400]
    assert block.index("demoForm.reset()") < block.index("setDemoOpen(false)")


def test_there_is_a_way_back_on_the_screen():
    assert "Back to sign in" in _panel()


# ── the autofill problem ─────────────────────────────────────────────
def test_the_browser_is_told_this_is_a_signup_not_a_login():
    p = _panel()
    assert 'autoComplete="new-password"' in p
    assert 'autoComplete="off"' in p
    assert "current-password" not in p


def test_the_email_field_does_not_take_a_saved_login():
    assert 'auto: "off"' in _panel()


# ── what the screen says ─────────────────────────────────────────────
def test_it_says_what_you_get_and_what_the_demo_costs():
    p = _panel()
    assert "50,00,000 virtual float" in p
    assert "3 demo clients" in p
    assert "nothing here touches real funds" in p
    assert "Free, and no approval needed" in p


def test_it_is_upfront_that_demos_expire():
    """True today — the hourly cleanup removes any demo account older than
    seven days, brokers included. If that changes, this line has to as well."""
    assert "cleared after 7 days" in _panel()


def test_the_password_rules_are_stated_before_the_user_trips_over_them():
    """The schema wants upper, lower, a digit and a symbol; finding that out
    from a red error after submitting is a poor first minute."""
    assert "upper and lower case, a number and a symbol" in _panel()


def test_the_password_can_be_shown():
    p = _panel()
    assert "setShowPw" in p and "Show password" in p


def test_the_submit_button_says_what_is_happening():
    p = _panel()
    assert "Start broker demo" in p
    assert "Setting up your demo" in p
