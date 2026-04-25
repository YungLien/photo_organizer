"""Review UI helpers."""

from __future__ import annotations

from photo_organizer.review_app import _groups_paths


def test_groups_paths_drops_video_only_exact_groups() -> None:
    data = {
        "similar_groups": [],
        "exact_duplicate_groups": [
            {"paths": ["/tmp/a/x.MOV", "/tmp/a/x_2.MOV"]},
            {"paths": ["/tmp/b/p.jpg", "/tmp/b/p2.jpg"]},
        ],
    }
    sim, ex = _groups_paths(data)
    assert sim == []
    assert len(ex) == 1
    assert all(str(p).lower().endswith(".jpg") for p in ex[0])


def test_groups_paths_keeps_mixed_image_exact_group() -> None:
    """Unusual same-hash image+image still listed if both are images."""
    data = {
        "similar_groups": [],
        "exact_duplicate_groups": [
            {"paths": ["/z/a.JPEG", "/z/b.JPEG"]},
        ],
    }
    _, ex = _groups_paths(data)
    assert len(ex) == 1
    assert len(ex[0]) == 2
