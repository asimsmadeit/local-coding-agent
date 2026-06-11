#!/usr/bin/env bash
# End-to-end checks that need no LLM credits: containers up, MCP endpoints
# reachable, wrapper exposes tools, goose config valid.
set -uo pipefail
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

[[ -f .env ]] && set -a && source .env && set +a

echo "[1/5] memory stack containers"
for c in mem0_store openmemory-mcp; do
  if docker ps --format '{{.Names}}' | grep -q "$c"; then ok "$c running"; else bad "$c not running (./scripts/memory-up.sh)"; fi
done

echo "[2/5] OpenMemory API + SSE endpoint"
if curl -sf "http://localhost:8765/docs" >/dev/null; then ok "API at :8765"; else bad "API not responding"; fi
SSE_URL="http://localhost:8765/mcp/smoketest/sse/${MEMORY_USER_ID:-default}"
if curl -sf -m 3 -o /dev/null -H 'Accept: text/event-stream' "$SSE_URL" 2>/dev/null || [[ $? -eq 28 ]]; then
  ok "SSE endpoint streams (timeout = healthy stream)"
else
  bad "SSE endpoint failed: $SSE_URL"
fi

echo "[3/5] local model servers (memory backend)"
if curl -sf -m 2 -o /dev/null http://localhost:8081/health; then ok "embedder on :8081"; else bad "embedder down (./scripts/local-llm-up.sh)"; fi
if curl -sf -m 2 -o /dev/null http://localhost:8082/health; then ok "extraction LLM on :8082"; else bad "extraction LLM down (./scripts/local-llm-up.sh)"; fi
if curl -sf -m 2 -o /dev/null http://localhost:4000/health/liveliness; then ok "LiteLLM gateway on :4000"; else bad "gateway down (./scripts/local-llm-up.sh)"; fi
if curl -sf -m 60 http://localhost:8765/api/v1/memories/ -X POST -H 'Content-Type: application/json' \
   -d "{\"user_id\":\"${MEMORY_USER_ID:-default}\",\"text\":\"smoke test: user likes green\",\"app\":\"smoketest\",\"infer\":true}" \
   | grep -qv '"error"'; then ok "end-to-end memory write"; else bad "memory write failed (docker logs memory-openmemory-mcp-1)"; fi

echo "[4/5] openhands-coder wrapper"
if (cd openhands-coder && uv run pytest -q 2>&1 | tail -1 | grep -qE '^[0-9]+ passed'); then
  ok "wrapper tests pass (tools exposed, validation works)"
else
  bad "wrapper tests failing (cd openhands-coder && uv run pytest)"
fi

echo "[5/5] goose installed + config rendered"
if command -v goose >/dev/null; then ok "goose CLI"; else bad "goose CLI missing (brew install block-goose-cli)"; fi
if [[ -f "$HOME/.config/goose/config.yaml" ]] && grep -q openhands_coder "$HOME/.config/goose/config.yaml"; then
  ok "config.yaml has openhands_coder + openmemory extensions"
else
  bad "goose config not rendered (./scripts/goose-setup.sh)"
fi

echo
echo "passed: $PASS  failed: $FAIL"
exit $((FAIL > 0))
