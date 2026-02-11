# Development Journey: Jitsi Multitrack Recording

## Goal

Record each participant's audio as a separate track, server-side, without browser automation (Jibri/Selenium). The output is a single Matroska Audio (MKA) file with one Opus track per participant, plus JSON metadata mapping tracks to participant names.

---

## Phase A: Official Multitrack Recorder Investigation (Nov 2025)

**Repo**: `jitsi-multitrack-recording` (archived as `_jitsi-multitrack-recording`)

### What we tried

Built custom JVB and Jicofo Docker containers to enable the `jitsi/jitsi-multitrack-recorder` container. Fixed multiple startup crashes and configuration issues.

### Outcome: BLOCKED

Jicofo gates multitrack recording on Jibri availability. Without a Jibri instance signaling readiness via the brewery MUC, Jicofo never instructs JVB to open a WebSocket connection to the recorder. No media ever flowed to the recorder.

### Key learnings

- Jicofo acts as the gatekeeper for all recording modes
- The multitrack recorder itself is passive --- it listens on a WebSocket, but only JVB can initiate the connection
- The Jicofo recording flow requires: Jibri in brewery MUC -> Jicofo allocates recording -> JVB opens WebSocket to recorder

---

## Phase B: Custom FFmpeg RTP Forwarder (Nov 2025)

**Repo**: `ffmpeg-multitrack-recorder` (initial approach, same repo as current)

### What we tried

Built an XMPP bot (slixmpp) that joins conference MUCs, then uses Colibri2 IQ stanzas to request RTP forwarders from JVB. The plan was to receive forwarded RTP streams and pipe them into FFmpeg for per-participant recording.

### Outcome: BLOCKED

JVB 2.3.x rejects Colibri v1 forwarder allocation requests with `service-unavailable`. The Colibri v1 conference IQ approach for creating forwarders is no longer supported. The bot successfully:
- Connected to XMPP as `jibri@auth.meet.jitsi`
- Joined brewery and conference MUCs
- Received Jingle session offers from Jicofo
- Completed WebRTC negotiation (SDP offer/answer)
- Discovered bridge session IDs

But the critical step --- allocating RTP forwarders via Colibri --- failed because JVB no longer supports this legacy API path.

### Key learnings

- JVB advertises both Colibri v1 and v2 features via XEP-0030, but v1 forwarder allocation is non-functional
- The XMPP bot infrastructure (MUC joining, presence handling, Jingle negotiation) works and is reusable
- Conference IDs can be discovered via Jingle bridge-session elements or the JVB debug endpoint

---

## Phase C: Official Recorder + Colibri2 REST API (Feb 2026) --- SUCCESS

### Approach

Instead of building a custom recorder, use the official `jitsi/jitsi-multitrack-recorder` Docker image and bypass Jicofo entirely by using JVB's REST API to instruct it to connect to the recorder.

### Key discovery

JVB exposes a REST endpoint at `PATCH /colibri/v2/conferences/{meetingId}` that accepts a `connects` array. When you provide a WebSocket URL pointing to the multitrack recorder, JVB opens the connection and starts streaming MediaJSON-encoded audio to it.

### Working payload

```json
{
  "connects": [
    {
      "url": "ws://recorder:8989/record/{meetingId}",
      "protocol": "mediajson",
      "type": "recorder",
      "audio": true,
      "video": false
    }
  ]
}
```

### Critical details

- The recorder WebSocket path uses a **path parameter**: `/record/{meetingId}` (NOT a query parameter)
- The PATCH payload **must** include `type`, `audio`, and `video` fields. Sending only `url` and `protocol` returns HTTP 400.
- To stop recording, send the same PATCH with `"connects": []`
- The meeting ID (UUID) must be discovered at runtime --- it's assigned by Jicofo when the conference starts

### Architecture

```
Browser Participants
        |
        v
   [Jitsi Meet Web] --XMPP--> [Prosody] --XMPP--> [Jicofo]
                                                        |
                                                        v
                                                      [JVB]
                                                     /     \
                                            UDP/ICE /       \ WebSocket (MediaJSON)
                                                  /         \
                                         Browsers    [jitsi-multitrack-recorder]
                                                              |
                                                              v
                                                     recordings/{meetingId}/
                                                        recording.mka

   [Controller (XMPP Bot + FastAPI)]
        |
        |-- Joins brewery MUC (discovers JVB)
        |-- Joins conference MUCs (tracks participants)
        |-- Polls JVB /debug endpoint (discovers conferences)
        |-- PATCH /colibri/v2/conferences/{id} (start/stop recording)
        |-- Writes metadata.json
        |-- Renames MKA tracks with ffmpeg
```

