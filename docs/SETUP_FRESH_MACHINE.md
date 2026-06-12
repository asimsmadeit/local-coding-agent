# Setup on a Fresh Machine


## 0. Prerequisites

| Requirement | macOS | Linux (Ubuntu/Debian) | Windows |
|---|---|---|---|
| Docker | `brew install orbstack` (or Docker Desktop) | `curl -fsSL https://get.docker.com \| sh && sudo usermod -aG docker $USER` (re-login) | Docker Desktop (WSL2 backend) |
| uv (Python manager) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | same | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| git | included | `sudo apt install -y git` | git for Windows |
| AWS CLI | `brew install awscli` | `sudo apt install -y awscli` | MSI from aws.amazon.com/cli |

Hardware: any machine that runs Docker comfortably (8 GB RAM is fine — the
only local services are Qdrant and the OpenMemory API).

AWS: credentials with Bedrock model access (Claude + Nova + Titan embeddings
enabled in the console under Bedrock → Model access):

```bash
aws configure        # or: aws sso login --profile <profile>
```

## 1. Host tools

```bash
# macOS
brew install block-goose-cli gettext

# Linux
curl -fsSL https://github.com/block/goose/releases/latest/download/download_cli.sh | bash

# Windows: install Goose from the releases page — github.com/block/goose
```

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
- `AWS_REGION` / `AWS_PROFILE` — where your Bedrock access lives (empty
  profile = the default profile).
- `OPENHANDS_LLM_MODEL` — implementer model. Default is Claude Sonnet;
  `bedrock/us.amazon.nova-pro-v1:0` is the cheaper option.
- `GOOSE_PLANNER_MODEL` — Bedrock model id for the planner.

## 4. Start everything

macOS/Linux (repo checkout):

```bash
./scripts/memory-up.sh     # qdrant + OpenMemory, pins mem0 to Bedrock
./scripts/goose-setup.sh   # renders ~/.config/goose/config.yaml,
                           #   links prefs/preferences.md as global hints
./scripts/smoke-test.sh    # end-to-end checks
```

Windows (or any platform, CLI mode):

```powershell
localagent init
localagent up
localagent goose-setup
localagent doctor
```

Optional: `localagent autostart` starts services at login (launchd on macOS,
Startup folder on Windows, XDG autostart on Linux).

## 5. Verify the agents

```bash
cd openhands-coder && uv run pytest -q && cd ..   # expect all tests passing

# Goose with all extensions:
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
- Memory stack logs: `docker logs memory-openmemory-mcp-1` (repo mode) or
  `docker compose -f ~/.config/local-coding-agent/docker-compose.yml logs`.
- Bedrock `AccessDeniedException`: the model isn't enabled for your account/
  region — Bedrock console → Model access. `ExpiredTokenException` inside the
  memory container: re-run `aws sso login` on the host (the container reads
  the mounted `~/.aws` SSO cache).
- Memory writes failing right after `up`: confirm the mem0 config pin
  succeeded — `curl http://localhost:8765/api/v1/config/mem0/llm` should show
  `aws_bedrock`, not `openai`.
