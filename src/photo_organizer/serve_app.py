"""Unified local app: dashboard + duplicate review on one server."""

from __future__ import annotations

import asyncio
import platform
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from photo_organizer.duplicates import scan_duplicates, write_report
from photo_organizer.organize import organize
from photo_organizer.review_app import (
    ReviewContext,
    mount_review_routes,
)

_STATIC_DIR = Path(__file__).resolve().parent / "review_static"


class PipelineBody(BaseModel):
    """Request body for POST /api/pipeline — controls which pipeline stages to run and where."""

    input_dir: str = Field(..., description="Folder of photos to process (absolute or relative to project root)")
    organized_root: str = Field(
        default="~/Desktop/Organized",
        description="Output root for organize (default: ~/Desktop/Organized on macOS)",
    )
    run_organize: bool = True
    run_duplicates: bool = True
    copy_files: bool = Field(default=True, description="If true, organize copies; if false, moves")
    scan_import_folder_for_duplicates: bool = Field(
        default=True,
        description="If true, duplicate/similar scan uses only the import folder (faster; ignores older files in Organized).",
    )
    include_similar_duplicates: bool = Field(
        default=True,
        description="If true, run perceptual-hash similar scan (slower on huge folders). If false, only byte-identical duplicates.",
    )

    @field_validator("input_dir", "organized_root", mode="before")
    @classmethod
    def strip_str(cls, v: object) -> object:
        """Strip leading/trailing whitespace from path fields before validation."""
        if isinstance(v, str):
            return v.strip()
        return v


def _resolve_path(project_root: Path, p: str) -> Path:
    """Resolve p to an absolute Path, treating relative paths as relative to project_root."""
    raw = Path(p).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (project_root / raw).resolve()


def _path_for_pipeline_form(project_root: Path, chosen: Path) -> str:
    """Prefer a path relative to project_root when the folder is inside the project."""
    chosen = chosen.expanduser().resolve()
    pr = project_root.resolve()
    try:
        return str(chosen.relative_to(pr))
    except ValueError:
        return str(chosen)


def _prewarm_osascript() -> None:
    """Run a no-op AppleScript to pre-load the runtime, eliminating cold-start delay on first Browse click."""
    if platform.system() != "Darwin":
        return
    try:
        subprocess.run(["osascript", "-e", "return"], capture_output=True, timeout=10)
    except Exception:
        pass


def _pick_folder_macos_sync(prompt: str) -> str:
    """
    Block until the user picks a folder or cancels (Finder dialog via AppleScript).
    Returns POSIX path with trailing slash stripped, or "" if cancelled / dialog error.
    """
    script = f"""try
  set t to choose folder with prompt "{prompt}"
  return POSIX path of t
on error number -128
  return ""
end try"""
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip().rstrip("/")


class PickFolderBody(BaseModel):
    """Request body for POST /api/pick-folder — specifies which path field to populate."""

    target: Literal["input", "organized"] = "input"


def validate_pipeline_inputs(project_root: Path, body: PipelineBody) -> dict | None:
    """
    Fast checks before starting a background job.
    Returns an error-shaped dict {"ok": False, "report_path": "", "errors": [...]} or None if OK.
    """
    inp = _resolve_path(project_root, body.input_dir)
    if not inp.is_dir():
        return {"ok": False, "report_path": "", "errors": [f"Input is not a directory: {inp}"]}

    pr = project_root.resolve()
    if inp == pr:
        return {
            "ok": False,
            "report_path": "",
            "errors": [
                "Input folder cannot be the project root (or '.'). Use only your import folder "
                "(e.g. photos). Scanning the whole repo includes Organized/, assets/, and .venv/ — "
                "you will see the same photo twice (import copy vs organized copy)."
            ],
        }
    return None


