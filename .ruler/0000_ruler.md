# Rules in this `.ruler/` directory are centrally managed

These files are hard-linked from a master `dev-context/` directory. Do not edit them in place — edits will not propagate, and may be overwritten by the next sync.

To add, rename, remove, or sync rules, use the `dev-context` Claude Code Skill (at `~/.claude/skills/dev-context/`).

## Project-specific rules

For rules that only apply to this repo, drop `.md` files into `.ruler/local/`. The sync script never touches anything inside `.ruler/local/` (or any other subdirectory of `.ruler/`). Ruler picks them up via recursive discovery and concatenates them into the generated `CLAUDE.md` / `AGENTS.md`.

Commit files in `.ruler/local/` to git just like the centrally-managed ones — generated `CLAUDE.md` / `AGENTS.md` at the repo root remain gitignored.
