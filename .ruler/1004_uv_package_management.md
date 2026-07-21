# Package Management with UV

Use UV for all Python package management. Never use pip or conda directly.

## Commands

- `uv add <package>` — add a dependency (updates `pyproject.toml` + lockfile)
- `uv remove <package>` — remove a dependency
- `uv sync` — sync venv to lockfile after pulling or switching branches
- `uv run pytest` — run tests inside the managed venv
- `uv run <script.py>` — run any script inside the managed venv

## PEP 723 inline scripts

For single-file scripts with their own dependencies, declare deps inline:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
```

Run with `uv run --script <file.py>` or directly via the shebang. No `pyproject.toml` needed.

## Negatives

- Never `pip install` — bypasses the lockfile and pollutes the venv silently.
- Never `conda install` or activate a conda env in these repos.
- Never edit `pyproject.toml` dep lists by hand then forget to run `uv sync`.
