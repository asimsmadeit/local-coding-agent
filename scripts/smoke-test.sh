#!/usr/bin/env bash
# End-to-end checks. No containers, no services — both memory layers run
# in-process. The one Bedrock call here is a cheap Titan embedding round trip
# (the honest proof that episodic recall will work).
set -uo pipefail
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

[[ -f .env ]] && set -a && source .env && set +a

echo "[1/4] AWS credentials (Bedrock)"
if [[ -n "${AWS_ACCESS_KEY_ID:-}" || -f "$HOME/.aws/credentials" || -f "$HOME/.aws/config" ]]; then
  ok "AWS credentials present (env or ~/.aws)"
else
  bad "no AWS credentials — run: aws configure (or aws sso login)"
fi

echo "[2/4] episodic memory: Bedrock embed → store → recall (in-process)"
if (cd openhands-coder && MEMORY_USER_ID=smoketest \
      MEMORY_EPISODIC_DIR="$(mktemp -d)" \
      uv run python -c "
from openhands_coder import memory_episodic as m
m._add('smoke test: the user likes green tea')
hits = m._search('favourite beverage', limit=1)
import sys
sys.exit(0 if (not hits.get('error') and 'green tea' in (hits.get('results') or [{}])[0].get('memory','')) else 1)
" 2>/dev/null); then
  ok "embed + semantic recall works"
else
  bad "episodic recall failed (check AWS creds + Bedrock model access for Titan)"
fi

echo "[3/4] openhands-coder wrapper"
if (cd openhands-coder && uv run pytest -q 2>&1 | tail -1 | grep -qE '^[0-9]+ passed'); then
  ok "wrapper tests pass (tools exposed, validation works)"
else
  bad "wrapper tests failing (cd openhands-coder && uv run pytest)"
fi

echo "[4/4] goose installed + config rendered"
if command -v goose >/dev/null; then ok "goose CLI"; else bad "goose CLI missing (brew install block-goose-cli)"; fi
cfg="$HOME/.config/goose/config.yaml"
if [[ -f "$cfg" ]] && grep -q openhands_coder "$cfg" && grep -q memory_episodic "$cfg" && grep -q memory_direct "$cfg"; then
  ok "config.yaml has openhands_coder + memory_episodic + memory_direct"
else
  bad "goose config not rendered with all extensions (./scripts/goose-setup.sh)"
fi

echo
echo "passed: $PASS  failed: $FAIL"
exit $((FAIL > 0))
