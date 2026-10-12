"""The dashboard shell must never be wider than the screen.

Reported on a laptop: the whole home page scrolled sideways and its right edge
(the demo banner's button, the last wallet card) was cut off. The layout's
content column is a CSS grid item, which by default will not shrink below its
content — and the announcement ticker is one long unbroken line, so it pushed
the column ~410 px past a 1366 px screen. `min-w-0` lets the column fit; the
ticker already clips itself.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_content_column_can_shrink_to_the_screen():
    src = (ROOT / "frontend-user/app/(dashboard)/layout.tsx").read_text(encoding="utf-8")
    assert '<div className="flex min-h-screen min-w-0 flex-col">' in src


def test_the_ticker_clips_its_own_line():
    src = (ROOT / "frontend-user/components/common/Ticker.tsx").read_text(encoding="utf-8")
    assert "overflow-hidden" in src
