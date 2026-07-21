# Learnings

| Date | Title | Non-obvious truth | Implication |
|---|---|---|---|
| 2026-02-14 | `ffmpeg -map 0` or tracks vanish | Remuxing a multi-track MKA with `-c copy` **without `-map 0`** keeps only the first audio stream (ffmpeg defaults to one stream per type) | Raw recorder MKA is correct; the post-process remux must pass `-map 0`. Verify track count with `ffprobe`, not file existence |
| 2026-02-11 | `connects` payload fields are mandatory | `PATCH /colibri/v2/conferences/{id}` needs `type`, `audio`, `video` — sending only `url`+`protocol` returns HTTP 400 | Controller must send the full object; stop recording = same PATCH with `"connects": []` |
| 2026-02-11 | Recorder path is a **path** param | WebSocket URL is `ws://recorder:8989/record/{meetingId}` (NOT a query param) | Wrong shape → no connection, no MKA |
| 2026-02-11 | P2P silently defeats recording | With exactly 2 participants Jitsi goes peer-to-peer and **bypasses JVB**, so no media reaches the recorder | `config.p2p.enabled=false` in `custom-config.js` is mandatory, not optional |
| 2026-02-11 | Bot identity must be `jibri@auth.meet.jitsi` | Stock Prosody pre-registers this JID with the Jibri password; a custom `recorder.meet.jitsi` VirtualHost does not work | Reuse the Jibri credential; don't invent a new XMPP user |
| 2026-02-11 | Meeting-ID UUID is late-bound | The conference UUID doesn't exist until Jicofo creates the conference | Controller must poll JVB `/debug` to discover the ID before it can PATCH |
| 2026-02-11 | JVB `/debug` shape varies by version | Endpoints may be dict or list; conference id under `meeting_id` or `id` | Parser handles both; re-check on every JVB upgrade |
| 2026-02-14 | `config.startAudioMuted=false` URL bug | In the URL hash Jitsi coerces `"false"`→`0`; since `count>=0` is always true it mutes **everyone** | Set mute thresholds server-side in `custom-config.js`, never via URL hash |
| 2026-02-12 | JVB video is hard-coded off | `ExporterWrapper.kt` throws `FeatureNotImplementedException("Video")`; true even on JVB master (Feb 2026) | Per-participant video is not possible via `connects`; composite headless-browser video is the only route |
| 2026-07-21 | Bind-mounts break on repo move | Controller crash-looped `Could not import module "app"` because 5-mo-old containers mounted the pre-archive path | After moving the repo, `compose down` + `up` from the new location to recreate with correct mounts |
| 2026-07-21 | Recordings are **root-owned** (now chowned back) | recorder + controller run as root over bind-mounted `recordings/`, so each `recording.mka`/dir is first written `root:root` | Controller finalize now `chown`s the finished dir tree to `HOST_UID:HOST_GID` (`fs_ownership.chown_tree_to_host`, guarded on running-as-root + both ids set); host-side `mixdown`/cleanup/backup then work without sudo. Still set `HOST_UID`/`HOST_GID` on VPS deploy |
| 2026-07-21 | E2E `find_latest_recording` picks by **mtime** | Tests locate "their" recording as the newest under `recordings/`; touching any old dir mid-suite (e.g. `just mixdown`) makes it "latest" → false failure | Don't mutate `recordings/` while the suite runs. `clean_recordings` now purges normally-finalized (host-owned) dirs via `rmtree` — no sudo — keeping `find_latest` honest |
| 2026-07-21 | `just test` browser-install step is broken here | `playwright install chromium` fails with `TypeError: onExit is not a function` (Playwright driver vs Python 3.14 in `tests/.venv`), aborting the recipe under `set -euo pipefail` before pytest runs | Chromium builds are already cached under `~/.cache/ms-playwright`; bypass the install and run `tests/.venv/bin/python -m pytest --deselect test_video.py` directly with the recipe's env (`JITSI_URL`/`CONTROLLER_URL`/`RECORDINGS_DIR=../recordings`/`RECORDER_API_SECRET`) |
| 2026-07-21 | Latest Jitsi `stable-11031` passes the audio proof unchanged | `stable-11031` (JVB **2.3.295**) + recorder:latest + latest controller deps ran the full E2E **34/34** with **2 Opus tracks == 2 participants**; the Colibri2 `connects` REST contract, recorder MediaJSON WS path, JVB `/debug` shape and the config templates are all identical to `stable-10590` — no code fixes needed | Adopt `stable-11031` as the Phase 2/3 version ceiling; keep `stable-10590` as documented fallback |
| 2026-07-21 | Bare-UUID root-owned recording dirs are benign test-churn | The manual-start API test PATCHes JVB to record a room it never drives to conference-end, so the controller's finalize path (dir-rename + metadata + chown) never fires → leftover `{uuid}/recording.mka` stays `root:root` with no `metadata.json`. Version-independent (seen on both stable-10590 and stable-11031) | Not a regression; finalized dirs (host-owned, with metadata) are the real artifact. `clean_recordings` can't `rmtree` these (root-owned) and falls back to `sudo` — pre-remove them via the recorder container (`docker exec jitsi_multitrack_recorder rm -rf /data/<uuid>`) to avoid a sudo prompt hanging the suite in a non-interactive session |

## Phase 1B version-compatibility matrix (2026-07-21)

Pinned known-good vs latest-tested; all PASS → **ceiling = `stable-11031`**.

| Component | Known-good (pinned) | Latest-tested | Result |
|---|---|---|---|
| jitsi/web | stable-10590 | **stable-11031** | PASS |
| jitsi/prosody | stable-10590 | **stable-11031** | PASS |
| jitsi/jvb | stable-10590 (JVB 2.3.259) | **stable-11031** (JVB 2.3.295-g8d5c0037b) | PASS |
| jicofo (custom `jicofo-jibri`) | base `jitsi/jicofo:unstable` | base **`jitsi/jicofo:stable-11031`** | PASS (`trusted-domains` sed patch still applies) |
| recorder | `jitsi-multitrack-recorder:latest` | `:latest` (2026-05-11 digest) | PASS |
| controller deps | slixmpp 1.17 / aiortc 1.15 / aiohttp 3.14 / fastapi 0.111 (via `>=` floors) | slixmpp 1.17 / aiortc 1.15 / aiohttp 3.14 / **fastapi 0.139.2** / **uvicorn 0.51** / **httpx 0.28.1** / **python-multipart 0.0.32** (starlette 1.3.1) | PASS |
| tests deps | playwright 1.40.x | playwright 1.58.0 (chromium-1208 cached) | PASS (unchanged; harness only) |
