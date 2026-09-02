"""The SL/TP routes have to actually be routes.

A helper got inserted between `@router.put(".../sl-tp")` and the endpoint it
was meant to decorate, so the decorator landed on the helper instead. FastAPI
read its bare `p` argument as a required QUERY param, and every save came back
"Request validation failed" — while `update_sl_tp` sat there undecorated and
unreachable.

Reading the source proves nothing here; the router is the only witness.
"""

from __future__ import annotations

from app.api.v1.user.positions import router

ROUTES = {(r.path, n): r for r in router.routes for n in getattr(r, "methods", ())}


def _route(path: str):
    r = ROUTES.get((path, "PUT"))
    assert r is not None, f"{path} is not registered: {sorted(p for p, _ in ROUTES)}"
    return r


def test_both_sl_tp_routes_exist():
    _route("/positions/{position_id}/sl-tp")
    _route("/positions/active-trades/{trade_id}/sl-tp")


def test_they_point_at_the_endpoint_and_not_a_helper():
    assert _route("/positions/{position_id}/sl-tp").endpoint.__name__ == "update_sl_tp"
    assert (
        _route("/positions/active-trades/{trade_id}/sl-tp").endpoint.__name__
        == "update_active_trade_sl_tp"
    )


def test_the_body_is_the_only_thing_the_client_has_to_send():
    """Anything else required would 422 the save. The path param and the
    authenticated user are supplied by the framework; `payload` is the body."""
    for path in ("/positions/{position_id}/sl-tp", "/positions/active-trades/{trade_id}/sl-tp"):
        names = {p.name for p in _route(path).dependant.query_params}
        assert not names, f"{path} wants query params: {names}"
