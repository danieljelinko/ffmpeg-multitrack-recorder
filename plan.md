# Plan — FFmpeg Audio-Only Multitrack Recorder for Jitsi

Treat this as standalone instructions for an autonomous agent. It assumes no prior knowledge beyond what’s written here and the context that Jibri is failing with the `isJoined` Selenium/Jitsi frontend error.

## Background & rationale
- Jibri’s Selenium flow is brittle (frontend `APP.conference._room.isJoined()` has regressed). Multiple 2024–2025 releases are broken.
- We bypass the browser entirely: command Jitsi Videobridge (JVB) to forward RTP for each endpoint, ingest with FFmpeg, and write per-participant audio.
- Scope: audio-only multitrack (one file per participant), optional mixed-down reference; server-side only.

## System architecture
- **Existing services (unchanged):** `web`, `prosody`, `jicofo`, `jvb` on Docker network `meet.jitsi`.
- **New services:**
  - `controller`: small API service (Python/Node) that:
    - Authenticates requests (shared secret header).
    - Discovers conference endpoints (via Prosody MUC/Jicofo or provided room name).
    - Uses Colibri2 REST/WebSocket to allocate RTP forwarders per participant (audio-only).
    - Launches/monitors FFmpeg jobs, tracks PIDs, handles lifecycle, writes manifests.
  - `ffmpeg-recorder` (could be same container as controller or separate worker image): includes FFmpeg with Opus support. Receives RTP from JVB, writes files.
- **Data plane:** JVB sends RTP/RTCP (Opus) flows per endpoint to allocated UDP ports on `ffmpeg-recorder`.
- **Control plane:** REST/WebSocket between controller and JVB (Colibri2); HTTP API exposed only on `meet.jitsi` network (not public).
- **Storage:** Bind mount `recordings/ffmpeg` from host; per-session folder `recordings/ffmpeg/<room>/<timestamp>/`.

## Key design decisions
- **Audio-only:** simplifies CPU/network and avoids layout concerns. Video optional later.
- **Per-participant files vs. multi-track container:** start with separate files (`audio-<endpoint>.m4a` or `.opus`) plus optional mixed track.
- **Codec handling:** ingest Opus RTP; prefer `-c:a copy` to `.opus` for lossless; optionally transcode to AAC/M4A for interoperability.
- **Manifest:** JSON with session metadata (room, start/end, participant↔file mapping, checksums).
- **Security:** controller API requires shared secret; bind to internal Docker network; no UDP exposed publicly.
- **Resilience:** handle SSRC changes (rejoin/layer switch) by re-querying Colibri2 and restarting/patching FFmpeg as needed; ensure cleanup on failure.

## Control flow (happy path)
1. Client calls `POST /recordings` with `{ room: "myroom", mode: "audio-multitrack" }` (optionally participant allowlist).
2. Controller resolves conference and active endpoints (via Prosody/Jicofo or passed roster).
3. For each endpoint, controller requests JVB Colibri2 RTP forwarder (audio) → receives IP/port/PT/SSRC.
4. Controller crafts FFmpeg command:
   - Inputs: one `-i rtp://<self_ip>:<port>?localrtcpport=<rtcp>` per endpoint; `-protocol_whitelist rtp,udp,file,crypto`.
   - Options: `-use_wallclock_as_timestamps 1 -fflags +igndts+genpts`.
   - Output (per endpoint): `-map <in_audio> -c:a copy recordings/ffmpeg/<room>/<ts>/audio-<endpoint>.opus` (or `-c:a aac` → `.m4a`).
   - Optional mixed track: `amix` over inputs to `mix.m4a`.
5. Controller supervises FFmpeg (stdout/stderr), gathers RTCP stats, and on stop:
   - Calls JVB to release forwarders.
   - Finalizes files (`-movflags +faststart` for AAC).
   - Writes manifest JSON.
6. Returns recording metadata via API response/webhook.

