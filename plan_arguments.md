# Feasibility Arguments — FFmpeg Audio-Only Multitrack Recorder

## Why this is feasible (pro)
- **Bypasses Jibri’s brittle UI automation**: Uses JVB Colibri2 RTP forwarders instead of Selenium/`APP.conference._room.isJoined()`, eliminating the known join failures. (Plan: control/data plane separation, controller API)
- **Audio-only scope reduces complexity**: No video layout or heavy transcoding; Opus passthrough keeps CPU and latency low and FFmpeg graphs simple. (Plan: Key design decisions)
- **Colibri2 provides the needed hooks**: Modern JVB exposes REST/WS to allocate RTP forwarders per endpoint, matching the requirement to pull per-participant audio. (Plan: Dependencies, Phase A)
- **Straightforward FFmpeg wiring**: One RTP input per participant, `-c:a copy` to `.opus`, optional `amix`—all well-supported, no exotic filters. (Plan: Control flow step 4)
- **Contained blast radius**: Services stay on the internal `meet.jitsi` network with shared-secret auth; no public UDP exposure. (Plan: Security)
- **Testability**: Synthetic RTP feeds allow validation without live meetings; E2E tests verify channel isolation. (Plan: Testing & benchmarking)
- **Incremental rollout**: Start with reference implementation (separate files + manifest) before adding uploads/retention. (Plan: Deliverables, Phases)

## Risks / why it could fail (contra)
- **Colibri2 forwarder availability/version drift**: If the shipped JVB image lacks forwarder support or behavior changed, allocation may fail; may need image bump or flags. (Plan: Risks – version compatibility)
- **SSRC churn & endpoint discovery**: Rejoins/layer switches can invalidate SSRCs; controller must resubscribe/update FFmpeg or restart cleanly. (Plan: Resilience)
- **Roster resolution**: Discovering endpoints via Prosody/Jicofo APIs can be brittle; fallback to user-provided participant lists needed. (Plan: Controller responsibilities)
- **Time sync/drift**: Wallclock alignment and RTP timing must be handled to avoid desync between tracks; transcoding to AAC can introduce drift without `aresample=async`. (Plan: Risks – clock drift)
- **Resource limits**: Many participants mean many RTP inputs; CPU/network could bottleneck even with passthrough, especially if mixed track is enabled. (Plan: Risks – resource limits)
- **Operational polish not yet implemented**: Controller image is a placeholder; health checks, retries, cleanup logic, and secure secret handling must be built and validated. (Plan: Deliverables)
- **Security exposure if misconfigured**: If Colibri2 or controller ports are exposed publicly or secrets mismanaged, could allow unauthorized recording/forwarding. (Plan: Security)

## Implications for TODOs
- Emphasize early validation of Colibri2 endpoints and version (Phase A) before building controller logic.
- Add fallback for participant discovery (allow user-supplied roster) to mitigate MUC/Jicofo quirks (Phase C).
- Ensure FFmpeg launcher supports reconfiguration/restart on SSRC churn rather than assuming stable streams (Phase F).
- Include explicit time-sync safeguards (`-use_wallclock_as_timestamps`, optional `aresample=async=1`) in FFmpeg tasks (Phase D).
- Guard security posture: require internal binding and mandatory secret checks before any recording start (Phase B/G).
