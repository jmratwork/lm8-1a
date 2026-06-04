#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[run_playbook] Required command '$cmd' not found" >&2
    exit 1
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLAYBOOK="$SCRIPT_DIR/playbook.yml"
COLLECTIONS_FILE="$SCRIPT_DIR/requirements.yml"

require_cmd ansible-galaxy
require_cmd ansible-playbook
require_cmd wget
require_cmd virtualbmc

echo "[run_playbook] Installing required collections and running provisioning/playbook.yml." >&2
echo "[run_playbook] Use this wrapper instead of calling ansible-playbook directly on KYPO/CRCZ to avoid missing modules." >&2

if [[ $# -gt 0 ]]; then
  INVENTORY="$1"
  shift
else
  INVENTORY="$REPO_ROOT/inventory.ini"
fi

if [[ ! -f "$COLLECTIONS_FILE" ]]; then
  echo "[run_playbook] Collections file '$COLLECTIONS_FILE' not found" >&2
  exit 1
fi

if [[ ! -f "$PLAYBOOK" ]]; then
  echo "[run_playbook] Playbook '$PLAYBOOK' not found" >&2
  exit 1
fi

if [[ ! -f "$INVENTORY" ]]; then
  echo "[run_playbook] Inventory file '$INVENTORY' not found" >&2
  exit 1
fi

ansible-galaxy collection install -r "$COLLECTIONS_FILE"
ansible-playbook -i "$INVENTORY" "$PLAYBOOK" "$@"
