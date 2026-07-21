# Handoff / Launch Prompt — Re-validate on latest Jitsi + deps (Task 2 of 3)

> Paste this whole file as the opening message of a fresh Claude Code session.
> Working directory: `~/Work/tools/ffmpeg-multitrack-recorder`

## 0. Orientation — read before acting
Server-side multitrack audio recording for Jitsi Meet. The **core mechanism**: the controller
PATCHes JVB `/colibri/v2/conferences/{meetingId}` with a `connects` array pointing at the official
`jitsi/jitsi-multitrack-recorder` WebSocket; JVB streams MediaJSON audio; the recorder writes one
Opus track per participant into `recording.mka`. No Jibri.

Read for full context first: `CLAUDE.md` (repo rules — **follow them**), `DEVELOPMENT_JOURNEY.md`
(esp. "Key Technical Learnings" + version table), `03_decisions.md`, `04_learnings.md`, and the
master plan `~/.claude/plans/prancy-brewing-sunbeam.md` (this is its **Phase 1B**).

**Current known-good:** `JITSI_IMAGE_VERSION=stable-10590`, JVB 2.3.259, recorder `:latest`.
Phase 1 proved audio multitrack green on this (E2E 34/34).

## 1. Shared-resource constraint (critical)
One localhost stack, host ports **8443/8288/10000-udp/8989** — be the **only** session driving it.
**Task 1 (host-owned recordings) is DONE**: the controller now `chown`s finished dirs to
`HOST_UID:HOST_GID` (`fs_ownership.py`; already wired in `.env`). Keep `HOST_UID`/`HOST_GID` set in
your task-local `.env`. Do all your work on a branch (`feat/latest-jitsi`); **never overwrite the
known-good pinned `.env` on `main`** — it's the fallback.

## 2. Mission
Find the **newest Jitsi + deps that still pass the Phase 1 audio proof**, and document the ceiling.

## 3. Steps
1. **Branch:** `git switch -c feat/latest-jitsi`.
2. **Pick the latest stable Jitsi tag.** Jitsi Docker images are tagged `stable-NNNNN`. Look up the
   current stable release (Docker Hub `jitsi/web` tags, or the `jitsi/docker-jitsi-meet` releases)
   and pin it **explicitly** (don't use `:latest` — reproducibility). Set `JITSI_IMAGE_VERSION` in a
   task-local `.env` (this bumps `web`/`prosody`/`jvb` together). Pull `jitsi/jitsi-multitrack-recorder:latest`.
3. **Custom jicofo:** inspect `Dockerfile.jicofo` (it builds `jicofo-jibri:latest`). Bump its base
   image tag to match, then `docker compose build jicofo`.
4. **Bump app deps** on the branch: `controller/requirements.txt` (slixmpp, fastapi, aiortc, …) and
   `tests/requirements.txt` (playwright). Rebuild controller.
   - **Tests venv caveat** (see `04_learnings.md`): `tests/.venv` is Python **3.14**, where
     `playwright install` can fail (`onExit is not a function`). `just test` now makes that step
     non-fatal and falls back to the **cached** Chromium under `~/.cache/ms-playwright`. If you bump
     Playwright to a version with no matching cached build, recreate the venv on 3.12
     (`uv venv --python 3.12 tests/.venv`) so `playwright install` works.
5. **Bring up + prove:** `just down && just up`, `just health`, then the audio E2E — either
   `just test`, or explicitly:
   `cd tests && JITSI_URL=https://localhost:8443 CONTROLLER_URL=http://localhost:8288 RECORDINGS_DIR=../recordings RECORDER_API_SECRET=recorder-secret .venv/bin/python -m pytest -v --tb=short --ignore=test_video.py`
   Then independently `just ffprobe recordings/<newest>` → N Opus tracks == N participants.
   (Recordings are now host-owned, so `clean_recordings` purges normally — but still don't mutate
   `recordings/` while the suite runs; `find_latest_recording` picks by mtime.)

## 4. Triage the real risk points (this is the whole point of the task)
If it breaks, the likely culprits — narrow to which:
- **The `connects` REST contract** on JVB `/colibri/v2/conferences/{id}` (payload fields, response) — the core mechanism; may change across JVB versions.
- **Config templates:** `config/web/custom-config.js` (P2P off, mute thresholds), prosody, and the jicofo config.
- **Recorder MediaJSON / WS path** (`/record/{meetingId}`).
- JVB `/debug` shape (dict vs list; `meeting_id` vs `id`) — the controller already handles both; re-check.
Fix forward where cheap; otherwise record the exact version ceiling and the failure.

## 5. Definition of done (verify)
- Either **latest passes** the audio E2E + `ffprobe` proof (→ recommend adopting it, updating `.env`
  after user OK), **or** you have the **newest-working** version pinned + a precise failure reason.
- A **compatibility note** appended to `04_learnings.md`: per-component (web/prosody/jvb/jicofo/recorder/controller/tests) — pinned known-good vs latest-tested — and the chosen version to carry to Phase 2 (Zulip) + Phase 3 (VPS).

## 6. On completion
- Update `02_progress.md` (Done row) and `03_decisions.md` (version policy outcome).
- Leave the pinned `.env` intact on `main`; keep your bumps on the branch.
- **Do not commit to `main`, and do not push, unless the user asks** (`CLAUDE.md`).
- Report back: the newest version that works, what (if anything) broke and why, and your adopt / hold recommendation.
