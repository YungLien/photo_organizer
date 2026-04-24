# AI Photo Organizer (Python)

## Overview

This project is a **local-first** CLI tool for cleaning up exported photo libraries (e.g. from Apple Photos on macOS).

The program:

- Sorts media into **`Organized/YYYY/MM/`** using capture-time metadata (with fallbacks when EXIF is missing).
- Finds **byte-identical** files (SHA-256) and **visually similar** images (perceptual hashing + clustering).
- Writes JSON reports under **`Reports/`**.
- Serves a **browser-based review UI** (FastAPI) so you can mark files to keep or move checked items to the **macOS Trash** (recoverable in Finder).

Everything runs on your machine; photos are not uploaded to a cloud service.

### Why “Start import” is not instant (and how the UI handles it)

Unlike a typical **upload** site—which only receives bytes in the background—this app **immediately copies** files into **`~/Desktop/Organized`** and **scans the folder on disk** (SHA-256 + optional similar-image hashing). That work uses **your CPU and disk**, so it cannot finish in zero time.

The dashboard does **not** block the browser on that work: `POST /api/pipeline` returns at once with a **`job_id`**, and the UI polls **`GET /api/pipeline/job/{job_id}`** for phase messages (e.g. organizing, duplicate scan, writing report) until the job finishes, then opens **`/review/`**.

From the **web dashboard**, duplicate detection **includes visually similar photos** (perceptual hash, exposure-tolerant `phash_led` mode). On **very large** trees you can run **`photo-organizer duplicates --no-similar`** (or tune thresholds) from the CLI instead of the default pipeline scan.

## Portfolio / GitHub

- **License:** [MIT](LICENSE) — safe to showcase on GitHub or a portfolio site.
- **Narrative:** local-first, privacy-respecting workflow; **FastAPI** API + static review UI; **background pipeline jobs** with pollable status (no fake “upload” latency—honest UX for heavy local work).
- **Outputs** (`Organized/`, `Reports/`) are **gitignored** by default; ship the repo with empty folders via `.gitkeep` only.

## Design Approach

The solution splits **CLI orchestration**, **domain logic** (organize / duplicates / screenshots), and **HTTP review** into separate modules. The review server only serves paths that appear in the loaded duplicates report (allowlist) and re-checks the filesystem on each meta request so the UI drops files that were already moved.

### Core Components

#### `cli.py`

- Argument parsing and dispatch for all subcommands (`init-dirs`, `organize`, `duplicates`, `review`, `serve`, `screenshots`).
- Chooses the latest `Reports/duplicates_*.json` for `review` when `--report` is omitted.

#### `serve_app.py`

- **Unified local app:** `GET /` dashboard (pick import folder + **Start**), `GET /health`, `POST /api/pipeline` **queues** a background job and returns `{ "accepted": true, "job_id": "…" }` after quick validation. Poll **`GET /api/pipeline/job/{job_id}`** for `{ status, message, result }`; when `status` is `complete`, `result` matches the former synchronous JSON. **organize** copies into **`~/Desktop/Organized/YYYY/MM/`**; duplicate scan runs on the import folder with **`include_similar_duplicates`: true** by default.
- **`/review/`** duplicate review UI; `POST /api/move-to-trash` sends checked files to Trash via **Send2Trash** (with Finder fallback on macOS). **`Reports/trash_audit.jsonl`** records each path, success/error, and method for auditing.

#### `organize.py`

- Walks an input tree, resolves a best-effort capture datetime per file, and **copies** (default) or **moves** into month folders under the output root.
- Counts unknown-date files routed to **`Organized/UnknownDate/`**.

#### `metadata.py`

- **Images:** EXIF / HEIF-friendly openers; extra macOS metadata hints where useful.
- **Videos:** on macOS, **xattr** from Photos / assetsd (same as stills) when present; otherwise **ffprobe** JSON reads `com.apple.quicktime.creationdate`, then video-stream `creation_time`, then other streams — **not** only `format.creation_time` (that field is often the re-mux / export time and would sort everything into “this month”).
- Helpers such as `is_image_file` / `is_media_file` shared by organize and duplicates.

#### `duplicates.py`

