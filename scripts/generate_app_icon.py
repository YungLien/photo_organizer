"""Write assets/photo_organizer_icon.png using the same palette as review.css / dashboard (local web UI).

On macOS, also builds AppIcon.icns (via sips + iconutil) and copies it into macOS/Photo Organizer.app so Finder/Dock
show the icon without using Get Info → Paste (aliases then pick up the bundle icon).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "photo_organizer_icon.png"

# review.css :root — keep in sync for Finder / Dock icon vs browser chrome
CORNSILK = (254, 250, 224, 255)  # --cornsilk #fefae0
BEIGE = (233, 237, 201, 255)  # --beige #e9edc9
PAPAYA = (250, 237, 205, 255)  # --papaya-whip #faedcd
DRY_SAGE = (204, 213, 174, 255)  # --dry-sage #ccd5ae
BORDER_STRONG = (191, 201, 160, 255)  # --border-strong #bfc9a0
LIGHT_BRONZE = (212, 163, 115, 255)  # --light-bronze #d4a373
TEXT = (60, 56, 51, 255)  # --text #3c3833


def _build_icns_from_png(src_png: Path, dest_icns: Path) -> None:
    """Requires macOS `sips` and `iconutil`."""
    with tempfile.TemporaryDirectory() as td:
        iset = Path(td) / "AppIcon.iconset"
        iset.mkdir()
        # iconutil expects these pixel sizes (see `man iconutil`)
        specs: list[tuple[str, int]] = [
            ("icon_16x16.png", 16),
            ("icon_16x16@2x.png", 32),
            ("icon_32x32.png", 32),
            ("icon_32x32@2x.png", 64),
            ("icon_128x128.png", 128),
            ("icon_128x128@2x.png", 256),
            ("icon_256x256.png", 256),
            ("icon_256x256@2x.png", 512),
            ("icon_512x512.png", 512),
            ("icon_512x512@2x.png", 1024),
        ]
        for name, size in specs:
            out = iset / name
            subprocess.run(
                ["sips", "-z", str(size), str(size), str(src_png), "--out", str(out)],
                check=True,
                capture_output=True,
            )
        dest_icns.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["iconutil", "-c", "icns", str(iset), "-o", str(dest_icns)],
            check=True,
            capture_output=True,
        )


def _embed_icons_into_macos_apps(icns: Path) -> None:
    """Copy AppIcon.icns into each .app bundle (repo-relative macOS/)."""
    apps = [ROOT / "macOS" / "Photo Organizer.app"]
    for app in apps:
        res = app / "Contents" / "Resources"
        if not res.is_dir():
            continue
        shutil.copy2(icns, res / "AppIcon.icns")
        # nudge Finder to notice metadata changes
        subprocess.run(["/usr/bin/touch", str(app)], check=False)


def main() -> None:
    w = 1024
    r = 200
    pad = 40
    im = Image.new("RGBA", (w, w), (0, 0, 0, 0))

    # Warm wash (matches dashboard mesh / body gradient feel)
    glow = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        (-w // 4, -w // 8, w + w // 4, w + w // 3),
        fill=(*PAPAYA[:3], 90),
    )
    gd.ellipse(
        (w // 3, w // 4, w + w // 2, w + w // 2),
        fill=(*BEIGE[:3], 70),
    )
    im = Image.alpha_composite(im, glow)

    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle(
        (pad, pad, w - pad, w - pad),
        radius=r,
        fill=CORNSILK,
        outline=BORDER_STRONG,
        width=6,
    )

    # Inner sage band (subtle, like card border in UI)
    inner = pad + 18
    dr.rounded_rectangle(
        (inner, inner, w - inner, w - inner),
        radius=r - 24,
        outline=DRY_SAGE,
        width=3,
    )

    ink = TEXT
    accent = LIGHT_BRONZE
    # Crescent (night / “organize” metaphor)
    cx, cy, rad = w // 2 - 110, w // 2 - 36, 188
    dr.arc(
        (cx - rad, cy - rad, cx + rad, cy + rad),
        start=200,
        end=340,
        fill=ink,
        width=34,
    )

    def star(x: int, y: int, s: int, fill: tuple[int, int, int, int]) -> None:
        pts = [
            (x, y - s),
            (x + s // 4, y - s // 4),
            (x + s, y),
            (x + s // 4, y + s // 4),
            (x, y + s),
            (x - s // 4, y + s // 4),
            (x - s, y),
            (x - s // 4, y - s // 4),
        ]
        dr.polygon(pts, fill=fill)

    star(312, 268, 26, ink)
    star(392, 208, 18, accent)
    star(720, 320, 16, accent)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT, format="PNG")
    print(f"Wrote {OUT}")

    if platform.system() == "Darwin":
        icns_path = OUT.parent / "AppIcon.icns"
        try:
            _build_icns_from_png(OUT, icns_path)
            print(f"Wrote {icns_path}")
            _embed_icons_into_macos_apps(icns_path)
            print("Embedded AppIcon.icns into macOS/Photo Organizer.app (touch for Finder).")
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            print(
                "Skipping .icns / .app embed (need macOS sips + iconutil, and macOS/Photo Organizer.app present):",
                e,
            )


if __name__ == "__main__":
    main()