---

## Phase D: Auto-Recording & Post-Processing (Feb 2026) --- SUCCESS

### Auto-recording

The controller polls the JVB debug endpoint (`GET /debug`) every `POLL_INTERVAL` seconds. When a conference has >= `MIN_PARTICIPANTS` endpoints, it automatically:

1. Joins the conference MUC (to track participant display names via XMPP presence)
2. Sends PATCH to JVB to start recording
3. Accumulates participant snapshots (including those who leave early)
4. Detects conference end (disappears from debug output)
5. Stops recording and writes metadata

### Post-processing

When a conference ends:

1. **metadata.json** is written alongside the MKA file, containing:
   - Meeting ID, room name, start/end timestamps
   - Participant list with endpoint IDs, display names, and JIDs

2. **MKA track renaming**: ffprobe reads existing track titles (format: `endpoint_id-ssrc`), maps endpoint IDs to display names from XMPP presence, and ffmpeg remuxes with new titles (format: `endpoint_id - display_name`)

3. **Directory renaming**: The recording directory is renamed from `{meetingId}/` to `{yymmdd_hhmmss}_{room}_{meetingId}/` for human readability

### Participant name discovery

Display names come from XMPP presence stanzas in the conference MUC. The bot parses `{http://jabber.org/protocol/nick}nick` elements. The MUC nickname equals the JVB endpoint ID, providing the link between XMPP presence data and MKA track tags.

---

## Video Recording Attempt (Feb 2026) --- BLOCKED

### What we tried

Set `video: true` in the connects payload to capture video alongside audio.

### Outcome

JVB 2.3.259 returns `"Unsupported request (Video)"` error. The multitrack recording connects API in this JVB version only supports audio.

### Path forward

- Upgrade to a newer JVB version that supports video in the connects API
- Alternatively, use Jibri for video recording (composite single-stream) alongside multitrack audio

---

## Key Technical Learnings

### Protocol details

| Topic | Detail |
|-------|--------|
| JVB REST base | `http://jvb:8080` (internal Docker network) |
| Conference list | `GET /debug` returns all conferences with meeting IDs and endpoints |
| Start recording | `PATCH /colibri/v2/conferences/{meetingId}` with connects array |
| Stop recording | Same PATCH with `"connects": []` |
| Recorder protocol | MediaJSON over WebSocket |
| Recorder path | `/record/{meetingId}` (path param) |
| Output format | Matroska Audio (MKA) with one Opus track per participant |

### Gotchas

1. **P2P must be disabled** --- When only 2 participants are in a room, Jitsi defaults to peer-to-peer. This bypasses JVB entirely, making recording impossible. Disable via `config.p2p = { enabled: false }` in `custom-config.js`.

2. **Bot credentials** --- The XMPP bot must use `jibri@auth.meet.jitsi` with the Jibri XMPP password. This user is pre-registered by the Prosody entrypoint. Creating a custom `recorder.meet.jitsi` VirtualHost does NOT work with stock Prosody config.

3. **Connects payload fields** --- The PATCH payload `type`, `audio`, and `video` fields are all mandatory. Omitting any returns HTTP 400.

4. **Conference ID timing** --- The meeting ID UUID doesn't exist until Jicofo creates the conference. The controller must poll or wait for the ID to appear in the JVB debug output.

5. **JVB debug endpoint structure** --- The structure varies by JVB version. Endpoints may be a dict or list. Conference IDs may be under `meeting_id` or `id`. The controller handles both formats.

### Version constraints

| Component | Version | Notes |
|-----------|---------|-------|
| Jitsi images | stable-10590 | Tested and working |
| JVB | 2.3.259 | Audio-only multitrack; video not supported |
| jitsi-multitrack-recorder | latest | Official image, works as-is |
| slixmpp | 1.8.x / 1.9.x | Bot handles both API styles |
