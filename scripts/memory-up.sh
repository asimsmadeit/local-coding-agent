#!/usr/bin/env bash
# Bring up the shared memory stack (OpenMemory MCP + Qdrant + UI).
# All inference (memory extraction LLM + embeddings) runs on AWS Bedrock —
# there are no local model servers and no GPU requirement.
# macOS/Linux convenience wrapper; on Windows use: localagent up
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "No .env found — creating from .env.example (edit it for your environment)."
  cp .env.example .env
fi
set -a; source .env; set +a

docker compose -f memory/docker-compose.yml --env-file .env up -d

# Wait for the API, then pin mem0's LLM + embedder to Bedrock (this image
# persists llm/embedder config in its DB, so env vars alone don't switch it).
echo -n "waiting for OpenMemory API"
for _ in $(seq 1 30); do
  curl -sf -m 2 -o /dev/null http://localhost:8765/docs && break
  echo -n "."; sleep 2
done; echo
pin() { # pin <llm|embedder> <json>; fail loudly if the API rejects it
  local out
  out=$(curl -s -X PUT "http://localhost:8765/api/v1/config/mem0/$1" \
    -H 'Content-Type: application/json' -d "$2")
  if echo "$out" | grep -qi '"detail"'; then
    echo "FAILED to pin mem0 $1 config: $out" >&2; exit 1
  fi
}
pin llm "{\"provider\":\"aws_bedrock\",\"config\":{\"model\":\"${MEMORY_LLM_MODEL:-us.amazon.nova-lite-v1:0}\",\"temperature\":0.1,\"max_tokens\":2000}}"
pin embedder "{\"provider\":\"aws_bedrock\",\"config\":{\"model\":\"${MEMORY_EMBEDDER_MODEL:-amazon.titan-embed-text-v2:0}\",\"embedding_dims\":${MEMORY_EMBEDDING_DIMS:-1024}}}"

# OpenMemory's vector_store config is not settable via its API and defaults
# to 1536 dims; pre-create the collection at the embedder's dims so mem0
# adopts it (Titan v2 = 1024).
WANT_DIMS="${MEMORY_EMBEDDING_DIMS:-1024}"
if ! curl -sf http://localhost:6333/collections/openmemory >/dev/null 2>&1; then
  curl -s -X PUT http://localhost:6333/collections/openmemory \
    -H 'Content-Type: application/json' \
    -d "{\"vectors\": {\"size\": ${WANT_DIMS}, \"distance\": \"Cosine\"}}" >/dev/null
  echo "pre-created qdrant collection (${WANT_DIMS}-dim)"
else
  # A collection left over from a different embedder breaks every memory
  # write with a dimension mismatch — fail loudly, never silently.
  HAVE_DIMS=$(curl -s http://localhost:6333/collections/openmemory \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['config']['params']['vectors']['size'])" 2>/dev/null || echo "?")
  if [[ "$HAVE_DIMS" != "$WANT_DIMS" ]]; then
    echo "ERROR: qdrant collection 'openmemory' is ${HAVE_DIMS}-dim but the" >&2
    echo "  embedder (${MEMORY_EMBEDDER_MODEL:-amazon.titan-embed-text-v2:0}) needs ${WANT_DIMS}." >&2
    echo "  Back up + recreate it:" >&2
    echo "    curl -X DELETE http://localhost:6333/collections/openmemory" >&2
    echo "    ./scripts/memory-up.sh" >&2
    exit 1
  fi
fi

echo
echo "Memory stack ready:"
echo "  MCP (SSE):  http://localhost:8765/mcp/<client>/sse/\${MEMORY_USER_ID}"
echo "  API docs:   http://localhost:8765/docs"
echo "  UI:         http://localhost:3000"
