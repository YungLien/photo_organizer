"""Exact (byte) and near-duplicate (perceptual hash) grouping."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import imagehash
from PIL import Image, ImageOps

from photo_organizer.metadata import is_image_file, is_media_file
from photo_organizer.screenshots import is_screenshot_name_match


def _iter_media_paths(root: Path) -> list[Path]:
    """List media files under root. Skips dotfiles; dedupes by (st_dev, st_ino) so hard links appear once."""
    root = root.resolve()
    if not root.is_dir():
        return []
    out: list[Path] = []
    seen_ino: set[tuple[int, int]] = set()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.startswith(".") or not is_media_file(p):
            continue
        rp = p.resolve()
        try:
            st = rp.stat()
            key = (st.st_dev, st.st_ino)
        except OSError:
            key = None
        if key is not None:
            if key in seen_ino:
                continue
            seen_ino.add(key)
        out.append(rp)
    return out


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class _UnionFind:
    def __init__(self) -> None:
        self._p: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self._p:
            self._p[x] = x
        if self._p[x] != x:
            self._p[x] = self.find(self._p[x])
        return self._p[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._p[rb] = ra


@dataclass
class ExactDuplicateGroup:
    sha256: str
    byte_size: int
    paths: list[str]


@dataclass
class SimilarGroup:
    paths: list[str]
    phash_hex: str


@dataclass
class DuplicateScanResult:
    input_dir: str
    generated_at: str
    exact_groups: list[ExactDuplicateGroup] = field(default_factory=list)
    similar_groups: list[SimilarGroup] = field(default_factory=list)
    similar_max_hamming: int = 14
    similar_ahash_max_hamming: int = 18
    similar_serial_max_gap: int = 0
    similar_serial_max_hamming: int = 16
    similar_serial_ahash_max_hamming: int = 16
    similar_match_mode: str = "phash_led"
    similar_phash_tight: int = 10
    similar_ahash_loose: int = 28
    similar_excluded_screenshots: int = 0
    similar_skipped: list[dict[str, str]] = field(default_factory=list)


def find_exact_duplicates(paths: list[Path]) -> list[ExactDuplicateGroup]:
    by_hash: dict[str, list[Path]] = defaultdict(list)
    sizes: dict[str, int] = {}
    for p in paths:
        try:
            d = file_sha256(p)
        except OSError:
            continue
        by_hash[d].append(p)
        sizes[d] = p.stat().st_size
    groups: list[ExactDuplicateGroup] = []
    for digest, ps in by_hash.items():
        if len(ps) < 2:
            continue
        groups.append(
            ExactDuplicateGroup(
                sha256=digest,
                byte_size=sizes.get(digest, ps[0].stat().st_size),
                paths=[str(x) for x in sorted(ps)],
            )
        )
    groups.sort(key=lambda g: (-len(g.paths), g.byte_size))
    return groups


_STEM_SERIAL_RE = re.compile(r"^(.+?)(\d+)$", re.IGNORECASE)


def _normalize_for_hash(img: Image.Image, max_edge: int = 512) -> Image.Image:
    """Resize so the long edge is at most max_edge (keeps aspect); stabilizes pHash across resolutions."""
    w, h = img.size
    m = max(w, h)
    if m <= max_edge or m < 1:
        return img
    scale = max_edge / m
    nw = max(1, round(w * scale))
    nh = max(1, round(h * scale))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _stem_prefix_and_serial(path: Path) -> tuple[str, int] | None:
    m = _STEM_SERIAL_RE.match(path.stem)
    if not m:
        return None
    return m.group(1).lower(), int(m.group(2))


def _pair_similar_global(
    dp: int,
    da: int,
    *,
    max_p: int,
    max_a: int,
    mode: str,
    phash_tight: int = 10,
    ahash_loose: int = 28,
) -> bool:
    """
    mode 'and': both hashes must pass.
    mode 'or': either passes (legacy; more false positives).
    mode 'phash_led': (p≤max_p and a≤max_a) OR (p≤phash_tight and a≤ahash_loose) — same scene,
    different exposure/WB often fails pure 'and' on aHash.
    """
    if max_a <= 0:
        return dp <= max_p
    if mode == "or":
        return dp <= max_p or da <= max_a
    if mode == "and":
        return dp <= max_p and da <= max_a
    if mode == "phash_led":
        if dp <= max_p and da <= max_a:
            return True
        if dp <= phash_tight and da <= ahash_loose:
            return True
        return False
    return dp <= max_p and da <= max_a


def _pair_similar_serial(
    dp: int,
    da: int,
    *,
    max_p: int,
    max_a: int,
) -> bool:
    """Neighbor filenames only when both hashes pass (avoids OR+wide limits that chain unrelated shots)."""
    if max_a <= 0:
        return dp <= max_p
    return dp <= max_p and da <= max_a


def find_similar_groups(
    paths: list[Path],
    *,
    max_hamming_phash: int = 14,
    max_hamming_ahash: int = 18,
    serial_max_gap: int = 0,
    serial_max_hamming_phash: int = 16,
    serial_max_hamming_ahash: int = 16,
    match_mode: str = "phash_led",
    phash_tight: int = 10,
    ahash_loose: int = 28,
) -> tuple[list[SimilarGroup], list[dict[str, str]]]:
    """
    Cluster with perceptual pHash + average aHash (default match_mode 'phash_led').
    If serial_max_gap > 0, same-prefix neighbor numbers (e.g. IMG_100 / IMG_101) may also link when
    hashes pass the serial thresholds.
    """
    items: list[tuple[str, imagehash.ImageHash, imagehash.ImageHash]] = []
    skipped: list[dict[str, str]] = []
    for p in paths:
        if not is_image_file(p):
            continue
        try:
            with Image.open(p) as img:
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                img = _normalize_for_hash(img)
                hp = imagehash.phash(img)
                ha = imagehash.average_hash(img)
        except OSError as e:
            skipped.append({"path": str(p), "reason": f"open_error:{e}"})
            continue
        except Exception as e:
            skipped.append({"path": str(p), "reason": f"hash_error:{e}"})
            continue
        items.append((str(p), hp, ha))

    uf = _UnionFind()
    n = len(items)
    meta: list[
        tuple[str, imagehash.ImageHash, imagehash.ImageHash, tuple[str, int] | None]
    ] = [(p, hp, ha, _stem_prefix_and_serial(Path(p))) for p, hp, ha in items]
    for i in range(n):
        pi, hip, hia, mi = meta[i]
        uf.find(pi)
        for j in range(i + 1, n):
            pj, hjp, hja, mj = meta[j]
            dp = hip - hjp
            da = hia - hja
            if _pair_similar_global(
                dp,
                da,
                max_p=max_hamming_phash,
                max_a=max_hamming_ahash,
                mode=match_mode,
                phash_tight=phash_tight,
                ahash_loose=ahash_loose,
            ):
                uf.union(pi, pj)
                continue
            if (
                serial_max_gap > 0
                and mi is not None
                and mj is not None
                and mi[0] == mj[0]
                and abs(mi[1] - mj[1]) <= serial_max_gap
                and _pair_similar_global(
                    dp,
                    da,
                    max_p=serial_max_hamming_phash,
                    max_a=serial_max_hamming_ahash,
                    mode=match_mode,
                    phash_tight=min(phash_tight, serial_max_hamming_phash),
                    ahash_loose=max(ahash_loose, serial_max_hamming_ahash),
                )
            ):
                uf.union(pi, pj)

    clusters: dict[str, list[str]] = defaultdict(list)
    ph_for_path: dict[str, str] = {}
    for p, hp, _ha in items:
        ph_for_path[p] = str(hp)
        root = uf.find(p)
        clusters[root].append(p)

    groups: list[SimilarGroup] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        members_sorted = sorted(members)
        rep = members_sorted[0]
        groups.append(
            SimilarGroup(paths=members_sorted, phash_hex=ph_for_path.get(rep, "")),
        )
    groups.sort(key=lambda g: (-len(g.paths), g.paths[0]))
    return groups, skipped


def filter_similar_against_exact(
    similar: list[SimilarGroup],
    exact: list[ExactDuplicateGroup],
) -> list[SimilarGroup]:
    """
    Drop similar groups already fully explained by exact (byte-identical) groups.

    If every path in a similar cluster is contained in some exact duplicate cluster, that similar
    group is redundant in the review UI (exact + similar would show the same files twice).
    """
    if not similar or not exact:
        return similar
    exact_sets = [set(g.paths) for g in exact]
    out: list[SimilarGroup] = []
    for sg in similar:
        s = set(sg.paths)
        if len(s) < 2:
            continue
        if any(s <= es for es in exact_sets):
            continue
        out.append(sg)
    return out


def scan_duplicates(
    input_dir: Path,
    *,
    do_exact: bool = True,
    do_similar: bool = True,
    similar_max_hamming: int = 14,
    similar_ahash_max_hamming: int = 18,
    similar_serial_max_gap: int = 0,
    similar_serial_max_hamming: int = 16,
    similar_serial_ahash_max_hamming: int = 16,
    similar_match_mode: str = "phash_led",
    similar_phash_tight: int = 10,
    similar_ahash_loose: int = 28,
    similar_include_screenshots: bool = False,
) -> DuplicateScanResult:
    input_dir = input_dir.resolve()
    paths = _iter_media_paths(input_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = DuplicateScanResult(
        input_dir=str(input_dir),
        generated_at=now,
        similar_max_hamming=similar_max_hamming,
        similar_ahash_max_hamming=similar_ahash_max_hamming,
        similar_serial_max_gap=similar_serial_max_gap,
        similar_serial_max_hamming=similar_serial_max_hamming,
        similar_serial_ahash_max_hamming=similar_serial_ahash_max_hamming,
        similar_match_mode=similar_match_mode,
        similar_phash_tight=similar_phash_tight,
        similar_ahash_loose=similar_ahash_loose,
    )
    if do_exact:
        result.exact_groups = find_exact_duplicates(paths)
    if do_similar:
        image_paths = [p for p in paths if is_image_file(p)]
        excluded = 0
        if not similar_include_screenshots:
            filtered: list[Path] = []
            for p in image_paths:
                if is_screenshot_name_match(p):
                    excluded += 1
                else:
                    filtered.append(p)
            image_paths = filtered
        result.similar_excluded_screenshots = excluded
        sim, skipped = find_similar_groups(
            image_paths,
            max_hamming_phash=similar_max_hamming,
            max_hamming_ahash=similar_ahash_max_hamming,
            serial_max_gap=similar_serial_max_gap,
            serial_max_hamming_phash=similar_serial_max_hamming,
            serial_max_hamming_ahash=similar_serial_ahash_max_hamming,
            match_mode=similar_match_mode,
            phash_tight=similar_phash_tight,
            ahash_loose=similar_ahash_loose,
        )
        result.similar_groups = filter_similar_against_exact(sim, result.exact_groups)
        result.similar_skipped = skipped
    return result


def result_to_json_dict(r: DuplicateScanResult) -> dict:
    return {
        "generated_at": r.generated_at,
        "input_dir": r.input_dir,
        "similar_max_hamming": r.similar_max_hamming,
        "similar_ahash_max_hamming": r.similar_ahash_max_hamming,
        "similar_serial_max_gap": r.similar_serial_max_gap,
        "similar_serial_max_hamming": r.similar_serial_max_hamming,
        "similar_serial_ahash_max_hamming": r.similar_serial_ahash_max_hamming,
        "similar_match_mode": r.similar_match_mode,
        "similar_phash_tight": r.similar_phash_tight,
        "similar_ahash_loose": r.similar_ahash_loose,
        "similar_excluded_screenshots": r.similar_excluded_screenshots,
        "exact_duplicate_groups": [asdict(g) for g in r.exact_groups],
        "similar_groups": [asdict(g) for g in r.similar_groups],
        "similar_skipped": r.similar_skipped,
    }


def write_report(r: DuplicateScanResult, report_path: Path) -> None:
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    data = result_to_json_dict(r)
    report_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
