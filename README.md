# Jitsi Multitrack Recorder

Server-side multitrack recording for Jitsi Meet. Captures each participant's audio as a separate Opus track in a single MKA (Matroska Audio) file, with optional composite video recording via headless browser.

## Features

- **Per-participant audio tracks** --- each speaker gets their own Opus track in one MKA file
- **Composite video recording** --- optional full-meeting video capture via headless Chromium (Playwright)
- **Auto-recording** --- automatically starts recording when participants join, stops when the conference ends
- **Participant metadata** --- `metadata.json` with display names, endpoint IDs, timestamps
- **Track renaming** --- MKA track titles rewritten to `endpoint_id - DisplayName`
- **Directory naming** --- recordings stored as `{yymmdd_hhmmss}_{room}_{meetingId}/`
- **Manual API** --- start/stop recording via REST endpoints
- **No Jibri required** --- audio via JVB REST API, video via lightweight headless browser
- **E2E tested** --- automated test suite with synthetic audio via Web Audio API

## Architecture

```
Browsers  --->  [Jitsi Meet Web]  --->  [Prosody]  --->  [Jicofo]
                                    ^                        |
                                    |                      [JVB]
                                    |                     /     \
                                    |              UDP/ICE    WebSocket (MediaJSON)
                                    |               /            \
                                    |         Browsers    [Multitrack Recorder]
                                    |                            |
                                    |                    recordings/*.mka (audio)
                              [Video Recorder]
                           (headless Chromium)
                                    |
                            recordings/*.webm (video)

[Controller] --- XMPP bot + FastAPI ---
  - Polls JVB /debug to discover conferences
  - PATCH /colibri/v2/conferences/{id} to start/stop audio recording
  - HTTP calls to video-recorder to start/stop video recording
  - Joins conference MUCs to track participant names
  - Writes metadata.json and renames MKA tracks
```

**Audio data flow**: The controller instructs JVB (via REST API) to open a WebSocket connection to the `jitsi/jitsi-multitrack-recorder` container. JVB streams MediaJSON-encoded audio over this WebSocket. The recorder writes a single MKA file with one track per participant.

**Video data flow** (when `RECORD_VIDEO=true`): The controller tells the video-recorder service to launch a headless Chromium browser that joins the Jitsi meeting. Playwright captures the rendered page (composite view of all participants) as a WebM video file.

## Prerequisites

- Docker and Docker Compose
- Ports: 8443 (HTTPS), 8000 (HTTP), 10000/udp (JVB media), 8288 (controller API)

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url>
cd ffmpeg-multitrack-recorder
cp .env.example .env
```

Edit `.env` --- at minimum, set these:

```bash
# Public URL for Jitsi Meet (use localhost for local testing)
PUBLIC_URL=https://localhost:8443

# Host IP for JVB media routing (127.0.0.1 for local testing)
DOCKER_HOST_ADDRESS=127.0.0.1

# Generate unique passwords (run: openssl rand -hex 32)
JICOFO_AUTH_PASSWORD=<generate>
JVB_AUTH_PASSWORD=<generate>
JIBRI_RECORDER_PASSWORD=<generate>
JIBRI_XMPP_PASSWORD=<generate>

# XMPP bot credentials (must match JIBRI_XMPP_PASSWORD)
XMPP_JID=jibri@auth.meet.jitsi
XMPP_PASSWORD=<same as JIBRI_XMPP_PASSWORD>
XMPP_HOST=xmpp.meet.jitsi
XMPP_PORT=5222

# API auth token for the controller REST API
RECORDER_API_SECRET=<generate>

# Auto-recording (enabled by default)
ENABLE_AUTO_RECORDING=1
MIN_PARTICIPANTS=2
```

### 2. Start the stack

The system uses two Docker Compose files: `docker-compose.yml` (Jitsi services + multitrack recorder) and `ffmpeg-recorder.yml` (controller).

**Audio-only recording** (default):

```bash
# Start Jitsi + recorder, then the controller
docker-compose up -d
docker-compose -f ffmpeg-recorder.yml up -d --build
```

**Audio + video recording**:

```bash
# Start Jitsi + recorder + video-recorder, then the controller
docker-compose --profile video up -d
docker-compose -f ffmpeg-recorder.yml up -d --build
```

Set `RECORD_VIDEO=true` in `.env` to enable video in the controller.

### 3. Verify the stack is running

```bash
# Check all containers are up
docker-compose ps
docker-compose -f ffmpeg-recorder.yml ps

