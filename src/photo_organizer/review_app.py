"""Local web UI to review duplicate / similar groups from a duplicates JSON report."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections import Counter
from typing import Literal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, field_validator

from send2trash import send2trash

from photo_organizer.metadata import is_image_file

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

_STATIC_DIR = Path(__file__).resolve().parent / "review_static"


def _path_key_str(p: str | Path) -> str:
    """Resolved path string with Unicode NFC (matches Finder / JSON quirks on macOS)."""
    from unicodedata import normalize

    try:
        return normalize("NFC", str(Path(p).expanduser().resolve()))
    except OSError:
        return ""


def _send_one_to_trash(path: Path) -> Literal["send2trash", "finder"]:
    """send2trash first; on macOS fall back to Finder so files reliably land in Trash."""
    posix = str(path.resolve())
    try:
        send2trash(posix)
        return "send2trash"
    except Exception as first:
        if sys.platform != "darwin":
            raise first
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    "on run argv",
                    "-e",
                    'tell application "Finder"',
                    "-e",
                    "delete (POSIX file (item 1 of argv))",
                    "-e",
                    "end tell",
                    "-e",
                    "end run",
                    "--",
                    posix,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return "finder"
        except Exception as second:
            msg = getattr(second, "stderr", None) or getattr(second, "stdout", None) or str(second)
            raise OSError(f"Trash failed (send2trash: {first!r}; Finder: {msg})") from second


class SelectedPathsBody(BaseModel):
    """POST body for save-manifest / move-to-trash."""

    paths: list[str]

    @field_validator("paths", mode="before")
    @classmethod
    def _drop_invalid_paths(cls, v: object) -> object:
        if not isinstance(v, list):
            return v
        return [x for x in v if isinstance(x, str) and x.strip()]


def _move_paths_to_trash(
    paths: list[str], allowed: set[str]
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Move files to the system Trash. Returns (moved_paths, errors, audit_rows for JSONL)."""
    inode_to_key: dict[tuple[int, int], str] = {}
    for s in allowed:
        try:
            st = Path(s).stat()
            inode_to_key[(st.st_dev, st.st_ino)] = s
        except OSError:
            continue

    moved: list[str] = []
    errors: list[str] = []
    audit: list[dict[str, str]] = []
    for p in paths:
        key = _path_key_str(p)
        rp = Path(p).expanduser()
        try:
            rp = rp.resolve()
        except OSError:
            msg = f"bad path: {p}"
            errors.append(msg)
            audit.append({"path": p, "result": "error", "detail": msg})
            continue
        if not rp.is_file():
            msg = f"not a file: {p}"
            errors.append(msg)
            audit.append({"path": p, "result": "error", "detail": msg})
            continue
        if key not in allowed:
            try:
                st = rp.stat()
                key = inode_to_key.get((st.st_dev, st.st_ino), "")
            except OSError:
                key = ""
        if not key or key not in allowed:
            msg = f"not in this review session (refresh the page if it is stale): {p}"
            errors.append(msg)
            audit.append({"path": p, "result": "error", "detail": msg})
            continue
        try:
            method = _send_one_to_trash(rp)
            moved.append(key)
            audit.append(
                {
                    "path": key,
                    "result": "moved_to_system_trash",
                    "method": method,
                    "platform": sys.platform,
                }
            )
        except OSError as e:
            msg = f"{p}: {e}"
            errors.append(msg)
            audit.append({"path": p, "result": "error", "detail": msg})
        except Exception as e:
            msg = f"{p}: {e}"
            errors.append(msg)
            audit.append({"path": p, "result": "error", "detail": msg})
    return moved, errors, audit


