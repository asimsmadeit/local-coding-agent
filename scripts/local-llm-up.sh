#!/usr/bin/env bash
# Start the local model servers that back the memory stack (and, on a dev
# laptop, can also serve as the implementer endpoint):
#   :8081  llama-server — nomic-embed-text-v1.5 (embeddings)
#   :8082  llama-server — qwen2.5-1.5b-instruct (memory extraction LLM)
#   :4000  LiteLLM gateway — single OpenAI-compatible URL routing by model name
# Models auto-download from HuggingFace into ~/.cache/huggingface on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

up() { curl -sf -m 2 -o /dev/null "$1"; }

if ! up http://localhost:8081/health; then
  nohup llama-server -hf nomic-ai/nomic-embed-text-v1.5-GGUF \
    --embeddings --port 8081 --host 127.0.0.1 > /tmp/llama-embed.log 2>&1 &
  echo "starting embedder on :8081"
fi
if ! up http://localhost:8082/health; then
  nohup llama-server -hf bartowski/Qwen2.5-3B-Instruct-GGUF:Q4_K_M \
    --port 8082 --host 127.0.0.1 -c 4096 > /tmp/llama-llm.log 2>&1 &
  echo "starting extraction LLM on :8082"
fi
if ! up http://localhost:4000/health/liveliness; then
  nohup uvx --from 'litellm[proxy]' litellm --config gateway/litellm.yaml \
    --port 4000 --host 127.0.0.1 > /tmp/litellm.log 2>&1 &
  echo "starting LiteLLM gateway on :4000"
fi

echo -n "waiting for all three"
for _ in $(seq 1 60); do
  if up http://localhost:8081/health && up http://localhost:8082/health \
     && up http://localhost:4000/health/liveliness; then
    echo " — ready"; exit 0
  fi
  echo -n "."; sleep 5
done
echo " — TIMED OUT (check /tmp/llama-*.log /tmp/litellm.log)"; exit 1
