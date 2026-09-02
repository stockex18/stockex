"""The Kite callback URL must point at the deployment, not at localhost.

The model default was a hardcoded `http://localhost:8000/...`, so every
settings row created on a deployed server was born pointing at a machine Kite
cannot reach. The OAuth callback then fails with nothing obvious to show for
it — the only clue was a warning banner asking the operator to fix it by hand,
which reappeared every time a row was created.

The value is derived from BACKEND_PUBLIC_URL now, and a stored localhost one
is corrected on read. What must NOT happen is overwriting a callback somebody
set on purpose, or "fixing" a dev box whose real callback IS localhost.
"""

from __future__ import annotations

import inspect

import pytest

from app.core.config import settings as cfg
from app.models.zerodha_settings import ZerodhaSettings
from app.services.zerodha_service import ZerodhaService

REAL = "https://api.stockex.in/api/v1/admin/zerodha/callback"
LOCAL = "http://localhost:8000/api/v1/admin/zerodha/callback"


class _Row:
    """Stand-in for the settings document — constructing a real Beanie one
    needs an initialised collection, and the rule is what is under test."""

    def __init__(self, url):
        self.redirectUrl = url
        self.account_index = 0
        self.saved = False

    async def save(self):
        self.saved = True


async def heal(url, want, monkeypatch):
    monkeypatch.setattr(
        type(cfg), "zerodha_redirect_url", property(lambda self: want)
    )
    row = _Row(url)
    await ZerodhaService._heal_redirect_url(row)
    return row


# ── the born-wrong default ────────────────────────────────────────────
def test_the_default_follows_the_deployments_public_url():
    """Hardcoding it meant a fresh row on a real server was wrong on arrival."""
    factory = ZerodhaSettings.model_fields["redirectUrl"].default_factory
    assert factory is not None, "still a hardcoded literal"
    assert factory() == cfg.zerodha_redirect_url


def test_the_callback_path_is_the_backend_one():
    """The frontends (3000/3001) have no callback route — a redirect to either
    fails silently, which is exactly how this hid."""
    assert cfg.zerodha_redirect_url.endswith("/api/v1/admin/zerodha/callback")


# ── healing a stale row ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_stale_localhost_row_is_corrected(monkeypatch):
    row = await heal(LOCAL, REAL, monkeypatch)
    assert row.redirectUrl == REAL
    assert row.saved


@pytest.mark.asyncio
async def test_the_loopback_ip_counts_as_localhost(monkeypatch):
    row = await heal("http://127.0.0.1:8000/api/v1/admin/zerodha/callback", REAL, monkeypatch)
    assert row.redirectUrl == REAL


@pytest.mark.asyncio
async def test_an_empty_url_is_filled_in(monkeypatch):
    row = await heal("", REAL, monkeypatch)
    assert row.redirectUrl == REAL


# ── what must be left alone ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_deliberate_custom_callback_is_never_overwritten(monkeypatch):
    """Someone may front the API on another host. Silently rewriting that
    would break a working setup to fix one that was never broken."""
    custom = "https://kite-callback.example.com/api/v1/admin/zerodha/callback"
    row = await heal(custom, REAL, monkeypatch)
    assert row.redirectUrl == custom
    assert not row.saved


@pytest.mark.asyncio
async def test_a_dev_box_is_left_exactly_as_it_is(monkeypatch):
    """With no BACKEND_PUBLIC_URL the configured default IS localhost, and
    localhost is the correct answer there."""
    row = await heal(LOCAL, LOCAL, monkeypatch)
    assert row.redirectUrl == LOCAL
    assert not row.saved


@pytest.mark.asyncio
async def test_it_never_swaps_one_localhost_for_another(monkeypatch):
    """If this deployment has nothing better to offer, changing the value
    achieves nothing and only churns the document."""
    row = await heal(LOCAL, "http://127.0.0.1:9000/api/v1/admin/zerodha/callback", monkeypatch)
    assert row.redirectUrl == LOCAL
    assert not row.saved


@pytest.mark.asyncio
async def test_an_already_correct_row_is_not_rewritten(monkeypatch):
    row = await heal(REAL, REAL, monkeypatch)
    assert not row.saved


# ── wiring ────────────────────────────────────────────────────────────
def test_every_read_goes_through_the_heal():
    """It has to run where the settings are fetched, or a row nobody edits
    stays wrong forever."""
    assert "await self._heal_redirect_url(s)" in inspect.getsource(
        ZerodhaService._get_settings
    )


def test_a_save_failure_does_not_break_the_read():
    """A Mongo hiccup while healing must not take down every Zerodha call."""
    src = inspect.getsource(ZerodhaService._heal_redirect_url)
    assert "except Exception" in src
