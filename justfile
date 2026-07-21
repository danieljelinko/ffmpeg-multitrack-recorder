# ffmpeg-multitrack-recorder — task runner
# Wraps the documented docker compose / controller-API / script commands.
# `.env` is auto-loaded so RECORDER_API_SECRET / RECORDER_API_PORT are available.

set dotenv-load := true

api := "http://localhost:" + env_var_or_default("RECORDER_API_PORT", "8288")
secret := env_var_or_default("RECORDER_API_SECRET", "recorder-secret")

# List recipes
default:
    @just --list

# Pull the base Jitsi + recorder images referenced by .env
pull:
    docker compose pull web prosody jvb recorder

# Bring up the AUDIO stack (web, prosody, jicofo, jvb, recorder) + controller
up:
    docker compose up -d
    docker compose -f ffmpeg-recorder.yml up -d --build
    @echo "→ stack up. Check: just health"

# Bring up AUDIO + composite VIDEO (needs RECORD_VIDEO=true in .env)
up-video:
    docker compose --profile video up -d
    docker compose -f ffmpeg-recorder.yml up -d --build
    @echo "→ audio+video stack up. Ensure RECORD_VIDEO=true in .env"

# (Re)build the controller image only
build:
    docker compose -f ffmpeg-recorder.yml build

# Tear the whole stack down (controller first, then Jitsi + recorder)
down:
    docker compose -f ffmpeg-recorder.yml down
    docker compose down

# Container status for both compose projects
ps:
    docker compose ps
    docker compose -f ffmpeg-recorder.yml ps

# Controller health (XMPP connected, auto-recording state)
health:
    curl -s {{api}}/health | (jq . 2>/dev/null || cat)

# Manually start recording a room:  just record myroom
record ROOM:
    curl -s -X POST {{api}}/api/record/start \
      -H "X-Auth-Token: {{secret}}" -H "Content-Type: application/json" \
      -d '{"room_id": "{{ROOM}}"}' | (jq . 2>/dev/null || cat)

# Manually stop recording a room:  just stop myroom
stop ROOM:
    curl -s -X POST {{api}}/api/record/stop \
      -H "X-Auth-Token: {{secret}}" -H "Content-Type: application/json" \
      -d '{"room_id": "{{ROOM}}"}' | (jq . 2>/dev/null || cat)

# List recordings via the controller API
recordings:
    curl -s {{api}}/api/recordings -H "X-Auth-Token: {{secret}}" | (jq . 2>/dev/null || cat)

# Tail logs for a service:  just logs controller | jvb | recorder | web
logs SERVICE="controller":
    #!/usr/bin/env bash
    if [ "{{SERVICE}}" = "controller" ]; then
        docker compose -f ffmpeg-recorder.yml logs -f controller
    else
        docker compose logs -f {{SERVICE}}
    fi

# Inspect a recording's audio tracks:  just ffprobe recordings/<dir>
ffprobe DIR:
    ffprobe -v error -select_streams a -show_entries stream=index,codec_name:stream_tags=title \
      -of default=noprint_wrappers=1 "{{DIR}}/recording.mka"

# Combined single-track audio (all speakers mixed) from a recording:  just mixdown recordings/<dir> [opus|wav|mp3]
mixdown DIR FORMAT="opus":
    ./scripts/mixdown.sh "{{DIR}}" "{{FORMAT}}"

# Merge audio + composite video for a recording dir:  just merge recordings/<dir>
merge DIR:
    ./scripts/merge-av.sh "{{DIR}}"

# Run the audio E2E suite (stack must be up). Skips video tests.
test:
    #!/usr/bin/env bash
    set -euo pipefail
    cd tests
    [ -d .venv ] || uv venv .venv
    uv pip install -q --python .venv/bin/python -r requirements.txt
    # Chromium builds are cached under ~/.cache/ms-playwright; the driver's install
    # step can fail on some Python builds (e.g. 3.14: "onExit is not a function"),
    # so keep it non-fatal and fall back to the cache.
    .venv/bin/python -m playwright install chromium || echo "playwright install skipped; using cached browsers"
    JITSI_URL=https://localhost:8443 \
    CONTROLLER_URL={{api}} \
    RECORDINGS_DIR=../recordings \
    RECORDER_API_SECRET={{secret}} \
      .venv/bin/python -m pytest -v --tb=short --ignore=test_video.py
