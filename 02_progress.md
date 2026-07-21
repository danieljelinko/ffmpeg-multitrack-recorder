# Progress

## In flight
- **Phase 1B complete (latest `stable-11031`).** Latest Jitsi passes the audio proof 34/34 → ADOPT `stable-11031`. Holding at checkpoint for go-ahead on **Phase 2**.

## Next
- Phase 2: Zulip → our Jitsi call-manager, record a Zulip-started call (run on `stable-11031`).
- Phase 3: ai4hu-vps deploy feasibility + design (gated).

## Blocked
- (none)

## Done

| Date | Task | Verified by |
|---|---|---|
| 2026-07-21 | **Phase 1B: revalidated on latest `stable-11031`** (web/prosody/jvb=stable-11031 / JVB 2.3.295, jicofo rebuilt on stable-11031 base, recorder:latest, controller deps→latest). ADOPT recommendation | full audio E2E **34/34** (no flakes, 627s); `ffprobe` fresh `260721_113806_test-meta-dir_…` = 2 Opus tracks == 2 participants + metadata maps tracks→names; `/health` xmpp connected + auto-recording enabled |
| 2026-07-21 | **Recordings chowned to host user**: controller finalize `chown`s the finished dir tree to `HOST_UID:HOST_GID` (new `fs_ownership.py` + guard; env wired in `ffmpeg-recorder.yml`/`.env`/`.env.example`) | 4/4 unit tests; live 2-participant E2E → dir+MKA+metadata `helinko:helinko`; `just mixdown` `(mode: host)`; inter-test `clean_recordings` ran with **no sudo**; `ffprobe` 2 Opus tracks |
| 2026-07-21 | **Phase 1 live audio proof (pinned)**: fresh `260721_070601` MKA, 2 Opus tracks (Alice/Bob) + metadata | `ffprobe` track-count == participants; full E2E audio suite 33/34, the 1 fail re-verified green in isolation (self-interference) |
| 2026-07-21 | Added `just mixdown` (on-demand combined-audio track) + `scripts/mixdown.sh` | produced `mixdown.opus`, 1 stream, dur ≈ source |
| 2026-07-21 | Brought up pinned audio stack (web/prosody/jicofo/jvb/recorder + controller) | `/health` xmpp connected + auto-recording enabled |
| 2026-07-21 | De-archived repo → `~/Work/tools/ffmpeg-multitrack-recorder` | `git remote -v` + `git status` intact on `main` |
| 2026-07-21 | Applied dev-context: `.ruler` synced, `CLAUDE.md` regenerated, `.bak` removed | `ls .ruler/`, fresh `CLAUDE.md` mtime, `git check-ignore` |
| 2026-07-21 | Torn down stale 5-month-old crash-looping stack | `docker ps -a` shows no `ffmpeg-multitrack` containers |
| 2026-07-21 | Established L4 docs | files present at repo root |
