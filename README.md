# Photo Organizer

**Local-first** tool for macOS: sort photos/videos by date into month folders, find duplicate and similar images, and review them in a **browser** (nothing is uploaded to the cloud).

**Requirements:** macOS (primary), **Python 3.11+**. Optional: **ffprobe** on `PATH` for better video dates.

---

## Install

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The command is **`photo-organizer`**. For tests / lint: `pip install -e ".[dev]"` then `pytest tests/`.

---

## Web app (recommended)

```bash
photo-organizer serve
```

Opens **http://127.0.0.1:8765/** — pick an **import folder** (path or **Browse…** on macOS), then **Start import**. Files are copied to **`~/Desktop/Organized/YYYY/MM/`**, a duplicate report is written under **`Reports/`**, then **Review** opens in the browser. Unchecked = keep; checked + **Move to Trash** sends files to the macOS Trash.

**Important:** The import folder should be **only** that batch of photos (e.g. `photos`). **Do not** use the project root or `.` as import — the scan would include `.venv/`, `src/`, etc.

**Why it’s not instant:** the app copies and scans on disk; the UI uses a background job (`job_id` + polling) so the browser does not freeze.

---

## macOS: `Photo Organizer.app`

In **`macOS/`**, double-click **`Photo Organizer.app`** to start the server and open the dashboard **without Terminal**.

- **First launch:** macOS may ask you to choose the **project folder** (the one that contains **`pyproject.toml`** and **`.venv`**). Your **photo import folder** is chosen **only in the web UI**, not here. That path is stored in `~/Library/Application Support/PhotoOrganizer/repo_path` — delete that file to pick a different project folder.
- If Gatekeeper blocks the app: **right-click → Open**, or run `xattr -cr "macOS/Photo Organizer.app"` from the repo root.
- If you see **“server did not start”**: read `~/Library/Application Support/PhotoOrganizer/serve.log`. On Apple Silicon, turn off **Open using Rosetta** in **Get Info** on the `.app`, or use the current `Contents/Resources/common.sh` from this repo (it runs `serve` under **`arch -arm64`** when needed).

Optional: **`scripts/Photo Organizer.command`** (`chmod +x`) starts `serve` from Terminal. Regenerate icons: `python scripts/generate_app_icon.py`.

---

## Command line

| Goal | Example |
|------|---------|
| Create output dirs | `photo-organizer init-dirs` |
| Sort by date | `photo-organizer organize -i photos -o Organized` |
| Scan duplicates | `photo-organizer duplicates -i photos` (or `-i Organized` after merging batches) |
| Open review UI | `photo-organizer review` (uses newest `Reports/duplicates_*.json` unless you pass `-r`) |
| Screenshot sweep | `photo-organizer screenshots -i photos` then `photo-organizer review --screenshots -S photos` |

Use **`photo-organizer <command> --help`** for all flags (e.g. `--move`, `--no-similar`, similar-hash tuning on `duplicates`).

---

## Repo layout

| Path | Purpose |
|------|---------|
| `src/photo_organizer/` | Application code |
| `tests/` | pytest test suite |
| `macOS/Photo Organizer.app` | macOS launcher for the web app |
| `assets/` | App icon source files (`AppIcon.icns`, `photo_organizer_icon.png`) |
| `scripts/` | `Photo Organizer.command` (double-click launcher); `generate_app_icon.py` (regenerate icons) |
| `Reports/` | Generated `duplicates_*.json` (gitignored except `.gitkeep`) |
| `Organized/` | CLI default output when you use `-o Organized` (gitignored) |

`~/Desktop/Organized` is the **fixed output** when using **`serve`**, not the repo’s `Organized/` folder.

---

## Troubleshooting

| Issue | What to do |
|-------|----------------|
| **Port 8765 in use** | Stop the other `photo-organizer serve`, or run `photo-organizer serve --port 8766`. |
| **Wrong folder remembered** | `rm -f ~/Library/Application\ Support/PhotoOrganizer/repo_path` and launch the `.app` again. |
| **Duplicate / similar** | Review lists **images only** on the web UI; videos are not shown in those tiles. Similar detection uses perceptual hashes; very different shots may not cluster. |

