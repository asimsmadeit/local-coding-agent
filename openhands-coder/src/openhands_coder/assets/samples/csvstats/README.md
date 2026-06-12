# csvstats — demo sample 2 (playbook reuse)

Same task CATEGORY as textstats (implement a stubbed function from its
docstring until the tests pass) but different content. Run this AFTER
textstats: the orchestrator should find the playbook written by the first
run and pass it to the implementer — that's the learning beat of the demo.

Starting state: `uv run --with pytest pytest -q` → 4 failed.

Run the agent on it:

```
goose run --recipe <home>/plan-and-delegate.yaml \
  --params task='Implement column_mean in csvstats/__init__.py per its docstring. Verify with: uv run --with pytest pytest -q (all tests must pass).' \
  --params repo_path=<this directory>
```
