"""One-off: write assets/photo_organizer_icon.png (mint rounded square, moon + stars). Run from repo root."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "photo_organizer_icon.png"


def main() -> None:
    w = 1024
    r = 200
    pad = 40
    im = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    # Mint background (CleanShot-adjacent palette, original artwork)
    dr.rounded_rectangle(
        (pad, pad, w - pad, w - pad),
        radius=r,
        fill=(216, 240, 232, 255),
        outline=(180, 210, 200, 255),
        width=4,
    )
    ink = (45, 52, 58, 255)
    # Crescent (thick arc)
    cx, cy, rad = w // 2 - 120, w // 2 - 40, 200
    dr.arc(
        (cx - rad, cy - rad, cx + rad, cy + rad),
        start=200,
        end=340,
        fill=ink,
        width=36,
    )
    # Sparkles
    def star(x: int, y: int, s: int) -> None:
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
        dr.polygon(pts, fill=ink)

    star(300, 260, 28)
    star(380, 200, 20)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT, format="PNG")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
