# Jitsi Multitrack Audio Recorder

Server-side multitrack recording for Jitsi Meet. Captures each participant's audio as a separate Opus track in a single MKA (Matroska Audio) file, with automatic participant metadata and human-readable track naming.

## Features

- **Per-participant audio tracks** --- each speaker gets their own Opus track in one MKA file
- **Auto-recording** --- automatically starts recording when participants join, stops when the conference ends
- **Participant metadata** --- `metadata.json` with display names, endpoint IDs, timestamps
- **Track renaming** --- MKA track titles rewritten from `endpoint_id-ssrc` to `endpoint_id - DisplayName`
- **Directory naming** --- recordings stored as `{yymmdd_hhmmss}_{room}_{meetingId}/`
- **Manual API** --- start/stop recording via REST endpoints
- **No browser automation** --- bypasses Jibri/Selenium entirely using JVB REST API

## Architecture

```
Browsers  --->  [Jitsi Meet Web]  --->  [Prosody]  --->  [Jicofo]
                                                             |
                                                           [JVB]
                                                          /     \
                                                   UDP/ICE    WebSocket
                                                    /            \
                                              Browsers    [Multitrack Recorder]
                                                                  |
                                                          recordings/*.mka

[Controller] --- XMPP bot + FastAPI ---
  - Polls JVB /debug to discover conferences
  - PATCH /colibri/v2/conferences/{id} to start/stop recording
  - Joins conference MUCs to track participant names
  - Writes metadata.json and renames MKA tracks
```

**Data flow**: The controller instructs JVB (via REST API) to open a WebSocket connection to the `jitsi/jitsi-multitrack-recorder` container. JVB streams MediaJSON-encoded audio over this WebSocket. The recorder writes a single MKA file with one track per participant.

## Prerequisites

- Docker and Docker Compose
- Ports: 8443 (HTTPS), 8000 (HTTP), 10000/udp (JVB media), 8288 (controller API)

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:
- `PUBLIC_URL` --- your server's public URL (e.g., `https://localhost:8443` for local testing)
- `DOCKER_HOST_ADDRESS` --- your host IP (e.g., `127.0.0.1` for local testing)
- Generate passwords for `JICOFO_AUTH_PASSWORD`, `JVB_AUTH_PASSWORD`, `JIBRI_RECORDER_PASSWORD`, `JIBRI_XMPP_PASSWORD`

For the XMPP bot (controller):
```bash
XMPP_JID=jibri@auth.meet.jitsi
XMPP_PASSWORD=<same as JIBRI_XMPP_PASSWORD>
XMPP_HOST=xmpp.meet.jitsi
XMPP_PORT=5222
```

### 2. Start the Jitsi stack + recorder

```bash
docker compose up -d
```

This starts: web, prosody, jicofo, jvb, and the multitrack recorder.

### 3. Start the controller

```bash
docker compose -f docker-compose.yml -f ffmpeg-recorder.yml up -d --build
```

### 4. Use it

**Auto-recording** (default when `ENABLE_AUTO_RECORDING=1`):
1. Open `https://localhost:8443` in your browser
2. Join a room with at least 2 participants (set display names for track identification)
3. Recording starts automatically
4. When all participants leave, recording stops and metadata is written

**Manual recording** via API:
```bash
# Start
curl -X POST http://localhost:8288/api/record/start \
  -H "X-Auth-Token: $RECORDER_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"room_id": "myroom"}'

# Stop
curl -X POST http://localhost:8288/api/record/stop \
  -H "X-Auth-Token: $RECORDER_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"room_id": "myroom"}'
```

## Configuration Reference

### Core settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBLIC_URL` | (required) | Public URL for Jitsi Meet web interface |
| `DOCKER_HOST_ADDRESS` | (required) | Host IP address for JVB media routing |
| `JITSI_IMAGE_VERSION` | `stable-10590` | Jitsi Docker image tag |
| `HTTP_PORT` | `8000` | HTTP port (redirects to HTTPS) |
| `HTTPS_PORT` | `8443` | HTTPS port for web interface |
| `TZ` | `UTC` | Timezone |

### Recording settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_AUTO_RECORDING` | `1` | Auto-start recording when participants join |
| `MIN_PARTICIPANTS` | `2` | Minimum endpoints before auto-recording triggers |
| `POLL_INTERVAL` | `5` | Seconds between JVB debug endpoint polls |
| `RECORD_VIDEO` | `false` | Video recording (not supported on JVB 2.3.x) |
| `RECORDER_API_SECRET` | (required) | Auth token for controller REST API |
| `RECORDINGS_DIR` | `/recordings` | Recording output path inside controller container |

### XMPP bot settings

| Variable | Default | Description |
|----------|---------|-------------|
| `XMPP_JID` | (required) | Bot JID, must be `jibri@auth.meet.jitsi` |
| `XMPP_PASSWORD` | (required) | Must match `JIBRI_XMPP_PASSWORD` |
| `XMPP_HOST` | `xmpp.meet.jitsi` | Prosody hostname (Docker network) |
| `XMPP_PORT` | `5222` | XMPP connection port |
| `JVB_BRIDGE_MUC` | `jvbbrewery@internal-muc.meet.jitsi` | JVB brewery MUC |

