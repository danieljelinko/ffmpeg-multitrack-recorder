# Handoff / Launch Prompt — Multitrack "review-master" MKV: consolidate A/V + labelled mux

> Paste this whole file as the opening message of a fresh Claude Code session.
> Working directory: `~/Work/tools/ffmpeg-multitrack-recorder`
> Supersedes the demo-only `260721_0926__handoff_composite_video_demo.md`: running that demo
> surfaced a real bug (below). This handoff is the fix-forward + the refined deliverable.

## 0. Orientation — read before acting
Server-side recording for Jitsi Meet. Audio is **per-participant multitrack**: the controller
PATCHes JVB `/colibri/v2/conferences/{id}` with a `connects` array → official
`jitsi/jitsi-multitrack-recorder` streams MediaJSON → one Opus track per participant in
`recording.mka`. Video is **composite only**: a `video-recorder` service (headless Chromium +
Playwright) joins as a hidden "Recorder" participant and records the meeting grid to `video.webm`.
Per-participant video is impossible (JVB hard-codes `FeatureNotImplementedException("Video")`).

Read first — **follow the repo rules**: `CLAUDE.md`, `DEVELOPMENT_JOURNEY.md`, `03_decisions.md`,
`04_learnings.md`, the master plan `~/.claude/plans/prancy-brewing-sunbeam.md` (this is Phase 1
video work), and this repo's `scripts/merge-av.sh`, `scripts/mixdown.sh`, `controller/xmpp_client.py`.

**Pinned known-good:** `JITSI_IMAGE_VERSION=stable-10590`, JVB 2.3.259, recorder `:latest`. Phase 1
proved **audio** multitrack green on this. This handoff stays on the pinned version (latest-version
re-validation is a separate track).

## 1. The refined objective (what the user actually wants)
One `.mkv` per recording — a reviewer-switchable **review master**:
- **1 video track** — the composite/screenshare.
- **N audio tracks** — one per speaker (the existing per-participant Opus tracks from `recording.mka`).
- **1 mixdown track** — all speakers combined.
- Every track carries a **human-readable title** (`endpoint - DisplayName`, `Mixdown`, `Screenshare`).
In VLC/mpv the reviewer picks the audio track from a menu: "Mixdown" for normal review, a speaker
name to isolate one voice, while the screenshare video plays throughout. Use case: reviewing
presentations with screenshare while keeping speakers separable.

**Terminology / format locked by the user:**
- **Tracks, not channels.** N+1 independent, individually-selectable audio *tracks* — never one
  multichannel stream (players downmix that; painful to isolate).
- **`.mkv`, not `.webm`.** `video.webm` is the raw capture; the muxed MKV is the deliverable/master.

