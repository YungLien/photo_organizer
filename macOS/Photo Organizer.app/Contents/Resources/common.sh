# Shared helpers for Photo Organizer .app bundles (sourced from MacOS/*).
# shellcheck shell=bash

photo_organizer_config_dir() {
  echo "${HOME}/Library/Application Support/PhotoOrganizer"
}

photo_organizer_repo_file() {
  echo "$(photo_organizer_config_dir)/repo_path"
}

# Sets global REPO_ROOT or exits after user alert.
photo_organizer_resolve_repo() {
  local rf
  rf="$(photo_organizer_repo_file)"
  mkdir -p "$(dirname "$rf")"
  if [[ -f "$rf" ]]; then
    REPO_ROOT="$(tr -d '\r\n' <"$rf")"
    REPO_ROOT="${REPO_ROOT%/}"
  else
    REPO_ROOT="$(
      osascript <<'APPLESCRIPT'
try
  set p to POSIX path of (choose folder with prompt "Select the PROJECT folder (must contain pyproject.toml and .venv). Do NOT pick your photo import folder (e.g. photos)—that comes later in the browser or the next dialog.")
  return p
on error number -128
  return ""
end try
APPLESCRIPT
    )"
    REPO_ROOT="${REPO_ROOT%/}"
    if [[ -z "$REPO_ROOT" ]]; then
      exit 0
    fi
    printf '%s' "$REPO_ROOT" >"$rf"
  fi

  if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
    osascript -e 'display alert "Photo Organizer" message "That folder is not the project root (missing pyproject.toml). You must choose the folder that CONTAINS pyproject.toml—usually named photo_organizer—not the photos subfolder inside it. Delete ~/Library/Application Support/PhotoOrganizer/repo_path and try again."'
    exit 1
  fi
  if [[ ! -f "$REPO_ROOT/.venv/bin/photo-organizer" ]]; then
    osascript -e 'display alert "Photo Organizer" message "No working .venv in that folder. Open Terminal there and run: python3 -m venv .venv && source .venv/bin/activate && pip install -e ."'
    exit 1
  fi
}

photo_organizer_host() {
  echo "${PHOTO_ORGANIZER_HOST:-127.0.0.1}"
}

photo_organizer_port() {
  echo "${PHOTO_ORGANIZER_PORT:-8765}"
}

photo_organizer_base_url() {
  local h p
  h="$(photo_organizer_host)"
  p="$(photo_organizer_port)"
  echo "http://${h}:${p}"
}

# Start serve in background if /health is down; waits until ready or shows alert.
photo_organizer_ensure_server() {
  local base log cfg
  base="$(photo_organizer_base_url)"
  cfg="$(photo_organizer_config_dir)"
  log="${cfg}/serve.log"
  mkdir -p "$cfg"

  if curl -sf "${base}/health" >/dev/null 2>&1; then
    return 0
  fi

  # Finder-launched .app may run under Rosetta: then uname -m is x86_64 but .venv is arm64 → ImportError in serve.log.
  # sysctl.proc_translated==1 means this shell is Rosetta; still force arch -arm64 for native arm64 venv.
  local po_bin="$REPO_ROOT/.venv/bin/photo-organizer"
  local inner translated
  translated="$(/usr/sbin/sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)"
  if [[ "$translated" == "1" ]] || [[ "$(/usr/bin/uname -m)" == "arm64" ]]; then
    inner="cd \"$REPO_ROOT\" && exec /usr/bin/arch -arm64 \"$po_bin\" serve --project-root \"$REPO_ROOT\" --host \"$(photo_organizer_host)\" --port \"$(photo_organizer_port)\" --no-browser"
  else
    inner="cd \"$REPO_ROOT\" && exec \"$po_bin\" serve --project-root \"$REPO_ROOT\" --host \"$(photo_organizer_host)\" --port \"$(photo_organizer_port)\" --no-browser"
  fi
  nohup /bin/bash -c "$inner" >>"$log" 2>&1 &
  disown 2>/dev/null || true

  local w=0
  while ! curl -sf "${base}/health" >/dev/null 2>&1; do
    sleep 0.2
    w=$((w + 1))
    if [[ "$w" -gt 150 ]]; then
      osascript -e "display alert \"Photo Organizer\" message \"Server did not start in time. See log: ${log}\""
      exit 1
    fi
  done
}
