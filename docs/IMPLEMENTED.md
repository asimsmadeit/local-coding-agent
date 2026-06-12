# Implemented So Far

Running record of everything built in this project. Updated as work lands.
Status of every item below: **working and verified** unless marked otherwise.
Companion docs: `FINDINGS.md` (research/why), `IMPLEMENTATION_STEPS.md`
(the full plan this is executing), `README.md` (how to run).

Last updated: 2026-06-12

---

## 1. Research & planning (2026-06-10)

| Artifact | What it is |
|---|---|
| `FINDINGS.md` | Architecture audit backed by web research (24 primary sources, key claims cross-checked) + file-level audit of the Goose and OpenHands repos. Key verdicts: single-orchestrator over peer agents; model routing validated; distilling from Claude/Bedrock violates ToS (open teacher instead); memory must be external; Bedrock PrivateLink posture checks out. |
| `FINDINGS.md` §9 | Project thesis: "distill to context, not weights" — playbooks authored by the planner, executed by the local model, frontier-call decay curve as the headline metric. |
| `IMPLEMENTATION_STEPS.md` | 10-phase build plan with effort estimates, including Phase 4.5 (playbook flywheel). |
| `playbooks/README.md` | Playbook schema and lifecycle convention (draft → trusted → retired). |

## 2. Project scaffold

- Standalone git repo (home dir was accidentally a git repo; this project got
  its own), directory layout, `.gitignore` (secrets, venvs, data dirs).
- `.env.example` — every environment-specific value externalized: planner
  model (Bedrock), implementer endpoint (vLLM/llama.cpp), memory stack URLs,
  `MEMORY_USER_ID` shared by both agents, `MEMORY_NOTES_DIR`. Nothing is
  hardcoded anywhere; company migration = edit `.env`, re-run setup scripts.

## 3. Shared memory stack (episodic layer)

- `memory/docker-compose.yml` — Qdrant + OpenMemory MCP server + web UI
  (localhost-only binds). Persistence for both vectors (`memory/data/qdrant`)
  and metadata SQLite (`memory/data/api` via `DATABASE_URL` mount).
- `scripts/memory-up.sh` / `memory-down.sh` — idempotent bring-up that also:
  starts the local model servers, waits for health, pins the mem0 LLM/embedder
  config via the REST API (the image ignores env vars for this — config lives
  in its DB), and pre-creates the Qdrant collection at 768 dims (the image
  hardcodes 1536 and its config API silently drops `vector_store` settings).
- Verified end to end: write → extraction → embedding → storage → semantic
  recall, through the same MCP endpoint both agents mount
  (`/mcp/<client>/sse/<user-id>`).

## 4. Local model serving (memory backend)

- `scripts/local-llm-up.sh` — two llama.cpp servers, models auto-download:
  - `:8081` nomic-embed-text-v1.5 (embeddings, 768-dim)
  - `:8082` Qwen2.5-3B-Instruct Q4 (mem0 fact extraction; 1.5B was tried
    first and returned malformed JSON — too small for format adherence)
- `gateway/litellm.yaml` + LiteLLM proxy on `:4000` — single OpenAI-compatible
  URL routing by model name (mirrors the company-side vLLM+gateway design).
  Includes the `text-embedding-3-small` alias: LiteLLM only allows mem0's
  `dimensions` param for models named like OpenAI's — the alias maps that
  name onto the local nomic backend.
- **Why not Ollama:** brew formula 0.30.7 shipped without its `llama-server`
  runner binary; the official app binary hangs on any invocation on this
  managed Mac (likely endpoint-security interception). llama.cpp executes
  fine and serves the same API.

## 5. OpenHands coder — `openhands-coder/` (implementer)

- fastmcp server wrapping the OpenHands SDK as a **task-shaped** tool:
  `delegate_coding_task(spec, repo_path, playbook)` → spins up a headless
  agent (terminal + file editor + task tracker) in the target repo, runs to
  completion, returns `{success, summary, diff, files_changed, error}`.
  Deliberately non-conversational — full spec in, structured result out —
  per the multi-agent handoff failure research.
- The delegated agent mounts the same shared memory (OpenMemory SSE +
  memory-direct stdio) with the same user ID as Goose.
- `coder_health()` reports config status (LLM endpoint, memory attached,
  preferences loaded).
