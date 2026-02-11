# E2E Testing Strategy

This document outlines approaches for automated end-to-end testing of the multitrack recording system. Implementation is deferred --- this is a planning document.

## Goal

Automated tests that verify recording works without manual browser participation. Tests should confirm that:
- Recordings are created with the correct number of tracks
- Participant metadata matches track titles
- Auto-recording starts and stops correctly
- Edge cases (late join, early leave) are handled

## Approach A: Headless Browser Automation

Use Playwright or Puppeteer to simulate real participants joining Jitsi rooms.

### How it works

1. Launch the full Docker Compose stack (jitsi + recorder + controller)
2. Use Playwright to open N browser instances, each joining the same room
3. Inject synthetic audio via Web Audio API (`OscillatorNode` at different frequencies per participant)
4. Wait for auto-recording to start (poll `/health` endpoint)
5. Close browser instances to trigger conference end
6. Wait for recording to finalize
7. Verify output: MKA file exists, track count matches participant count, metadata.json is valid

### Pros

- Tests the full pipeline including WebRTC, JVB, and the recorder
- Most realistic simulation of actual usage
- Can verify audio content (frequency analysis per track)

### Cons

- Heavyweight: requires Chromium instances
- Slower test execution (30-60s per test case)
- Browser automation can be flaky

### Audio injection

```javascript
// In Playwright page context:
const ctx = new AudioContext();
const osc = ctx.createOscillator();
osc.frequency.value = 440; // Unique frequency per participant
const dest = ctx.createMediaStreamDestination();
osc.connect(dest);
osc.start();

// Replace getUserMedia to return synthetic stream
navigator.mediaDevices.getUserMedia = async () => dest.stream;
```

## Approach B: Synthetic Media Injection via XMPP

Use a test XMPP client to join conferences and inject media packets directly.

### How it works

1. Launch the Docker Compose stack
2. Connect a test XMPP client (Python/slixmpp) as a participant
3. Complete Jingle negotiation with Jicofo
4. Send synthetic RTP audio packets directly to JVB via the ICE/DTLS connection
5. Use aiortc to establish the WebRTC connection programmatically
6. Trigger recording via controller API
7. Verify output

### Pros

- Lighter weight than browser automation
- Faster execution
- More control over media timing and content

### Cons

- Complex to implement (WebRTC negotiation, DTLS, SRTP)
- Less realistic than browser-based tests
- The existing bot code already does Jingle negotiation but doesn't generate media

## Test Scenarios

### Basic recording (2 participants)

1. Two participants join a room
2. Auto-recording starts (verified via `/health`)
3. Participants stay for 10 seconds
4. Both leave
5. **Assert**: MKA file has 2 Opus tracks, metadata.json has 2 participants

### Metadata accuracy

1. Two participants join with known display names ("Alice", "Bob")
2. Recording completes
3. **Assert**: metadata.json `participants` keys contain "Alice" and "Bob"
4. **Assert**: MKA track titles match `endpoint_id - Alice` and `endpoint_id - Bob`

### Auto-start threshold

1. One participant joins (below `MIN_PARTICIPANTS=2`)
2. **Assert**: no recording started (check `/health`)
3. Second participant joins
4. **Assert**: recording starts within `POLL_INTERVAL` seconds

### Auto-stop on conference end

1. Two participants join, recording starts
2. Both leave simultaneously
3. **Assert**: recording stops, metadata.json exists, directory is renamed

### Late join

1. Two participants join, recording starts
2. Third participant joins mid-recording
3. All leave
4. **Assert**: MKA has 3 tracks, metadata.json has 3 participants

### Early leave

1. Three participants join, recording starts
2. One leaves mid-recording
3. Remaining two leave
4. **Assert**: MKA has 3 tracks (early leaver's track included), metadata.json has 3 participants (accumulated snapshot)

### Manual API

1. Two participants join
2. Start recording via `POST /api/record/start`
3. **Assert**: recording active (check `/health`)
4. Stop recording via `POST /api/record/stop`
5. **Assert**: MKA file exists

## CI Integration

### Docker Compose test environment

```yaml
# test-compose.yml (extends main compose)
services:
  test-runner:
    image: mcr.microsoft.com/playwright:latest
    depends_on:
      - web
      - controller
    volumes:
      - ./tests:/tests
    command: npx playwright test /tests/e2e/
    networks:
      meet.jitsi:
```

### Test runner workflow

1. `docker compose -f docker-compose.yml -f ffmpeg-recorder.yml -f test-compose.yml up -d`
2. Wait for all services healthy (poll `/health` endpoints)
3. Run Playwright tests
4. Collect test results and recording artifacts
5. Tear down

### Assertions library

For MKA verification, use ffprobe:

```bash
# Count tracks
ffprobe -v quiet -print_format json -show_streams recording.mka | jq '.streams | length'

# Get track titles
ffprobe -v quiet -print_format json -show_streams recording.mka | jq '.streams[].tags.title'
```

For metadata verification, parse `metadata.json` and check fields.

## Recommended first implementation

Start with **Approach A** (Playwright) for the "Basic recording" and "Metadata accuracy" scenarios. These give the highest confidence with moderate implementation effort. The synthetic audio injection via `OscillatorNode` is well-documented and avoids microphone permission issues.
