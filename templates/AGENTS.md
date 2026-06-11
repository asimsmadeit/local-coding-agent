# AGENTS.md — copy to the ROOT of each work repo and fill in.
# The OpenHands coder wrapper injects this file into every delegated task
# prompt for this repo (and OpenHands tooling reads AGENTS.md natively).
# Keep it in sync with .goosehints — same facts, this one is for the
# implementer, so emphasize build/test mechanics over planning context.

## Build & test
- Install: <command>
- Run tests: <command — run this before reporting success>
- Lint/typecheck: <command>

## Code conventions
- <style, naming, error-handling patterns to match>

## Do not
- <files/dirs never to edit (generated code, vendored deps)>
- Do not commit or push; return changes as a working-tree diff.
