"""MCP server for episodic memory — in-process, no containers, no downloads.

This replaces the former OpenMemory(mem0) + Qdrant + UI Docker stack. The whole
episodic layer now ships inside this package: embeddings come from AWS Bedrock
(Titan v2 — the same model the old stack used), vectors live in a local SQLite
file, and semantic search is a brute-force cosine in NumPy. There is nothing to
`docker compose up`, no image to build, no Qdrant binary to fetch, and no
`uvx mcp-proxy` bridge — Goose launches this as a plain stdio extension, exactly
like the curated-notes server.

Two memory layers, unchanged in spirit (see memory_direct.py):
  - Curated notes (memory_direct): verbatim markdown, the source of truth.
  - Episodic recall (HERE): semantic search over stored fragments — the
    supplemental long tail.

Unlike mem0, add_memories stores text VERBATIM (then embeds it). mem0 routed
writes through an extraction LLM that dropped detail in testing; storing the
text as written is both simpler and strictly less lossy. Tool names match the
OpenMemory MCP (add_memories / search_memory / list_memories /
delete_all_memories) so the orchestrator recipe and both agents work unchanged.

Storage:   MEMORY_EPISODIC_DIR/episodic.db   (SQLite; kept OUT of the curated
           notes dir so memory_direct's git snapshots don't churn on a binary)
Embedding: Bedrock MEMORY_EMBEDDER_MODEL (default Titan v2, 1024-dim), via the
           standard boto3 credential chain — same account as every other call.
"""

import datetime
import json
import os
import sqlite3

from fastmcp import FastMCP

mcp = FastMCP("memory-episodic")


def _user() -> str:
    return os.environ.get("MEMORY_USER_ID", "default")


def _dims() -> int:
    try:
        return int(os.environ.get("MEMORY_EMBEDDING_DIMS") or 1024)
    except ValueError:
        return 1024


def _embedder_model() -> str:
    return os.environ.get("MEMORY_EMBEDDER_MODEL") or "amazon.titan-embed-text-v2:0"


def _region() -> str:
    return (os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")


def _db_dir() -> str:
    d = os.environ.get(
        "MEMORY_EPISODIC_DIR",
        os.path.join(os.path.expanduser("~"), ".local", "share", "agent-episodic"),
    )
    os.makedirs(d, exist_ok=True)
    return d


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.join(_db_dir(), "episodic.db"))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memories (
               id         INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id    TEXT NOT NULL,
               app        TEXT,
               text       TEXT NOT NULL,
               vec        BLOB NOT NULL,
               dims       INTEGER NOT NULL,
               created_at TEXT NOT NULL
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON memories(user_id)")
    return conn


# ── embedding (Bedrock Titan) ─────────────────────────────────────────
# Lazy boto3 client so the server starts and lists tools even without AWS
# creds; the failure surfaces on the first add/search, not at launch.
_client = None


def _bedrock():
    global _client
    if _client is None:
        import boto3  # local import keeps cold-start light
        _client = boto3.client("bedrock-runtime", region_name=_region())
    return _client


def _embed(text: str):
    """Return a unit-normalized float32 vector for `text` (cosine == dot)."""
    import numpy as np

    body = {"inputText": text, "dimensions": _dims(), "normalize": True}
    resp = _bedrock().invoke_model(
        modelId=_embedder_model(), body=json.dumps(body)
    )
    vec = np.asarray(json.loads(resp["body"].read())["embedding"], dtype="float32")
    # Titan returns normalized vectors when normalize=true, but renormalize
    # defensively so cosine == dot holds even for other embedders.
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


# ── core logic (plain functions; the @mcp.tool wrappers below are thin) ──
# Keeping the logic out of the decorated callables lets the CLI doctor and the
# test suite exercise it directly, without going through the MCP transport.


def _add(text: str) -> dict:
    from .audit import log_event, sha

    if not text or not text.strip():
        return {"stored": False, "error": "text is required"}
    try:
        vec = _embed(text.strip())
    except Exception as exc:  # no creds / model access / network
        return {"stored": False,
                "error": f"episodic memory unavailable ({type(exc).__name__}: {exc})"}

    conn = _connect()
    try:
        dup = conn.execute(
            "SELECT id FROM memories WHERE user_id=? AND text=?",
            (_user(), text.strip()),
        ).fetchone()
        if dup:
            return {"stored": False, "id": dup[0], "duplicate": True}
        cur = conn.execute(
            "INSERT INTO memories (user_id, app, text, vec, dims, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (_user(), os.environ.get("MEMORY_APP_NAME", "unknown"),
             text.strip(), vec.tobytes(), _dims(),
             datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")),
        )
        conn.commit()
        mem_id = cur.lastrowid
    finally:
        conn.close()
    log_event("episodic_add", mem_id=mem_id, text_sha=sha(text))
    return {"stored": True, "id": mem_id}


def _search(query: str, limit: int = 5) -> dict:
    import numpy as np

    if not query or not query.strip():
        return {"results": [], "error": "query is required"}
    try:
        q = _embed(query.strip())
    except Exception as exc:
        return {"results": [],
                "error": f"episodic memory unavailable ({type(exc).__name__}: {exc})"}

    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT text, vec, created_at, app FROM memories "
            "WHERE user_id=? AND dims=?",
            (_user(), _dims()),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"results": []}

    mat = np.stack([np.frombuffer(r[1], dtype="float32") for r in rows])
    scores = mat @ q  # both unit-normalized → cosine similarity
    order = np.argsort(scores)[::-1][: max(1, int(limit))]
    return {"results": [
        {"memory": rows[i][0], "score": round(float(scores[i]), 4),
         "created_at": rows[i][2], "app": rows[i][3]}
        for i in order
    ]}


