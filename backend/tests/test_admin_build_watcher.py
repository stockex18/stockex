"""An admin / broker panel left open across a deploy must pick the deploy up.

The 401-loop fix was live, yet the super-admin's phone kept looping: the panel
had been open since before the deploy, and signing in again inside a
single-page app does not reload its JS. The panel now compares the build id
compiled into its bundle with the one the server reports and reloads when they
differ (on open, on return to the tab, every 5 minutes; never mid-typing).
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "frontend-admin"


def test_every_build_gets_an_id_in_the_bundle():
    cfg = (ROOT / "next.config.js").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_BUILD_ID: buildId()" in cfg
    # Stable across the several evaluations of next.config in ONE build: a
    # clock value gave the client and the server two different ids.
    assert "git rev-parse HEAD" in cfg
    assert "Date.now()" not in cfg


def test_the_server_reports_its_build_uncached():
    route = (ROOT / "app/build-version/route.ts").read_text(encoding="utf-8")
    assert 'export const dynamic = "force-dynamic";' in route
    assert "process.env.NEXT_PUBLIC_BUILD_ID" in route
    assert '"Cache-Control": "no-store"' in route


def test_the_panel_reloads_on_a_new_build_but_never_mid_typing():
    w = (ROOT / "components/common/BuildWatcher.tsx").read_text(encoding="utf-8")
    assert 'fetch("/build-version", { cache: "no-store" })' in w
    assert "build !== MINE" in w
    assert '!typing()' in w and 'document.visibilityState === "visible"' in w
    layout = (ROOT / "app/layout.tsx").read_text(encoding="utf-8")
    assert "<BuildWatcher />" in layout
