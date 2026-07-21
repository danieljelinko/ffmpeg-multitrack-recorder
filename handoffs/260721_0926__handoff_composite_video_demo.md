# Handoff / Launch Prompt — Composite-video demo (Task 3 of 3)

> Paste this whole file as the opening message of a fresh Claude Code session.
> Working directory: `~/Work/tools/ffmpeg-multitrack-recorder`

## 0. Orientation — read before acting
Server-side recording for Jitsi Meet. Audio is **per-participant multitrack** (via JVB Colibri2
`connects` → official recorder → `recording.mka`). Video is **composite only** (the meeting grid),
captured by a `video-recorder` service: headless Chromium (Node + Playwright) that joins as a hidden
"Recorder" participant and records the page to `video.webm`. Per-participant video is impossible
(JVB hard-codes `FeatureNotImplementedException("Video")` — see `DEVELOPMENT_JOURNEY.md` Phase D/E).

Read for full context first: `CLAUDE.md` (repo rules — **follow them**), `DEVELOPMENT_JOURNEY.md`
(Phase E + video section), `README.md` (video flow), `04_learnings.md`, and the master plan
`~/.claude/plans/prancy-brewing-sunbeam.md`.

**Current state:** Phase 1 proved audio on pinned `stable-10590`. The video path is already
implemented and covered by `tests/test_video.py`; it just isn't enabled/built yet. This task is a
**demo + verification**, targeting the pinned known-good version (independent of Task 2).

## 1. Shared-resource constraint (critical)
One localhost stack, host ports **8443/8288/10000-udp/8989** — be the **only** session driving it.
**Task 1 (host-owned recordings) is DONE** — recordings are now `HOST_UID:HOST_GID`, so `just merge`
runs on the host without sudo. Run after Task 2, or solo. Little/no code change expected — mostly
config + producing artifacts; if you branch, `feat/video-demo`.

## 2. Mission
Enable composite video, record one call, and show `recording.mka` + `video.webm` + a merged A/V file.

## 3. Steps
1. Set `RECORD_VIDEO=true` in `.env`.
2. `just up-video` — this builds the `video-recorder` image (Node + Playwright + Chromium, ~1 GB
   first build) and starts it under the compose `video` profile, then (re)starts the controller.
3. `just health` → expect ok. Confirm the `jitsi_video_recorder` container is up (`just ps`).
4. Produce a recording with video. Simplest is the existing video E2E:
   `cd tests && RECORD_VIDEO=true JITSI_URL=https://localhost:8443 CONTROLLER_URL=http://localhost:8288 VIDEO_RECORDER_URL=http://localhost:3000 RECORDINGS_DIR=../recordings RECORDER_API_SECRET=recorder-secret .venv/bin/python -m pytest -v --tb=short test_video.py`
   (or drive a manual 2-participant call and stop it).
   - **Tests venv caveat** (see `04_learnings.md`): don't run `playwright install` — `tests/.venv`
     is Python 3.14 where it can fail; the Chromium used by the test participants is **cached** under
     `~/.cache/ms-playwright`. This is separate from the `video-recorder` **container**, which ships
     its own Node + Playwright + Chromium and is built by `just up-video`.
5. `just merge recordings/<newest-dir>` → produces `merged.mkv` (video + all audio tracks) and
   `merged-mixdown.mp4` (video + mixed audio). The merge aligns the A/V start offset via
   `metadata.json` timestamps (audio starts instantly, video waits for the browser to join, ~7–15 s).

## 4. Expectations / costs (verify these are acceptable, note in report)
- **Composite only** — one `video.webm` (default 1280×720), not per-participant video.
- **~300–500 MB RAM + real CPU per active recording** (headless Chromium). This is the main driver
  for the VPS sizing question (Phase 3) — quantify what you observe (`docker stats` during a recording).
- A visible **"Recorder" participant** appears in the call (customizable via `RECORDER_DISPLAY_NAME`
  / `RECORDER_AVATAR_URL` / `RECORDER_VIDEO_FEED`).

## 5. Definition of done (verify)
- A recording dir with **all three**: `recording.mka` (per-participant Opus tracks), `video.webm`
  (has a video stream — `ffprobe -show_streams video.webm`), and `metadata.json` with
  `record_video: true` + a `video_started_at`.
- `merged.mkv` / `merged-mixdown.mp4` play with video + audio aligned.
- Note measured RAM/CPU per recording (for Phase 3).

## 6. On completion
- Update `02_progress.md` (Done row); add a `04_learnings.md` row for any video-specific gotcha
  (A/V offset, resource use, cert handling in the headless browser).
- Revert `RECORD_VIDEO` to `false` on `main` unless the user wants it default-on.
- **Do not commit or push unless the user asks** (`CLAUDE.md`).
- Report back: paths to the three artifacts + merged files, measured resource use, and any caveats.