# Check controller health (XMPP connected, auto-recording enabled)
curl http://localhost:8288/health
```

Expected health response:

```json
{
  "status": "ok",
  "xmpp": {"enabled": true, "connected": true},
  "auto_recording": {"enabled": true, "active_recordings": 0, "rooms": []}
}
```

### 4. Record a meeting

**Auto-recording** (default when `ENABLE_AUTO_RECORDING=1`):
1. Open `https://localhost:8443` in your browser (accept the self-signed cert)
2. Join a room --- set a display name for track identification
3. Have a second participant join the same room
4. Recording starts automatically when >= `MIN_PARTICIPANTS` are present
5. When all participants leave, recording stops and post-processing runs

**Manual recording** via API:

```bash
# Start recording
curl -X POST http://localhost:8288/api/record/start \
  -H "X-Auth-Token: $RECORDER_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"room_id": "myroom"}'

# Stop recording
curl -X POST http://localhost:8288/api/record/stop \
  -H "X-Auth-Token: $RECORDER_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"room_id": "myroom"}'
```

## Recording Output

### Directory structure

```
recordings/
  260211_072841_testroom_5e27da12-.../
    recording.mka          # Matroska Audio: one Opus track per participant
    video.webm             # Composite video (only when RECORD_VIDEO=true)
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

### Extracting individual audio tracks

```bash
# Extract Alice's track (stream 0) to a standalone Opus file
ffmpeg -i recording.mka -map 0:0 -c copy alice.opus

# Extract Bob's track (stream 1)
ffmpeg -i recording.mka -map 0:1 -c copy bob.opus

# Convert a track to WAV
ffmpeg -i recording.mka -map 0:0 alice.wav
```

### Merging audio + video

Audio and video recordings have slightly different start times (~7-15 seconds offset) because the audio starts via JVB API (instant) while video requires a headless browser to join the meeting (slow). The `metadata.json` records both `started_at` (audio) and `video_started_at` timestamps.

Use the merge script to combine them with proper alignment:

```bash
# Produces merged.mkv (video + all audio tracks) and merged-mixdown.mp4 (video + mixed audio)
./scripts/merge-av.sh recordings/260211_072841_testroom_5e27.../
```

The script reads the timestamps from `metadata.json`, computes the offset, and uses ffmpeg's `-itsoffset` to align them.

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
| `RECORD_VIDEO` | `false` | Enable composite video recording via headless browser |
| `VIDEO_RECORDER_URL` | `http://video-recorder:3000` | Video recorder service URL |
| `RECORDER_API_SECRET` | (required) | Auth token for controller REST API |
| `RECORDINGS_DIR` | `/recordings` | Recording output path inside controller container |

### Recorder appearance

| Variable | Default | Description |
|----------|---------|-------------|
| `RECORDER_DISPLAY_NAME` | `Recorder` | Display name for the recorder participant in meetings |
| `RECORDER_AVATAR_URL` | (empty) | URL to avatar image shown in the recorder's participant tile |
| `RECORDER_VIDEO_FEED` | (empty) | Path to Y4M file for fake video capture (must be mounted into container) |

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

## API Reference

All endpoints require `X-Auth-Token` header matching `RECORDER_API_SECRET`.

### `GET /health`

Health check. Returns XMPP connection status, auto-recording state, active rooms.

### `POST /api/record/start`

Start recording for a room. Body: `{"room_id": "myroom"}`.

The controller joins the MUC, discovers the conference ID, and sends PATCH to JVB.

### `POST /api/record/stop`

Stop recording for a room. Body: `{"room_id": "myroom"}`.

Sends empty connects array to JVB to stop the media stream.

### `GET /api/recordings`

