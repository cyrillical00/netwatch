"""
Run this once on your Mac to generate assets/icon.icns.

Requirements:
    pip3 install pillow

Usage:
    python3 make_icon.py
"""

import math
import subprocess
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Run: pip3 install pillow")

# ── Design constants ──────────────────────────────────────────────────────────
BG      = (15, 23, 42)       # #0F172A  dark navy
GREEN   = (34, 197, 94)      # #22C55E  NetWatch green
WHITE   = (241, 245, 249)    # #F1F5F9


def draw_icon(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded square background
    r    = size // 5
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    cx, cy = size / 2, size / 2

    # ── Wifi arcs (3 arcs, outer to inner) ───────────────────────────────────
    arc_configs = [
        (0.72, 8),   # outer
        (0.50, 7),   # mid
        (0.30, 6),   # inner
    ]
    arc_start = 225   # degrees — opens upward
    arc_span  = 90

    for scale, lw in arc_configs:
        radius  = (size * scale) / 2
        lw_px   = max(1, int(size * lw / 128))
        bbox    = [cx - radius, cy - radius, cx + radius, cy + radius]
        draw.arc(bbox, start=arc_start, end=arc_start + arc_span,
                 fill=GREEN, width=lw_px)

    # ── Center dot ───────────────────────────────────────────────────────────
    dot_r = size * 0.07
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=GREEN)

    # ── Small "pulse" ring around the dot (subtle) ───────────────────────────
    ring_r = size * 0.14
    lw_ring = max(1, int(size * 4 / 128))
    draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                 outline=(*GREEN, 120), width=lw_ring)

    return img


def build_iconset(iconset_dir: Path):
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for s in sizes:
        img = draw_icon(s)
        img.save(iconset_dir / f"icon_{s}x{s}.png")
        # Retina variants
        if s <= 512:
            img2x = draw_icon(s * 2)
            img2x.save(iconset_dir / f"icon_{s}x{s}@2x.png")


def main():
    assets = Path(__file__).parent / "assets"
    assets.mkdir(exist_ok=True)

    iconset = assets / "NetWatch.iconset"
    iconset.mkdir(exist_ok=True)

    print("Drawing icon at all required sizes...")
    build_iconset(iconset)

    # iconutil is macOS-only — skip on other platforms and leave PNGs in place
    if subprocess.run(["which", "iconutil"], capture_output=True).returncode != 0:
        print("iconutil not found (not on macOS) — PNGs written to assets/NetWatch.iconset/")
        print("Run this script on a Mac to produce assets/icon.icns")
        return

    print("Converting to .icns via iconutil...")
    out = assets / "icon.icns"
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(out)],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"iconutil failed: {result.stderr}")
        raise SystemExit(1)

    import shutil
    shutil.rmtree(iconset)

    print(f"Done → {out}")


if __name__ == "__main__":
    main()