**Open decision (raise with the user, don't block):** *where is this reviewed?* VLC/mpv/ffmpeg
switch audio tracks fine, but a browser `<video>` element **cannot** switch between multiple audio
tracks in one file. If review happens in a web UI, the deliverable is either per-speaker sidecar
files or a small custom player, and the fat MKV becomes the archive master only. This shapes whether
"one MKV" is the deliverable or just the master.

## 2. There is a real bug blocking this — root cause already found
Enabling `RECORD_VIDEO=true` and running the video E2E revealed that **audio and video land in
different directories**, so nothing can be muxed. This is a genuine, never-before-exercised defect
(Phase 1 only ever ran the audio path).

**Evidence (from the controller logs of the E2E run):**

| Test room | JVB `/debug` `meeting_id` (→ video.webm + metadata + finalize dir) | audio recorder WS "Using conference ID" (→ `recording.mka` dir) |
|---|---|---|
| test-video | `82bce564…` | `0107d939…` |
| test-videometa | `4a63abed…` | `ab2eb873…` |

Finalize logged `"No MKA file found in …, skipping track rename"` — it finalized the *video* dir,
leaving the MKA orphaned in a separate UUID dir.

**Root cause (confirmed, not inferred):**
- The **audio** recorder names its output dir after the **Colibri2 `conference-modify` meeting-id**,
  which the controller caches in the mutable slot `self.conference_ids[room_short]`
  (`controller/xmpp_client.py` ~line 588, and read in `start_multitrack_recording` line ~1003).
- `_start_video_recording` (line ~1203) and `_write_recording_metadata` (line ~1443) instead use the
  **JVB `/debug` `meeting_id`** (from `get_active_conferences_from_debug`, line ~1176; passed through
  `_auto_recording_tick`, line ~1276).
- These are **two different UUIDs for the same conference**. In `_auto_recording_tick`, line 1300 sets
  `conference_ids[room_short] = /debug id`, but then `await join_conference_muc` + `await asyncio.sleep(2)`
  (lines ~1308–1309) run **before** audio starts at line 1322 — and during that window the Jingle
  `conference-modify` handler overwrites the slot with the Colibri2 id. So audio uses the Colibri2 id;
  video + finalize use the `/debug` id.
- **Why audio-only (Phase 1) still worked:** `_write_recording_metadata` has a fallback that finds "the
  most-recent dir containing an MKA" — but it is gated behind `if not rec_dir.exists()`
  (line ~1483). In audio-only mode `recordings/{debug_id}` does not exist, so the fallback fires and
  silently reconciles the mismatch. With video enabled, the video-recorder **creates**
  `recordings/{debug_id}/video.webm` first, so `rec_dir.exists()` is true, the fallback is skipped, and
  the MKA is orphaned. The mismatch was always latent; video exposes it.

**Approved fix (Option A — the user chose "fix-forward, TDD"):** align video + finalize to the id the
audio recorder actually used, rather than forcing the audio path onto the `/debug` id (which would risk
the JVB PATCH URL and thus the known-good audio connect).
- Make `start_multitrack_recording` **return the `conference_id` it used** on success (`str`), `None`
  on failure, instead of `bool`. **Blast radius is safe:** both callers use the return only for
  truthiness — `app.py:131` (`if not success: return 500`) and `_auto_recording_tick` line 1323
  (`if success:`). A non-empty string is truthy, `None` is falsy. (Confirm both sites when you edit.)
- In `_auto_recording_tick`, capture that returned id, store it on the rec dict (e.g.
  `rec["recorder_dir_id"]`), and pass **it** to `_start_video_recording(room_short, recorder_dir_id)`
  and use **it** in `_write_recording_metadata` for the `rec_dir` lookup and the rename suffix.
- **Keep `auto_recordings` keyed on the `/debug` `meeting_id`** — the start/stop lifecycle detection
  compares against `active_meeting_ids` from `/debug` (lines 1285, 1359). Only the *directory identity*
  changes, not the lifecycle key. Keep `meeting_id` in `metadata.json` content.
- This does **not** touch the JVB PATCH (still uses `conference_ids` internally) → **no risk to the
  proven audio connect**. Net effect: MKA + video.webm + metadata.json all land in one dir, and
  finalize's `_rename_mka_tracks` + dir-rename + chown all operate on the dir that actually has the MKA.

**TDD:** the finalize dir-resolution is unit-testable **without the stack** — given a temp `recordings/`
with an MKA-bearing dir and a separate video dir, assert the consolidated behaviour. Then prove
end-to-end by re-running the video E2E (below) and, critically, **re-run the audio-only E2E to confirm
Phase 1 stays green** (the fix must not regress the fallback path).

## 3. The deliverable mux — extend `scripts/merge-av.sh`
`merge-av.sh` today emits **two** files: `merged.mkv` (video + N speaker tracks, `-map 0` copy) and
`merged-mixdown.mp4` (video + a single amix). The objective is to **unify** into one `.mkv` with
**N+1 titled audio tracks** (speakers **and** mixdown), reviewer-switchable, mixdown as the default
audio track. Keep it an **on-demand host-side step** (a `just merge` recipe) — recordings are now
host-owned (chown landed on `main`), so no sudo and no stack interaction. Do **not** move the mux into
the controller finalize (keeps the container lean; revisit auto-mux later if the user wants it).

**A working reference already exists — a PoC I built by hand from the split artifacts:**
`recordings/260721_095854_test-videometa-451013dc_4a63abed…/screenshare_review.mkv`
(4 streams, 47.657 s, mixdown = default). Open it in mpv/VLC to see the exact target format. The
recipe (generalise the track loop to N speakers; pull titles from `metadata.json` `participants` +
the MKA track titles):

```bash
# video_started_at - started_at, from metadata.json (see §4 for alignment rationale)
OFFSET=3.657
ffmpeg -y \
  -itsoffset "$OFFSET" -i video.webm \
  -i recording.mka \
  -filter_complex "[1:a:0][1:a:1]amix=inputs=2:normalize=0[mix]" \
  -map 0:v:0 -map 1:a:0 -map 1:a:1 -map "[mix]" \
  -c:v copy -c:a:0 copy -c:a:1 copy -c:a:2 libopus -b:a:2 128k \
  -metadata:s:v:0 title="Screenshare (composite 1280x720)" \
  -metadata:s:a:0 title="Bob (0a5d548e)" \
  -metadata:s:a:1 title="Alice (9fe1672f)" \
  -metadata:s:a:2 title="Mixdown (all speakers)" \
  -disposition:a:0 0 -disposition:a:1 0 -disposition:a:2 default \
  screenshare_review.mkv
```
Notes: speaker tracks are `-c copy` (Opus passthrough); only the mix is re-encoded. `amix` needs
`normalize=0` (else it attenuates each input by 1/N). For N speakers, build the `[1:a:i]` list and the
per-track `-map`/`-metadata:s:a:i`/`-disposition` args programmatically.

## 4. A/V sync — design it deliberately (do not mux blind)
Video and audio are **two independent pipelines** with different start/stop times. In the PoC call:
`video.webm` = **44.0 s**, `recording.mka` = **18.7 s**, offset (`video_started_at - started_at`) =
**3.657 s** (the recorder browser joins ~3–15 s after audio starts). A naive mux misaligns them.

Align on the **wall-clock reference in `metadata.json`** (`started_at`, `video_started_at`,
`ended_at`). Two valid strategies — pick per the user, note the choice:
- **Preserve all audio (PoC choice, recommended for review):** `t=0` = audio start; delay the video by
  the offset (`-itsoffset OFFSET -i video.webm`). First `OFFSET` s shows no video (honest: the recorder
  hadn't joined). No speech lost.
- **Trim to video start (current merge-av.sh behaviour):** shift the MKA by `-OFFSET` so its first
  `OFFSET` s are dropped and audio-time `OFFSET` aligns with video-time 0.

The **duration gap** (audio 18.7 s vs video 44 s) is expected here because the E2E injects only ~15 s
of synthetic tone (Opus DTX stops sending during silence); audio tracks simply end early and the video
plays on with silent audio tracks — fine for MKV. For a real continuous-speech presentation the gap
shrinks. Do not "fix" it by stretching; alignment is a **start-offset** problem, not a rate problem.

## 5. Current stack + repo state (so you don't rebuild or get confused)
- **Stack is UP on pinned `stable-10590` with `RECORD_VIDEO=true`** — `web/prosody/jvb/jicofo` (up
  hours), `jitsi_multitrack_recorder`, and **`jitsi_video_recorder`** (image already built, ~1 GB;
  the controller was rebuilt with `RECORD_VIDEO=true`). `curl localhost:8288/health` → xmpp connected,
  auto-recording enabled. You can reuse it, or `just down && just up-video` for a clean slate.
- **`.env`** (gitignored) currently has `RECORD_VIDEO=true`. Revert to `false` when done unless the
  user wants video default-on.
- **Git / coordination (important):**
  - The chown work is **committed to `main`** (`3c39afa "Chown finished recordings to host user"`).
    `feat/video-demo` currently == `main` (no unique commits). Branch fresh for this work, e.g.
    `feat/video-review-mux`.
  - The working tree has assorted **untracked/modified `.ruler/`, L4 (`0*_*.md`), `handoffs/`, and
    `justfile`** changes — these are dev-context/tooling sync artifacts, **not** the feature. Leave them.
  - **Another session may be driving this same localhost stack** (host ports 8443/8288/10000-udp/8989).
    Evidence: `recordings/260721_101021_manual-verify-audio_…/` (with `mixdown.opus` +
    `speaker_*.opus` sidecars) was produced by a parallel session, not the video E2E. **Be the only
    driver** — confirm with the user before bringing the stack down or recording, and **do not have two
    sessions editing the controller finalize path at once.**
  - **Do not commit or push unless the user asks** (`CLAUDE.md`).
- **`recordings/` is messy** — a mix of this investigation's split-dir evidence and the parallel
  session's manual recording. Contents at handoff time:
  - `260721_095854_test-videometa…_4a63abed/` — video.webm + metadata.json + (copied-in) recording.mka
    + **`screenshare_review.mkv` (the PoC)**.
  - `ab2eb873…/`, `0107d939…/`, `abca796b…/` — **orphaned root-owned** `recording.mka` dirs (the bug's
    fingerprint; also demonstrate that orphans survive the test's non-sudo cleanup).
  - `260721_101021_manual-verify-audio…/` — the parallel session's recording (don't rely on it).
  You may clean these up (host-owned ones with `rm -rf`; root-owned ones need `sudo`) once you've noted
  them as evidence.
- **Resource datapoint for Phase 3 (VPS sizing):** during a recording, `jitsi_video_recorder` (headless
  Chromium) peaked at **~1.07 cores CPU and ~260 MiB RAM** (short 2-tile render; the earlier 300–500 MB
  estimate is an upper bound for busier/longer grids). Re-measure with `docker stats` on a realistic call.

## 6. Steps
1. **Branch:** `git switch -c feat/video-review-mux` (off `main` @ `3c39afa`).
2. **Confirm you're the only stack driver** (ask the user; check `docker ps` + `recordings/` mtimes).
3. **Fix the consolidation bug** (Option A, §2) — red/green: unit-test finalize dir-resolution first.
4. **Extend the mux** (`scripts/merge-av.sh` → unified N+1-track titled MKV, §3) + a `just merge` recipe;
   generalise the PoC recipe to N speakers; apply the §4 alignment.
5. **Prove it** — reuse the running stack (or `just up-video`), then the video E2E:
   `cd tests && RECORD_VIDEO=true JITSI_URL=https://localhost:8443 CONTROLLER_URL=http://localhost:8288 RECORDINGS_DIR=../recordings RECORDER_API_SECRET=recorder-secret .venv/bin/python -m pytest -v --tb=short test_video.py`
   (Tests-venv caveat: **don't** run `playwright install` — `tests/.venv` is Python 3.14 and it fails;
   Chromium is cached under `~/.cache/ms-playwright`.) Then `just merge recordings/<newest>` →
   the review-master MKV; `ffprobe` shows **1 video + N speaker + 1 mixdown**, all titled, in **one** dir.
6. **Re-run the audio-only E2E** to confirm Phase 1 stays green (`--ignore=test_video.py`).

## 7. Definition of done (verify, don't assume)
- A single recording dir contains `recording.mka` (N Opus tracks), `video.webm`, `metadata.json`
  (`record_video:true` + `video_started_at`), and **one review-master `.mkv`** with **1 video + N
  per-speaker + 1 mixdown** audio tracks, each **titled**, mixdown default, A/V aligned (plays in mpv/VLC;
  switching audio tracks isolates each speaker while the screenshare plays throughout).
- The audio-only E2E is still green (no regression to the known-good path).
- Unit test(s) cover the finalize dir-resolution fix and pass under `uv run pytest`.

## 8. On completion
- `04_learnings.md`: the dir-split root cause + the A/V-offset gotcha (start-offset, not rate) +
  the web-`<video>` single-audio-track limitation.
- `03_decisions.md`: Option A (align dir identity to the recorder's id) + on-demand host-side mux + the
  review-master-MKV format decision (and the web-review deliverable question, once resolved).
- `02_progress.md`: Done row.
- Revert `RECORD_VIDEO=false` in `.env` unless the user wants it default-on. **Do not commit/push unless
  asked.** Report: the fix, the mux recipe, the sync design chosen, measured resource use, and the
  open web-review decision.
