#!/usr/bin/env bash
# Render goose/config-template.yaml -> ~/.config/goose/config.yaml using .env.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

if [[ ! -f .env ]]; then
  echo "No .env — copy .env.example to .env and edit it first." >&2
  exit 1
fi
set -a; source .env; set +a
export PROJECT_ROOT
# Derived: host-only form of the local LLM URL for Goose's openai provider.
export LOCAL_LLM_BASE_URL_HOST="${LOCAL_LLM_BASE_URL%/v1}"

CONFIG_DIR="$HOME/.config/goose"
mkdir -p "$CONFIG_DIR"
if [[ -f "$CONFIG_DIR/config.yaml" ]]; then
  cp "$CONFIG_DIR/config.yaml" "$CONFIG_DIR/config.yaml.bak.$(date +%s)"
  echo "Backed up existing config.yaml"
fi

# Substitute only our ${VARS}; leave anything unknown intact.
# Default for older .env files that predate MEMORY_NOTES_DIR.
export MEMORY_NOTES_DIR="${MEMORY_NOTES_DIR:-$HOME/.local/share/agent-memory}"

# The Goose extensions launch console scripts by absolute path. Install the
# package as a uv tool (editable, so repo edits take effect immediately).
uv tool install -q -e "$PROJECT_ROOT/openhands-coder" --force
export CODER_BIN_DIR="$(dirname "$(readlink -f "$(command -v openhands-coder 2>/dev/null || echo "$HOME/.local/bin/openhands-coder")")")"
[[ -x "$CODER_BIN_DIR/openhands-coder" ]] || CODER_BIN_DIR="$HOME/.local/bin"

envsubst '${GOOSE_PLANNER_MODEL} ${LOCAL_LLM_MODEL} ${LOCAL_LLM_BASE_URL_HOST}
${OPENMEMORY_MCP_URL} ${MEMORY_USER_ID} ${MEMORY_NOTES_DIR} ${PROJECT_ROOT}
${OPENHANDS_LLM_MODEL} ${OPENHANDS_LLM_BASE_URL} ${OPENHANDS_LLM_API_KEY}
${OPENHANDS_MAX_ITERATIONS} ${CODER_BIN_DIR}' \
  < goose/config-template.yaml > "$CONFIG_DIR/config.yaml"

echo "Wrote $CONFIG_DIR/config.yaml"

# Deterministic preference loading: link the standing-preferences file as
# Goose's GLOBAL hints file — injected into every session, no retrieval step.
# Symlink (not copy) so agent/user edits to either path hit the one source
# of truth in this repo.
if [[ -f "$CONFIG_DIR/.goosehints" && ! -L "$CONFIG_DIR/.goosehints" ]]; then
  cp "$CONFIG_DIR/.goosehints" "$CONFIG_DIR/.goosehints.bak.$(date +%s)"
fi
ln -sf "$PROJECT_ROOT/prefs/preferences.md" "$CONFIG_DIR/.goosehints"
echo "Linked prefs/preferences.md -> $CONFIG_DIR/.goosehints (global, every session)"
echo "Run a session:  goose session"
echo "Run the recipe: goose run --recipe goose/recipes/plan-and-delegate.yaml \\"
echo "                  --params task='...' repo_path=/path/to/repo"