## Dependencies & configuration
- JVB must expose Colibri2 REST and WebSocket internally (enable ports/env in compose).
- Network: all new services join `meet.jitsi`; no host networking needed.
- Volumes: `recordings/ffmpeg` bind mount for outputs; optional temp workspace.
- Secrets/env:
  - `RECORDER_API_SECRET` for controller auth.
  - Optional S3-compatible creds for uploads (phase 2).
  - `JVB_COLIBRI2_URL`, `JVB_COLIBRI2_WS` internal endpoints.

## Testing & benchmarking system
- **Synthetic ingest:** Use `ffmpeg -re -f lavfi -i sine=... -f rtp ...` to feed fake Opus RTP into recorder ports to validate graphs without Jitsi.
- **E2E validation:** Two or three participants in a room; start recording; each participant speaks uniquely; verify each output file contains only the speaker’s audio (energy/voice activity check).
- **Drift/robustness:** Introduce participant join/leave mid-call; confirm manifest tracks state and files finalize cleanly.
- **Failure injection:** Kill FFmpeg mid-run → controller should clean up forwarders and mark session failed; restart still possible.
- **Performance notes:** Measure CPU/mem per active participant; set concurrency limits in controller.

## Success criteria
- API can start/stop a recording for a given room with auth.
- For N participants, N audio files exist with correct mappings in manifest; optional mixed track works.
- Files finalize correctly on normal stop and on failure handling.
- No public exposure of control plane or UDP ports; secrets loaded from env.
- Docs (this plan, TODOs, README) allow an autonomous agent to follow without extra context.

## Interfaces (to be implemented)
- **Controller API (internal):**
  - `POST /recordings` body: `{ room, participants?, mode="audio-multitrack", upload?: { provider: "s3", bucket, prefix } }`
  - `DELETE /recordings/{id}` stop.
  - `GET /recordings/{id}` status/paths.
- **Manifest schema (JSON):**
  ```json
  {
    "id": "rec-uuid",
    "room": "myroom",
    "started_at": "iso8601",
    "ended_at": "iso8601",
    "participants": [
      { "endpoint": "abcd", "display_name": "Alice?", "audio_file": "audio-abcd.opus", "ssrc": 12345 }
    ],
    "mix": "mix.m4a",
    "checksums": { "audio-abcd.opus": "sha256:..." }
  }
  ```

## Implementation phases (overview)
- **Phase A:** Enable Colibri2 forwarders on JVB; add compose env/ports; verify reachable from controller container.
- **Phase B:** Build controller skeleton with auth, start/stop/status, manifest writing, JVB Colibri2 client.
- **Phase C:** Build FFmpeg launcher (script or service) that takes a JSON of endpoints→ports and runs per-participant outputs + optional mix.
- **Phase D:** Compose integration (services + volumes + env); logging/metrics; retention policy.
- **Phase E:** Testing/benchmarking flows; document runbooks.
- **Phase F:** Optional uploads (S3/MinIO) and alerting.

## Risks & mitigations
- **SSRC churn:** Detect via Colibri2 updates; restart/reconfigure FFmpeg; log manifest updates.
- **Codec mismatch:** Ensure JVB sends Opus; if PCMU/PCMA negotiate, transcode before write.
- **Clock drift:** Use wallclock timestamps and `aresample=async=1` if transcoding to AAC.
- **Resource limits:** Cap concurrent recordings; document CPU/mem expectations; consider one FFmpeg per recording.
- **Version compatibility:** Confirm current JVB image has Colibri2 forwarders; if not, bump image or enable feature flags.

## Deliverables for initial cut
- Updated compose file(s) with controller + ffmpeg-recorder services and JVB Colibri2 exposure.
- Controller code (even stub) with Colibri2 forwarder allocation and FFmpeg spawn logic.
- FFmpeg command templates (per-participant files + optional mix).
- Docs: this plan, TODOs, README; manifests + testing instructions.
