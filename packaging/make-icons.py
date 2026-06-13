"""Generate the FlintTrade desktop app icons from a single vector-style render.

Produces, under ``packages/apps/desktop/src-tauri/icons/``:
  * icon.png (512), 32x32.png, 128x128.png, 128x128@2x.png (256)
  * icon.ico (multi-size, Windows)
  * icon.icns (macOS)

The mark mirrors the splash screen: a dark rounded tile with an orange "flint
spark" — a rotated rounded square with an outer glow.

Run: ``.venv/bin/python packaging/make-icons.py``
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ICONS_DIR = Path(__file__).resolve().parent.parent / "packages" / "apps" / "desktop" / "src-tauri" / "icons"

# Brand palette (matches splash/index.html).
BG = (11, 13, 18, 255)          # #0b0d12
ACCENT = (255, 106, 61)         # #ff6a3d
ACCENT_2 = (255, 176, 114)      # #ffb072

MASTER = 1024


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """A vertical top→bottom gradient swatch."""
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel(
            (0, y),
            tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    return grad.resize((size, size))


def render_master() -> Image.Image:
    """Render the 1024px master icon."""
    img = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded dark tile.
    pad = 96
    draw.rounded_rectangle(
        [pad, pad, MASTER - pad, MASTER - pad],
        radius=200,
        fill=BG,
    )

    # Soft radial accent glow near the top.
    glow = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse([MASTER * 0.18, MASTER * 0.04, MASTER * 0.82, MASTER * 0.68], fill=(*ACCENT, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    # Clip the glow to the tile so it doesn't bleed past the rounded corners.
    mask = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, MASTER - pad, MASTER - pad], radius=200, fill=255)
    img.paste(glow, (0, 0), Image.composite(glow.split()[3], Image.new("L", (MASTER, MASTER), 0), mask))

    # The spark: a gradient-filled rounded square, drawn upright then rotated 45°.
    spark_size = 440
    spark = Image.new("RGBA", (spark_size, spark_size), (0, 0, 0, 0))
    spark_mask = Image.new("L", (spark_size, spark_size), 0)
    ImageDraw.Draw(spark_mask).rounded_rectangle(
        [0, 0, spark_size - 1, spark_size - 1], radius=110, fill=255
    )
    grad = _vertical_gradient(spark_size, ACCENT_2, ACCENT).convert("RGBA")
    spark.paste(grad, (0, 0), spark_mask)
    spark = spark.rotate(45, expand=True, resample=Image.BICUBIC)

    # Outer glow for the spark.
    spark_glow = spark.filter(ImageFilter.GaussianBlur(40))
    cx = (MASTER - spark_glow.width) // 2
    cy = (MASTER - spark_glow.height) // 2
    img.alpha_composite(spark_glow, (cx, cy))
    cx = (MASTER - spark.width) // 2
    cy = (MASTER - spark.height) // 2
    img.alpha_composite(spark, (cx, cy))

    return img


def main() -> None:
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    master = render_master()

    # Square PNGs Tauri references directly.
    master.resize((512, 512), Image.LANCZOS).save(ICONS_DIR / "icon.png")
    master.resize((32, 32), Image.LANCZOS).save(ICONS_DIR / "32x32.png")
    master.resize((128, 128), Image.LANCZOS).save(ICONS_DIR / "128x128.png")
    master.resize((256, 256), Image.LANCZOS).save(ICONS_DIR / "128x128@2x.png")

    # Windows multi-size ICO.
    master.save(
        ICONS_DIR / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    # macOS ICNS.
    master.save(ICONS_DIR / "icon.icns")

    print(f"Icons written to {ICONS_DIR}")
    for p in sorted(ICONS_DIR.iterdir()):
        print(f"  {p.name:18} {p.stat().st_size:>8} bytes")


if __name__ == "__main__":
    main()