- **Exact groups:** SHA-256 over file contents.
- **Similar groups:** pHash + aHash on images **normalized to 512px long edge**, Hamming thresholds, **union–find** clustering. Default **`phash_led`**: match if `(pHash and aHash within global limits)` **or** `(very tight pHash + looser aHash)` so same composition with different exposure is not missed. Optional **serial filename** neighbor rule (e.g. `IMG_1234` / `IMG_1235`) is **off by default**. **Similar clusters fully contained in an exact duplicate cluster are removed** so Review does not list the same files twice.
- **Input walk:** Media files are collected recursively; **hard links** to the same inode are **deduplicated** so one physical file does not appear as two tiles.
- Files whose **filename** looks like a screenshot are excluded from the similar pass by default (tall PNG aspect ratio alone is **not** excluded — that was catching normal phone exports). See CLI `--similar-include-screenshots`.
- Writes **`Reports/duplicates_<timestamp>.json`**.

#### `screenshots.py`

- Heuristic detection (filename patterns, PNG aspect, etc.) and JSON report under **`Reports/`**.
- Used by `screenshots` CLI and **`review --screenshots`**.

#### `review_app.py` + `review_static/`

- **`ReviewContext`** + **`mount_review_routes`:** duplicate-report state can be **reloaded** after a new scan (used by `serve`).
- **FastAPI** review app: `/api/meta`, `/api/thumb`, `/api/save-manifest`, `/api/move-to-trash` (standalone `review`); under `serve`, mounted at `/review/api/...`.
- Static assets: duplicates review, screenshots review, and **`dashboard.html`** (launcher UI).

#### `filecopy.py`

- macOS-oriented copy helper (e.g. preserving Finder “Date Created” where applicable) used by organize when copying.

#### `__main__.py` / `__init__.py`

- Package entry and version string for the `photo-organizer` console script.

## Behavior & Rules (v1)

- **Organize:** copy-first; `--move` performs a true move. `--dry-run` prints the plan only.
- **Duplicates:** configurable pHash/aHash limits, `--similar-match phash_led|and|or`, `--similar-phash-tight` / `--similar-ahash-loose`, `--serial-max-gap` and related serial thresholds.
- **Review (web):** unchecked = keep; checked = **Move to Trash** (Finder Trash via **Send2Trash**). **Done** returns to the dashboard; if the last run had not organized yet, it runs **organize-only** first (otherwise skips to avoid copying twice). **`POST /api/save-manifest`** remains for scripting. Trash actions are also appended to **`Reports/trash_audit.jsonl`** (path, result, method) for your records—the in-app copy stays minimal on purpose.
- **CLI** `organize` / `review` still support custom `-o` paths; the **serve** dashboard is fixed to **`~/Desktop/Organized`** for output.

## Repository Layout

| Path | Role |
|------|------|
| `src/photo_organizer/` | Application package |
| `assets/` | Optional branding (e.g. `photo_organizer_icon.png` for the launcher shortcut) |
| *(any folder you create)* | **Import / scan input** — e.g. `photos`, `photos1`, `~/Desktop/Exports`. The CLI does **not** require the name `photos`; pass it with `-i` / `--input`. |
| `Organized/` (CLI `-o`, or **`~/Desktop/Organized`** from **serve**) | Output of `organize` (`YYYY/MM/`, `UnknownDate/`) |
| `Reports/` | `duplicates_*.json`, `screenshots_*.json`, optional manifests |

The repo may ship folders like **`photos/`** or **`photos1/`** only as examples; your real library can live anywhere on disk—use absolute or relative paths on the command line.

## Requirements

- **macOS** (primary target).
- **Python 3.11+**
- **ffprobe** on `PATH` if you want richer video timestamps (optional).

### Stack

- **Pillow**, **pillow-heif**, **ImageHash**, **FastAPI**, **uvicorn**, **send2trash**

## How to Run

From the repo root, install in editable mode:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

The CLI entry point is **`photo-organizer`**.

### Local app (dashboard + review)

From the **project root** (where `Reports/` is written; sorted copies go to **`~/Desktop/Organized`**):

```bash
photo-organizer serve
```