def run_pipeline_sync(
    project_root: Path,
    body: PipelineBody,
    *,
    on_progress: Callable[[str, str], None] | None = None,
) -> dict:
    """Run organize and/or duplicates; return dict for JSON response."""
    errors: list[str] = []
    inp = _resolve_path(project_root, body.input_dir)
    if not inp.is_dir():
        return {"ok": False, "report_path": "", "errors": [f"Input is not a directory: {inp}"]}

    pr = project_root.resolve()
    if inp == pr:
        return {
            "ok": False,
            "report_path": "",
            "errors": [
                "Input folder cannot be the project root (or '.'). Use only your import folder "
                "(e.g. photos). Scanning the whole repo includes Organized/, assets/, and .venv/ — "
                "you will see the same photo twice (import copy vs organized copy)."
            ],
        }

    organized = _resolve_path(project_root, body.organized_root)
    reports_dir = (project_root / "Reports").resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    if body.run_organize:
        if on_progress:
            on_progress("organizing", "Organizing files by capture date…")
        org_result = organize(
            inp,
            organized,
            copy=body.copy_files,
            dry_run=False,
        )
        for e in org_result.errors:
            errors.append(str(e))
        if org_result.errors:
            return {"ok": False, "report_path": "", "errors": errors}

    # Scan only the import tree for duplicates (default): avoids mixing in years of old copies under Organized.
    # Scan Organized only when explicitly requested (finds matches across months in the full library).
    if not body.run_organize:
        dup_input = inp
    elif body.scan_import_folder_for_duplicates:
        dup_input = inp
    else:
        dup_input = organized

    if not body.run_duplicates:
        return {
            "ok": True,
            "report_path": "",
            "errors": errors,
            "message": "Organize finished; duplicates scan skipped.",
        }

    if not dup_input.is_dir():
        return {
            "ok": False,
            "report_path": "",
            "errors": errors + [f"Scan folder is not a directory: {dup_input}"],
        }

    if on_progress:
        on_progress(
            "duplicates",
            "Scanning for duplicates (this can take a while on large folders)…",
        )
    r = scan_duplicates(
        dup_input,
        do_exact=True,
        do_similar=body.include_similar_duplicates,
    )
    if on_progress:
        on_progress("writing", "Writing report…")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = reports_dir / f"duplicates_{stamp}.json"
    write_report(r, out_path)
    return {"ok": True, "report_path": str(out_path), "errors": errors}


@dataclass
class _PipelineJob:
    """In-memory state for a single background pipeline run, keyed by UUID."""

    id: str
    body_dict: dict
    phase: str = "queued"
    message: str = ""
    result: dict | None = None
    ctx_applied: bool = False
    created_at: float = field(default_factory=time.time)


_jobs: dict[str, _PipelineJob] = {}
_jobs_lock = threading.Lock()


def _prune_jobs() -> None:
    """Evict completed/failed jobs older than one hour, capping the job map at 40 entries."""
    now = time.time()
    with _jobs_lock:
        dead = [k for k, j in _jobs.items() if now - j.created_at > 3600 and j.phase in ("complete", "failed")]
        for k in dead:
            del _jobs[k]
        if len(_jobs) > 40:
            for k, _ in sorted(_jobs.items(), key=lambda kv: kv[1].created_at)[: len(_jobs) - 40]:
                del _jobs[k]


