# TODOs — FFmpeg Audio-Only Multitrack Recorder (XMPP Colibri2)

Structured for autonomous agent execution. Phases follow the XMPP/Colibri2 (IQ) approach; REST `/colibri2` is not expected. Acceptance criteria included.

-## Phase A — XMPP plumbing & policy (with matched stable tag)
- [ ] Set a single Jitsi tag (e.g., `JITSI_IMAGE_VERSION=stable-10590`) across web/prosody/jicofo/jvb to avoid protocol drift.
- [ ] Configure controller XMPP identity (component or client) and secrets: `XMPP_HOST`, `XMPP_PORT`, `XMPP_DOMAIN`, `XMPP_JID`/`XMPP_PASSWORD` or `XMPP_COMPONENT_SECRET`.
- [ ] Disable P2P/E2EE for recorded rooms; document as precondition.
- [ ] Acceptance: Controller can authenticate to Prosody and join the room MUC as a non-media occupant.
- **Test:** `test_xmpp_auth()` — connect/auth, join MUC, see roster.

## Phase B — Colibri2 IQ client (over XMPP)
- [ ] Implement Colibri2 IQs to allocate/release audio forwarders per endpoint via bridge JID (discover from brewery MUC).
- [ ] Subscribe to forwarder/SSRC updates; request receiver audio subscriptions if supported.
- [ ] Acceptance: For a live room, API returns mapping endpoint→{ip,port,pt,ssrc}; releases succeed.
- **Test:** `test_forwarder_allocation_xmpp()` — send allocate/release IQs, assert non-empty transport tuples.

## Phase C — FFmpeg via SDP (audio multitrack)
- [ ] Generate SDP per forwarder tuple (Opus PT from Colibri2, include SSRC/rtcp-mux if present).
- [ ] Launch FFmpeg per SDP: `-protocol_whitelist file,udp,rtp,crypto`, `-use_wallclock_as_timestamps 1`, `-fflags +igndts+genpts`, `-c:a copy` → `.mka`; optional `amix` mix track.
- [ ] Supervisor captures logs, restarts affected inputs on SSRC change.
- [ ] Acceptance: Starting a session produces N .mka files; optional mix when enabled.
- **Test:** `test_ffmpeg_synthetic_sdp()` — feed synthetic RTP matching SDP, verify files non-silent.

## Phase D — Manifest & metadata
- [ ] Enrich manifest with bridge JID, colibri_conference_id, forwarder tuples (ip,port,pt,ssrc), ssrc_history, receiver subscription flag, P2P/E2EE policy.
- [ ] Compute checksums; record start/end timestamps and log tail.
- [ ] Acceptance: Manifest matches files and contains transport/bridge metadata.
- **Test:** `test_manifest_integrity()` — checksum validation and presence of transport fields.

## Phase E — Compose integration & env
- [ ] Apply XMPP/Colibri env vars to controller; ensure internal-only binding.
- [ ] Keep JVB REST `/colibri/stats` internal; no `/colibri2` HTTP expected.
- [ ] Acceptance: `docker compose up` yields healthy services; controller `/health` 200 with auth; JVB `/colibri/stats` 200.
- **Test:** `test_compose_health()` — services up, health endpoints reachable.

## Phase F — End-to-end validation
- [ ] Run 2–3 participant meeting; trigger recording via XMPP Colibri2; verify per-participant .mka with distinct speech; optional mix.
- [ ] Verify SSRC churn handling (rejoin/rename) refreshes affected inputs only.
- [ ] Acceptance: Audio isolation confirmed; manifest accurate; forwarders released on stop.
- **Test:** `test_e2e_multitrack_xmpp()` — speech separation + manifest checks; simulate churn.

## Phase G — Resilience & ops
- [ ] Handle controller/JVB restarts gracefully; retry IQs with backoff; mark failures.
- [ ] Document P2P/E2EE disablement requirement and receiver subscription flag behavior.
- [ ] Acceptance: Stop cleans forwarders; failures marked; restart resumes new sessions cleanly.
- **Test:** `test_stop_and_cleanup()` — start/stop; verify no lingering forwarders; inject crash and recover.

## Phase H — Optional uploads/retention
- [ ] Add S3/MinIO upload post-finalize; retention job to prune old recordings.
- [ ] Acceptance: Upload succeeds when configured; retention removes aged folders.
- **Test:** `test_upload_and_retention()` — sandbox bucket; verify upload + prune.

## Phase I — Documentation & runbooks
- [ ] Update README/plan with XMPP/IQ approach, env matrix, P2P/E2EE policy, troubleshooting (no `/colibri2` HTTP).
- [ ] Provide sample SDP template and curl examples for stats.
- [ ] Acceptance: Docs standalone; references consistent with this TODOs; include testing commands.

## Definition of Done
- Controller authenticates over XMPP and allocates/releases forwarders via Colibri2 IQs.
- Per-participant .mka files (Opus passthrough) and enriched manifest produced for live room.
- Compose stack healthy; controller secured with secret; JVB REST stats internal only.
- Testing flows (synthetic SDP + E2E) documented and runnable; uploads/retention optional but documented.
