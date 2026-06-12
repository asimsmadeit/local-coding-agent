---
marp: true
theme: default
paginate: true
class: lead
---

# local-coding-agent

### A coding agent you run yourself — that remembers, learns, and gets cheaper every time it works.

---

## The two-sided problem

**Teams with private code can't use hosted assistants**
Code can't leave the boundary — the popular tools are someone else's data plane.

**And the assistants don't learn anyway**
Every developer re-solves the same problem, every session.
Knowledge evaporates when the session ends — or when a senior dev leaves.

> Today's fallback: nothing, or autocomplete.

---

## What it is

A planner model reads what the system **already knows** — preferences, past
decisions, step-by-step playbooks — writes a precise spec, and hands it to an
implementer agent that edits files and runs the tests in your repo.

When the work is done, the system **writes down what it learned** as a
human-readable playbook. The next similar task starts ahead.

**ORIENT → RECALL → PLAN → DELEGATE → REVIEW → LEARN**

---

## Architecture

```
You ──task──▶ Goose (orchestrator, Bedrock Claude)
                 │  complete spec in / diff + summary out
                 ▼
              OpenHands (implementer, Bedrock Claude or Nova)
                 │  edits files, runs tests in your repo
                 ▼
   ┌──── shared persistent memory (MCP, in-process) ─┐
   │ curated notes: playbooks, preferences,          │
   │   decisions — markdown, git-versioned           │
   │ episodic recall: Bedrock Titan embeddings       │
   │   + local SQLite vectors (no containers)        │
   └─────────────────────────────────────────────────┘
   All inference: YOUR AWS Bedrock account · all state: your machine
   No Docker, no GPU — runs on a plain VM
   Every action + memory write → append-only hashed audit log
```

---

## Demo — watch it learn

1. `localagent doctor` — all green, **real Bedrock round trip**
2. **Task 1** (textstats): plan → delegate → tests pass → **playbook saved**
   — open the markdown file, see the git commit
3. **Task 2** (csvstats, same category): playbook **found and reused**
   → faster, fewer iterations → `localagent report`

---

## Why nothing else does this

| | GitHub Copilot | Claude Code | **This** |
|---|---|---|---|
| Memory scope | per-repo | per-machine | **org-wide, yours** |
| Memory lifetime | 28 days | one laptop | **forever, git-versioned** |
| What it learns | facts | hand-written skills | **procedures (playbooks)** |
| Where it lives | GitHub's servers | local, siloed | **your infra, shared** |
| Auditable? | no | partial | **every write, hashed** |

Others remember *"this repo uses pytest."*
This writes the **recipe** — and hands it to a cheaper model next time.

---

## Compounding economics, auditable trust

**Two models, one brain.** Frontier model plans; a cheaper model executes the
distilled experience. The cost dial is one line in `.env`.

**Measured, not promised.** `localagent report`: playbook hit rate ↑,
escalation rate ↓, week over week.

**Audit everything.** Every action and memory write logged with content
hashes; every learned playbook is a file you can read, edit, or delete.

---

## Real today · next

**Real:** fresh clone → working agent in ~15 min on Windows/macOS/Linux ·
no Docker / no GPU — runs on a plain VM · 27 passing tests · verified Bedrock
pipeline · bundled demo repos · append-only audit trail

**Next:** human approval gate on playbook writes · org-shared memory on a
shared host · IDE integration via ACP

### Solve it once. Own what it learned. Watch the cost fall.
