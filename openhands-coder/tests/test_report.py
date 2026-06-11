"""Flywheel report tests — synthetic events, no filesystem or services."""

from openhands_coder.report import to_csv, to_text, weekly_metrics


def _ev(ts, kind, **kw):
    return {"ts": ts, "kind": kind, **kw}


def test_weekly_aggregation_and_rates():
    events = [
        # week 1: two delegations, one with playbook, one escalation
        _ev("2026-06-01T10:00:00+00:00", "task_start", playbook_used=False),
        _ev("2026-06-01T10:05:00+00:00", "task_end", success=True, duration_s=300),
        _ev("2026-06-02T10:00:00+00:00", "task_start", playbook_used=True),
        _ev("2026-06-02T10:08:00+00:00", "task_end", success=False, duration_s=480),
        _ev("2026-06-02T10:09:00+00:00", "note_saved", category="escalation"),
        # week 2: one delegation with playbook, no escalation — flywheel improving
        _ev("2026-06-08T10:00:00+00:00", "task_start", playbook_used=True),
        _ev("2026-06-08T10:04:00+00:00", "task_end", success=True, duration_s=240),
        _ev("2026-06-08T10:05:00+00:00", "note_saved", category="playbook"),
    ]
    rows = weekly_metrics(events)
    assert len(rows) == 2
    week1, week2 = rows
    assert week1["delegations"] == 2
    assert week1["playbook_hit_rate"] == 0.5
    assert week1["escalation_rate"] == 0.5
    assert week2["delegations"] == 1
    assert week2["playbook_hit_rate"] == 1.0
    assert week2["escalation_rate"] == 0.0
    assert week2["notes_saved"] == 1
    # the decay thesis direction: escalations fall, playbook hits rise
    assert week2["escalation_rate"] < week1["escalation_rate"]
    assert week2["playbook_hit_rate"] > week1["playbook_hit_rate"]


def test_empty_and_malformed_events_are_safe():
    assert weekly_metrics([]) == []
    assert weekly_metrics([{"kind": "task_start"}]) == []  # no ts → skipped
    assert "no audit events" in to_text([])


def test_csv_output_parses():
    rows = weekly_metrics([
        _ev("2026-06-01T10:00:00+00:00", "task_start", playbook_used=False),
        _ev("2026-06-01T10:05:00+00:00", "task_end", success=True, duration_s=10),
    ])
    csv_text = to_csv(rows)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("week,delegations,success_rate")
    assert len(lines) == 2