def _append_trash_audit_jsonl(log_path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a", encoding="utf-8") as f:
        for row in rows:
            line = json.dumps({"ts": ts, **row}, ensure_ascii=False)
            f.write(line + "\n")


def _review_groups_images_only(groups: list[list[str]]) -> list[list[str]]:
    """
    Review UI is photo-focused: keep only image paths in each cluster; drop groups with <2 images.
    (Similar scan is already image-only; exact SHA groups often include .mov — user skips those here.)
    """
    out: list[list[str]] = []
    for paths in groups:
        imgs = [p for p in paths if is_image_file(Path(p))]
        if len(imgs) >= 2:
            out.append(sorted(imgs, key=lambda p: p.lower()))
    return out


def _allowed_from_groups(similar: list[list[str]], exact: list[list[str]]) -> set[str]:
    allowed: set[str] = set()
    for paths in similar + exact:
        for p in paths:
            k = _path_key_str(p)
            if k:
                allowed.add(k)
    return allowed


def _groups_paths(data: dict) -> tuple[list[list[str]], list[list[str]]]:
    similar = [list(g.get("paths", [])) for g in data.get("similar_groups", [])]
    exact = [list(g.get("paths", [])) for g in data.get("exact_duplicate_groups", [])]
    return _review_groups_images_only(similar), _review_groups_images_only(exact)


def _display_names_for_paths(paths: list[str]) -> list[str]:
    """Basename, or parent/basename when the same name appears more than once in the group."""
    names = [Path(p).name for p in paths]
    counts = Counter(names)
    out: list[str] = []
    for p in paths:
        fp = Path(p)
        n = fp.name
        if counts[n] > 1:
            out.append(f"{fp.parent.name}/{n}")
        else:
            out.append(n)
    return out


def _groups_existing_files(groups: list[list[str]]) -> list[list[str]]:
    """Drop missing paths (e.g. after quarantine move); omit empty groups."""
    out: list[list[str]] = []
    for paths in groups:
        alive: list[str] = []
        for p in paths:
            try:
                rp = Path(p).resolve()
            except OSError:
                continue
            if rp.is_file():
                alive.append(_path_key_str(rp))
        if alive:
            out.append(alive)
    return out


def latest_duplicates_json(reports_dir: Path) -> Path | None:
    reports_dir = reports_dir.resolve()
    if not reports_dir.is_dir():
        return None
    files = list(reports_dir.glob("duplicates_*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


@dataclass
class ReviewContext:
    """Mutable duplicate-report state for the review API (supports reload without restart)."""

    report_path: Path | None = None
    allowed: set[str] = field(default_factory=set)
    similar_paths: list[list[str]] = field(default_factory=list)
    exact_paths: list[list[str]] = field(default_factory=list)
    # Last successful /api/pipeline body (for Review "finish classify" without re-typing paths).
    last_input_dir: str | None = None
    last_organized_root: str = "Organized"
    last_copy_files: bool = True
    last_scan_import_folder_for_duplicates: bool = True
    last_run_organize: bool = False
    last_include_similar_duplicates: bool = False
    # When set (unified serve app), each move-to-trash batch appends JSON lines for auditing.
    trash_audit_path: Path | None = None

    def record_last_pipeline(
        self,
        *,
        input_dir: str,
        organized_root: str,
        copy_files: bool,
        scan_import_folder_for_duplicates: bool,
        run_organize: bool,
        include_similar_duplicates: bool = True,
    ) -> None:
        self.last_input_dir = input_dir.strip()
        self.last_organized_root = (organized_root or "Organized").strip() or "Organized"
        self.last_copy_files = copy_files
        self.last_scan_import_folder_for_duplicates = scan_import_folder_for_duplicates
        self.last_run_organize = run_organize
        self.last_include_similar_duplicates = include_similar_duplicates

    def load_report(self, path: Path | None) -> None:
        """Load JSON report from disk, or clear state if path is None or not a file."""
        if path is None:
            self.report_path = None
            self.allowed = set()
            self.similar_paths = []
            self.exact_paths = []
            return
        path = path.resolve()
        if not path.is_file():
            self.report_path = None
            self.allowed = set()
            self.similar_paths = []
            self.exact_paths = []
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.report_path = path
        self.similar_paths, self.exact_paths = _groups_paths(raw)
        self.allowed = _allowed_from_groups(self.similar_paths, self.exact_paths)


def mount_review_routes(
    app: FastAPI,
    ctx: ReviewContext,
    *,
    path_prefix: str = "",
) -> None:
    """
    Register duplicate-review HTTP routes on ``app``.
    ``path_prefix`` is e.g. '' (apis at /api/...) or '/review' (apis at /review/api/...).
    """
    prefix = path_prefix.rstrip("/")
    router = APIRouter(prefix=prefix) if prefix else APIRouter()

    @router.get("/api/meta")
    def api_meta() -> dict:
        def pipeline_hints() -> dict:
            return {
                "last_input_dir": ctx.last_input_dir or "",
                "last_organized_root": ctx.last_organized_root,
                "last_copy_files": ctx.last_copy_files,
                "last_scan_import_folder_for_duplicates": ctx.last_scan_import_folder_for_duplicates,
                "last_run_organize": ctx.last_run_organize,
                "last_include_similar_duplicates": ctx.last_include_similar_duplicates,
            }

        if ctx.report_path is None or not ctx.report_path.is_file():
            return {
                "report_path": "",
                "similar_groups": [],
                "exact_groups": [],
                **pipeline_hints(),
            }

        def summarize(groups: list[list[str]]) -> list[dict]:
            live = _groups_existing_files(groups)
            out = []
            for paths in live:
                labels = _display_names_for_paths(paths)
                items = []
                for p, display_name in zip(paths, labels, strict=True):
                    fp = Path(p)
                    items.append(
                        {
                            "path": p,
                            "name": fp.name,
                            "display_name": display_name,
                            "is_image": is_image_file(fp),
                        }
                    )
                out.append({"items": items})
            return out

        return {
            "report_path": str(ctx.report_path),
            "similar_groups": summarize(ctx.similar_paths),
            "exact_groups": summarize(ctx.exact_paths),
            **pipeline_hints(),
        }

    @router.get("/api/thumb")
    def api_thumb(kind: str, gid: int, idx: int, max_dim: int = 400) -> Response:
        max_dim = max(64, min(int(max_dim), 3200))
        if kind not in ("similar", "exact"):
            raise HTTPException(400, "kind must be similar or exact")
        raw = ctx.similar_paths if kind == "similar" else ctx.exact_paths
        groups = _groups_existing_files(raw)
        if gid < 0 or gid >= len(groups) or idx < 0 or idx >= len(groups[gid]):
            raise HTTPException(404, "out of range")
        path = Path(groups[gid][idx]).resolve()
        sp = _path_key_str(path)
        if sp not in ctx.allowed:
            raise HTTPException(403)
        if not path.is_file():
            raise HTTPException(404, "file missing")
        if not is_image_file(path):
            raise HTTPException(415, "not an image")
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im = im.convert("RGB")
                im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=88)
                return Response(content=buf.getvalue(), media_type="image/jpeg")
        except OSError as e:
            raise HTTPException(500, str(e)) from e

    @router.post("/api/save-manifest")
    def api_save_manifest(body: SelectedPathsBody) -> dict:
        if ctx.report_path is None:
            raise HTTPException(400, "no report loaded")
        rd = ctx.report_path.parent.resolve()
        rd.mkdir(parents=True, exist_ok=True)
        for p in body.paths:
            rp = _path_key_str(p)
            if not rp or rp not in ctx.allowed:
                raise HTTPException(400, f"path not in report: {p}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = rd / f"review_manifest_{stamp}.json"
        payload = {
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_report": str(ctx.report_path),
            "paths": [_path_key_str(p) for p in body.paths],
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"saved": str(out), "count": len(body.paths)}

    @router.post("/api/move-to-trash")
    def api_move_to_trash(body: SelectedPathsBody) -> dict:
        moved, errors, audit_rows = _move_paths_to_trash(body.paths, ctx.allowed)
        audit_log = ""
        if ctx.trash_audit_path is not None:
            audit_log = str(ctx.trash_audit_path.resolve())
            if audit_rows:
                try:
                    _append_trash_audit_jsonl(ctx.trash_audit_path, audit_rows)
                except OSError:
                    pass
        payload: dict[str, object] = {"moved": moved, "errors": errors, "audit_log": audit_log}
        if sys.platform == "darwin":
            payload["trash_locations_hint"] = (
                "macOS: Finder → Trash, or folder ~/.Trash (per volume also under /.Trashes)."
            )
        return payload

    app.include_router(router)


def create_review_app(report_path: Path, *, quarantine_root: Path | None = None) -> FastAPI:
    report_path = report_path.resolve()
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    _ = quarantine_root  # deprecated; kept for call-site compatibility
    ctx = ReviewContext()
    ctx.load_report(report_path)

    app = FastAPI(title="Photo Organizer Review", version="0.1.0")
    mount_review_routes(app, ctx, path_prefix="")

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR), html=False), name="static")

    @app.get("/")
    def index_page() -> FileResponse:
        index = _STATIC_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(500, "review_static missing")
        return FileResponse(index)

    return app


