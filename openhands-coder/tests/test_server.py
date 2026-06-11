"""Wrapper tests that run without any LLM or memory stack."""

import asyncio

from fastmcp import Client

from openhands_coder.server import mcp


def test_tools_exposed():
    async def _list():
        async with Client(mcp) as client:
            return {t.name for t in await client.list_tools()}

    names = asyncio.run(_list())
    assert {"delegate_coding_task", "coder_health"} <= names


def test_delegate_rejects_missing_repo():
    async def _call():
        async with Client(mcp) as client:
            res = await client.call_tool(
                "delegate_coding_task",
                {"spec": "noop", "repo_path": "/nonexistent/path/xyz"},
            )
            return res.data

    data = asyncio.run(_call())
    assert data["success"] is False
    assert "does not exist" in data["error"]


def test_delegate_requires_model_env(tmp_path, monkeypatch):
    # Empty (not deleted): the SDK calls load_dotenv() on import, which would
    # refill a deleted var from the repo-root .env, but never overrides one
    # that is set — even to "".
    monkeypatch.setenv("OPENHANDS_LLM_MODEL", "")

    async def _call():
        async with Client(mcp) as client:
            res = await client.call_tool(
                "delegate_coding_task",
                {"spec": "noop", "repo_path": str(tmp_path)},
            )
            return res.data

    data = asyncio.run(_call())
    assert data["success"] is False
    assert "OPENHANDS_LLM_MODEL" in data["error"]


def test_health_reports_config(monkeypatch):
    monkeypatch.setenv("OPENMEMORY_MCP_URL", "http://localhost:8765")
    monkeypatch.setenv("MEMORY_USER_ID", "tester")

    async def _call():
        async with Client(mcp) as client:
            res = await client.call_tool("coder_health", {})
            return res.data

    data = asyncio.run(_call())
    assert data["memory_attached"] is True
