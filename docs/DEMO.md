# Demo: What Works Today

A scripted tour of the current system. All models run on AWS Bedrock
(Claude / Nova) — assumes setup is done (`SETUP_FRESH_MACHINE.md`),
AWS credentials work, and services are up (`./scripts/memory-up.sh` or
`localagent up`, all green on `./scripts/smoke-test.sh` / `localagent doctor`).

## Demo 1 — Shared memory, both layers (2 min)

```bash
# Curated layer (verbatim notes + index — the knowledge both agents trust):
cat ~/.local/share/agent-memory/INDEX.md
git -C ~/.local/share/agent-memory log --oneline | head   # every change versioned

# Episodic layer (semantic search over extracted fragments):
open http://localhost:3000        # browse memories in the OpenMemory UI
```

## Demo 2 — Delegated coding task, end to end (5 min)

Materialize the bundled sample repo (stubbed function + failing tests,
git-initialized, works on Windows too):

```bash
localagent demo-repo textstats /tmp/demo-textstats
cd /tmp/demo-textstats && uv run --with pytest pytest -q   # 3 failed — the starting state
```

(For the playbook-reuse beat afterwards: `localagent demo-repo csvstats ...`
— same task category, different content; run it AFTER textstats and watch
the orchestrator pass the learned playbook to the implementer.)

Delegate it straight to the implementer (the same tool Goose calls):

```bash
cd <this-repo>/openhands-coder
OPENHANDS_LLM_MODEL=bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
AWS_REGION=us-east-1 \
uv run python -c "
import asyncio
from fastmcp import Client
from openhands_coder.server import mcp
SPEC = '''Implement most_common_word in textstats/__init__.py per its
docstring. Verify with: uv run --with pytest pytest -q (all tests must pass).'''
async def main():
    async with Client(mcp) as c:
        r = await c.call_tool('delegate_coding_task',
            {'spec': SPEC, 'repo_path': '/tmp/demo-textstats'}, timeout=1800)
        print('files:', r.data['files_changed'])
        print(r.data['diff'][:800])
asyncio.run(main())"

cd /tmp/demo-textstats && uv run --with pytest pytest -q    # all pass — verified result
```

What just happened: MCP call → headless OpenHands agent in the repo →
Bedrock model via the boto3 credential chain → file edits → tests run →
structured diff back.

## Demo 3 — The full orchestrated loop (10 min)

```bash
goose run \
  --recipe <this-repo>/goose/recipes/plan-and-delegate.yaml \
  --params task='Implement most_common_word so all tests pass. Test command: uv run --with pytest pytest -q' \
  --params repo_path=/tmp/demo-textstats
```

Watch for the loop phases: index read (ORIENT) → episodic search (RECALL) →
spec written (PLAN) → delegate_coding_task call → diff review → save_note
calls (LEARN: playbook + preferences). Then inspect what it learned:

```bash
cat ~/.local/share/agent-memory/INDEX.md     # new playbook/notes appear here
localagent report                            # delegation/escalation metrics
```

## Demo 4 — Interactive session with memory (5 min)

```bash
goose session
```

Try:
- "What do you remember about me?" → reads the memory index + standing
  preferences (loaded deterministically every session).
- "Remember that I prefer tabs over spaces in Makefiles" → watch it call
  save_note; check `INDEX.md` after.
- "Use the coder to add a --version flag to <some toy repo>" → delegation
  from conversation.

## Demo 5 — The compliance story (2 min)

```bash
# Hash-only audit trail of everything the agents did:
cat ~/.local/share/agent-audit/audit-$(date +%F).jsonl | python3 -m json.tool --json-lines | head -40

# Everything bound to localhost — nothing listens externally:
lsof -nP -iTCP -sTCP:LISTEN | grep -E "8765|6333|3000"
```

## Cost / model notes

- Defaults: Claude Sonnet for planner + implementer, Nova Lite for memory
  extraction, Titan v2 for embeddings. The memory-side calls are tiny and
  cheap; the implementer dominates cost.
- To cut cost, set `OPENHANDS_LLM_MODEL=bedrock/us.amazon.nova-pro-v1:0` —
  the wrapper flags empty diffs and the recipe escalates after two failed
  delegations, so a weaker implementer degrades gracefully instead of
  silently failing.
- Tool-calling support varies by model — see the verified table in
  `BEDROCK_INTEGRATION.md` before swapping models.