def run_review_server(
    report_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    quarantine_root: Path | None = None,
) -> None:
    import uvicorn

    app = create_review_app(report_path, quarantine_root=quarantine_root)
    uvicorn.run(app, host=host, port=port, log_level="info")


def create_screenshot_review_app(scan_dir: Path, *, quarantine_root: Path | None = None) -> FastAPI:
    from photo_organizer.screenshots import scan_screenshots_folder

    scan_dir = scan_dir.resolve()
    if not scan_dir.is_dir():
        raise FileNotFoundError(scan_dir)
    hits = scan_screenshots_folder(scan_dir)
    allowed = {h.path for h in hits}
    rows = [{"path": h.path, "name": Path(h.path).name, "reason": h.reason} for h in hits]
    _ = quarantine_root

    app = FastAPI(title="Photo Organizer — Screenshots", version="0.1.0")

    @app.get("/api/meta")
    def api_meta() -> dict:
        return {
            "review_mode": "screenshots",
            "scan_dir": str(scan_dir),
            "count": len(rows),
            "items": rows,
        }

    @app.get("/api/thumb-shot")
    def api_thumb_shot(idx: int, max_dim: int = 400) -> Response:
        if idx < 0 or idx >= len(rows):
            raise HTTPException(404, "out of range")
        path = Path(rows[idx]["path"]).resolve()
        sp = str(path)
        if sp not in allowed:
            raise HTTPException(403)
        if not path.is_file():
            raise HTTPException(404, "file missing")
        if not is_image_file(path):
            raise HTTPException(415)
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im = im.convert("RGB")
                im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=88)
                return Response(content=buf.getvalue(), media_type="image/jpeg")
        except OSError as e:
            raise HTTPException(500, str(e)) from e

    @app.post("/api/save-manifest")
    def api_save_manifest(body: SelectedPathsBody) -> dict:
        rd = (Path.cwd() / "Reports").resolve()
        rd.mkdir(parents=True, exist_ok=True)
        for p in body.paths:
            rp = str(Path(p).resolve())
            if rp not in allowed:
                raise HTTPException(400, f"path not in scan: {p}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = rd / f"screenshot_review_manifest_{stamp}.json"
        payload = {
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scan_dir": str(scan_dir),
            "paths": [str(Path(p).resolve()) for p in body.paths],
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"saved": str(out), "count": len(body.paths)}

    @app.post("/api/move-to-trash")
    def api_move_to_trash(body: SelectedPathsBody) -> dict:
        moved, errors, _audit = _move_paths_to_trash(body.paths, allowed)
        return {"moved": moved, "errors": errors}

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR), html=False), name="static")

    @app.get("/")
    def index_page() -> FileResponse:
        p = _STATIC_DIR / "screenshots.html"
        if not p.is_file():
            raise HTTPException(500, "screenshots.html missing")
        return FileResponse(p)

    return app


def run_screenshot_review_server(
    scan_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    quarantine_root: Path | None = None,
) -> None:
    import uvicorn

    app = create_screenshot_review_app(scan_dir, quarantine_root=quarantine_root)
    uvicorn.run(app, host=host, port=port, log_level="info")
