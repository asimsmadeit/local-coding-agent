"""Append-only JSONL audit log — the compliance artifact.

Every consequential agent action gets one line: timestamps, content hashes
(not raw content — the log must be safe to ship to a SIEM without leaking
source code), and outcome. One file per day under AUDIT_LOG_DIR.

Used by the coder wrapper (task start/end) and memory-direct (note writes/
deletes). Goose's own session logs live in ~/.local/state/goose/logs and
complement this; scripts/decay_report.py reads both.
"""

import datetime
import hashlib
import json
import os
import threading

_lock = threading.Lock()


def audit_dir() -> str:
    d = os.environ.get(
        "AUDIT_LOG_DIR",
        os.path.join(os.path.expanduser("~"), ".local", "share", "agent-audit"),
    )
    os.makedirs(d, exist_ok=True)
    return d


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def log_event(kind: str, **fields) -> str:
    """Append one event; returns the path written. Never raises — auditing
    must not break the action being audited (failures go to stderr)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    record = {
        "ts": now.isoformat(timespec="seconds"),
        "kind": kind,
        "app": os.environ.get("MEMORY_APP_NAME", "unknown"),
        **fields,
    }
    path = os.path.join(audit_dir(), f"audit-{now.date().isoformat()}.jsonl")
    try:
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:  # pragma: no cover
        import sys
        print(f"audit write failed: {exc}", file=sys.stderr)
    return path
