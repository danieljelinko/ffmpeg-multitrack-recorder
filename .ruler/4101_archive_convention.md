# Archive convention

## `archive/` directory

Completed-decision or superseded-research documents live in `archive/` at repo root.

**Archive** a doc when its content is a *decision now made* or *research now superseded by
built reality*, AND all durable conclusions are already captured in `03_decisions.md`,
`04_learnings.md`, or a runbook. **Keep** docs that are live operational reference or contain
unanswered requirements.

Move with `git mv`; the timestamp prefix is preserved so chronology is maintained.
Cross-references in history tables (`02_progress.md` Done rows) can stay as-is —
they are historical records, not live links that need updating.

## Naming

Archive files keep their original names including timestamp prefix (e.g.
`archive/260528__email_setup.md`). No rename needed — sorting by name gives chronological order.

## Relationship to living docs

Update `03_decisions.md` / `04_learnings.md` **before** archiving — archive is a consequence
of those files being complete, not a replacement for them. The archive holds the full narrative;
the L4 tables hold the durable signal.
