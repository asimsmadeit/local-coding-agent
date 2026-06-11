"""Flywheel instrumentation: weekly delegation/escalation/playbook metrics.

The thesis metric (FINDINGS §9) is the frontier-call decay curve: as the
playbook library grows, the share of work needing the frontier planner should
fall. v1 measures the two proxies available locally:

- escalation rate  = escalation notes / delegated tasks   (falling = good)
- playbook hit rate = delegations that carried a playbook  (rising = good)

Data sources: the audit JSONL (task_start/task_end, note_saved) — nothing
else needed. True frontier-vs-local TOKEN split requires parsing Goose's
session DB; documented as the v2 upgrade.

Pure functions over event dicts so tests need no filesystem.
"""

import csv
import datetime
import io
import json
import os
from collections import defaultdict


def load_events(audit_dir: str) -> list[dict]:
    events = []
    if not os.path.isdir(audit_dir):
        return events
    for name in sorted(os.listdir(audit_dir)):
        if name.startswith("audit-") and name.endswith(".jsonl"):
            with open(os.path.join(audit_dir, name), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
    return events


def _week(ts: str) -> str:
    date = datetime.date.fromisoformat(ts[:10])
    year, week, _ = date.isocalendar()
    return f"{year}-W{week:02d}"


def weekly_metrics(events: list[dict]) -> list[dict]:
    """Aggregate audit events into one row per ISO week."""
    weeks: dict[str, dict] = defaultdict(
        lambda: {"delegations": 0, "successes": 0, "playbook_hits": 0,
                 "escalations": 0, "notes_saved": 0, "total_duration_s": 0.0}
    )
    for ev in events:
        if "ts" not in ev:
            continue
        bucket = weeks[_week(ev["ts"])]
        kind = ev.get("kind")
        if kind == "task_start":
            bucket["delegations"] += 1
            if ev.get("playbook_used"):
                bucket["playbook_hits"] += 1
        elif kind == "task_end":
            if ev.get("success"):
                bucket["successes"] += 1
            bucket["total_duration_s"] += ev.get("duration_s", 0) or 0
        elif kind == "note_saved":
            bucket["notes_saved"] += 1
            if ev.get("category") == "escalation":
                bucket["escalations"] += 1

    rows = []
    for week in sorted(weeks):
        b = weeks[week]
        n = b["delegations"]
        rows.append({
            "week": week,
            "delegations": n,
            "success_rate": round(b["successes"] / n, 2) if n else 0.0,
            "playbook_hit_rate": round(b["playbook_hits"] / n, 2) if n else 0.0,
            "escalations": b["escalations"],
            "escalation_rate": round(b["escalations"] / n, 2) if n else 0.0,
            "notes_saved": b["notes_saved"],
            "avg_duration_s": round(b["total_duration_s"] / n, 1) if n else 0.0,
        })
    return rows


def to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def to_text(rows: list[dict]) -> str:
    if not rows:
        return ("no audit events yet — run some delegated tasks first\n"
                "(audit dir: set AUDIT_LOG_DIR, default ~/.local/share/agent-audit)")
    header = (f"{'week':<9} {'deleg':>5} {'succ%':>6} {'pbook%':>7} "
              f"{'escal':>5} {'esc%':>6} {'notes':>5} {'avg_s':>7}")
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['week']:<9} {r['delegations']:>5} {r['success_rate']*100:>5.0f}% "
            f"{r['playbook_hit_rate']*100:>6.0f}% {r['escalations']:>5} "
            f"{r['escalation_rate']*100:>5.0f}% {r['notes_saved']:>5} "
            f"{r['avg_duration_s']:>7.1f}"
        )
    lines.append("")
    lines.append("flywheel health: escalation_rate should FALL and "
                 "playbook_hit_rate should RISE as the library grows.")
    return "\n".join(lines)
