"""Generate the PWA icon set (192 + 512 + maskable 512) on a black tile.

    py frontend-user/public/icons/_gen_pwa_icons.py

Source of truth is `../images/fevicon.png` — the 1024x1024 StockEx-coin
master, which already carries a TRANSPARENT background. So the tile is just
"composite the master onto black"; no colour-keying or flood-fill of a baked-in
white background, which is what would leave a pale halo around the coin's
anti-aliased rim.

This replaces the original emerald/white-sprout generator. That art stopped
being what ships the moment the coin icons were dropped in by hand, so running
the old script would have silently reverted the launcher icon to a mark the
product no longer uses.

BACKGROUND is `#0a0a0a`, not pure `#000` — it matches `background_color` /
`theme_color` in `app/manifest.webmanifest/route.ts`, so the icon square blends
into the PWA splash screen instead of sitting on it as a slightly darker patch.

MASKABLE sizing matters: Android crops a maskable icon to a circle/squircle and
only the inner 80% is guaranteed to survive. The coin is therefore drawn at 64%
of the canvas there, versus 86% on the plain tiles which are cropped far less.
"""
import os

from PIL import Image

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(OUT_DIR, os.pardir, "images", "fevicon.png")

# Matches manifest background_color / theme_color and the locked Tailwind bg.
BG = (10, 10, 10, 255)  # #0a0a0a

# Fraction of the tile the coin occupies.
SCALE_ANY = 0.86      # plain tile — only the corners get rounded off
SCALE_MASKABLE = 0.64  # maskable — must survive a circle crop (inner 80%)


def tile(size: int, coin_scale: float) -> Image.Image:
    """The coin centred on a full-bleed black square."""
    master = Image.open(MASTER).convert("RGBA")
    side = max(1, int(size * coin_scale))
    coin = master.resize((side, side), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), BG)
    off = (size - side) // 2
    # alpha_composite (not paste) so the master's soft anti-aliased rim blends
    # into the black instead of being cut against it.
    canvas.alpha_composite(coin, (off, off))
    return canvas


def main() -> None:
    for s in (192, 512):
        path = os.path.join(OUT_DIR, f"icon-{s}.png")
        tile(s, SCALE_ANY).save(path, "PNG")
        print(f"wrote {path} ({s}x{s})")

    mp = os.path.join(OUT_DIR, "icon-maskable-512.png")
    tile(512, SCALE_MASKABLE).save(mp, "PNG")
    print(f"wrote {mp} (512x512 maskable)")


if __name__ == "__main__":
    main()
