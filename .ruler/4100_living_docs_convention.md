# Living Documentation Convention

Lesson 2 (*The Portable Context Stack*) calls out a fourth layer of context usually missing from rule files: the **living documentation** that explains what a project is currently trying to do. Conversations end, summaries are lossy, context windows are finite — durable progress must live in files and version control, not only in chat.

## The four files

All four live at **repo root** with a **numeric prefix for natural sort order** — no timestamp (persistent like `README.md`, see §8 of [`1100_document_naming_conventions.md`](./1100_document_naming_conventions.md)). The order encodes the natural reading sequence: anchor intent → track progress → log choices → distil wisdom.

| File | Purpose | Format | Update cadence |
|---|---|---|---|
| `01_plan.md` | Current objective, sequence, checkpoints. | Markdown checklist. | When direction changes. |
| `02_progress.md` | Active state first, then history. | `## In flight` / `## Next` / `## Blocked` at top; Done table at bottom, prepended newest-first: Date / Task / Verified by. | After each meaningful step. |
| `03_decisions.md` | Durable choices + trade-offs. Append-only at bottom. | Table: Date / Title / Context / Decision / Consequences. | On any decision future-you would need to recall. |
| `04_learnings.md` | Non-obvious constraints, fragile commands, integration quirks. Append-only at bottom. | Table: Date / Title / Non-obvious truth / Implication. One row = one learning. | Every time a non-discoverable hazard is found. |

## Two scopes: per-repo and workspace-root (cross-repo)

The same four files can exist at **two scopes**:

- **Per-repo L4** — at each repo root. The default home for anything specific to that repo: its current objective, progress, decisions, and learnings.
- **Workspace-root L4** — at the root of a multi-repo workspace (the parent directory holding many sibling repos). It exists **only for cross-repo work**: efforts that span several repos and have no single-repo home — dependency-graph hygiene, ecosystem-wide refactors, a deployment that bundles many packages, migrations that ripple across repos.

The workspace root usually **isn't a git repo** (a `.git` there makes multi-repo tooling treat the whole workspace as one repo). To get history anyway, **host these L4 in a sibling meta-repo and symlink them to the root**. Ruler never distributes root-level L4 docs. They're the cross-repo entry point: read root `01`+`02` first, then drill into the relevant repo's L4.

### Routing — which scope does an entry belong to?

- Concerns **one repo** (its code, its plan, a decision/learning local to it) → that repo's L4.
- Spans **two or more repos**, or is about the **ensemble** (the dependency graph, shared conventions, a workspace-wide audit, who-depends-on-what) → workspace-root L4.
- When a cross-repo effort lands concrete work *inside* a repo, put the cross-repo intent/decision at the root and the repo-specific detail (what changed, how verified) in that repo's L4. Link by naming the other doc; do not duplicate the content in both.

### When to update the workspace-root layer

Update it when the thing you decided or learned is **only true across repos**: a new cross-repo track or its status (`01`/`02`); a decision about repo boundaries or shared dependencies (`03`); a hazard that only appears when repos interact — e.g. a transitive dependency that reaches an app through an unrelated package (`04`). Keep repo-internal detail out of the root, and keep ensemble-level signal out of the individual repos — each scope stays lean by holding only what belongs to it.

## Rules

### 1. Stay concise

L4 files are signals, not essays. Each entry should be skimmable in 5–10 seconds. If you need more than 2–3 sentences for a learning or decision, split or trim. When in doubt, remove a cell rather than expand it — a lean table that always gets read beats a detailed one that gets skipped.

### 2. Use the prescribed formats

- **`03_decisions.md`** — table, append at bottom. One row = one decision; delete a row to remove it.
- **`04_learnings.md`** — table, append at bottom. One row = one learning; delete a row to remove it.
- **`02_progress.md`** — Active state first: `## In flight`, `## Next`, `## Blocked` at the top; Done table at the bottom, prepended newest-first (Date / Task / Verified by).
- **`01_plan.md`** — markdown checklist; structure varies with the objective.

### 3. Append to `learnings.md` on discovery

When the agent discovers a constraint, fragile command, undocumented dependency, or surprising default that **would not be discoverable** by a fresh agent reading the code, append a new row immediately — do not let it evaporate in chat history.

### 4. The "what earns a line" filter

If a fact is discoverable cheaply by `ls`, a nearby README, or reading the code, it belongs in the code — not in L4. L4 is for:
- non-obvious local truths (hazards, quirks, half-finished migrations)
- current intent (what we're changing *this week*)
- decisions that look arbitrary without history

Do not stuff L4 files with generic, aspirational, or upstream-available content.

### 5. `01_plan.md` lifecycle

The agent's `/plan` tool writes to `~/.claude/plans/<branch>.md` — the **negotiation record**. When approved, the executable portion moves to `<repo>/01_plan.md`. On completion, archive it to `plan/archive/YYMMDD__<slug>.md` (timestamp convention from `1100_*`) and start `01_plan.md` fresh.

### 6. `02_progress.md` is the session bridge

A new session must be able to read `01_plan.md` + `02_progress.md` and know exactly where to pick up. Mark items done / in-flight / blocked. When blocked, name the blocker.

## What is *not* an L4 file

- `README.md` — project docs for humans; not L4.
- `MEMORY.md` — agent auto-memory, per-machine, not version-controlled; not L4.
- `CHANGELOG.md` — release artefact; not L4.

## Cross-references

- [`1100_document_naming_conventions.md`](./1100_document_naming_conventions.md) — §8: persistent repo-root files have no timestamp prefix.
