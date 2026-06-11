"""Audit log tests — no services needed."""

import asyncio
import json
import os

from fastmcp import Client


def _read_events(audit_dir: str) -> list[dict]:
    events = []
    for name in sorted(os.listdir(audit_dir)):
        if name.startswith("audit-") and name.endswith(".jsonl"):
            with open(os.path.join(audit_dir, name), encoding="utf-8") as f:
                events.extend(json.loads(line) for line in f if line.strip())
    return events


def test_log_event_writes_parseable_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path))
    from openhands_coder.audit import log_event

    log_event("task_start", spec_sha="abc", repo="/x")
    log_event("task_end", spec_sha="abc", success=False)
    events = _read_events(str(tmp_path))
    assert [e["kind"] for e in events] == ["task_start", "task_end"]
    assert all("ts" in e for e in events)


def test_delegate_failure_is_audited(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    from openhands_coder.server import mcp

    async def _call():
        async with Client(mcp) as client:
            await client.call_tool(
                "delegate_coding_task",
                {"spec": "noop", "repo_path": "/nonexistent/xyz"},
            )

    asyncio.run(_call())
    events = _read_events(str(tmp_path / "audit"))
    kinds = [e["kind"] for e in events]
    assert kinds == ["task_start", "task_end"]
    end = events[-1]
    assert end["success"] is False and "does not exist" in end["error"]
    assert end["duration_s"] >= 0


def test_note_save_is_audited(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("MEMORY_NOTES_DIR", str(tmp_path / "notes"))
    from openhands_coder.memory_direct import mcp

    async def _call():
        async with Client(mcp) as client:
            await client.call_tool(
                "save_note",
                {"title": "T", "text": "body", "category": "note"},
            )

    asyncio.run(_call())
    events = _read_events(str(tmp_path / "audit"))
    assert events[-1]["kind"] == "note_saved"
    assert "text" not in events[-1]  # hashes only — no content leaks


def test_audit_never_stores_raw_content(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path))
    from openhands_coder.audit import log_event, sha

    secret = "API_KEY=super-secret-value"
    log_event("task_end", diff_sha=sha(secret), diff_bytes=len(secret))
    raw = open(
        os.path.join(str(tmp_path), os.listdir(str(tmp_path))[0]),
        encoding="utf-8",
    ).read()
    assert "super-secret-value" not in raw
