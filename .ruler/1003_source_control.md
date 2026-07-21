# Source Control

## Branching

- Work on topic branches; keep `main` clean and always deployable.
- Branch name: `<type>/<short-slug>` — e.g. `feat/add-login`, `fix/null-pointer`.

## Commits

- Commit message subject: imperative mood, ≤72 chars — e.g. "Add login endpoint", not "Added" or "Adding".
- One logical change per commit; don't bundle unrelated fixes.

## Dangerous operations — ask first

- `git push --force` or `--force-with-lease`
- `git reset --hard`
- `git rebase` on a shared branch
- Any operation that rewrites published history

## Pull Requests

- PR description must include: what changed and why; a test plan (steps to verify).
- Don't merge without at least one review.
- Keep PRs small enough to review in one sitting; split large changes into a sequence.