### JVB REST API settings

| Variable | Default | Description |
|----------|---------|-------------|
| `JVB_REST_URL` | `http://jvb:8080` | JVB REST API base URL |
| `RECORDER_WS_URL` | `ws://recorder:8989/record` | Multitrack recorder WebSocket base URL |
| `ENABLE_P2P` | `false` | **Must be false** for recording to work |

## Recording Output

### Directory structure

```
recordings/
  260211_072841_testroom_5e27da12-.../
    recording.mka          # Matroska Audio: one Opus track per participant
    metadata.json          # Participant names, timestamps, meeting info
```

### metadata.json format

```json
{
  "meeting_id": "5e27da12-0992-4614-a7b3-b371bfb59133",
  "room": "testroom",
  "started_at": "2026-02-11T07:28:41.922952+00:00",
  "ended_at": "2026-02-11T07:31:47.086592+00:00",
  "record_video": false,
  "participants": {
    "a9c5e6e0 - Alice": {
      "endpoint_id": "a9c5e6e0",
      "display_name": "Alice",
      "stats_id": null,
      "jid": "testroom@muc.meet.jitsi/a9c5e6e0",
      "joined_at": "2026-02-11T07:28:39.369047Z"
    },
    "2cd89787 - Bob": {
      "endpoint_id": "2cd89787",
      "display_name": "Bob",
      "stats_id": null,
      "jid": "testroom@muc.meet.jitsi/2cd89787",
      "joined_at": "2026-02-11T07:28:39.369519Z"
    }
  }
}
```

### MKA track naming

Each track in the MKA file is titled `endpoint_id - DisplayName` (e.g., `a9c5e6e0 - Alice`). Use ffprobe to inspect:

```bash
ffprobe -v quiet -print_format json -show_streams recording.mka
```

## API Reference

All endpoints require `X-Auth-Token` header matching `RECORDER_API_SECRET`.

### `GET /health`

Health check. Returns XMPP connection status, auto-recording state, active rooms.

```json
{
  "status": "ok",
  "xmpp": {"enabled": true, "connected": true, "bridge_jid": "jvb@auth.meet.jitsi"},
  "auto_recording": {"enabled": true, "active_recordings": 1, "rooms": ["testroom"]},
  "brewery_muc": "jvbbrewery@internal-muc.meet.jitsi"
}
```

### `POST /api/record/start`

Start recording for a room. Body: `{"room_id": "myroom"}`.

The controller joins the MUC, discovers the conference ID, and sends PATCH to JVB.

### `POST /api/record/stop`

Stop recording for a room. Body: `{"room_id": "myroom"}`.

Sends empty connects array to JVB to stop the media stream.

### `GET /api/recordings`

List all recordings with metadata and file listings.

## Troubleshooting

### Recording doesn't start (auto-recording)

1. Check controller logs: `docker compose -f docker-compose.yml -f ffmpeg-recorder.yml logs controller`
2. Verify XMPP bot connected: `curl http://localhost:8288/health`
3. Check JVB has conferences: `curl http://localhost:8080/debug`
4. Ensure `ENABLE_AUTO_RECORDING=1` in `.env`
5. Ensure at least `MIN_PARTICIPANTS` (default 2) are in the room

### Recording doesn't start (manual API)

1. Check the room exists and has participants
2. Verify `RECORDER_API_SECRET` matches between `.env` and your request
3. Check that JVB REST API is accessible from the controller container

### P2P bypass (2-person calls skip JVB)

If recording fails with exactly 2 participants, P2P may be enabled. Verify:
- `ENABLE_P2P=false` in `.env`
- `config/web/custom-config.js` contains `config.p2p = { enabled: false };`

### JVB returns 400 on PATCH

The connects payload must include `type`, `audio`, and `video` fields. Verify the controller is sending the full payload.

### JVB returns 404 on PATCH

The conference ID may be stale or wrong. The controller auto-retries via the debug endpoint. Check if the conference still exists: `curl http://localhost:8080/debug`.

### No participant names in metadata

Display names come from XMPP presence. Participants must set a display name in the Jitsi UI before joining. If names are missing, the endpoint ID is used as fallback.

## Known Limitations

- **Audio only** --- JVB 2.3.x does not support video in the multitrack connects API. `video: true` returns "Unsupported request (Video)".
- **P2P must be disabled** --- 2-person calls bypass JVB by default, making recording impossible. This is enforced via `custom-config.js`.
- **No Ogg/WAV export** --- Output is always MKA with Opus tracks. Use ffmpeg to convert individual tracks if needed.
- **Single JVB** --- Designed for single-JVB deployments. Multi-JVB (Oocyte) would require routing the PATCH to the correct JVB instance.
