# FFmpeg Audio-Only Multitrack Recorder for Jitsi

Server-side recording alternative to Jibri that captures individual participant audio tracks from Jitsi Videobridge (JVB) via Colibri2 RTP forwarders and writes separate files per speaker using FFmpeg. Designed to be automated, scriptable, and resilient to Jitsi UI/frontend changes.

## Goals
- Reliable recordings when Jibri/Chromium automation fails (`isJoined` errors, prejoin/lobby fragility).
- Audio-only multitrack: one file per participant (or per-track in a single container) for downstream diarization/mixing.
- Headless, server-side pipeline: no Selenium/browser; all control over APIs and FFmpeg.
- Clear testing/benchmarking and ops runbooks an autonomous agent can execute.

## What’s in this repo snapshot
- `docker-compose.yml` + `.env.example` — clean Jitsi stack (web, prosody, jicofo, jvb) mirroring the baseline from `jitsi-jibri-recording` but without Jibri.
- `ffmpeg-recorder.yml` — overlay that introduces the controller + FFmpeg worker services (placeholders you’ll implement).
- `plan.md` — detailed architecture/design decisions, dependencies, risks, success criteria.
- `TODOs.md` — execution checklists and acceptance criteria for each phase.
- This README — quick overview and quick start for agents/operators.

## Quick Start (conceptual)
1) Copy `.env.example` to `.env` and fill the basics (`PUBLIC_URL`, `HTTP_PORT`, `HTTPS_PORT`, `JVB_ADVERTISE_IPS` or `DOCKER_HOST_ADDRESS`).  
2) Bring up Jitsi baseline:  
   ```bash
   docker compose up -d
   ```  
   (uses `docker-compose.yml` and `.env`).
3) Enable Colibri2 on JVB (per `plan.md` / `TODOs.md`) and start the overlay:  
   ```bash
   docker compose -f docker-compose.yml -f ffmpeg-recorder.yml up -d
   ```
4) Trigger recording via controller API (once implemented):  
   ```bash
   curl -H "X-Auth-Token: $RECORDER_API_SECRET" \
     -X POST http://localhost:${RECORDER_API_PORT:-8288}/recordings \
     -d '{"room":"myroom","mode":"audio-multitrack"}'
   ```
5) Artifacts: `recordings/ffmpeg/<room>/<timestamp>/audio-<participant>.opus` (or `.m4a`) plus `manifest.json`.  
6) Validate with synthetic RTP and a live meeting per the testing section.

## Why this over Jibri?
Jibri depends on Jitsi Meet frontend internals (`APP.conference._room.isJoined()`) and Selenium; current releases fail to join reliably. This design bypasses the browser entirely by commanding JVB to forward RTP to FFmpeg.

## Dependencies (high level)
- Jitsi stack (prosody, jicofo, jvb) with Colibri2 forwarder support.
- Docker Compose; network `meet.jitsi`.
- FFmpeg with Opus/H.264 support (H.264 optional if no video).
- Lightweight controller (Python/Node) to allocate RTP forwarders and launch FFmpeg graphs.

## Outputs
- Per-participant audio files (Opus or AAC/M4A).
- Optional mixed reference track.
- Manifest describing participant ↔ file mapping, timestamps, codecs, checksums.

## Testing/Benchmarking overview
- Synthetic RTP injection to validate FFmpeg graph without Jitsi.
- End-to-end meeting with 2–3 participants; verify each speaker gets a distinct file; confirm channel identity in manifest.
- Drift/robustness checks: joins/leaves mid-recording; JVB restart; packet loss tolerance.

See `plan.md` and `TODOs.md` for full details and agent-ready steps.