def _list(limit: int = 50) -> dict:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, text, created_at, app FROM memories WHERE user_id=? "
            "ORDER BY id DESC LIMIT ?",
            (_user(), max(1, int(limit))),
        ).fetchall()
    finally:
        conn.close()
    return {"results": [
        {"id": r[0], "memory": r[1], "created_at": r[2], "app": r[3]}
        for r in rows
    ]}


def _delete_all() -> dict:
    from .audit import log_event

    conn = _connect()
    try:
        n = conn.execute("DELETE FROM memories WHERE user_id=?", (_user(),)).rowcount
        conn.commit()
    finally:
        conn.close()
    log_event("episodic_delete_all", deleted=n)
    return {"deleted": n}


# ── tools (names mirror the OpenMemory MCP) ───────────────────────────


@mcp.tool
def add_memories(text: str) -> dict:
    """Store a fragment in episodic memory (verbatim) and index it for recall.

    Use this for supplemental context worth recalling semantically later —
    observations, partial results, breadcrumbs. For anything whose exact
    wording matters (preferences, decisions, playbooks), use the curated
    save_note instead. Unlike the old mem0 backend this stores the text as
    written; no extraction LLM, no silent loss. Exact duplicates for the same
    user are skipped.
    """
    return _add(text)


@mcp.tool
def search_memory(query: str, limit: int = 5) -> dict:
    """Semantically search episodic memory for fragments matching `query`.

    Call this in the RECALL step for the repo name, task category, and related
    past work. Returns the closest stored fragments with cosine scores. This is
    the supplemental layer — the curated memory index is authoritative.
    """
    return _search(query, limit)


@mcp.tool
def list_memories(limit: int = 50) -> dict:
    """List the most recent episodic fragments for this user (no search)."""
    return _list(limit)


@mcp.tool
def delete_all_memories() -> dict:
    """Delete ALL episodic fragments for this user. Irreversible.

    Curated notes (save_note) are untouched — this only clears the episodic
    semantic layer.
    """
    return _delete_all()


def main() -> None:
    mcp.run()  # stdio transport — launched by Goose / the coder wrapper


if __name__ == "__main__":
    main()
