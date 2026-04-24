"""Tests for ffprobe / QuickTime date string parsing."""

from __future__ import annotations

from datetime import datetime

from photo_organizer.metadata import _parse_ffprobe_datetime_string


def test_parse_iso_naive_no_tz() -> None:
    dt = _parse_ffprobe_datetime_string("2024-03-15T08:30:45")
    assert dt == datetime(2024, 3, 15, 8, 30, 45)


def test_parse_space_separated_with_compact_tz() -> None:
    dt = _parse_ffprobe_datetime_string("2024-03-15 16:00:00+0800")
    assert dt is not None
    assert dt.year == 2024 and dt.month == 3 and dt.day == 15


def test_parse_exif_style_colon_date() -> None:
    dt = _parse_ffprobe_datetime_string("2024:01:02 03:04:05")
    assert dt == datetime(2024, 1, 2, 3, 4, 5)
