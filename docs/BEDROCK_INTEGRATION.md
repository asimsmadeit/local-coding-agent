# Bedrock Integration

Bedrock is the DEFAULT and only wired provider for this stack: planner
(Goose), implementer (OpenHands), and the memory backend (mem0 extraction +
embeddings) all run on it — there is no local inference and no GPU
requirement. Section C covers substituting any OpenAI-compatible endpoint
for the implementer later (e.g. a company vLLM box).

The architecture doesn't change across providers: Goose plans, the OpenHands
coder implements, both share memory. Only the LLM "sockets" move. Everything
is `.env` + one re-render — no code changes.

---

## A. Planner on Bedrock (Goose)

Goose has a native Bedrock provider using the standard AWS credential chain.

### 1. AWS side (one-time, account admin)

```bash
# Model access: AWS console → Bedrock → Model access → enable Claude models.

# Private connectivity (optional hardening — no public internet path):
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name com.amazonaws.<region>.bedrock-runtime \
  --vpc-endpoint-type Interface \
  --subnet-ids <subnet-id> --security-group-ids <sg-id>
```

Replace the endpoint's DEFAULT policy (which allows everything) with a scoped
one — this is the exfiltration control:

```json
{
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<acct>:role/<agent-role>"},
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.*"
  }]
}
```

IAM for the agent host: the same two actions, nothing more. For compliance
reviews cite the Bedrock third-party model legal terms (no training on
customer content), not the marketing page.

### 2. This machine

```bash
aws configure          # or SSO: aws sso login --profile <profile>
```

In `.env`:
```bash
AWS_REGION=us-east-1
AWS_PROFILE=<profile>        # empty if using default chain
GOOSE_PLANNER_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

In `goose/config-template.yaml`: the Bedrock block is already the default
(`GOOSE_PROVIDER: bedrock`). Then:

```bash
./scripts/goose-setup.sh     # or: localagent goose-setup
goose session                # planner now runs on Bedrock
```

## B. Implementer on Bedrock (OpenHands coder) — the default

The wrapper speaks LiteLLM model strings, so Bedrock works directly:

```bash
# .env (this is the shipped default)
OPENHANDS_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
OPENHANDS_LLM_BASE_URL=          # EMPTY — boto3 credential chain is used
OPENHANDS_LLM_API_KEY=           # EMPTY
```

Cheaper alternative: `bedrock/us.amazon.nova-pro-v1:0` (Nova supports
structured tool calling; quality is below Claude on hard tasks — the
escalation path in the recipe covers the gap).

Re-run `./scripts/goose-setup.sh` / `localagent goose-setup` (the wrapper
gets its env from the Goose extension config). AWS credentials/region come
from the environment.

## B2. Memory backend on Bedrock (mem0)

mem0 (inside the OpenMemory container) needs an extraction LLM + embedder.
Defaults (set in `.env`, pinned via the OpenMemory config API by
`memory-up` / `localagent up`):

```bash
MEMORY_LLM_MODEL=us.amazon.nova-lite-v1:0        # cheap, high-volume calls
MEMORY_EMBEDDER_MODEL=amazon.titan-embed-text-v2:0
MEMORY_EMBEDDING_DIMS=1024                       # Titan v2 native dims
```

The container reads credentials from the host's `~/.aws` (mounted read-only
in `memory/docker-compose.yml`) or static `AWS_*` keys passed through from
`.env`. Enable Nova + Titan in Bedrock → Model access alongside Claude.
If you change `MEMORY_EMBEDDING_DIMS` after first run, delete the qdrant
collection (`memory/data/qdrant`) — vectors of different dims can't mix.

## C. Implementer on any OpenAI-compatible endpoint

Works for: a remote vLLM box, a shared llama.cpp server, OpenRouter, a
company LiteLLM gateway — anything serving `/v1/chat/completions` with
structured tool calls.

```bash
# .env
OPENHANDS_LLM_MODEL=openai/<model-name-as-served>
OPENHANDS_LLM_BASE_URL=https://<host>/v1
OPENHANDS_LLM_API_KEY=<key>
```

For the Goose planner on the same endpoint, use the dev-mode block in
`goose/config-template.yaml`:
```yaml
GOOSE_PROVIDER: openai
GOOSE_MODEL: <model-name-as-served>
OPENAI_BASE_URL: https://<host>/v1
```
and run sessions with `OPENAI_API_KEY=<key> goose session` (Goose reads the
key from env or its keyring).

### Hard requirement: structured tool calling

The endpoint MUST return OpenAI-format `tool_calls` objects, not tool-call
text in `content`. Verify before pointing agents at it:

```bash
curl -s $BASE_URL/chat/completions -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{
  "model":"<model>","temperature":0,
  "messages":[{"role":"user","content":"List /tmp using the list_dir tool."}],
  "tools":[{"type":"function","function":{"name":"list_dir",
    "description":"List directory contents","parameters":{"type":"object",
    "properties":{"path":{"type":"string"}},"required":["path"]}}}]}' \
  | python3 -c "import json,sys; m=json.load(sys.stdin)['choices'][0]['message']; print('structured:', bool(m.get('tool_calls')))"
```

`structured: True` → usable. `False` → the agent loop will not work with
that endpoint/model. Live-fire findings on this machine:

| Model | Structured tool calls |
|---|---|
| Qwen3-4B-Instruct (llama.cpp `--jinja`) | ✓ |
| Qwen2.5-3B-Instruct (llama.cpp `--jinja`) | ✓ |
| Qwen2.5-Coder-7B-Instruct | ✗ broken — emits pseudo-XML even at temp 0 with the official template and `tool_choice: required` |
| vLLM + Qwen3-Coder | ✓ but ONLY with `--enable-auto-tool-choice --tool-call-parser qwen3_coder` |

### Context window requirement

The OpenHands agent's first request is ~9k tokens before any work happens.
Serve the implementer with **≥32k context** (`llama-server -c 32768`,
vLLM `--max-model-len 32768`+). An 8k window fails immediately — observed.

## D. What stays local regardless

Memory STORAGE (curated notes + episodic vectors in Qdrant), audit logs, and
all orchestration state never leave the machine. Bedrock sees only the
prompts routed to it: planner/implementer turns, and the memory extraction/
embedding calls (snippets of agent conversations — same data class as the
planner traffic, same account controls). If Bedrock is unreachable, episodic
memory writes fail safe; curated notes still work — they're plain files, no
LLM needed to write them.
