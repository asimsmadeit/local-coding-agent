"""memory-episodic tests — in-process semantic memory, no containers, no Bedrock.

The embedding call is monkeypatched with a deterministic bag-of-words vector so
the store + cosine-ranking + dedup logic is exercised without AWS credentials.
"""

import asyncio

import numpy as np
from fastmcp import Client

from openhands_coder import memory_episodic as m

VOCAB = ["deploy", "api", "terraform", "pytest", "fixtures", "tea", "beverage"]


def _fake_embed(text: str):
    """Multi-hot over a tiny vocab, unit-normalized → cosine == dot."""
    toks = text.lower().split()
    vec = np.array([float(w in toks) for w in VOCAB], dtype="float32")
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else np.ones(len(VOCAB), dtype="float32")


def _isolate(monkeypatch, tmp_path, user="tester"):
    monkeypatch.setattr(m, "_embed", _fake_embed)
    monkeypatch.setenv("MEMORY_EPISODIC_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_USER_ID", user)


def test_tools_exposed():
    async def _list():
        async with Client(m.mcp) as client:
            return {t.name for t in await client.list_tools()}

    names = asyncio.run(_list())
    assert {"add_memories", "search_memory", "list_memories",
            "delete_all_memories"} <= names


def test_store_and_semantic_recall(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert m._add("deploy the api with terraform")["stored"] is True
    assert m._add("the user prefers pytest fixtures")["stored"] is True

    hits = m._search("how do we deploy the api", limit=1)["results"]
    assert len(hits) == 1
    assert "terraform" in hits[0]["memory"]      # deploy/api beat pytest note
    assert hits[0]["score"] > 0


def test_dedup_same_text(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    first = m._add("user likes tea")
    second = m._add("user likes tea")
    assert first["stored"] is True
    assert second["stored"] is False and second.get("duplicate") is True


def test_per_user_isolation(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, user="alice")
    m._add("deploy api terraform")
    monkeypatch.setenv("MEMORY_USER_ID", "bob")
    assert m._search("deploy api", limit=5)["results"] == []


def test_delete_all(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    m._add("deploy api terraform")
    m._add("pytest fixtures")
    assert m._delete_all()["deleted"] == 2
    assert m._list()["results"] == []


def test_empty_text_rejected(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert m._add("   ")["stored"] is False
