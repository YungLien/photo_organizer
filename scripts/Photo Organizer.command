#!/bin/bash
# Double-click launcher (macOS). First run: right-click → Open if Gatekeeper warns.
cd "$(dirname "$0")/.." || exit 1
if [[ ! -d .venv ]]; then
  echo "Create a venv and run: pip install -e ."
  read -r _
  exit 1
fi
# shellcheck source=/dev/null
source .venv/bin/activate
exec photo-organizer serve "$@"
