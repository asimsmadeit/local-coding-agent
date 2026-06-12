# local-coding-agent

A private coding agent with persistent, shared memory. **Goose** orchestrates
(plans tasks with a frontier model), **OpenHands** implements (executes
delegated coding tasks), and both share one memory over MCP — preferences,
project decisions, and reusable playbooks that carry across sessions and
agents. All models run on **AWS Bedrock** (Claude / Nova); nothing is sent to
any other service, no local inference, no GPU required.

```
Goose (orchestrator, planner LLM = Bedrock Claude)
 ├─ extension: openmemory       ──┐  shared persistent memory
 └─ extension: openhands_coder    │  (OpenMemory MCP + Qdrant in Docker;
      └─ OpenHands SDK agent    ──┘   extraction LLM = Bedrock Nova Lite,
         (implementer LLM =           embeddings = Bedrock Titan v2)
          Bedrock Claude or Nova)
```

How a task flows: the orchestrator reads the memory index, recalls anything
relevant (including playbooks from past tasks), writes a complete spec, and
delegates it to the implementer, which edits files and runs tests in your
repo and returns a structured diff. After review, the orchestrator writes
what it learned back to memory — so the next similar task starts ahead.
Every action and memory write is recorded in an append-only audit log
(content hashes, not source code).

Runs on macOS, Linux, and Windows. The `localagent` CLI (pure Python) is the
cross-platform entry point; `scripts/*.sh` are macOS/Linux conveniences.

## Quick start

**1. Install the prerequisites** (each is a one-time install):

| Tool | macOS | Windows |
|---|---|---|
| Docker | `brew install orbstack` or Docker Desktop | Docker Desktop (WSL2) |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `winget install astral-sh.uv` |
| AWS CLI | `brew install awscli` | `winget install Amazon.AWSCLI` |
| Goose | `brew install block-goose-cli` | release from github.com/block/goose |

**2. Get the project and install the CLI:**

```bash
git clone <repo-url> local-coding-agent
cd local-coding-agent
uv tool install -e ./openhands-coder --force
localagent init          # materializes configs + checks the prerequisites
```

**3. Add your Bedrock access** — the only configuration there is:

```bash
aws configure            # paste your AWS access key / secret / region
```

Use the **default** profile. In the AWS console under **Bedrock → Model
access**, enable: your two chosen models below, plus `amazon.nova-lite-v1:0`
and `amazon.titan-embed-text-v2:0` (they power the memory backend).

**4. Pick your two models** — edit `~/.config/local-coding-agent/.env`
(Windows: `%USERPROFILE%\.config\local-coding-agent\.env`):

```bash
GOOSE_PLANNER_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0          # planner
OPENHANDS_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0  # implementer
```

The planner is a bare Bedrock model id; the implementer takes a `bedrock/`
prefix. (`bedrock/us.amazon.nova-pro-v1:0` is the budget implementer option.)

**5. Start it and check everything:**

```bash
localagent up            # memory stack in Docker, wired to Bedrock
localagent goose-setup   # renders the Goose config + preference link
localagent doctor        # must be ALL green — it does a real Bedrock
                         #   round trip, so green means working
```

**6. See it run** on a bundled sample (a tiny repo with failing tests):

```bash
localagent demo-repo textstats demo1   # prints the exact run command
cd demo1 && uv run --with pytest pytest -q     # failing — the starting state
# now run the printed `goose run ...` command and watch the loop:
# memory read → plan → delegate → diff → tests pass → playbook saved
cat ~/.local/share/agent-memory/INDEX.md       # what it learned

localagent demo-repo csvstats demo2    # second sample, same task category —
                                       # this run reuses the learned playbook
```

Day-to-day use: `goose session` (interactive, all extensions loaded), or
`goose run --recipe ~/.config/local-coding-agent/plan-and-delegate.yaml
--params task='...' --params repo_path=/path/to/repo` for one-shot tasks.
Copy `templates/goosehints` and `templates/AGENTS.md` into each work repo
and fill them in (build commands, conventions).

## Layout

| Path | What |
|---|---|
| `openhands-coder/` | The Python package: `localagent` CLI, the OpenHands MCP wrapper (`delegate_coding_task`), curated-memory MCP server, audit log |
| `memory/` | docker-compose for the shared memory stack (OpenMemory MCP + Qdrant + UI) |
| `goose/` | Goose config template + the plan-and-delegate recipe |
| `prefs/preferences.md` | Standing user preferences — loaded into every session of both agents |
| `templates/` | `.goosehints` + `AGENTS.md` starters for work repos |
| `scripts/` | macOS/Linux setup + smoke-test scripts |
| `.env.example` | every environment-specific value; nothing is hardcoded |
| `docs/` | full documentation (below) |

## Documentation

- `docs/QUICKSTART.md` — the full ordered path from a fresh Windows machine
  to the running examples, with a verification gate at every phase
- `docs/OVERVIEW.md` — architecture diagram, component breakdown, and what
  makes this different from hosted coding assistants
- `docs/SETUP_FRESH_MACHINE.md` — detailed setup for macOS / Linux / Windows
- `docs/WINDOWS_VM.md` — step-by-step Windows run-sheet with troubleshooting
- `docs/BEDROCK_INTEGRATION.md` — credentials, model choices, optional private
  VPC connectivity, and how to point at any OpenAI-compatible endpoint instead
- `docs/DEMO.md` — a scripted tour of every working capability
- `docs/FINDINGS.md` — the research behind the architecture choices
- `docs/IMPLEMENTATION_STEPS.md` — the original build plan
- `docs/IMPLEMENTED.md` — dated record of what was built and verified

## Memory model (two layers)

1. **Curated notes** (`memory-direct`): verbatim markdown files + `INDEX.md`
   under `MEMORY_NOTES_DIR`, written deliberately via `save_note` and read at
   session start. Preferences, decisions, playbooks, escalations — exact
   wording preserved, human-reviewable, git-versioned on every change.
2. **Episodic recall** (OpenMemory + Qdrant): semantic search over extracted
   fragments — the supplemental long tail, not the source of truth.

Standing preferences skip retrieval entirely: `prefs/preferences.md` is
loaded deterministically every session for both agents.

## Privacy & safety properties

- All inference goes to AWS Bedrock under your own account and credentials;
  memory storage, audit logs, and orchestration state stay on your machine.
  The memory stack binds to `127.0.0.1` only.
- The implementer has a hard iteration ceiling (`OPENHANDS_MAX_ITERATIONS`)
  as a cost/runaway guard; the recipe escalates after two failed delegations
  and records why.
- Recalled memory is treated as information, not instructions; raw
  third-party text is never stored as memory.
- For tasks that ingest untrusted content, run the implementer in OpenHands'
  Docker sandbox (SDK workspace option) — local exec is for trusted repos.
