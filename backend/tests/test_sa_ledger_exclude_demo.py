"""Super Admin Ledger: "Exclude demo accounts" (client request, Nov 2026).

Demo accounts trade with virtual coins (topped up to 9 lakh across main and
segment wallets) held in the same wallet tables as real money, and the SA
Ledger summed them with everything else: a lone demo account showed up as a
9,00,000 "Direct (under SA)" pool. With `exclude_demo` every section leaves
demo accounts out. Off by default on the API; the page sends it ticked."""

from __future__ import annotations

import asyncio

from app.api.v1.admin import sa_ledger


def test_the_filter_leaves_demo_accounts_out_only_when_asked():
    base = {"role": "CLIENT"}
    assert sa_ledger._users_filter(base, False) == {"role": "CLIENT"}
    assert sa_ledger._users_filter(base, True) == {"role": "CLIENT", "is_demo": {"$ne": True}}
    assert base == {"role": "CLIENT"}  # the caller's dict is not changed


def test_the_ledger_maps_skip_demo_clients(monkeypatch):
    seen: list = []

    class _Q:
        async def to_list(self):
            return []

    monkeypatch.setattr(sa_ledger.User, "find", lambda filt, *a, **k: seen.append(filt) or _Q())
    asyncio.run(sa_ledger._maps(True))
    asyncio.run(sa_ledger._maps(False))
    assert seen == [
        {"role": "CLIENT", "is_demo": {"$ne": True}},
        {"role": "CLIENT"},
    ]


def test_every_ledger_endpoint_takes_the_option_and_defaults_to_off():
    import inspect

    for fn in (sa_ledger.sa_ledger, sa_ledger.kuber_recon, sa_ledger.kuber_recon_reset,
               sa_ledger.admin_drill):
        p = inspect.signature(fn).parameters["exclude_demo"]
        assert p.default.default is False, fn.__name__
