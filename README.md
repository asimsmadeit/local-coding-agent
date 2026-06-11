# local-coding-agent

Private, enterprise-safe coding agent: **Goose** orchestrates (plans with a
frontier model), **OpenHands** implements (local model), and both share one
persistent memory over MCP. Background and rationale: `FINDINGS.md`; full
build plan: `IMPLEMENTATION_STEPS.md`; record of everything built so far:
`IMPLEMENTED.md`.

```
Goose (orchestrator, planner LLM = Bedrock Claude or any endpoint)
 ├─ extension: openmemory       ──┐  shared persistent memory
 └─ extension: openhands_coder    │  (OpenMemory MCP + Qdrant, fully local:
      └─ OpenHands SDK agent    ──┘   llama.cpp embeddings/extraction behind
         (implementer LLM = local     a LiteLLM gateway on :4000)
          vLLM / llama.cpp / any OpenAI-compatible endpoint)
```

## Layout

| Path | What |
|---|---|
| `memory/` | docker-compose for the shared memory stack (OpenMemory MCP + Qdrant + UI) |
| `openhands-coder/` | Python MCP server wrapping an OpenHands SDK agent as `delegate_coding_task` |
| `goose/config-template.yaml` | Goose provider + extensions config, rendered from `.env` |
| `goose/recipes/plan-and-delegate.yaml` | Orchestrator loop with the playbook flywheel (orient → recall → plan → delegate → review → learn) |
| `prefs/preferences.md` | Standing user preferences — symlinked as Goose's global hints AND injected into every delegated task (deterministic, never retrieved) |
| `templates/` | `.goosehints` + `AGENTS.md` starters — copy into each work repo (the CLAUDE.md pattern) |
| `scripts/` | setup + smoke-test scripts |
| `.env.example` | every environment-specific value; nothing is hardcoded |
| `docs/SETUP_FRESH_MACHINE.md` | full command list for a clean macOS/Linux machine |
| `docs/BEDROCK_INTEGRATION.md` | planner/implementer on Bedrock or any OpenAI-compatible API (incl. the structured-tool-call verification curl) |
| `docs/DEMO.md` | scripted tour of everything working today |

## Install as a package (end users)

```bash
uv tool install local-coding-agent   # or pipx install (from PyPI once published;
                                     #  until then: uv tool install -e ./openhands-coder)
localagent init          # configs -> ~/.config/local-coding-agent + dependency check
localagent up            # memory stack + local model servers (downloads models first run)
localagent goose-setup   # renders ~/.config/goose/config.yaml + preference link
localagent doctor        # health-check everything
goose session            # go
```

Host prerequisites the CLI checks for: Docker, `brew install llama.cpp
block-goose-cli`, uv. Services run in Docker; agents and inference run on the
host (Docker on macOS has no Metal passthrough — containerizing inference
would make it several times slower).

## Setup (dev machine, repo checkout)

Prereqs: Docker, Homebrew, `uv`.

```bash
brew install llama.cpp block-goose-cli
cp .env.example .env            # edit for your environment
./scripts/memory-up.sh          # local llama servers + gateway + qdrant +
                                #   OpenMemory MCP (all localhost-only;
                                #   models auto-download on first run)
cd openhands-coder && uv sync && uv run pytest && cd ..   # implementer wrapper
./scripts/goose-setup.sh        # renders ~/.config/goose/config.yaml
./scripts/smoke-test.sh         # end-to-end checks (no LLM calls)
```

Memory backend detail: mem0 (inside OpenMemory) needs an extraction LLM and
an embedder. Both run locally via llama.cpp (`scripts/local-llm-up.sh`:
nomic-embed on :8081, Qwen2.5-3B on :8082) behind a LiteLLM gateway on :4000.
We use llama.cpp rather than Ollama because the Ollama app binary hangs on
managed Macs and the brew formula shipped without its runner binary; llama.cpp
also matches the company-side architecture (OpenAI-compatible servers behind
a gateway). Note the gateway aliases the embedder as `text-embedding-3-small`
— see the comment in `gateway/litellm.yaml`.

Use it:

```bash
goose session                   # interactive, both extensions loaded
goose run --recipe goose/recipes/plan-and-delegate.yaml \
  --params task='add a --verbose flag' repo_path=/path/to/repo
```

## What still needs the company environment

These are intentionally left as `.env` values (see `IMPLEMENTATION_STEPS.md`
Phases 1–2 and 7):

1. **Bedrock planner** — AWS credentials/profile + PrivateLink VPC endpoint
   with the scoped (`InvokeModel`-only) endpoint policy. Until then, point
   `GOOSE_PROVIDER` at any OpenAI-compatible endpoint for dev.
2. **Local implementer model** — the vLLM box serving Qwen3-Coder
   (`--tool-call-parser qwen3_coder` is mandatory) behind an authenticating
   reverse proxy; set `OPENHANDS_LLM_*` to it. For laptop dev, llama.cpp or
   LM Studio with a small coder model works.
3. **Company repos / data** — nothing in this repo touches them; index and
   audit-log wiring happens on the inside.

## Memory model (two layers, mirrors Claude Code)

1. **Curated notes** (`memory-direct` extension): verbatim markdown files +
   `INDEX.md` under `MEMORY_NOTES_DIR`, written deliberately by the planner
   via `save_note` and read via `get_memory_index`/`read_note` at session
   start. Preferences, project decisions, playbooks, escalations live here —
   exact wording preserved, human-reviewable, shared by both agents.
2. **Episodic recall** (OpenMemory + Qdrant): semantic search over extracted
   fragments — the supplemental long tail, not the source of truth.

Standing preferences skip memory entirely: `prefs/preferences.md` is loaded
deterministically every session (Goose global hints + wrapper prompt
injection). Note: OpenMemory's `infer:false` raw mode silently stores nothing
in the shipped image — that's why curated notes are files, not vectors.

## Security notes (enterprise posture)

- Memory stack binds to `127.0.0.1` only; memories never leave the machine
  (Ollama does extraction/embeddings locally).
- The implementer's iteration ceiling (`OPENHANDS_MAX_ITERATIONS`) is the
  cost/runaway guard; the recipe escalates after two failed delegations and
  records the escalation in memory (the routing flywheel's training data).
- Recalled memory is treated as information, not instructions (prompt-
  injection hygiene, FINDINGS §7); don't store raw third-party text.
- For tasks ingesting untrusted content, run the implementer in OpenHands'
  Docker sandbox (SDK workspace option) — local exec is for trusted repos.
