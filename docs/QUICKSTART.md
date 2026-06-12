# Quick Start — Windows, Zero to Demo

The complete order, from a fresh Windows machine to running the bundled
examples. Budget ~45–60 minutes the first time (downloads dominate).
Each phase ends with a gate — don't continue past a failed gate.

## Phase 1 — Install the tools (~15 min, one time)

PowerShell, in this order:

```powershell
winget install Docker.DockerDesktop      # 1. enable WSL2 backend when asked
winget install astral-sh.uv              # 2.
winget install Git.Git                   # 3.
winget install Amazon.AWSCLI             # 4.
# 5. Goose: download + run the Windows installer from
#    github.com/block/goose/releases
```

Then: **start Docker Desktop once** and let it finish its first-run setup,
and **open a NEW PowerShell** so PATH updates take effect.

## Phase 2 — Get the project (~3 min)

```powershell
git clone https://github.com/asimsmadeit/local-coding-agent.git
cd local-coding-agent
uv tool install -e ./openhands-coder --force
localagent init
```

**Gate:** `init` shows ✓ for docker, goose, uvx, aws. Fix any ✗ before
continuing.

## Phase 3 — Your two inputs (~5 min)

**(a) Bedrock credentials** — use the DEFAULT profile:

```powershell
aws configure        # access key, secret, region (e.g. us-east-1)
```

In the AWS console → **Bedrock → Model access** (same region!), enable:
your planner + implementer models below, **plus** `amazon.nova-lite-v1:0`
and `amazon.titan-embed-text-v2:0` (they power the memory backend).

**(b) Your two models** — edit
`%USERPROFILE%\.config\local-coding-agent\.env`, just two lines:

```bash
GOOSE_PLANNER_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
OPENHANDS_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Planner is a bare Bedrock model id; implementer takes the `bedrock/` prefix.
(`bedrock/us.amazon.nova-pro-v1:0` is the budget implementer option.)

## Phase 4 — Start and verify (~10 min first run)

```powershell
localagent up            # builds memory image, starts containers, pins Bedrock
localagent goose-setup   # renders Goose config + preference link
localagent doctor        # ← THE gate
```

**Gate:** doctor ALL green — especially
`episodic memory write (Bedrock round trip)`. That line is a real Bedrock
call, so green means the whole pipeline works. If red, the message names the
fix; most common: model not enabled in your region → Bedrock console →
Model access. More in `WINDOWS_VM.md` (troubleshooting table).

## Phase 5 — First live run, sample 1 (~5–10 min)

```powershell
localagent demo-repo textstats C:\demo\textstats
cd C:\demo\textstats
uv run --with pytest pytest -q       # confirm: 3 failed — the starting state
```

Now run the exact `goose run ...` command that `demo-repo` printed. Watch
the loop phases in the output: memory index read → spec →
`delegate_coding_task` → diff → tests pass → `save_note` (playbook).

**Gate:** tests pass afterwards (`uv run --with pytest pytest -q` → all
green), and the playbook exists:

```powershell
type %USERPROFILE%\.local\share\agent-memory\INDEX.md
```

## Phase 6 — The learning beat, sample 2 (~5 min)

```powershell
localagent demo-repo csvstats C:\demo\csvstats
```

Run its printed `goose run` command. This is the key moment: the ORIENT
phase should **find the textstats playbook** and pass it to the implementer.

**Gate:** tests pass, and `localagent report` shows delegations with a
playbook hit.

## Phase 7 — Showing it off

In this order (each builds on the last):

1. Screen-record a fresh sample-1 run (`localagent demo-repo textstats
   C:\demo\take2` for a clean repo).
2. Open the learned playbook file in an editor — human-readable markdown.
3. Record the sample-2 run reusing it.
4. Closers: `localagent report` (the improvement, measured),
   `type %USERPROFILE%\.local\share\agent-audit\audit-<date>.jsonl`
   (the audit trail), and the memory UI at `http://localhost:3000`.

## Daily use after that

```powershell
goose session            # interactive, all extensions loaded
goose run --recipe "$env:USERPROFILE\.config\local-coding-agent\plan-and-delegate.yaml" `
  --params task='...' --params repo_path=C:\path\to\repo
```

Copy `templates/goosehints` and `templates/AGENTS.md` into each work repo and
fill them in (build commands, conventions).

---

macOS/Linux: identical flow — swap winget for brew/apt (table in
`SETUP_FRESH_MACHINE.md`); paths become `~/.config/local-coding-agent/` and
`~/.local/share/agent-memory/`.
