# Setup on a Fresh Machine

Every command needed to go from a clean macOS or Linux machine to a working
agent stack. Total time: ~20 min of commands + model downloads (~5 GB) in the
background.

## 0. Prerequisites

| Requirement | macOS | Linux (Ubuntu/Debian) |
|---|---|---|
| Package manager | Homebrew: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` | apt (built in) |
| Docker | `brew install orbstack` (or Docker Desktop) | `curl -fsSL https://get.docker.com \| sh && sudo usermod -aG docker $USER` (re-login) |
| uv (Python manager) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | same |
| git | included | `sudo apt install -y git` |

Hardware: 16 GB RAM minimum for the dev tier (embedder + extraction LLM +
small coder). The implementer quality scales with what you can host — see
`docs/BEDROCK_INTEGRATION.md` to use a remote model instead.

## 1. Host tools

```bash
# macOS
brew install llama.cpp block-goose-cli gettext

# Linux
# llama.cpp: download a release binary or build:
sudo apt install -y build-essential cmake
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build && cmake --build build --config Release -j && sudo cp build/bin/llama-server /usr/local/bin/
# goose:
curl -fsSL https://github.com/block/goose/releases/latest/download/download_cli.sh | bash
```

Note (macOS, managed/enterprise machines): use llama.cpp, NOT Ollama — the
Ollama brew formula has shipped without its runner binary and the app binary
can hang under endpoint-security software. llama.cpp is also what matches the
production architecture (OpenAI-compatible server behind a gateway).

## 2. Get the project

```bash
git clone <your-github-repo-url> local-coding-agent
cd local-coding-agent

# Install the CLI + agent package (editable so your edits take effect)
uv tool install -e ./openhands-coder --force
localagent --help
```

## 3. Configure

```bash
cp .env.example .env
$EDITOR .env
```

Minimum to touch:
- `MEMORY_USER_ID` — your handle; BOTH agents share one memory under this id.
- `OPENHANDS_LLM_MODEL` / `OPENHANDS_LLM_BASE_URL` — the implementer model.
  Local dev tier default works out of the box; for Bedrock or any remote
  OpenAI-compatible endpoint see `docs/BEDROCK_INTEGRATION.md`.
- `GOOSE_PLANNER_MODEL` — Bedrock model id for the planner (company), or use
  the dev-mode block in `goose/config-template.yaml` (no AWS needed).

## 4. Start everything

```bash
./scripts/memory-up.sh     # memory stack + local model servers + gateway
                           # (first run downloads ~5 GB of models — wait)
./scripts/goose-setup.sh   # renders ~/.config/goose/config.yaml,
                           #   links prefs/preferences.md as global hints
./scripts/smoke-test.sh    # 11 checks — expect 11/11
```

Equivalent for an installed (non-repo) machine: `localagent init && localagent
up && localagent goose-setup && localagent doctor`.

Optional: `localagent autostart` (macOS) installs a launchd agent so services
start at login.

## 5. Verify the agents

```bash
cd openhands-coder && uv run pytest -q && cd ..   # expect all tests passing

# Goose with all extensions (needs a planner LLM — see BEDROCK_INTEGRATION):
goose session
#   try: "what do you remember about me?"  → should read the memory index

# Flywheel metrics (will be empty until you run tasks):
localagent report
```

## 6. Per-repo onboarding (each work repo)

```bash
cp templates/goosehints  /path/to/work-repo/.goosehints   # then fill in
cp templates/AGENTS.md   /path/to/work-repo/AGENTS.md     # then fill in
```

These are auto-loaded (Goose) and prompt-injected (OpenHands coder) every
session — build/test commands, conventions, gotchas.

## Where state lives (backup these)

| Path | What |
|---|---|
| `~/.local/share/agent-memory/` | curated memory notes (auto git-versioned) |
| `memory/data/` (repo) or `~/.config/local-coding-agent/data/` | episodic vectors + metadata |
| `~/.local/share/agent-audit/` | audit JSONL |
| `prefs/preferences.md` | standing preferences |
| `.env` | your config — never commit |

## Troubleshooting

- `./scripts/smoke-test.sh` / `localagent doctor` first — every check names
  the fix.
- Model server logs: `/tmp/llama-*.log`, `/tmp/litellm.log` (repo mode) or
  `~/.config/local-coding-agent/*.log` (CLI mode).
- Memory stack logs: `docker logs memory-openmemory-mcp-1`.
- Tool calls coming back as text instead of structured: the model serving
  on :8083 must support hermes-style tool calling — Qwen3-family instruct
  models work; **Qwen2.5-Coder does not** (verified broken).
