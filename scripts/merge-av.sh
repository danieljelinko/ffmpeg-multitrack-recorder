#!/bin/bash
# merge-av.sh — Merge multitrack audio (MKA) with composite video (WebM)
#
# Usage:
#   ./scripts/merge-av.sh <recording-dir>
#   ./scripts/merge-av.sh recordings/260211_072841_testroom_5e27.../
#
# Produces:
#   merged.mkv — Video + all audio tracks in one Matroska container
#   merged-mixdown.mp4 — Video + single mixed-down audio (for playback)
#
# The audio (MKA) and video (WebM) have different start times because:
# - Audio starts immediately via JVB connects API
# - Video starts later (headless browser needs ~7-15s to join + render)
#
# This script uses metadata.json timestamps to compute the offset and
# aligns them with ffmpeg's -itsoffset.

set -euo pipefail

REC_DIR="${1:?Usage: $0 <recording-dir>}"

MKA=$(find "$REC_DIR" -name "*.mka" -type f | head -1)
WEBM=$(find "$REC_DIR" -name "*.webm" -type f | head -1)
META="$REC_DIR/metadata.json"

if [ -z "$MKA" ]; then
    echo "ERROR: No .mka file found in $REC_DIR"
    exit 1
fi

if [ -z "$WEBM" ]; then
    echo "ERROR: No .webm file found in $REC_DIR"
    echo "Video recording may not have been enabled (RECORD_VIDEO=true)"
    exit 1
fi

echo "Audio: $MKA"
echo "Video: $WEBM"

# Calculate offset between audio and video start times from metadata
OFFSET=0
if [ -f "$META" ]; then
    AUDIO_START=$(python3 -c "
import json, sys
m = json.load(open('$META'))
print(m.get('started_at', ''))
" 2>/dev/null || echo "")

    VIDEO_START=$(python3 -c "
import json, sys
m = json.load(open('$META'))
print(m.get('video_started_at', ''))
" 2>/dev/null || echo "")

    if [ -n "$AUDIO_START" ] && [ -n "$VIDEO_START" ]; then
        OFFSET=$(python3 -c "
from datetime import datetime
a = datetime.fromisoformat('$AUDIO_START')
v = datetime.fromisoformat('$VIDEO_START')
# Positive offset = video started later than audio
diff = (v - a).total_seconds()
print(f'{diff:.3f}')
" 2>/dev/null || echo "0")
        echo "Audio-video offset: ${OFFSET}s (video started ${OFFSET}s after audio)"
    else
        echo "WARNING: Could not determine timestamps from metadata, using offset=0"
    fi
else
    echo "WARNING: No metadata.json found, using offset=0"
fi

# Get number of audio streams in MKA
N_AUDIO=$(ffprobe -v quiet -print_format json -show_streams "$MKA" | \
    python3 -c "import json,sys; print(len(json.load(sys.stdin).get('streams',[])))")
echo "Audio tracks: $N_AUDIO"

# --- 1. Merged MKV: video + all individual audio tracks ---
echo ""
echo "=== Creating merged.mkv (video + $N_AUDIO audio tracks) ==="

# Build ffmpeg command:
# - Video from WebM (no offset needed, it's the reference)
# - Audio from MKA, shifted by -offset to align with video timeline
# If offset > 0, audio started before video, so we delay audio by $OFFSET
# relative to video (or equivalently, trim $OFFSET from the start of audio)
MAP_ARGS=""
for i in $(seq 0 $((N_AUDIO - 1))); do
    MAP_ARGS="$MAP_ARGS -map 1:a:$i"
done

ffmpeg -y \
    -i "$WEBM" \
    -itsoffset "-${OFFSET}" -i "$MKA" \
    -map 0:v:0 $MAP_ARGS \
    -c:v copy -c:a copy \
    "$REC_DIR/merged.mkv"

echo "Created: $REC_DIR/merged.mkv"

# --- 2. Merged MP4: video + mixed-down single audio ---
echo ""
echo "=== Creating merged-mixdown.mp4 (video + mixed audio) ==="

# Build amix filter for all audio tracks
if [ "$N_AUDIO" -gt 1 ]; then
    FILTER_INPUTS=""
    for i in $(seq 0 $((N_AUDIO - 1))); do
        FILTER_INPUTS="${FILTER_INPUTS}[1:a:${i}]"
    done
    FILTER="${FILTER_INPUTS}amix=inputs=${N_AUDIO}:normalize=0[mixed]"

    ffmpeg -y \
        -i "$WEBM" \
        -itsoffset "-${OFFSET}" -i "$MKA" \
        -map 0:v:0 \
        -filter_complex "$FILTER" -map "[mixed]" \
        -c:v libx264 -preset fast -crf 23 \
        -c:a aac -b:a 192k \
        -movflags +faststart \
        "$REC_DIR/merged-mixdown.mp4"
else
    ffmpeg -y \
        -i "$WEBM" \
        -itsoffset "-${OFFSET}" -i "$MKA" \
        -map 0:v:0 -map 1:a:0 \
        -c:v libx264 -preset fast -crf 23 \
        -c:a aac -b:a 192k \
        -movflags +faststart \
        "$REC_DIR/merged-mixdown.mp4"
fi

echo "Created: $REC_DIR/merged-mixdown.mp4"
echo ""
echo "Done! Files in $REC_DIR:"
ls -lh "$REC_DIR"/*.mkv "$REC_DIR"/*.mp4 2>/dev/null || true
