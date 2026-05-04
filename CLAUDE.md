# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # includes pytest and ruff
```

Optional: install `ffprobe` (via `brew install ffmpeg`) for better video capture-date extraction.

## Common commands

```bash
# Run all tests
pytest tests/

# Run a single test
pytest tests/test_duplicates.py::test_filter_similar_drops_subset_of_exact

# Lint
ruff check src/ tests/

# Start the web app (dashboard at http://127.0.0.1:8765/)
photo-organizer serve

# Organize a photo folder (copy into ~/Desktop/Organized/YYYY/MM/)
photo-organizer organize -i photos

# Scan for duplicates and write a JSON report
photo-organizer duplicates -i photos

# Open the review UI against the latest report
photo-organizer review
```

## Architecture

The app has two modes that share the same FastAPI backend logic:

**CLI mode** (`cli.py` → individual modules): each subcommand (`organize`, `duplicates`, `review`, `screenshots`) runs independently and exits.

**Web / serve mode** (`serve_app.py`): a single long-running FastAPI server that owns the full pipeline. The dashboard (`/`) lets users pick an import folder, then `POST /api/pipeline` starts a background thread (job pattern: POST returns a `job_id`, frontend polls `GET /api/pipeline/job/{id}`). On completion the server loads the resulting JSON report into `ReviewContext` and the review UI at `/review/` becomes live.

### Key data flow

1. `metadata.py` — extracts capture datetime from images (EXIF via Pillow), videos (ffprobe JSON), and macOS Photos xattrs (`com.apple.assetsd.*` via `xattr` + `plutil`). Priority order: EXIF → assetsd xattr → ffprobe QuickTime atom → ffprobe stream/format `creation_time`.
2. `organize.py` — iterates the import folder, calls `capture_datetime()`, copies/moves each file to `organized_root/YYYY/MM/filename` (or `UnknownDate/`). Flattens subdirectory structure; renames collisions with `_2`, `_3`, etc.
3. `duplicates.py` — two-pass scan: SHA-256 exact grouping, then perceptual hash (pHash + aHash via `imagehash`) with union-find clustering. The default `phash_led` match mode is: `(pHash ≤ 14 AND aHash ≤ 18) OR (pHash ≤ 10 AND aHash ≤ 28)`. Similar groups whose members are fully covered by an exact group are filtered out before the review UI sees them. Hard links are deduplicated by `(st_dev, st_ino)`.
4. `review_app.py` — `ReviewContext` holds the loaded report in memory. `mount_review_routes()` registers review API routes onto any FastAPI app (`/api/meta`, `/api/thumb`, `/api/save-manifest`, `/api/move-to-trash`). The trash operation tries `send2trash` first, falls back to AppleScript Finder on macOS. Every trash action is appended to `Reports/trash_audit.jsonl`. The review UI only surfaces image files from duplicate groups (video-only groups are dropped).
5. `serve_app.py` — creates one FastAPI app, mounts review routes at `/review` via `mount_review_routes()`, and adds the pipeline/job/pick-folder endpoints. The `ReviewContext` is created once at startup and reloaded after each successful pipeline run.

### Frontend

Static files live in `src/photo_organizer/review_static/` and are shipped as package data. Three pages: `dashboard.html` (import pipeline), `index.html` (duplicate review), `screenshots.html` (screenshot review). Each page has a paired `.js` file; `review.css` and `dashboard.css` are shared.

### macOS app bundle

`macOS/Photo Organizer.app` is an AppleScript-based launcher that locates the project's `.venv`, runs `photo-organizer serve`, and opens the browser. It stores the user-chosen project root in `~/Library/Application Support/PhotoOrganizer/repo_path`.

## Important constraints

- **Never use the project root (`.`) as the import folder.** `serve_app.py` explicitly rejects this to prevent scanning `.venv/`, `src/`, and `Organized/` alongside the actual photos.
- The `serve` command always outputs to `~/Desktop/Organized/` (not the repo's `Organized/` folder).
- `Reports/` is gitignored (except `.gitkeep`). JSON report filenames are timestamped: `duplicates_YYYYMMDD_HHMMSS.json`.
- `ruff` is the only linter; line length is 100, target is Python 3.11.
