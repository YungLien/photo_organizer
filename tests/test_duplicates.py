"""Tests for duplicate grouping helpers."""

from __future__ import annotations

from pathlib import Path

from photo_organizer.duplicates import (
    ExactDuplicateGroup,
    SimilarGroup,
    _pair_similar_global,
    _pair_similar_serial,
    filter_similar_against_exact,
)


def test_filter_similar_drops_subset_of_exact() -> None:
    exact = [
        ExactDuplicateGroup(
            sha256="a" * 64,
            byte_size=10,
            paths=["/lib/a.jpg", "/lib/b.jpg"],
        )
    ]
    similar = [
        SimilarGroup(paths=["/lib/a.jpg", "/lib/b.jpg"], phash_hex="abc"),
        SimilarGroup(paths=["/lib/x.jpg", "/lib/y.jpg"], phash_hex="def"),
    ]
    out = filter_similar_against_exact(similar, exact)
    assert len(out) == 1
    assert out[0].paths == ["/lib/x.jpg", "/lib/y.jpg"]


def test_filter_similar_drops_proper_subset() -> None:
    """Similar pair {A,B} subset of exact {A,B,C} — already covered by exact cluster."""
    exact = [
        ExactDuplicateGroup(
            sha256="x" * 64,
            byte_size=5,
            paths=["/p/a", "/p/b", "/p/c"],
        )
    ]
    similar = [SimilarGroup(paths=["/p/a", "/p/b"], phash_hex="00")]
    out = filter_similar_against_exact(similar, exact)
    assert out == []


def test_pair_similar_global_phash_led() -> None:
    """Second branch: tight pHash allows high aHash (exposure mismatch)."""
    assert _pair_similar_global(
        9,
        26,
        max_p=14,
        max_a=18,
        mode="phash_led",
        phash_tight=10,
        ahash_loose=28,
    )
    assert not _pair_similar_global(
        11,
        26,
        max_p=14,
        max_a=18,
        mode="phash_led",
        phash_tight=10,
        ahash_loose=28,
    )
    assert _pair_similar_global(
        14,
        18,
        max_p=14,
        max_a=18,
        mode="phash_led",
        phash_tight=10,
        ahash_loose=28,
    )


def test_pair_similar_serial_requires_both_hashes() -> None:
    """Serial neighbor rule must not use OR with huge limits (that merged unrelated IMG_n, IMG_n+1)."""
    assert _pair_similar_serial(10, 10, max_p=16, max_a=16) is True
    assert _pair_similar_serial(20, 10, max_p=16, max_a=16) is False
    assert _pair_similar_serial(10, 20, max_p=16, max_a=16) is False
    assert _pair_similar_serial(30, 30, max_p=16, max_a=16) is False


def test_filter_similar_keeps_partial_overlap() -> None:
    """Similar {A,D} is not a subset of exact {A,B} — keep."""
    exact = [
        ExactDuplicateGroup(sha256="y" * 64, byte_size=1, paths=["/q/a", "/q/b"]),
    ]
    similar = [SimilarGroup(paths=["/q/a", "/q/d"], phash_hex="11")]
    out = filter_similar_against_exact(similar, exact)
    assert len(out) == 1


def test_iter_media_paths_dedupes_hardlinks(tmp_path: Path) -> None:
    from photo_organizer.duplicates import _iter_media_paths

    f = tmp_path / "one.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # minimal junk; may not be valid JPEG
    # If Pillow fails on hash later, we only test path listing here
    h = tmp_path / "link.jpg"
    try:
        h.hardlink_to(f)
    except OSError:
        import pytest

        pytest.skip("hard links not supported")
    paths = _iter_media_paths(tmp_path)
    assert len(paths) == 1
