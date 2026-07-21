# Handoff / Launch Prompt — Fix root-owned recordings (Task 1 of 3)

> Paste this whole file as the opening message of a fresh Claude Code session.
> Working directory: `~/Work/tools/ffmpeg-multitrack-recorder`

## 0. Orientation — read before acting
This repo does **server-side multitrack audio recording for Jitsi Meet**: a controller (XMPP bot +
FastAPI) tells JVB, via its Colibri2 REST `connects` API, to stream each participant's audio over a
WebSocket to the official `jitsi/jitsi-multitrack-recorder`, which writes one Opus track per
participant into a single `recording.mka`. No Jibri involved.

Read for full context first: `CLAUDE.md` (repo rules — **follow them**), `DEVELOPMENT_JOURNEY.md`,
`04_learnings.md`, `02_progress.md`, and the master plan `~/.claude/plans/prancy-brewing-sunbeam.md`.

**Current state:** Phase 1 is proven green on pinned `stable-10590` (audio multitrack works; E2E
34/34). Stack controls: `just up` / `just down` / `just health` / `just test` / `just record <room>`
/ `just recordings` / `just mixdown <dir>`.

## 1. Shared-resource constraint (critical)
One localhost stack, host ports **8443/8288/10000-udp/8989**. Be the **only** session driving it.
This is **Task 1 of 3** and should run **first** (see `handoffs/README.md`). Land your change on a
branch off `main`; the other two tasks build on it.

## 2. Mission
Make finished recording directories + files **owned by the host user**, not `root`.

**Why:** the recorder and controller run as root over the bind-mounted `recordings/`, so every
`recording.mka`/dir is `root:root`. The host user then can't write into a recording dir — blocking
`just mixdown`/`just merge` (they currently fall back to a container), backups, rotation, and the
E2E `clean_recordings` fixture (it hits `sudo` and fails). See the "Recordings are root-owned" and
"find_latest_recording picks by mtime" rows in `04_learnings.md`.

## 3. Approach (recommended)
The **controller is the last writer** — it renames `{meetingId}` → `{ts_room_id}`, writes
`metadata.json`, and remuxes track titles (`_rename_mka_tracks`, the `-map 0` path). So chowning the
final dir there covers everything.

1. In `controller/app.py`, find the post-processing/finalize path (dir rename + metadata write +
   `_rename_mka_tracks`). After it completes, recursively `os.chown` the recording dir + its files
   to a configurable `HOST_UID:HOST_GID`.
2. Add `HOST_UID` / `HOST_GID` env to `ffmpeg-recorder.yml` (controller service) and to `.env` +
   `.env.example` (default `1000:1000`; document that it should match the host user running the tool).
3. The controller runs as root, so `os.chown` is permitted. Guard it: skip silently if not root or
   if uid/gid unset, so nothing breaks in odd environments.
4. Keep it surgical — don't refactor unrelated code (see `CLAUDE.md` §3).

## 4. Key files
- `controller/app.py` — finalize/post-process function (the chown hook)
- `ffmpeg-recorder.yml` — controller `environment:` (+ `HOST_UID`/`HOST_GID`)
- `.env`, `.env.example` — defaults + docs
- `04_learnings.md`, `02_progress.md` — update on completion

## 5. Hazards
- Rebuilding/recreating the controller changes the running stack — you own it exclusively.
- `recording.mka` is written by the **recorder** (root) before the controller renames; chown at the
  end (recursive on the final dir) still covers it.
- Don't mutate `recordings/` while `just test` runs (mtime races — see `04_learnings.md`).
- TDD note (`CLAUDE.md`): `chown` to an arbitrary uid needs root, so a host-run unit test can't
  fully exercise it. Add a small unit test for the dir-walk/idempotence/guard logic if practical;
  otherwise verify end-to-end (below) and say so honestly.

## 6. Definition of done (verify)
1. `just up` (rebuilds controller), `just health` → xmpp connected + auto-recording enabled.
2. Produce a recording: `just test` (or a manual 2-participant call). Then:
   - `stat -c '%U:%G %n' recordings/<newest-dir> recordings/<newest-dir>/recording.mka` → **host user**, not root.
   - `just mixdown recordings/<newest-dir>` prints `(mode: host)` (no docker fallback) and writes `mixdown.opus`.
   - `just test` runs its cleanup without `sudo:` password errors in the log.
3. Confirm a fresh MKA still has one Opus track per participant (`just ffprobe recordings/<dir>`).

## 7. On completion
- Append a Done row to `02_progress.md`; add/adjust the relevant `04_learnings.md` row; add a
  `03_decisions.md` row for the chown approach.
- **Do not commit or push unless the user asks** (`CLAUDE.md`). Leave the working tree for review.
- Report back: what changed, the `stat` proof of host ownership, and whether host-mode mixdown works.
