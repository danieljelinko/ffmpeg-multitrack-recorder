# TODOs — FFmpeg Audio-Only Multitrack Recorder

Structured for autonomous agent execution. Follow phases in order; each item has acceptance criteria and testing hooks. Reference `plan.md` for architecture details.

## Phase A: Enable JVB Colibri2 forwarders
- [ ] Expose Colibri2 REST/WS in compose for `jvb` (internal only); document ports/env.
- [ ] Verify JVB version supports forwarders; if missing, bump image or enable feature flags.
- [ ] Verify from controller container: `curl $JVB_COLIBRI2_URL/about` returns info.
- [ ] Acceptance: Colibri2 reachable from inside `meet.jitsi`; no public exposure.

## Phase B: Controller skeleton
- [x] Scaffold controller service (Python/Node) with env-configured secret `RECORDER_API_SECRET`.
- [x] Implement API:
  - [x] `POST /recordings` accepts `{ room, participants?, mode="audio-multitrack" }`, validates secret header.
  - [x] `DELETE /recordings/{id}` stops recording and releases forwarders.
  - [x] `GET /recordings/{id}` returns status + file paths.
- [x] Acceptance: API returns 401 without secret; 200 health check; stub responses wired (verified with TestClient and mocked FFmpeg).
- **Test:** `test_api_auth()` - success with correct secret, fail without/wrong. (Ran via TestClient; auth reject confirmed when secret set before import.)

## Phase C: Colibri2 client + discovery
- [ ] Implement helper to resolve conference endpoints (Roster) via Prosody/Jicofo; support user-provided participant list as fallback.
- [ ] Implement Colibri2 client: allocate/release RTP forwarders for audio per endpoint; capture IP/port/PT/ssrc; listen for SSRC refresh events.
- [ ] Acceptance: For a live room, API returns mapping endpoint→RTP ports in response/logs.
- **Test:** `test_forwarder_allocation()` - creates and releases forwarders; asserts non-empty ports.

## Phase D: FFmpeg launcher (audio multitrack)
- [x] Build FFmpeg command generator given forwarder map:
  - [x] One input per participant (`rtp://...` with RTCP, `-protocol_whitelist rtp,udp,file,crypto`, `-use_wallclock_as_timestamps 1`, `-fflags +igndts+genpts`).
  - [x] Output per participant: `.opus` with `-c:a copy` (or AAC `.m4a` if configured, with `aresample=async=1` to avoid drift).
  - [x] Optional mixed track via `amix`.
- [x] Implement process supervisor: spawn FFmpeg, monitor exit, handle stop signal (log pump + tail stored).
- [ ] Acceptance: Starting a session produces N audio files for N inputs; files have audio energy.
- **Test:** `test_ffmpeg_synthetic_rtp()` - feed synthetic sine RTP into designated ports; verify files exist and non-silent.

## Phase E: Manifest + storage
- [ ] Create per-session folder `recordings/ffmpeg/<room>/<timestamp>/`.
- [ ] Write manifest JSON with session metadata, participant↔file mapping, checksums.
- [ ] Acceptance: Manifest present and matches files; checksum verification passes.
- **Test:** `test_manifest_integrity()` - compute checksums and compare to manifest entries.

## Phase F: Lifecycle & resilience
- [ ] Handle participant join/leave and SSRC churn: refresh forwarders/manifest or restart FFmpeg safely.
- [x] Handle failures: on FFmpeg crash, clean up forwarders and mark status `failed` (stop path now releases Colibri2 session and writes end timestamp).
- [ ] Acceptance: Stop endpoint stops recording cleanly; forwarders released; status reflects outcome; SSRC changes do not orphan jobs.
- **Test:** `test_stop_and_cleanup()` - start recording, stop via API, ensure no forwarders remain; simulate SSRC change and recover.

## Phase G: Compose integration
- [ ] Add `controller` and `ffmpeg-recorder` services to compose, join `meet.jitsi`, mount recordings volume.
- [ ] Wire env defaults: secrets, JVB URLs, recording path; ensure controller binds internally (meet.jitsi/localhost only) unless explicitly published.
- [ ] Acceptance: `docker compose up` brings new services healthy; API reachable internally; controller and Colibri2 not exposed publicly by default.
- **Test:** `test_compose_health()` - `docker compose ps` reports healthy controller; `/health` 200.

## Phase H: End-to-end validation
- [ ] Run 2–3 participant meeting; trigger recording; each participant speaks uniquely.
- [ ] Verify outputs: N per-participant files with distinct speech; optional mix track.
- [ ] Acceptance: Audio isolation confirmed; manifest accurate; files playable.
- **Test:** `test_e2e_multitrack()` - automated or manual check for speech separation; confirm manifest entries.

## Phase I: Optional uploads/ops
- [ ] Add optional S3/MinIO upload after finalize; include retry/backoff.
- [ ] Add retention policy (delete after X days) and basic metrics/logging.
- [ ] Acceptance: Upload succeeds when configured; retention job removes old folders.
- **Test:** `test_upload_and_retention()` - mock/sandbox bucket; verify file presence then removal after retention run.

## Phase J: Documentation & runbooks
- [ ] Update README with quick start, env matrix, security notes.
- [ ] Add troubleshooting (Colibri2 unreachable, FFmpeg errors, missing audio).
- [ ] Acceptance: Docs standalone; references to plan/TODOs consistent; includes testing commands.

## Progress log (tests/execution)
- FastAPI TestClient with mocked FFmpeg: verified `/health` 200, auth enforced (401 without secret), start/status/stop succeed with dummy RTP inputs; manifests written to local `RECORDINGS_PATH`.
- FFmpeg command generation validated via Python to ensure required flags and mix track present.
- Process supervisor added: log tail captured into manifest on stop (requires real FFmpeg run to populate).

## Definition of Done
- Start/stop/status APIs operational with auth.
- Per-participant audio files and manifest produced for live room.
- Compose stack runs with controller + ffmpeg services; no public exposure.
- Testing flows (synthetic + E2E) documented and runnable.
- Upload/retention optional but documented; defaults safe (local only).
