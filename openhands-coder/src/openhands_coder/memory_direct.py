"""MCP server for curated, verbatim memory — plain markdown files + index.

Why files, not the vector store: OpenMemory's write path routes everything
through mem0's extraction LLM (lossy — it dropped half of a two-part
preference in testing), and its `infer: false` raw mode silently stores
nothing in the shipped image. More importantly, Claude Code's memory model —
the thing this stack is mimicking — IS files: one note per fact, an index
loaded deterministically each session, content written verbatim by the model
that authored it. This server reproduces that for both agents.

Layout under MEMORY_NOTES_DIR:
    INDEX.md                       one line per note — read this every session
    <category>/<slug>.md           the notes (preference/project/playbook/...)

OpenMemory (the other extension) remains the EPISODIC layer: semantic search
over extracted fragments. Curated knowledge lives here, episodic recall there.

Shared by both agents: Goose mounts this as a stdio extension; the coder
wrapper adds it to the delegated agent's mcp_config. Same MEMORY_NOTES_DIR →
same notes.
"""

import datetime
import os
import re
import shutil
import subprocess

from fastmcp import FastMCP

mcp = FastMCP("memory-direct")

CATEGORIES = ("preference", "project", "playbook", "escalation", "note")


def _notes_dir() -> str:
    d = os.environ.get(
        "MEMORY_NOTES_DIR",
        os.path.join(os.path.expanduser("~"), ".local", "share", "agent-memory"),
    )
    os.makedirs(d, exist_ok=True)
    return d


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "untitled"


def _index_path() -> str:
    return os.path.join(_notes_dir(), "INDEX.md")


def _git_snapshot(message: str) -> None:
    """Version every memory change — full history of what the agents learned,
    and instant rollback if a bad note slips in. Best-effort: memory writes
    must not fail because git does."""
    base = _notes_dir()
    if not shutil.which("git"):
        return
    try:
        if not os.path.isdir(os.path.join(base, ".git")):
            subprocess.run(["git", "-C", base, "init", "-q"], check=True, timeout=30)
        subprocess.run(["git", "-C", base, "add", "-A"], check=True, timeout=30)
        subprocess.run(
            ["git", "-C", base, "-c", "user.name=memory-direct",
             "-c", "user.email=memory@localagent", "commit", "-q",
             "-m", message],
            check=False, timeout=30, capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        pass


def _rewrite_index_line(rel_path: str, line: str | None) -> None:
    """Add/replace (or remove, if line is None) this note's index entry."""
    path = _index_path()
    lines: list[str] = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f]
    else:
        lines = ["# Memory index", ""]
    lines = [l for l in lines if f"({rel_path})" not in l]
    if line is not None:
        lines.append(line)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


@mcp.tool
def get_memory_index() -> str:
    """Read the memory index — call this once at the START of every session.

    Returns one line per stored note (title, category, hook, file path).
    Use read_note on any entry that looks relevant to the current task.
    """
    path = _index_path()
    if not os.path.isfile(path):
        return "(no memories yet)"
    with open(path, encoding="utf-8") as f:
        return f.read()


@mcp.tool
def save_note(title: str, text: str, category: str = "note", hook: str = "") -> dict:
    """Save a curated memory note VERBATIM as a markdown file, and index it.

    Use this (not OpenMemory's add_memories) for anything whose exact wording
    matters: user preferences, project decisions, playbooks, escalation
    records. Compose `text` as a complete, self-contained note — future
    sessions see only this text. Include provenance (date, source task) for
    playbooks and decisions. Saving again with the same title and category
    overwrites the note (use this to update playbook status).

    Args:
        title: Short imperative title; becomes the filename slug.
        text: Full markdown body, stored exactly as written.
        category: preference | project | playbook | escalation | note.
        hook: One-line summary for the index (when to read this note).
    """
    cat = category.strip().lower()
    if cat not in CATEGORIES:
        return {"saved": False, "error": f"category must be one of {CATEGORIES}"}
    if not text.strip() or not title.strip():
        return {"saved": False, "error": "title and text are required"}

    base = _notes_dir()
    os.makedirs(os.path.join(base, cat), exist_ok=True)
    rel_path = os.path.join(cat, _slugify(title) + ".md")
    today = datetime.date.today().isoformat()
    body = (
        f"# {title.strip()}\n\n"
        f"_category: {cat} · updated: {today} · app: "
        f"{os.environ.get('MEMORY_APP_NAME', 'unknown')}_\n\n"
        f"{text.strip()}\n"
    )
    with open(os.path.join(base, rel_path), "w", encoding="utf-8") as f:
        f.write(body)
    _rewrite_index_line(
        rel_path, f"- [{title.strip()}]({rel_path}) — {cat}: {hook.strip() or title.strip()}"
    )
    from .audit import log_event, sha
    log_event("note_saved", path=rel_path, category=cat, text_sha=sha(text))
    _git_snapshot(f"save {rel_path}")
    return {"saved": True, "path": rel_path}


@mcp.tool
def read_note(path: str) -> str:
    """Read a note by its index path (e.g. 'playbook/add-api-endpoint.md')."""
    full = os.path.realpath(os.path.join(_notes_dir(), path))
    if not full.startswith(os.path.realpath(_notes_dir()) + os.sep):
        return "ERROR: path escapes the memory directory"
    if not os.path.isfile(full):
        return f"ERROR: no such note: {path}"
    with open(full, encoding="utf-8") as f:
        return f.read()


@mcp.tool
def delete_note(path: str) -> dict:
    """Delete a note and its index entry (e.g. a retired playbook)."""
    full = os.path.realpath(os.path.join(_notes_dir(), path))
    if not full.startswith(os.path.realpath(_notes_dir()) + os.sep):
        return {"deleted": False, "error": "path escapes the memory directory"}
    if not os.path.isfile(full):
        return {"deleted": False, "error": f"no such note: {path}"}
    os.remove(full)
    _rewrite_index_line(path, None)
    from .audit import log_event
    log_event("note_deleted", path=path)
    _git_snapshot(f"delete {path}")
    return {"deleted": True}


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
