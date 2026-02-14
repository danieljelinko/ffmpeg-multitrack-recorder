# E2E Tests for Multitrack Recording

Automated end-to-end tests that verify the Jitsi multitrack recording pipeline using pytest + Playwright.

## How It Works

Tests simulate real participants using headless Chromium browsers with **synthetic audio** injected via the Web Audio API. Each participant gets a unique oscillator frequency (440Hz, 880Hz, 660Hz), replacing `getUserMedia` so no real microphone is needed. The `inject_audio.js` script also intercepts WebRTC-level mute operations (`track.enabled`, `track.stop()`, `replaceTrack(null)`, `removeTrack()`) to ensure audio packets always flow through the JVB to the recorder.

## Test Architecture

```
tests/
  conftest.py          # Fixtures: stack health, Playwright browser, recording cleanup
  helpers.py           # Utilities: ffprobe wrappers, metadata parsing, participant simulation
  inject_audio.js      # Web Audio API getUserMedia override + WebRTC mute protection
  pytest.ini           # pytest-asyncio config (session-scoped event loop)
  test_api.py          # Controller REST API tests (health, start/stop, listings)
  test_audio.py        # Audio recording pipeline tests (auto-recording lifecycle)
  test_metadata.py     # Metadata.json and directory naming validation
  test_video.py        # Video recording tests (requires RECORD_VIDEO=true)
  test_helpers.py      # Unit tests for helpers.py (no Docker stack required)
  requirements.txt     # Python dependencies
  Dockerfile           # Test runner container image
test-compose.yml       # Docker Compose overlay for containerized test runner
```

## Prerequisites

- Docker stack running (Jitsi + controller + recorder)
- Python 3.11+ with uv
- Playwright Chromium browser
- ffprobe (for MKA inspection)

## Running Tests

### Quick Start (stack already running)

```bash
cd ffmpeg-multitrack-recorder/tests

# Create venv and install deps
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium

# Run all tests
JITSI_URL=https://localhost:8443 \
CONTROLLER_URL=http://localhost:8288 \
RECORDINGS_DIR=../recordings \
RECORDER_API_SECRET=recorder-secret \
  pytest -v --tb=short
```

### With Video Recording Tests

```bash
# Start stack with video profile first:
# docker-compose --profile video up -d
# docker-compose -f ffmpeg-recorder.yml up -d --build

RECORD_VIDEO=true \
JITSI_URL=https://localhost:8443 \
CONTROLLER_URL=http://localhost:8288 \
RECORDINGS_DIR=../recordings \
RECORDER_API_SECRET=recorder-secret \
  pytest -v --tb=short
```

### Unit Tests Only (no Docker required)

```bash
pytest test_helpers.py -v
```

### Docker-based Test Runner

```bash
# Start full stack + test runner
docker-compose -f docker-compose.yml -f ffmpeg-recorder.yml -f test-compose.yml \
  --profile test up -d --build

# Watch test output
docker-compose -f docker-compose.yml -f ffmpeg-recorder.yml -f test-compose.yml \
  logs -f test-runner

# Tear down
docker-compose -f docker-compose.yml -f ffmpeg-recorder.yml -f test-compose.yml \
  --profile test down -v
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `JITSI_URL` | `https://localhost:8443` | Jitsi web frontend URL |
| `CONTROLLER_URL` | `http://localhost:8288` | Controller API URL |
| `VIDEO_RECORDER_URL` | `http://localhost:3000` | Video recorder service URL |
| `RECORDER_API_SECRET` | `recorder-secret` | API auth token |
| `RECORDINGS_DIR` | `../recordings` | Path to recordings directory |
| `RECORD_VIDEO` | `false` | Enable video recording tests |

## Test Summary

| Test | File | What it verifies |
|---|---|---|
| `test_health_shape` | test_api.py | Health endpoint returns expected JSON structure |
| `test_manual_start_returns_response` | test_api.py | Manual start API returns structured response |
| `test_manual_stop_returns_response` | test_api.py | Manual stop API returns structured response |
| `test_start_missing_room_id` | test_api.py | Missing room_id returns 400 |
| `test_unauthorized_without_token` | test_api.py | Missing auth returns 401 |
| `test_list_after_recording` | test_api.py | Recordings list has entries after recording |
| `test_recording_pipeline` | test_audio.py | Auto-recording produces MKA + metadata |
| `test_two_participant_track_count` | test_audio.py | MKA has exactly 2 audio tracks |
| `test_single_participant_no_recording` | test_audio.py | Below MIN_PARTICIPANTS: no recording |
| `test_late_join_recording_continues` | test_audio.py | 3rd participant doesn't break recording |
| `test_late_join_adds_track` | test_audio.py | 3rd participant adds a 3rd audio track |
| `test_early_leaver_in_metadata` | test_audio.py | Early leaver in accumulated metadata snapshot |
| `test_names_in_metadata` | test_metadata.py | Participant names in metadata.json |
| `test_titles_match_metadata` | test_metadata.py | MKA track titles match metadata endpoint IDs |
| `test_directory_renamed` | test_metadata.py | Directory matches yymmdd_hhmmss_room_id pattern |
| `test_video_file_produced` | test_video.py | WebM file produced (requires RECORD_VIDEO=true) |
| `test_metadata_reflects_video` | test_video.py | Metadata includes video flag (requires RECORD_VIDEO=true) |

## Known Limitations

- **Root-owned recording directories**: Docker creates recording dirs as root. The cleanup fixture uses `sudo rm -rf` as fallback if `shutil.rmtree` fails.
- **Session-scoped event loop**: All tests share a single asyncio event loop. Tests use unique room names (with UUID suffixes) to avoid cross-test interference.
- **Manual recording API timing**: JVB may return HTTP 400 for the Colibri2 PATCH when called via the manual API (timing-dependent). Tests accept both 200 and 500 responses.
- **Video tests require video-recorder service**: The 2 video tests skip when `RECORD_VIDEO` is not set. Start the stack with `--profile video` and set `RECORD_VIDEO=true` to run them.