- Iteration ceiling via `OPENHANDS_MAX_ITERATIONS` (feature-detected against
  the SDK's Conversation signature) as the cost/runaway guard.
- Discovery encoded in a test: `openhands-sdk` calls `load_dotenv()` on
  import — repo-root `.env` files leak into its environment.
- Tests: 10/10 passing, no LLM or services required.

## 6. Curated memory — `memory_direct.py` (knowledge layer)

- MCP server exposing `get_memory_index` / `save_note` / `read_note` /
  `delete_note`. Notes are **verbatim markdown files** + an `INDEX.md`, under
  `MEMORY_NOTES_DIR` (default `~/.local/share/agent-memory`), shared by both
  agents, human-reviewable, path-traversal-guarded.
- Categories: preference, project, playbook, escalation, note. Re-saving the
  same title+category updates in place (playbook promotion); each note
  carries a hook line ("when to read this") in the index.
- **Why files, not vectors:** OpenMemory's extraction dropped half of a
  two-part preference in testing, and its `infer: false` raw mode silently
  stores nothing in the shipped image. Curated memory therefore bypasses the
  vector store entirely: markdown files + an index, loaded deterministically.
- Verified live: the exact preference the extractor truncated round-trips
  with both halves intact.

## 7. Deterministic preference loading

- `prefs/preferences.md` — standing user preferences, single source of truth
  (seeded: pytest fixtures over mocks; direct non-AI writing; verify-and-state
  workflow rules).
- Symlinked as Goose's **global hints file** (`~/.config/goose/.goosehints`)
  → in context every session, never retrieved.
- Injected by the wrapper into **every delegated task prompt**, along with
  the target repo's `AGENTS.md` if present.
- Symlink (not copy) so the recipe's LEARN step can append durable
  preferences and both consumers see the change immediately.

## 8. Repo instruction templates — `templates/`

- `templates/goosehints` and `templates/AGENTS.md` — fill-in starters to copy
  into each work repo (build/test commands, conventions, gotchas, do-nots).
  Goose auto-loads `.goosehints` natively; the wrapper injects `AGENTS.md`
  into delegated prompts. Deterministic context loading — injected every session, never retrieved.

## 9. Goose orchestrator configuration

- Goose 1.37 (brew `block-goose-cli`).
- `goose/config-template.yaml` rendered to `~/.config/goose/config.yaml` by
  `scripts/goose-setup.sh` (envsubst from `.env`; backs up what it replaces):
  - Planner: Bedrock provider (AWS credential chain); commented dev-mode
    block for any OpenAI-compatible endpoint.
  - Extensions: `developer` (builtin), `openmemory` (episodic memory via
    `uvx mcp-proxy` stdio bridge — Goose dropped SSE transport),
    `memory_direct` (curated notes), `openhands_coder` (delegation).
  - Auto-compaction at 80% context.
- `goose/recipes/plan-and-delegate.yaml` — the orchestrator loop:
  ORIENT (deterministic `get_memory_index` read, every task) → RECALL
  (targeted episodic search) → PLAN (self-contained spec with verification
  command) → DELEGATE (playbook + prefs auto-injected) → REVIEW (refine once;
  after second failure implement directly and save an escalation note) →
  LEARN (verbatim notes via `save_note`; playbook draft→trusted→retired
  lifecycle; durable preferences graduated into the standing file).

## 10. Distribution — pip-installable `localagent` CLI (2026-06-11)

- The package is now `local-coding-agent` (PyPI-ready): `pipx install` /
  `uv tool install` gives three console commands — **`localagent`** (the
  front door), `openhands-coder`, `memory-direct`.
- `localagent init` materializes all configs (compose, gateway, goose
  template, recipe, preferences, repo templates) into
  `~/.config/local-coding-agent/` from bundled package assets and checks
  host dependencies with install hints. `up`/`down` manage the full service
  stack (including the mem0 config pinning and 768-dim collection
  workarounds, ported from the bash scripts). `goose-setup` renders the
  Goose config + preference symlink. `doctor` is the smoke test (verified:
  11/11-equivalent all green against the live stack).
- **Why pip + Docker hybrid, not full containerization:** the services are
  already containers; the agents can't be — Goose is an interactive CLI on
  the user's repos, and llama.cpp inside Docker on macOS loses Metal (no GPU
  passthrough). The pip CLI orchestrates the host pieces.