List all recordings with metadata and file listings.

## Deployment

### Production deployment

For production, change these from the local testing defaults:

```bash
# Use your real domain
PUBLIC_URL=https://meet.example.com

# Use the server's public IP
DOCKER_HOST_ADDRESS=203.0.113.42

# Enable Let's Encrypt
ENABLE_LETSENCRYPT=1
LETSENCRYPT_DOMAIN=meet.example.com
LETSENCRYPT_EMAIL=admin@example.com
DISABLE_HTTPS=0

# Generate strong passwords for all secrets
# Run: openssl rand -hex 32
```

### Stopping the stack

```bash
docker-compose -f ffmpeg-recorder.yml down
docker-compose down
```

### Viewing logs

```bash
# Controller logs (XMPP bot + recording logic)
docker-compose -f ffmpeg-recorder.yml logs -f controller

# JVB logs (media bridge)
docker-compose logs -f jvb

# Recorder logs (MKA writer)
docker-compose logs -f recorder

# Video recorder logs (headless browser)
docker-compose logs -f video-recorder
```

### Restarting the controller

After changing controller code or `.env` settings:

```bash
docker-compose -f ffmpeg-recorder.yml up -d --build
```

## E2E Tests

Automated end-to-end tests verify the full recording pipeline using pytest + Playwright with synthetic audio (Web Audio API oscillators at unique frequencies per participant).

### Running tests

```bash
cd tests

# Create venv and install deps
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium

# Run all tests (stack must be running)
JITSI_URL=https://localhost:8443 \
CONTROLLER_URL=http://localhost:8288 \
RECORDINGS_DIR=../recordings \
RECORDER_API_SECRET=recorder-secret \
  pytest -v --tb=short
```

### What the tests cover

| Area | Tests |
|------|-------|
| Audio pipeline | Auto-recording starts, MKA + metadata produced, correct track count |
| Auto-start threshold | Recording only starts at >= MIN_PARTICIPANTS |
| Late join | Third participant mid-recording adds a track |
| Early leave | Participant who leaves early appears in accumulated metadata |
| Metadata | Participant names, track titles match metadata, directory naming |
| REST API | Health endpoint, manual start/stop, auth, recordings list |
| Video | WebM produced, metadata reflects video (requires `RECORD_VIDEO=true`) |

See [tests/README.md](tests/README.md) for full details.

## Troubleshooting

### Recording doesn't start (auto-recording)

1. Check controller logs: `docker-compose -f ffmpeg-recorder.yml logs controller`
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

### MKA has fewer tracks than expected

If the MKA file has fewer audio tracks than participants, check that the ffmpeg remux step includes `-map 0` (selects all streams). Without this flag, ffmpeg defaults to selecting only one stream per type.

### JVB returns 400 on PATCH

The connects payload must include `type`, `audio`, and `video` fields. Verify the controller is sending the full payload.

### JVB returns 404 on PATCH

The conference ID may be stale or wrong. The controller auto-retries via the debug endpoint. Check if the conference still exists: `curl http://localhost:8080/debug`.

### No participant names in metadata

Display names come from XMPP presence. Participants must set a display name in the Jitsi UI before joining. If names are missing, the endpoint ID is used as fallback.

## Known Limitations

- **Audio multitrack, video composite** --- Per-participant audio tracks are captured via JVB connects API. Video is composite only (captured via headless browser), not per-participant, because JVB does not support video in the connects API.
- **P2P must be disabled** --- 2-person calls bypass JVB by default, making recording impossible. This is enforced via `custom-config.js`.
- **No Ogg/WAV export** --- Audio output is always MKA with Opus tracks. Use ffmpeg to convert individual tracks if needed.
- **Video recorder resources** --- The headless Chromium browser uses ~300-500 MB RAM per active recording session. The recorder participant is visible to other users (customizable via `RECORDER_DISPLAY_NAME`, `RECORDER_AVATAR_URL`, and `RECORDER_VIDEO_FEED`).
- **Single JVB** --- Designed for single-JVB deployments. Multi-JVB (Oocyte) would require routing the PATCH to the correct JVB instance.