Opens the **dashboard**: choose the **import folder** only (path or **Browse…** on macOS), then **Start**. That copies into **`~/Desktop/Organized/YYYY/MM/`**, scans duplicates on the import folder, then opens **Review**. Use `--project-root` if needed; `--no-browser` skips auto-open.

**Important:** The import folder must contain **only** incoming photos/videos—not the app project root or `.` (otherwise the scan walks `assets/`, `.venv/`, etc.).

**Browse…** uses `osascript` on **macOS**; elsewhere, type a path.

**Fresh import:** Old copies under **`~/Desktop/Organized`** can still match new imports in duplicate review; clear or rename that folder if you want a clean slate.

**Desktop shortcut (macOS):** use [`scripts/Photo Organizer.command`](scripts/Photo%20Organizer.command) — make it executable (`chmod +x`), then double-click or drag an alias to the Desktop. If Gatekeeper blocks the first run, use **right-click → Open**.

**Folder picker (macOS):** [`scripts/Photo Organizer Picker.command`](scripts/Photo%20Organizer%20Picker.command) starts the server if needed, opens Finder to pick the import folder, runs the same pipeline (output **`~/Desktop/Organized`**), then opens **Review**.

**App icon (optional):** the repo includes [`assets/photo_organizer_icon.png`](assets/photo_organizer_icon.png) (mint rounded square, moon + stars — original artwork inspired by a flat “clean tool” look). To assign it to a `.command` file: Finder → **Get Info** on the file → click the icon in the top-left → paste from clipboard (open the PNG, copy all, then paste onto the icon). Regenerate with `python scripts/generate_app_icon.py` if you change the script.

**Import folder:** Every command that reads files uses **your** path. Replace `photos` below with whatever directory you created (e.g. **`photos1`**, `Imports`, or `/Users/you/Pictures/export`).

Typical flow:

```bash
photo-organizer init-dirs
photo-organizer organize -i photos -o Organized
photo-organizer duplicates -i Organized
photo-organizer review
```

**Merging several phone dumps into one library (recommended):**  
If photos arrive in different folders (e.g. `photos`, `photos1`) because you imported in batches, point **every** `organize` run at the **same** output root. Files land under `Organized/YYYY/MM/` by capture date; same month + same filename automatically gets `_2`, `_3`, … so nothing is silently overwritten. Then run **one** duplicate scan on the merged tree:

```bash
photo-organizer organize -i photos -o Organized
photo-organizer organize -i photos1 -o Organized
photo-organizer duplicates -i Organized
photo-organizer review
```

You do **not** need two `Organized_*` trees unless you want to keep libraries physically separate on purpose.

`review` with no `-r` loads the **newest** `Reports/duplicates_*.json` by modification time—after scanning `Organized`, that should be the new report. If an older report is picked up, pin the file explicitly:

```bash
photo-organizer review -r Reports/duplicates_YYYYMMDD_HHMMSS.json
```

To **only** find duplicates inside a flat folder (skip `organize`), scan it directly (paths are still arbitrary):

```bash
photo-organizer duplicates -i photos1
photo-organizer review
```

**Avoid** using `Organized` as the `-i` input for another `organize` pass unless you mean to re-process that tree (it would recurse and duplicate files into deeper month folders). Always use your **raw import** folders as `-i`.

Open the URL printed in the terminal (default **`http://127.0.0.1:8765`**). The `--quarantine` flag on **`review`** is legacy and ignored for the Trash-based web UI.

Optional screenshot sweep (again, any input folder name):

```bash
photo-organizer screenshots -i photos1
photo-organizer review --screenshots -S photos1
```

Use `photo-organizer <command> --help` for full flags.

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Assumptions

- Paths inside a duplicates report are absolute or resolvable from the machine where `review` runs.
- Review security model is **local trust**: the server binds to loopback by default; the allowlist is derived from the report JSON.
- Default **cwd** matters for relative `Reports/` and `--reports-dir`.

## Future Improvements

- Signed **.app** bundle or pywebview window (beyond `.command` + browser).
- **pytest** coverage for `duplicates`, `organize`, and review API contracts.
- Optional vision-based tagging or quality hints after the duplicate workflow feels solid.
- Richer backup / sync stories (still local-first where possible).

## License

TBD
