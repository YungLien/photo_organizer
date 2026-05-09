"""Copy or move files into Organized/YYYY/MM/ (or UnknownDate/)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from photo_organizer.filecopy import copy_preserve_metadata, move_preserving_metadata
from photo_organizer.metadata import capture_datetime, is_media_file


@dataclass
class OrganizeResult:
    """Counters and file-plan produced by a single organize() run."""

    copied: int = 0
    skipped: int = 0
    unknown_date: int = 0
    errors: list[str] = field(default_factory=list)
    planned: list[tuple[Path, Path]] = field(default_factory=list)


def _unique_dest(dest: Path) -> Path:
    """Return dest unchanged if it is free, else append _2, _3, ... until a free name is found."""
    if not dest.exists():
        return dest
    stem, suf = dest.stem, dest.suffix
    parent = dest.parent
    n = 2
    while True:
        cand = parent / f"{stem}_{n}{suf}"
        if not cand.exists():
            return cand
        n += 1


def _iter_files(root: Path) -> list[Path]:
    """Recursively list all non-hidden files under root, sorted for determinism."""
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            out.append(p)
    return out


def organize(
    input_dir: Path,
    organized_root: Path,
    *,
    copy: bool = True,
    dry_run: bool = False,
) -> OrganizeResult:
    """
    Place each media file under organized_root/YYYY/MM/name or .../UnknownDate/name.
    Skips non-media files. Nested structure under input_dir is flattened to basename
    (collisions get _2, _3, ...).
    """
    input_dir = input_dir.resolve()
    organized_root = organized_root.resolve()
    result = OrganizeResult()
    files = _iter_files(input_dir)

    for src in files:
        if not is_media_file(src):
            result.skipped += 1
            continue

        dt = capture_datetime(src)
        if dt is None:
            rel = organized_root / "UnknownDate"
            result.unknown_date += 1
        else:
            rel = organized_root / f"{dt.year:04d}" / f"{dt.month:02d}"

        dest = _unique_dest(rel / src.name)
        result.planned.append((src, dest))

        if dry_run:
            continue

        try:
            rel.mkdir(parents=True, exist_ok=True)
            if copy:
                copy_preserve_metadata(src, dest)
            else:
                move_preserving_metadata(src, dest)
            result.copied += 1
        except OSError as e:
            result.errors.append(f"{src}: {e}")

    return result
