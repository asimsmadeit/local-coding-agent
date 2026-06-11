# Playbooks

Playbooks live in **shared memory** (OpenMemory, category `playbooks`), not in
this folder — this folder documents the convention and holds exported reviews.

Schema for every playbook memory (see IMPLEMENTATION_STEPS.md Phase 4.5):

```
title: <short imperative name>
task_category: <e.g. add-api-endpoint, fix-flaky-test, db-migration>
status: draft | trusted | retired
provenance: <date, source task, which model wrote it>
success_count / failure_count
procedure:
  1. <stepwise, generalized — no task-specific values>
  2. ...
verification: <how to confirm it worked>
```

Lifecycle (enforced by the plan-and-delegate recipe):
- Planner writes a playbook as `draft` when a task type looks recurring.
- First successful execution by the implementer promotes it to `trusted`.
- Two consecutive failures retire it; failure context feeds the revision.

Weekly review: export and skim (`http://localhost:3000` UI), correct or delete
stale entries. A small curated library beats a large stale one.

The metric that matters: **frontier-call decay** — the fraction of work needing
the Bedrock planner should fall, per task category, as this library grows.
