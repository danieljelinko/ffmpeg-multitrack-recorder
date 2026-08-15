# Linting with Ruff

Ruff is the linter for every Python repo. Since v0.16 its **default rule set is 413 rules** (up
from 59), so `ruff check .` with almost no configuration catches syntax errors, immediate runtime
errors, unused imports, blind excepts and naive datetimes out of the box.

## Setup

Add it as a dev dependency (`uv add --dev ruff`), never as a global tool, so CI and laptop agree:

```toml
[dependency-groups]
dev = ["ruff>=0.16.0"]

[tool.ruff.lint]
ignore = ["I001", "ISC004", "FURB167"]   # see "Rules we turn off" below
```

## Commands

- `uv run ruff check .` — lint the repo; run it before every commit
- `uv run ruff check . --output-format=concise` — one line per finding, best for scanning
- `uv run ruff check . --fix --diff` — **preview** the auto-fixes as a diff
- `uv run ruff check . --fix` — apply them
- `uvx ruff@latest check .` — try the newest version without touching the project's deps

## Rules we turn off, and why

These three fight conventions in `1001_python_coding_style.md`. Turn nothing else off without a
reason worth writing down next to it.

| Rule | Why it's off |
|---|---|
| `I001` (isort) | Splits `import os, sys` onto separate lines, against the house style — and its reordering is *unsafe* around star imports (see below) |
| `ISC004` | Flags implicit concatenation, which is how multi-line prose strings are written here |
| `FURB167` | Wants `re.MULTILINE` over `re.M`; the style rules favour concision |

## Never let the fixer reorder imports around a star import

`I001` is off for a correctness reason, not a taste one. When a module does a star import, a later
`from <pkg> import <name>` can be re-binding a name the star import shadowed — and hoisting it
above, as isort does, silently changes what the name refers to:

```python
from fasthtml.common import *
from monsterui.all import *
from fasthtml import ft     # must stay last: the star imports export an `ft` *function*
```

Reordered by isort, `ft` becomes that function and every `ft.Select(...)` raises `AttributeError`
at request time. Import order after a star import is load-bearing; leave it alone.

## Working with the fixer

- Read the diff before applying. `--fix` is safe for the mechanical rules and wrong for anything
  where import order, evaluation order, or shadowing carries meaning.
- Fix the finding, don't silence it. Reach for `# noqa: RULE` only with a trailing reason, and
  prefer a scoped `[tool.ruff.lint.per-file-ignores]` entry when a whole file legitimately differs.
- A finding that contradicts a rule in this ruleset is a bug in the config, not in the code — add
  it to the `ignore` list above with its justification rather than reformatting the code.

## Pin the version

Ruff enables new rules in minor releases, so an unpinned `ruff` dev dependency turns a green CI red
without a code change. Keep the floor in `pyproject.toml`, let the lockfile pin the exact version,
and treat a Ruff upgrade as its own commit — never bundled into a feature change.