- Goose extensions now launch console scripts by absolute path (works for
  both repo-dev via `uv tool install -e` and end-user installs); the wrapper
  locates `memory-direct` next to its own interpreter.
- Known drift risk (documented): `assets/` are copies of the repo configs —
  release checklist must re-sync them.

## 11. Audit log (2026-06-11)

- `audit.py` — append-only JSONL, one file per day under `AUDIT_LOG_DIR`
  (default `~/.local/share/agent-audit`). Content is **hashed, never raw**
  (spec/diff sha256 + sizes), so the log is SIEM-shippable without leaking
  source. Auditing never raises — a logging failure can't break the action.
- Wired into: `delegate_coding_task` (task_start/task_end with model, repo,
  duration, files changed, diff hash, error) and memory-direct (note_saved /
  note_deleted). Goose's own session logs complement this.
- 4 dedicated tests including a no-raw-content assertion. Suite: 14/14.

## 12. Flywheel instrumentation — `localagent report` (2026-06-11)

- `report.py` + CLI subcommand: aggregates the audit JSONL into weekly rows —
  delegations, success rate, **playbook hit rate** (should rise),
  escalations and **escalation rate** (should fall), notes saved, avg task
  duration. `--csv` for export. This is the v1 of the frontier-decay curve
  (FINDINGS §9); v2 (true token split) needs Goose session-DB parsing —
  documented in the module docstring.
- Pure functions over event dicts; 3 tests with synthetic two-week data
  asserting the decay-direction math. Suite: 17/17.

## 13. Durability warts fixed (2026-06-11)

- **Memory notes are git-versioned**: every save_note/delete_note auto-commits
  in `MEMORY_NOTES_DIR` (repo auto-inits; best-effort so git problems can't
  break memory writes). Full history of what the agents learned + rollback.
  Tested: one commit per change, prior versions retrievable.
- **Services survive reboots**: `localagent autostart` installs a launchd
  agent running the idempotent `localagent up` at login (`--remove` to
  uninstall). Installed and verified loaded on this machine.
- **OpenMemory REST list 500 — diagnosed, upstream**: the image's background
  memory-categorization step fails against non-OpenAI models
  (`RetryError[AttributeError]`), leaving rows that break the list
  endpoint's `Page[MemoryResponse]` validation. The MCP tools
  (list/search) and the filter endpoint use different code paths and work.
  Impact: cosmetic (one REST listing route). Workaround documented; not
  worth forking the image.

## 14. Live-fire: first verified end-to-end delegation (2026-06-11)

- **A delegated coding task completed successfully through the entire
  stack**: MCP call → openhands-coder wrapper → OpenHands SDK agent in a
  toy repo → LiteLLM gateway → local model → file edits → tests run →
  structured diff returned → audit-logged. Result: 5/5 tests passing,
  1.5 KB diff, independently verified outside the agent.
- Dev-tier implementer: **Qwen3-4B-Instruct** behind a stable `dev-coder`
  gateway alias (swap models without touching configs), served by llama.cpp
  with `--jinja` at **32k context** (OpenHands' opening prompt is ~9k tokens
  — 8k windows fail outright; observed).
- **Model findings (verified live, recorded in docs/BEDROCK_INTEGRATION.md):**
  - Qwen2.5-Coder-7B tool calling is broken in llama-server — pseudo-XML
    text even at temp 0 with the official template and tool_choice=required.
  - Qwen2.5-3B-Instruct and Qwen3-4B-Instruct produce correct structured
    tool calls.
  - A 3B implementer ran the full loop but **claimed success without editing
    anything** — the predicted weak-model failure. The wrapper now flags
    empty-diff completions with an explicit warning (the recipe's escalation
    trigger), so false completions can't pass silently.
- Setup/integration docs added: `docs/SETUP_FRESH_MACHINE.md`,
  `docs/BEDROCK_INTEGRATION.md` (incl. the structured-tool-call verification
  curl and context-window requirements), `docs/DEMO.md`.

## 15. Verification

- `scripts/smoke-test.sh` — 11 checks, no LLM credits needed: containers,
  API + SSE endpoint, all three model servers, an end-to-end memory write,
  wrapper test suite, Goose CLI + config. **11/11 passing.**
