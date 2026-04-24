#!/bin/bash
# macOS: native folder picker, then organize + duplicate scan + open Review in the browser.
# Double-click this file (chmod +x). First Gatekeeper run: right-click → Open.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -d .venv ]]; then
  osascript -e 'display alert "Photo Organizer" message "Create a .venv in the project folder and run: pip install -e ."'
  exit 1
fi
# shellcheck source=/dev/null
source .venv/bin/activate

HOST="${PHOTO_ORGANIZER_HOST:-127.0.0.1}"
PORT="${PHOTO_ORGANIZER_PORT:-8765}"
BASE="http://${HOST}:${PORT}"

ensure_server() {
  if curl -sf "${BASE}/health" >/dev/null 2>&1; then
    return 0
  fi
  photo-organizer serve --project-root "$ROOT" --host "$HOST" --port "$PORT" --no-browser >/tmp/photo-organizer-serve.log 2>&1 &
  local w=0
  while ! curl -sf "${BASE}/health" >/dev/null 2>&1; do
    sleep 0.15
    w=$((w + 1))
    if [[ "$w" -gt 120 ]]; then
      echo "Server did not become ready. Log: /tmp/photo-organizer-serve.log" >&2
      tail -20 /tmp/photo-organizer-serve.log >&2 || true
      exit 1
    fi
  done
}

ensure_server

FOLDER="$(osascript <<'APPLESCRIPT'
try
  set p to POSIX path of (choose folder with prompt "Choose the folder of photos to organize and scan for duplicates")
  return p
on error number -128
  return ""
end try
APPLESCRIPT
)" || true

if [[ -z "${FOLDER// }" ]]; then
  echo "Cancelled."
  exit 0
fi
FOLDER="${FOLDER%/}"

BODY="$(
  PHOTO_ORGANIZER_ROOT="$ROOT" PHOTO_ORGANIZER_FOLDER="$FOLDER" python3 <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PHOTO_ORGANIZER_ROOT"]).resolve()
folder = Path(os.environ["PHOTO_ORGANIZER_FOLDER"]).expanduser().resolve()
try:
    input_dir = str(folder.relative_to(root))
except ValueError:
    input_dir = str(folder)
print(
    json.dumps(
        {
            "input_dir": input_dir,
            "organized_root": "~/Desktop/Organized",
            "run_organize": True,
            "run_duplicates": True,
            "copy_files": True,
            "scan_import_folder_for_duplicates": True,
            "include_similar_duplicates": True,
        }
    )
)
PY
)"

RESP="$(curl -sS -X POST "${BASE}/api/pipeline" -H "Content-Type: application/json" -d "$BODY")"

TMPRESP="$(mktemp)"
trap 'rm -f "$TMPRESP"' EXIT
printf '%s' "$RESP" > "$TMPRESP"
export PHOTO_ORGANIZER_TMP="$TMPRESP"
export PHOTO_ORGANIZER_BASE="$BASE"
python3 <<'PY'
import json
import os
import sys
import time
import urllib.error
import urllib.request

base = os.environ["PHOTO_ORGANIZER_BASE"].rstrip("/")
with open(os.environ["PHOTO_ORGANIZER_TMP"], encoding="utf-8") as f:
    first = json.load(f)
if not first.get("accepted"):
    print("Pipeline failed:", file=sys.stderr)
    for e in first.get("errors") or [first]:
        print(" ", e, file=sys.stderr)
    sys.exit(1)
job = first["job_id"]
while True:
    url = f"{base}/api/pipeline/job/{job}"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            state = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(e.read().decode(), file=sys.stderr)
        sys.exit(1)
    st = state.get("status")
    if st in ("complete", "failed"):
        result = state.get("result") or {}
        if not result.get("ok"):
            print("Pipeline failed:", file=sys.stderr)
            for e in result.get("errors") or [result]:
                print(" ", e, file=sys.stderr)
            sys.exit(1)
        break
    time.sleep(0.3)
PY

open "${BASE}/review/"
echo "Review opened for: $FOLDER"
