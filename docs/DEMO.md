# Demo: What Works Today

A scripted tour of the current system using only local models — no AWS, no
company resources. Assumes setup is done (`docs/SETUP_FRESH_MACHINE.md`) and
services are up (`./scripts/memory-up.sh`, 11/11 on `./scripts/smoke-test.sh`).

The dev tier runs Qwen3-4B as the implementer ("dev-coder" gateway alias).
Expectation-setting: a 4B model demonstrates the *machinery* — real planning
quality arrives when the planner socket points at Bedrock Claude
(`docs/BEDROCK_INTEGRATION.md`).

## Demo 1 — Shared memory, both layers (2 min)

```bash
# Curated layer (verbatim notes + index — the knowledge both agents trust):
cat ~/.local/share/agent-memory/INDEX.md
git -C ~/.local/share/agent-memory log --oneline | head   # every change versioned

# Episodic layer (semantic search over extracted fragments):
open http://localhost:3000        # browse memories in the OpenMemory UI
```

## Demo 2 — Delegated coding task, end to end (5 min)

Create a toy repo with a failing test suite:

```bash
rm -rf /tmp/demo-repo && mkdir -p /tmp/demo-repo/textstats && cd /tmp/demo-repo
cat > textstats/__init__.py <<'EOF'
def most_common_word(text: str) -> str:
    """Most frequent word, lowercased, punctuation ignored, ties by first
    occurrence. Raises ValueError on empty input."""
    raise NotImplementedError
EOF
cat > test_demo.py <<'EOF'
import pytest
from textstats import most_common_word

def test_basic():
    assert most_common_word("the cat and the hat") == "the"

def test_punct_case():
    assert most_common_word("Dog! dog, bird. DOG bird") == "dog"

def test_empty():
    with pytest.raises(ValueError):
        most_common_word("  ")
EOF
git init -q && git add -A && git -c user.name=demo -c user.email=d@d commit -qm init
python3 -m pytest -q   # 2 failed, 1 passed — the starting state
```

Delegate it straight to the implementer (the same tool Goose calls):

```bash
cd <this-repo>/openhands-coder
OPENHANDS_LLM_MODEL=openai/dev-coder \
OPENHANDS_LLM_BASE_URL=http://localhost:4000/v1 \
OPENHANDS_LLM_API_KEY=local \
uv run python -c "
import asyncio
from fastmcp import Client
from openhands_coder.server import mcp
SPEC = '''Implement most_common_word in textstats/__init__.py per its
docstring. Verify with: python3 -m pytest -q (all tests must pass).'''
async def main():
    async with Client(mcp) as c:
        r = await c.call_tool('delegate_coding_task',
            {'spec': SPEC, 'repo_path': '/tmp/demo-repo'}, timeout=1800)
        print('files:', r.data['files_changed'])
        print(r.data['diff'][:800])
asyncio.run(main())"

cd /tmp/demo-repo && python3 -m pytest -q    # all pass — verified result
```

What just happened: MCP call → headless OpenHands agent in the repo →
local model through the gateway → file edits → tests run → structured
diff back. (First verified live: 2026-06-11, 5/5 tests, 1.5 KB diff.)

## Demo 3 — The full orchestrated loop (10 min)

```bash
OPENAI_API_KEY=local goose run \
  --recipe <this-repo>/goose/recipes/plan-and-delegate.yaml \
  --params task='Implement most_common_word so all tests pass. Test command: python3 -m pytest -q' \
  --params repo_path=/tmp/demo-repo
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
OPENAI_API_KEY=local goose session
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
lsof -nP -iTCP -sTCP:LISTEN | grep -E "8765|6333|8081|8082|8083|4000"
```

## Known dev-tier limits (expected, by design)

- Sub-7B implementers can claim success without making changes — the wrapper
  flags empty diffs and the recipe escalates (observed live with a 3B; the
  warning text in the result is the flywheel's escalation trigger).
- The 4B planner follows the recipe loosely; spec quality and playbook
  writing improve dramatically with a frontier planner.
- Tool-calling support varies by model — see the verified table in
  `docs/BEDROCK_INTEGRATION.md` before swapping models.