- Wrapper test suite: 10 tests (tool exposure, validation, env guard,
  verbatim round-trip, playbook overwrite semantics, path traversal,
  graceful failures).
- Live integration checks performed: OpenMemory tools over the SSE bridge;
  both wrapper servers over stdio exactly as Goose launches them; verbatim
  write → semantic recall across the stack.

## 16. Re-architecture: Bedrock-only, no local inference (2026-06-12)

Constraint change: no local compute/GPU available, and the stack must run on
Windows as well as macOS/Linux. Everything model-shaped moved to AWS Bedrock;
everything local-inference-shaped was removed.

- **Removed**: LiteLLM gateway (`gateway/`, the `:4000` proxy, the
  `text-embedding-3-small` alias hack), `scripts/local-llm-up.sh`, both
  llama.cpp servers (:8081 embedder, :8082 extraction), the `dev-coder`
  local implementer tier (Qwen3-4B), all Ollama config remnants, and the
  packaged copies of these in `openhands-coder/.../assets/`.
- **Model sockets now** (all Bedrock, `.env`-configurable): planner =
  Claude Sonnet; implementer = `bedrock/us.anthropic.claude-sonnet-...`
  (Nova Pro as the cheap alternative); mem0 extraction =
  `us.amazon.nova-lite-v1:0`; embeddings = `amazon.titan-embed-text-v2:0`
  (1024-dim — qdrant collection pre-created accordingly).
- **Memory container auth**: host `~/.aws` mounted read-only +
  `AWS_*` env passthrough in `memory/docker-compose.yml`; `memory-up` /
  `localagent up` pin mem0's `aws_bedrock` provider via the config API and
  now FAIL LOUDLY if the API rejects the config (previously silent).
- **Windows compatibility** (`localagent` CLI, stdlib-only): removed the
  POSIX-only process spawning and pkill calls (nothing left to spawn);
  `.goosehints` symlink falls back to copy where symlinks need privileges;
  `autostart` now supports launchd (macOS), Startup-folder .bat (Windows),
  and XDG autostart (Linux). `scripts/*.sh` remain as macOS/Linux
  conveniences; the CLI is the cross-platform path.
- **Live-verified up to the AWS credential boundary (2026-06-12)** — and the
  verification caught three real blockers, all fixed:
  1. The OpenMemory image ships WITHOUT boto3 → `aws_bedrock` provider could
     never load. Fixed: derived image (`memory/openmemory-bedrock.Dockerfile`,
     compose `build:`).
  2. Setting `AWS_PROFILE` in the container (even empty) makes boto3 raise
     ProfileNotFound BEFORE trying env keys (verified empirically in the
     image). Fixed: container gets no AWS_PROFILE; default profile or
     static keys only.
  3. A qdrant collection left over from the old 768-dim local embedder would
     reject every 1024-dim Titan write. Fixed: old points backed up
     (`memory/data/qdrant-768dim-backup-2026-06-12.json`), collection
     recreated at 1024; `memory-up.sh` now fails loudly on a dim mismatch.
  Also fixed during verification: `localagent doctor` had two false
  positives (passed on an empty `~/.aws` dir; treated HTTP 200 with an
  `{"error": ...}` body as a successful memory write) — both now read the
  actual evidence. Windows `.exe` console-script lookups fixed in doctor/
  autostart; `localagent init` now also checks for the AWS CLI; `up` ensures
  `~/.aws` exists before the bind mount and passes `--build`.
  Fresh-install dress rehearsal (clean copy → `uv tool install` → `init` →
  `up` → `goose-setup` → `doctor`) passes with only the two AWS-credential
  checks failing, each naming the exact fix. Run-sheet: `docs/WINDOWS_VM.md`.
  Still pending real credentials: one live Bedrock memory write + one real
  delegated task. Wrapper unit tests: 18/18 passing.

## Not yet wired (by design — needs company side)

- **PrivateLink endpoint + scoped endpoint policy** for Bedrock (Phase 2) —
  credentials/model access from any machine work in the meantime.
- Evaluation harness, escalation/decay-curve dashboards, finetuning track —
  Phases 6–8 of `IMPLEMENTATION_STEPS.md`, not started.
