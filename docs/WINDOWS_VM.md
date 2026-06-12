# Windows VM Run-Sheet — Fresh Machine to Working Agent


## 1. Install prerequisites (PowerShell, once)

```powershell
# Docker Desktop (enable the WSL2 backend when the installer asks)
winget install Docker.DockerDesktop

# uv (Python manager — installs/runs everything Python)
winget install astral-sh.uv

# git + AWS CLI
winget install Git.Git Amazon.AWSCLI

# Goose (orchestrator) — download the Windows release:
#   https://github.com/block/goose/releases
```

Start Docker Desktop once and let it finish setup. Open a NEW PowerShell
after the installs so PATH updates apply.

## 2. Get the project and install the CLI

```powershell
git clone <repo-url> local-coding-agent
cd local-coding-agent
uv tool install -e ./openhands-coder --force
localagent init     # materializes configs + checks docker/goose/uvx/aws
```

## 3. The ONLY configuration you do

**(a) Bedrock credentials** (one time):

```powershell
aws configure       # paste your access key, secret, region (e.g. us-east-1)
```

Use the DEFAULT profile — the memory container reads `~/.aws` and only
sees the default profile. Make sure your account has these enabled under
Bedrock → Model access: your two chosen models + `amazon.nova-lite-v1:0`
+ `amazon.titan-embed-text-v2:0` (the memory backend).

**(b) Your two models** — edit `%USERPROFILE%\.config\local-coding-agent\.env`:

```bash
GOOSE_PLANNER_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0   # planner
OPENHANDS_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0  # implementer
```

Planner is a bare Bedrock model id; implementer is the same id with the
`bedrock/` prefix. Everything else in `.env` works as shipped.

## 4. Start and verify

```powershell
localagent up           # builds the memory image (adds boto3), starts
                        #   qdrant + OpenMemory, pins mem0 to Bedrock
localagent goose-setup  # renders Goose config + preference link
localagent doctor       # MUST be all green, including
                        #   "episodic memory write (Bedrock round trip)"
```

`doctor` is honest: it does a REAL Bedrock-backed memory write. If
credentials or model access are wrong, it fails with the actual AWS error.

## 5. Use it

```powershell
goose session           # interactive, both extensions loaded
goose run --recipe "$env:USERPROFILE\.config\local-coding-agent\plan-and-delegate.yaml" `
  --params task='add a --verbose flag' --params repo_path=C:\path\to\repo
```

**Demo targets** — two bundled sample repos with failing tests (run
textstats first; csvstats afterwards shows the learned playbook being
reused on a same-category task):

```powershell
localagent demo-repo textstats C:\demo\textstats   # prints the exact goose run command
localagent demo-repo csvstats  C:\demo\csvstats    # run AFTER textstats
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `doctor`: AWS credentials ✗ | `aws configure` (default profile), reopen shell |
| memory write: `Unable to locate credentials` | same as above — the container reads `%USERPROFILE%\.aws` |
| memory write: `AccessDeniedException` | enable the model in Bedrock console → Model access (check region matches `AWS_REGION`) |
| memory write: dimension error | `curl -X DELETE http://localhost:6333/collections/openmemory` then `localagent up` (collection left over from a different embedder) |
| `localagent` not found | reopen PowerShell, or `uv tool update-shell` |
| Docker mount error on `~/.aws` | Docker Desktop → Settings → Resources → File sharing: ensure `C:\Users` is shared (default on WSL2) |
| Goose can't start extensions | re-run `localagent goose-setup` after any `.env` change |
