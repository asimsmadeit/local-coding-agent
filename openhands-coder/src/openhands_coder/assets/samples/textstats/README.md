# textstats — demo sample 1 (first-time task)

A tiny package with a stubbed function and a failing test suite. Use it to
demo the agent solving a task it has never seen — the LEARN step should
write a new playbook afterwards.

Starting state: `uv run --with pytest pytest -q` → 3 failed.

Run the agent on it:

```
goose run --recipe <home>/plan-and-delegate.yaml \
  --params task='Implement most_common_word in textstats/__init__.py per its docstring. Verify with: uv run --with pytest pytest -q (all tests must pass).' \
  --params repo_path=<this directory>
```
