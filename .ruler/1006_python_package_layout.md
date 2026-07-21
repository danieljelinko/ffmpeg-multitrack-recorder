# Python package layout

How a library package is organised. Applies to importable packages under `src/`; scripts,
apps and notebook repos take what fits and ignore the rest.

## Separate the domain objects from the storage code

When a package holds both the objects a domain reasons about **and** the code that reads/writes
them, split them into two sub-packages:

```
src/<ns>/<pkg>/
├── entities/       # the domain objects; know nothing about storage
├── persistence/    # how those objects are read from / written to a backend
├── <verbs>.py      # operations over the two — consumers of both, members of neither
```

- **The dependency runs one way**: `entities` ← `persistence` ← operations. An entity that imports
  a store has the layering backwards.
- **Enforce the direction with a test**, don't just document it. A layout that documents layering
  without enforcing it buys nothing; an AST scan over the entity package asserting it imports no
  storage module is ~10 lines and fails loudly the day someone reverses an arrow.
- **Operations that span both** (bridges, census/reporting verbs, cross-domain copies) sit at the
  package top level. They consume persistence; they are not part of it.
- **The connection helper belongs to `persistence/`** — it is the backend, however caller-facing.

## Create a package when it has residents, not before

Don't scaffold `utils/`/`constants/` "for later" — an empty package is speculative structure. Add
it when something real lives in it.

Keep the packages honest once created: `entities/` holding constants, comparison helpers and
examples, or `persistence/` holding an entity, is the common decay — the direction guard catches
the imports, but only review catches misfiled residents.

## One module per class, named in the singular

`entities/segment.py` defines `Segment`; `entities/segment_list.py` defines `SegmentList`. Helpers
that are that class's own vocabulary (parsers, delimiters, factories) live beside it — they don't
make the module plural. Reach for a plural name only when the module genuinely holds several peer
classes.

## Name persistence modules after the backend

`persistence/segment_mongo.py`, not `persistence/segment_store.py`. Inside a `persistence/`
package the `_store` suffix restates the package name and says nothing; naming the backend says
which one, reads honestly (the signatures take a `Database`, so the module is not backend-agnostic),
and leaves room for a second backend without renaming the first. Naming a module for a genericity
it does not have is the same "looks generic, isn't" smell this ruleset rejects for arguments.

## Split a module by reason-to-change, not by symmetry

Split out a concern that has its own vocabulary and its own reason to change (e.g. turning model
predictions into stored objects: confidences, IOB tags, unknown-label markers). Do **not** split
codec from CRUD just because the tests do — test files split for readability, which is not evidence
of a module seam; code that changes together stays together.

## Scripts live outside the package

CLI entry points go in a top-level `scripts/`, not nested inside the importable package: they stay
out of the shipped wheel and out of any dependency scan over `src/`.

## nbdev is a deliberate choice, per directory

Notebook-first authoring is opt-in, not the default: libraries are plain `src/` + tests unless the
narrative genuinely is the artifact (exploratory / ML work). Two consequences:

- **A repo is not uniformly nbdev.** Confine generated code to the sub-packages that need it
  (`utils/gen/`) and hand-author the rest.
- **Adding an `nbs/` or `*_nbs/` directory silently changes the repo's entire agent rule set** —
  the rule sync auto-detects those directories and distributes the nbdev tier on sight. Never add
  one incidentally.
