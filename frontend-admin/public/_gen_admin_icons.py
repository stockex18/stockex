"""Generate the ADMIN app icon set from the real StockEx logo.

    py frontend-admin/public/_gen_admin_icons.py

Source of truth is the user app's `public/images/stockexlogoenhanced.png` — the
3375x3375 StockEx master (blue diamond, gold rising arrow, gold ring, wordmark
underneath) on a transparent background.

Only the EMBLEM is used, not the wordmark: at 192px the "STOCKEX" lettering and
the tagline under it are unreadable, and the emblem alone is what reads as the
brand at launcher size. It is also what tells this app apart from the other two
on one home screen — the user app and the broker app both carry the gold coin.

The emblem is found, not hard-coded: the top part of the master is cropped to
the bounding box of its opaque pixels, so a re-exported master with different
padding still centres correctly.

This replaces the emerald leaf (`icon-192.png` / `icon-512.png`) left over from
the old brand. BACKGROUND is `#0a0a0a` to match the manifest's
background_color / theme_color, so the tile blends into the splash screen.
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MASTER = os.path.join(
    HERE, os.pardir, os.pardir, "frontend-user", "public", "images", "stockexlogoenhanced.png"
)

BG = (10, 10, 10, 255)  # #0a0a0a

#: The emblem sits in the top part of the master; the wordmark starts below it.
EMBLEM_BAND = 0.635

SCALE_ANY = 0.84       # plain tile — only the corners get rounded off
SCALE_MASKABLE = 0.62  # maskable — must survive Android's circle crop (inner 80%)


def emblem() -> Image.Image:
    master = Image.open(MASTER).convert("RGBA")
    w, h = master.size
    band = master.crop((0, 0, w, int(h * EMBLEM_BAND)))
    # Bounding box of anything not near-transparent — the emblem itself.
    alpha = band.split()[3].point(lambda a: 255 if a > 24 else 0)
    box = alpha.getbbox()
    if box is None:
        raise SystemExit("emblem not found in master")
    em = band.crop(box)
    # Pad to a square so resizing keeps the proportions.
    side = max(em.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.alpha_composite(em, ((side - em.width) // 2, (side - em.height) // 2))
    return sq


def tile(src: Image.Image, size: int, scale: float, bg=BG) -> Image.Image:
    side = max(1, int(size * scale))
    art = src.resize((side, side), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), bg)
    off = (size - side) // 2
    canvas.alpha_composite(art, (off, off))
    return canvas


def main() -> None:
    em = emblem()
    for s in (192, 512):
        p = os.path.join(HERE, f"icon-{s}.png")
        tile(em, s, SCALE_ANY).save(p, "PNG")
        print("wrote", p)
    p = os.path.join(HERE, "icon-maskable-512.png")
    tile(em, 512, SCALE_MASKABLE).save(p, "PNG")
    print("wrote", p)
    # iOS ignores manifest icons and squares its own corners — full-bleed tile.
    p = os.path.join(HERE, "apple-touch-icon.png")
    tile(em, 180, SCALE_ANY).convert("RGB").save(p, "PNG")
    print("wrote", p)
    # Browser tab.
    p = os.path.join(HERE, "favicon-32.png")
    tile(em, 32, 0.92).save(p, "PNG")
    print("wrote", p)
    # A transparent emblem for the in-app brand mark (header / login).
    p = os.path.join(HERE, "stockex-mark.png")
    em.resize((256, 256), Image.LANCZOS).save(p, "PNG")
    print("wrote", p)


if __name__ == "__main__":
    main()
