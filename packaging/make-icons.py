"""Generate the FlintTrade desktop app icons from the canonical brand mark.

Produces, under ``packages/apps/desktop/resources/icons/``:
  * icon.png (512), 32x32.png, 128x128.png, 128x128@2x.png (256)
  * icon.ico (multi-size, Windows)
  * icon.icns (macOS)

The angular ``F`` and faceted green spark mirror ``docs/assets/logo.svg`` and
the shared ``@flinttrade/design-system`` LogoIcon. A fixed dark tile keeps the
desktop icon legible in light and dark operating-system themes.

Run: ``.venv/bin/python packaging/make-icons.py``
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ICONS_DIR = Path(__file__).resolve().parent.parent / "packages" / "apps" / "desktop" / "resources" / "icons"

MASTER = 1024
BG = (10, 10, 15, 255)  # #0a0a0f
BORDER = (39, 39, 42, 255)  # #27272a
MARK = (244, 244, 245, 255)  # #f4f4f5
SPARK = (34, 197, 94, 255)  # #22c55e
SPARK_HIGHLIGHT = (74, 222, 128, 255)  # #4ade80

TILE_PAD = 48
TILE_RADIUS = 220
MARK_ORIGIN = 128
MARK_UNIT = 24


def _mark_point(x: int, y: int) -> tuple[int, int]:
    """Scale a point from the canonical 32×32 LogoIcon viewBox."""
    return MARK_ORIGIN + (x * MARK_UNIT), MARK_ORIGIN + (y * MARK_UNIT)


def _mark_box(x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    """Scale a rectangle from the canonical 32×32 LogoIcon viewBox."""
    left, top = _mark_point(x, y)
    right, bottom = _mark_point(x + width, y + height)
    return left, top, right, bottom


def render_master() -> Image.Image:
    """Render the 1024px master icon from the shared FlintTrade geometry."""
    img = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # A subtle border keeps the dark app tile distinct on black backgrounds.
    draw.rounded_rectangle(
        [TILE_PAD, TILE_PAD, MASTER - TILE_PAD, MASTER - TILE_PAD],
        radius=TILE_RADIUS,
        fill=BORDER,
    )
    draw.rounded_rectangle(
        [TILE_PAD + 8, TILE_PAD + 8, MASTER - TILE_PAD - 8, MASTER - TILE_PAD - 8],
        radius=TILE_RADIUS - 8,
        fill=BG,
    )

    spark_points = [
        _mark_point(x, y)
        for x, y in ((24, 1), (29, 6), (24, 11), (21, 7), (24, 5), (21, 3))
    ]
    spark_highlight_points = [_mark_point(x, y) for x, y in ((25, 0), (28, 3), (26, 3), (24, 1))]

    # A restrained green glow supports the spark without changing its geometry.
    glow = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.polygon(spark_points, fill=(*SPARK[:3], 150))
    glow = glow.filter(ImageFilter.GaussianBlur(52))
    tile_mask = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        [TILE_PAD, TILE_PAD, MASTER - TILE_PAD, MASTER - TILE_PAD],
        radius=TILE_RADIUS,
        fill=255,
    )
    glow.putalpha(Image.composite(glow.getchannel("A"), Image.new("L", (MASTER, MASTER), 0), tile_mask))
    img.alpha_composite(glow)

    # Canonical F letterform: stem, top arm and middle arm.
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(_mark_box(3, 3, 5, 26), radius=MARK_UNIT, fill=MARK)
    draw.rounded_rectangle(_mark_box(3, 3, 20, 5), radius=MARK_UNIT, fill=MARK)
    draw.rounded_rectangle(_mark_box(3, 13, 14, 5), radius=MARK_UNIT, fill=MARK)

    # Canonical faceted flint spark and its highlight sliver.
    draw.polygon(spark_points, fill=SPARK)
    draw.polygon(spark_highlight_points, fill=SPARK_HIGHLIGHT)

    return img


def write_icons(destination: Path) -> list[Path]:
    """Write every platform icon from one canonical render."""
    destination.mkdir(parents=True, exist_ok=True)
    master = render_master()

    # Square PNGs used by electron-builder and the runtime tray.
    master.resize((512, 512), Image.LANCZOS).save(destination / "icon.png")
    master.resize((32, 32), Image.LANCZOS).save(destination / "32x32.png")
    master.resize((128, 128), Image.LANCZOS).save(destination / "128x128.png")
    master.resize((256, 256), Image.LANCZOS).save(destination / "128x128@2x.png")

    # Windows multi-size ICO.
    master.save(
        destination / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    # macOS ICNS.
    master.save(destination / "icon.icns")

    return sorted(path for path in destination.iterdir() if path.is_file())


def main() -> None:
    written = write_icons(ICONS_DIR)
    print(f"Icons written to {ICONS_DIR}")
    for p in written:
        print(f"  {p.name:18} {p.stat().st_size:>8} bytes")


if __name__ == "__main__":
    main()
