"""memory-direct tests — file-based curated memory, no services needed."""

import asyncio

from fastmcp import Client

from openhands_coder.memory_direct import mcp


def _call(tool: str, args: dict):
    async def _run():
        async with Client(mcp) as client:
            res = await client.call_tool(tool, args)
            return res.data

    return asyncio.run(_run())


def test_tools_exposed():
    async def _list():
        async with Client(mcp) as client:
            return {t.name for t in await client.list_tools()}

    names = asyncio.run(_list())
    assert {"get_memory_index", "save_note", "read_note", "delete_note"} <= names


def test_round_trip_verbatim(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_NOTES_DIR", str(tmp_path))
    text = (
        "User prefers pytest fixtures over mocks, AND direct non-AI-sounding "
        "writing in docs. Both halves matter."
    )
    saved = _call(
        "save_note",
        {"title": "Testing and writing style", "text": text,
         "category": "preference", "hook": "before writing tests or docs"},
    )
    assert saved["saved"] is True

    index = _call("get_memory_index", {})
    assert "Testing and writing style" in index
    assert "before writing tests or docs" in index

    note = _call("read_note", {"path": saved["path"]})
    assert text in note  # verbatim — nothing extracted or dropped


def test_overwrite_updates_not_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_NOTES_DIR", str(tmp_path))
    _call("save_note", {"title": "Deploy api", "text": "v1 status: draft",
                        "category": "playbook"})
    _call("save_note", {"title": "Deploy api", "text": "v2 status: trusted",
                        "category": "playbook"})
    index = _call("get_memory_index", {})
    assert index.count("playbook/deploy-api.md") == 1
    note = _call("read_note", {"path": "playbook/deploy-api.md"})
    assert "trusted" in note and "draft" not in note


def test_delete_removes_note_and_index(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_NOTES_DIR", str(tmp_path))
    saved = _call("save_note", {"title": "Old way", "text": "x",
                                "category": "playbook"})
    assert _call("delete_note", {"path": saved["path"]})["deleted"] is True
    assert "Old way" not in _call("get_memory_index", {})


def test_path_traversal_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_NOTES_DIR", str(tmp_path))
    assert "ERROR" in _call("read_note", {"path": "../../etc/hosts"})
    assert _call("delete_note", {"path": "../x.md"})["deleted"] is False


def test_notes_are_git_versioned(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_NOTES_DIR", str(tmp_path))
    import subprocess

    _call("save_note", {"title": "First", "text": "v1", "category": "note"})
    _call("save_note", {"title": "First", "text": "v2", "category": "note"})
    log = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "--oneline"],
        capture_output=True, text=True,
    ).stdout
    assert len(log.strip().splitlines()) == 2  # one commit per change
    old = subprocess.run(
        ["git", "-C", str(tmp_path), "show", "HEAD~1:note/first.md"],
        capture_output=True, text=True,
    ).stdout
    assert "v1" in old  # history preserved — rollback possible


def test_bad_category_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_NOTES_DIR", str(tmp_path))
    res = _call("save_note", {"title": "t", "text": "x", "category": "vibes"})
    assert res["saved"] is False
