"""MCP server wrapping an OpenHands SDK agent as a delegated coding tool.

Shape B integration (see docs/FINDINGS.md §1): the orchestrator (Goose) hands this
server a complete, self-contained task spec and gets back a structured result.
The interface is deliberately task-shaped — full spec in, diff + summary out —
never conversational, because mid-task conversational handoffs between agents
are the documented multi-agent failure mode.

Both this agent and the orchestrator mount the same OpenMemory MCP endpoint,
so memories written by either side are visible to both.
"""

import os
import subprocess
from dataclasses import dataclass, field

from fastmcp import FastMCP

mcp = FastMCP("openhands-coder")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _git(repo_path: str, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _memory_mcp_config(client_name: str) -> dict:
    """Shared-memory MCP config, if the OpenMemory stack is configured."""
    base = _env("OPENMEMORY_MCP_URL")
    user = _env("MEMORY_USER_ID")
    if not base or not user:
        return {}
    servers = {
        "openmemory": {
            "url": f"{base.rstrip('/')}/mcp/{client_name}/sse/{user}",
        }
    }
    # Curated notes (verbatim files + index). The console script lives next
    # to our interpreter in both dev (uv venv) and installed (uv tool/pipx).
    import sys
    memory_direct = os.path.join(os.path.dirname(sys.executable), "memory-direct")
    if os.path.isfile(memory_direct):
        servers["memory_direct"] = {"command": memory_direct, "args": []}
    return servers


def _standing_context(repo_path: str) -> str:
    """Deterministically loaded context: standing user preferences (global)
    plus the repo's AGENTS.md conventions, if present. Injected into every
    task, never retrieved."""
    sections = []
    prefs_file = _env("PREFERENCES_FILE")
    if prefs_file and os.path.isfile(prefs_file):
        try:
            with open(prefs_file, encoding="utf-8") as f:
                sections.append(
                    "--- STANDING USER PREFERENCES ---\n" + f.read().strip()
                )
        except OSError:
            pass
    agents_md = os.path.join(repo_path, "AGENTS.md")
    if os.path.isfile(agents_md):
        try:
            with open(agents_md, encoding="utf-8") as f:
                sections.append(
                    "--- REPO CONVENTIONS (AGENTS.md) ---\n" + f.read().strip()
                )
        except OSError:
            pass
    return "\n\n".join(sections)


@dataclass
class TaskResult:
    success: bool
    summary: str
    diff: str = ""
    files_changed: list[str] = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "summary": self.summary,
            "diff": self.diff,
            "files_changed": self.files_changed,
            "error": self.error,
        }


