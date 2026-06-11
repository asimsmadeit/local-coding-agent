#!/usr/bin/env bash
# Bring up the shared memory stack (OpenMemory MCP + Qdrant + UI).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "No .env found — creating from .env.example (edit it for your environment)."
  cp .env.example .env
fi

# Local model servers (llama.cpp + LiteLLM gateway) back the memory stack.
./scripts/local-llm-up.sh

docker compose -f memory/docker-compose.yml --env-file .env up -d

# Wait for the API, then pin mem0 to the local gateway (this image persists
# llm/embedder config in its DB, so env vars alone don't switch it).
echo -n "waiting for OpenMemory API"
for _ in $(seq 1 30); do
  curl -sf -m 2 -o /dev/null http://localhost:8765/docs && break
  echo -n "."; sleep 2
done; echo
curl -s -X PUT http://localhost:8765/api/v1/config/mem0/llm \
  -H 'Content-Type: application/json' \
  -d '{"provider":"openai","config":{"model":"qwen2.5-3b-instruct","temperature":0.1,"max_tokens":2000,"api_key":"local"}}' >/dev/null
# Embedder model name must be text-embedding-3-* so LiteLLM accepts mem0's
# `dimensions` param; the gateway aliases it to local nomic (768-dim).
curl -s -X PUT http://localhost:8765/api/v1/config/mem0/embedder \
  -H 'Content-Type: application/json' \
  -d '{"provider":"openai","config":{"model":"text-embedding-3-small","api_key":"local","embedding_dims":768}}' >/dev/null

# OpenMemory's vector_store config is not settable via its API and defaults
# to 1536 dims; pre-create the collection at nomic's 768 so mem0 adopts it.
if ! curl -sf http://localhost:6333/collections/openmemory >/dev/null 2>&1; then
  curl -s -X PUT http://localhost:6333/collections/openmemory \
    -H 'Content-Type: application/json' \
    -d '{"vectors": {"size": 768, "distance": "Cosine"}}' >/dev/null
  echo "pre-created qdrant collection (768-dim)"
fi

echo
echo "Memory stack ready:"
echo "  MCP (SSE):  http://localhost:8765/mcp/<client>/sse/\${MEMORY_USER_ID}"
echo "  API docs:   http://localhost:8765/docs"
echo "  UI:         http://localhost:3000"
