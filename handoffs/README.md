# Handoff launch prompts

Three independent tasks branching off the completed **Phase 1** (multitrack audio proven on
pinned `stable-10590`). Each `.md` here is a **launch prompt**: paste the whole file as the first
message of a fresh Claude Code session whose working dir is
`~/Work/tools/ffmpeg-multitrack-recorder`.

| Order | File | Task | Touches | Status |
|---|---|---|---|---|
| 1 | `260721_0926__handoff_fix_root_owned_recordings.md` | Make finished recording dirs host-owned (controller `chown`) | `controller/app.py`, compose env | ✅ done 2026-07-21 |
| 2 | `260721_0926__handoff_latest_jitsi_revalidation.md` | Re-validate on latest Jitsi + deps; record version ceiling | `.env`, `Dockerfile.jicofo`, `*/requirements.txt` | ⏳ next |
| 3 | `260721_0926__handoff_composite_video_demo.md` | Enable + demo composite video (headless browser) | `.env`, `video-recorder/`, produces artifacts | ⏳ pending |

**Task 1 landed:** recordings are now chowned to `HOST_UID:HOST_GID` by the controller; `just test`'s
Playwright-install step was made non-fatal (Python-3.14 driver bug — uses cached Chromium). Handoffs
2 and 3 have been updated to reflect this.

## ⚠️ They share ONE localhost stack — do not run in parallel naively

All three drive the same Jitsi stack on host-bound ports **8443 / 8288 / 10000-udp / 8989**. Two
sessions bringing the stack up/down at once will collide.

- **Default: run sequentially in the order above.** Task 1 first (it's foundational — host-owned
  recordings also fix the E2E cleanup the other two rely on).
- **If you must parallelise:** give each its own `git worktree` + a distinct compose project name
  (`-p`) + remapped host ports in a task-local `.env`. Running 3 full Jitsi stacks on one host is
  heavy (~2 GB RAM + Chromium each, and UDP/10000 must be remapped) — not recommended.

## Every session must first
Read `CLAUDE.md` (repo rules — follow them), `DEVELOPMENT_JOURNEY.md`, the L4 docs
(`01_plan`/`02_progress`/`03_decisions`/`04_learnings`), and the master plan
`~/.claude/plans/prancy-brewing-sunbeam.md`. Do **not** commit/push unless the user asks.