def _run_openhands_task(spec: str, repo_path: str, playbook: str) -> TaskResult:
    # Imported lazily so the server can start (and list tools) even before
    # the SDK env is fully configured.
    from openhands.sdk import LLM, Agent, Conversation, Tool
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.task_tracker import TaskTrackerTool
    from openhands.tools.terminal import TerminalTool

    model = _env("OPENHANDS_LLM_MODEL")
    if not model:
        return TaskResult(
            success=False, summary="",
            error="OPENHANDS_LLM_MODEL is not set — configure the implementer "
                  "LLM in .env (LiteLLM format, e.g. openai/qwen3-coder-30b).",
        )

    llm = LLM(
        model=model,
        api_key=_env("OPENHANDS_LLM_API_KEY") or None,
        base_url=_env("OPENHANDS_LLM_BASE_URL") or None,
    )

    agent_kwargs: dict = {
        "llm": llm,
        "tools": [
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name=TaskTrackerTool.name),
        ],
    }
    memory_servers = _memory_mcp_config(client_name="openhands")
    if memory_servers:
        agent_kwargs["mcp_config"] = {"mcpServers": memory_servers}

    agent = Agent(**agent_kwargs)

    final_messages: list[str] = []

    def _collect(event):
        try:
            from openhands.sdk import LLMConvertibleEvent
        except ImportError:
            return
        if isinstance(event, LLMConvertibleEvent):
            msg = event.to_llm_message()
            role = getattr(msg, "role", None) or (
                msg.get("role") if isinstance(msg, dict) else None
            )
            if role == "assistant":
                content = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else ""
                )
                final_messages.append(str(content))

    before = _git(repo_path, "rev-parse", "HEAD").strip()

    convo_kwargs: dict = {
        "agent": agent, "workspace": repo_path, "callbacks": [_collect]
    }
    # Iteration ceiling = escalation guard / cost control (param name has
    # varied across SDK versions, so feature-detect it).
    import inspect
    max_iters = int(_env("OPENHANDS_MAX_ITERATIONS", "50"))
    sig = inspect.signature(Conversation)
    for param in ("max_iteration_per_run", "max_iterations"):
        if param in sig.parameters:
            convo_kwargs[param] = max_iters
            break

    conversation = Conversation(**convo_kwargs)

    parts = []
    standing = _standing_context(repo_path)
    if standing:
        parts.append(standing)
    if playbook:
        parts.append(
            "Follow this validated playbook where it applies. If a step does "
            "not fit the actual code you find, deviate and say why in your "
            "final summary.\n\n--- PLAYBOOK ---\n" + playbook +
            "\n--- END PLAYBOOK ---"
        )
    parts.append("--- TASK ---\n" + spec)
    prompt = "\n\n".join(parts)

    conversation.send_message(prompt)
    conversation.run()

    diff = _git(repo_path, "diff", "HEAD") if before else _git(repo_path, "diff")
    status = _git(repo_path, "status", "--porcelain")
    files = [line[3:] for line in status.splitlines() if len(line) > 3]

    summary = final_messages[-1] if final_messages else "(agent produced no final message)"
    # Weak models claim success without editing anything (observed live with
    # a 3B implementer). An empty diff on an implementation task is the
    # orchestrator's signal to refine or escalate — flag it loudly.
    error = ""
    if not diff.strip() and not files:
        error = ("WARNING: agent reported completion but produced NO file "
                 "changes — do not trust the summary; verify, refine the "
                 "spec, or escalate.")
    return TaskResult(success=True, summary=summary, diff=diff,
                      files_changed=files, error=error)


@mcp.tool
def delegate_coding_task(spec: str, repo_path: str, playbook: str = "") -> dict:
    """Delegate a self-contained coding task to the OpenHands implementer agent.

    Args:
        spec: COMPLETE task specification. Include everything the implementer
            needs: goal, acceptance criteria, relevant file paths, constraints,
            and how to verify (e.g. the test command). The implementer cannot
            ask follow-up questions.
        repo_path: Absolute path to the repository/workspace to operate in.
        playbook: Optional validated playbook (markdown procedure) retrieved
            from shared memory for this task category.

    Returns:
        {success, summary, diff, files_changed, error} — review the diff before
        accepting; on failure or empty diff, consider escalating to the planner.
    """
    import time

    from .audit import log_event, sha

    started = time.monotonic()
    log_event(
        "task_start", spec_sha=sha(spec), spec_bytes=len(spec),
        repo=repo_path, model=_env("OPENHANDS_LLM_MODEL") or "(unset)",
        playbook_used=bool(playbook),
    )
    if not os.path.isdir(repo_path):
        result = TaskResult(
            success=False, summary="", error=f"repo_path does not exist: {repo_path}"
        )
    else:
        try:
            result = _run_openhands_task(spec, repo_path, playbook)
        except Exception as exc:  # surface, don't crash the MCP server
            result = TaskResult(
                success=False, summary="",
                error=f"{type(exc).__name__}: {exc}",
            )
    log_event(
        "task_end", spec_sha=sha(spec), success=result.success,
        duration_s=round(time.monotonic() - started, 1),
        files_changed=result.files_changed, diff_sha=sha(result.diff),
        diff_bytes=len(result.diff), error=result.error[:300],
    )
    return result.as_dict()


@mcp.tool
def coder_health() -> dict:
    """Report wrapper configuration status (LLM endpoint, shared memory wiring)."""
    prefs = _env("PREFERENCES_FILE")
    return {
        "llm_model": _env("OPENHANDS_LLM_MODEL") or "(unset)",
        "llm_base_url": _env("OPENHANDS_LLM_BASE_URL") or "(unset)",
        "memory_attached": bool(_memory_mcp_config("openhands")),
        "preferences_loaded": bool(prefs and os.path.isfile(prefs)),
        "max_iterations": _env("OPENHANDS_MAX_ITERATIONS", "50"),
    }


def main() -> None:
    mcp.run()  # stdio transport — launched by the orchestrator (Goose)


if __name__ == "__main__":
    main()