def create_serve_app(project_root: Path) -> FastAPI:
    """Build the unified FastAPI app with dashboard, pipeline, and duplicate-review routes."""
    project_root = project_root.resolve()
    threading.Thread(target=_prewarm_osascript, daemon=True).start()
    ctx = ReviewContext()
    # Do not preload the last JSON report: it often points at Organized or old paths and confuses users who
    # replaced their import folder. Review stays empty until a successful pipeline run.
    ctx.load_report(None)
    reports_dir = (project_root / "Reports").resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    ctx.trash_audit_path = reports_dir / "trash_audit.jsonl"

    app = FastAPI(title="Photo Organizer", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/pick-folder")
    async def api_pick_folder(body: PickFolderBody) -> dict:
        """
        Open the native macOS folder picker (osascript). Only meaningful on Darwin;
        the dashboard uses this to fill path fields without typing.
        """
        if platform.system() != "Darwin":
            raise HTTPException(
                501,
                "Native folder picker runs only on macOS. Type the import path in the dashboard, or use Browse there.",
            )
        prompts = {
            "input": "Choose the folder that contains your incoming photos",
            "organized": "Choose the Organized output folder (year/month tree goes here)",
        }
        prompt = prompts[body.target]
        raw_path = await asyncio.to_thread(_pick_folder_macos_sync, prompt)
        if not raw_path:
            return {"cancelled": True, "path": ""}
        chosen = Path(raw_path).resolve()
        if not chosen.is_dir():
            raise HTTPException(400, f"Not a directory: {chosen}")
        pr = project_root.resolve()
        if chosen == pr:
            raise HTTPException(
                400,
                "That folder is the project root. Pick a folder that only holds imports (e.g. photos).",
            )
        return {"cancelled": False, "path": _path_for_pipeline_form(project_root, chosen)}

    @app.post("/api/pipeline")
    async def api_pipeline(body: PipelineBody) -> dict:
        """Validate immediately; heavy work runs in a background thread (poll GET /api/pipeline/job/{id})."""
        sync_err = validate_pipeline_inputs(project_root, body)
        if sync_err:
            return {**sync_err, "accepted": False}

        _prune_jobs()
        job_id = str(uuid.uuid4())
        body_dump = body.model_dump()
        with _jobs_lock:
            _jobs[job_id] = _PipelineJob(id=job_id, body_dict=body_dump, phase="queued", message="Queued…")

        def worker() -> None:
            pb = PipelineBody(**body_dump)

            def on_progress(phase: str, msg: str) -> None:
                with _jobs_lock:
                    j = _jobs.get(job_id)
                    if j:
                        j.phase = phase
                        j.message = msg

            try:
                with _jobs_lock:
                    j = _jobs.get(job_id)
                    if j:
                        j.phase = "starting"
                        j.message = "Starting…"
                result = run_pipeline_sync(project_root, pb, on_progress=on_progress)
                with _jobs_lock:
                    j = _jobs.get(job_id)
                    if j:
                        j.result = result
                        if result.get("ok"):
                            j.phase = "complete"
                            j.message = "Done."
                        else:
                            j.phase = "failed"
                            errs = result.get("errors") or []
                            j.message = str(errs[0]) if errs else "Pipeline failed."
            except OSError as e:
                with _jobs_lock:
                    j = _jobs.get(job_id)
                    if j:
                        j.result = {"ok": False, "report_path": "", "errors": [str(e)]}
                        j.phase = "failed"
                        j.message = str(e)
            except Exception as e:
                with _jobs_lock:
                    j = _jobs.get(job_id)
                    if j:
                        j.result = {"ok": False, "report_path": "", "errors": [str(e)]}
                        j.phase = "failed"
                        j.message = str(e)

        threading.Thread(target=worker, daemon=True).start()
        return {"accepted": True, "job_id": job_id}

    @app.get("/api/pipeline/job/{job_id}")
    async def api_pipeline_job(job_id: str) -> dict:
        with _jobs_lock:
            job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found or expired.")

        if (
            job.phase == "complete"
            and job.result
            and job.result.get("ok")
            and not job.ctx_applied
        ):
            with _jobs_lock:
                j = _jobs.get(job_id)
                if j and not j.ctx_applied and j.result and j.result.get("ok"):
                    j.ctx_applied = True
                    pb = PipelineBody(**j.body_dict)
                    ctx.record_last_pipeline(
                        input_dir=pb.input_dir,
                        organized_root=pb.organized_root,
                        copy_files=pb.copy_files,
                        scan_import_folder_for_duplicates=pb.scan_import_folder_for_duplicates,
                        run_organize=pb.run_organize,
                        include_similar_duplicates=pb.include_similar_duplicates,
                    )
                    rp = j.result.get("report_path") or ""
                    if rp:
                        ctx.load_report(Path(rp))

        with _jobs_lock:
            job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found or expired.")
        return {
            "status": job.phase,
            "message": job.message,
            "result": job.result,
        }

    mount_review_routes(app, ctx, path_prefix="/review")

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR), html=False), name="static")

    @app.get("/review")
    def review_slash_redirect() -> RedirectResponse:
        return RedirectResponse(url="/review/", status_code=307)

    @app.get("/review/")
    def review_index_page() -> FileResponse:
        index = _STATIC_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(500, "review_static missing")
        return FileResponse(index)

    @app.get("/")
    def dashboard_page() -> FileResponse:
        dash = _STATIC_DIR / "dashboard.html"
        if not dash.is_file():
            raise HTTPException(500, "dashboard.html missing")
        return FileResponse(dash)

    return app


def run_serve_server(
    project_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Start the serve uvicorn server, optionally opening the dashboard in the system browser."""
    import threading
    import time
    import uvicorn
    import webbrowser

    app = create_serve_app(project_root)
    url = f"http://{host}:{port}/"
    if open_browser:

        def _open() -> None:
            time.sleep(0.9)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    print(f"Photo Organizer dashboard: {url}")
    print("Press Ctrl+C to stop.")
    uvicorn.run(app, host=host, port=port, log_level="info")
