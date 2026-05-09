"""Heuristics to find likely screen captures for separate review."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from photo_organizer.metadata import is_image_file

# macOS / iOS / Android / common exports
_SCREENSHOT_NAME_RE = re.compile(
    r"(?i)screenshot|screen[-_\s]?shot|螢幕截圖|螢幕快照|截圖|录屏|錄屏|"
    r"screencapture|screen\s*recording|zrzut|captura"
)


@dataclass
class ScreenshotHit:
    """A single image identified as a likely screenshot, with its detection reason and dimensions."""

    path: str
    reason: str
    width: int
    height: int
    format: str | None


def _png_phone_screenshot_shape(w: int, h: int) -> bool:
    """Tall PNG canvas typical of phone full-screen captures (not proof alone)."""
    short, long = (w, h) if w <= h else (h, w)
    if short < 500:
        return False
    ar = long / max(short, 1)
    return ar >= 1.75


def screenshot_reason(path: Path) -> str | None:
    """
    Return a short reason string if this file is treated as a screenshot candidate, else None.
    """
    path = path.resolve()
    if not path.is_file() or not is_image_file(path):
        return None
    if _SCREENSHOT_NAME_RE.search(path.name):
        return "filename"
    try:
        with Image.open(path) as im:
            fmt = im.format
            w, h = im.size
    except OSError:
        return None
    if fmt == "PNG" and _png_phone_screenshot_shape(w, h):
        return "png_shape"
    return None


def is_screenshot_candidate(path: Path) -> bool:
    """Return True if the file matches any screenshot heuristic (filename or PNG shape)."""
    return screenshot_reason(path) is not None


def is_screenshot_name_match(path: Path) -> bool:
    """
    Filename-only screenshot signal (for excluding from *similar-image* clustering).

    Tall PNG aspect-ratio alone matches many normal phone photos/exports; those stay in the
    similar scan. Full shape+name heuristics remain in screenshot_reason / iter_screenshot_hits.
    """
    path = path.resolve()
    if not path.is_file() or not is_image_file(path):
        return False
    return bool(_SCREENSHOT_NAME_RE.search(path.name))


def iter_screenshot_hits(root: Path) -> list[ScreenshotHit]:
    """Walk root recursively and return ScreenshotHit records for all likely screenshots found."""
    root = root.resolve()
    if not root.is_dir():
        return []
    out: list[ScreenshotHit] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if not is_image_file(p):
            continue
        reason = screenshot_reason(p)
        if not reason:
            continue
        try:
            with Image.open(p) as im:
                w, h = im.size
                fmt = im.format
        except OSError:
            continue
        out.append(ScreenshotHit(str(p.resolve()), reason, w, h, fmt))
    return out


def write_screenshots_report(hits: list[ScreenshotHit], out_path: Path, *, input_dir: Path) -> None:
    """Serialise screenshot scan results to a timestamped JSON file at out_path."""
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_dir": str(input_dir.resolve()),
        "count": len(hits),
        "items": [asdict(h) for h in hits],
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def scan_screenshots_folder(input_dir: Path) -> list[ScreenshotHit]:
    """Return all screenshot candidates under input_dir (thin wrapper over iter_screenshot_hits)."""
    return iter_screenshot_hits(input_dir)
