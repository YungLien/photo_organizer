"""Read capture time from images and videos."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

# Pillow Exif: DateTimeOriginal
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306
_EXIF_DATETIME_DIGITIZED = 36868

_IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".jpe",
    ".png",
    ".webp",
    ".heic",
    ".heif",
    ".tif",
    ".tiff",
}
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

_EXIF_DATETIME_RE = re.compile(
    r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})"
)

# ffprobe / QuickTime: "+0800" at end (no colon in offset)
_RE_TZ_COMPACT = re.compile(r"([+-])(\d{2})(\d{2})$")


def _parse_exif_datetime(s: str | None) -> datetime | None:
    """Parse an EXIF-style datetime string (e.g. '2024:01:15 12:30:45') to a naive datetime."""
    if not s or not isinstance(s, str):
        return None
    m = _EXIF_DATETIME_RE.match(s.strip())
    if not m:
        return None
    y, mo, d, h, mi, se = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, se)
    except ValueError:
        return None


def _datetime_from_image(path: Path) -> datetime | None:
    """Extract capture datetime from image EXIF tags via Pillow."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif is None:
                return None
            for tag in (_EXIF_DATETIME_ORIGINAL, _EXIF_DATETIME_DIGITIZED, _EXIF_DATETIME):
                raw = exif.get(tag)
                if raw:
                    dt = _parse_exif_datetime(str(raw))
                    if dt:
                        return dt
    except OSError:
        return None
    return None


def _datetime_from_macos_assetsd_xattr(path: Path) -> datetime | None:
    """
    Photos / assetsd often store the library capture time in extended attributes while
    stripping classic EXIF date tags. Finder shows that time as the photo date.
    """
    if sys.platform != "darwin":
        return None
    for key in (
        "com.apple.assetsd.customCreationDate",
        "com.apple.assetsd.addedDate",
    ):
        try:
            hx = subprocess.check_output(
                ["xattr", "-px", key, str(path)],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue
        parts = hx.split()
        if not parts:
            continue
        try:
            raw = bytes(int(x, 16) for x in parts)
        except ValueError:
            continue
        try:
            proc = subprocess.run(
                ["plutil", "-p", "-"],
                input=raw,
                capture_output=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue
        line = proc.stdout.decode().strip()
        if not line:
            continue
        try:
            aware = datetime.strptime(line, "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            continue
        return aware.astimezone().replace(tzinfo=None)
    return None


def _parse_ffprobe_datetime_string(raw: object) -> datetime | None:
    """Parse creation_time / QuickTime date strings from ffprobe tags to naive local wall time."""
    if raw is None:
        return None
    s = str(raw).strip().strip('"')
    if not s:
        return None
    m = _RE_TZ_COMPACT.search(s)
    if m:
        s = s[: m.start()] + f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    s = s.replace("Z", "+00:00")
    # "2024-01-15 08:00:00+08:00" — fromisoformat wants T between date and time
    if " " in s and "T" not in s.split("+", 1)[0]:
        head, _, tail = s.partition(" ")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", head):
            s = head + "T" + tail
    # EXIF-style "2024:01:15 12:30:45" in some atoms
    em = _EXIF_DATETIME_RE.match(s)
    if em:
        y, mo, d, h, mi, se = (int(x) for x in em.groups())
        try:
            return datetime(y, mo, d, h, mi, se)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _datetime_from_ffprobe(path: Path) -> datetime | None:
    """
    Read embedded times via ffprobe JSON.

    ``format.creation_time`` alone is often the *mux* time (re-export = current month).
    Prefer ``com.apple.quicktime.creationdate``, then **video** stream ``creation_time``,
    then other streams' ``creation_time``, then format ``creation_time`` / ``date``.
    """
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None

    qt_dates: list[datetime] = []
    video_stream_ct: list[datetime] = []
    other_stream_ct: list[datetime] = []
    format_mux_dt: list[datetime] = []

    def scan_stream_tags(tags: object, *, is_video: bool) -> None:
        if not isinstance(tags, dict):
            return
        q = tags.get("com.apple.quicktime.creationdate")
        if q:
            dt = _parse_ffprobe_datetime_string(q)
            if dt:
                qt_dates.append(dt)
        ct = tags.get("creation_time")
        if ct:
            dt = _parse_ffprobe_datetime_string(ct)
            if dt:
                if is_video:
                    video_stream_ct.append(dt)
                else:
                    other_stream_ct.append(dt)

    fmt = data.get("format") or {}
    ftags = fmt.get("tags")
    if isinstance(ftags, dict):
        q = ftags.get("com.apple.quicktime.creationdate")
        if q:
            dt = _parse_ffprobe_datetime_string(q)
            if dt:
                qt_dates.append(dt)
        for key in ("creation_time", "date"):
            if key not in ftags:
                continue
            dt = _parse_ffprobe_datetime_string(ftags[key])
            if dt:
                format_mux_dt.append(dt)

    for stream in data.get("streams") or []:
        scan_stream_tags(stream.get("tags"), is_video=stream.get("codec_type") == "video")

    if qt_dates:
        return min(qt_dates)
    if video_stream_ct:
        return min(video_stream_ct)
    if other_stream_ct:
        return min(other_stream_ct)
    if format_mux_dt:
        return min(format_mux_dt)
    return None


def capture_datetime(path: Path) -> datetime | None:
    """Best-effort capture time for sorting into YYYY/MM. None if unknown."""
    path = path.resolve()
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTS:
        dt = _datetime_from_image(path)
        if dt:
            return dt
        dt = _datetime_from_macos_assetsd_xattr(path)
        if dt:
            return dt
    if suffix in _VIDEO_EXTS:
        # Photos / Finder often expose capture time on exported .mov/.mp4 via the same xattr as stills.
        if sys.platform == "darwin":
            dt = _datetime_from_macos_assetsd_xattr(path)
            if dt:
                return dt
        dt = _datetime_from_ffprobe(path)
        if dt:
            return dt
    return None


def is_media_file(path: Path) -> bool:
    """Return True if the file extension is a recognised image or video type."""
    return path.suffix.lower() in _IMAGE_EXTS | _VIDEO_EXTS


def is_image_file(path: Path) -> bool:
    """Return True if the file extension is a recognised image type."""
    return path.suffix.lower() in _IMAGE_EXTS
