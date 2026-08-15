#!/bin/bash
# merge-av.sh — Build the review-master MKV for a recording.
#
# Usage:
#   ./scripts/merge-av.sh <recording-dir>
#   ./scripts/merge-av.sh recordings/260721_095854_test-videometa_4a63abed.../
#
# Produces ONE file: screenshare_review.mkv — a reviewer-switchable master with
#   • 1 video track  — the composite screenshare (titled "Screenshare")
#   • N audio tracks — one per speaker, Opus passthrough (titled "endpoint - Name")
#   • 1 audio track  — the mixdown of all speakers (titled "Mixdown", default)
# In VLC/mpv pick the audio track: "Mixdown" for normal review, a speaker name to
# isolate one voice, while the screenshare plays throughout. Tracks, not channels.
#
# A/V sync: audio and video are two pipelines with different start times. We align
# on the wall-clock refs in metadata.json and PRESERVE ALL AUDIO — delay the video
# by OFFSET = video_started_at - started_at (-itsoffset), so audio t=0 stays at 0.
# It's a start-offset problem, not a rate problem — no stretching.

set -euo pipefail

REC_DIR="${1:?Usage: $0 <recording-dir>}"
REC_DIR="${REC_DIR%/}"

MKA=$(find "$REC_DIR" -maxdepth 1 -name "*.mka" -type f | head -1)
WEBM=$(find "$REC_DIR" -maxdepth 1 -name "*.webm" -type f | head -1)
META="$REC_DIR/metadata.json"
OUT="$REC_DIR/screenshare_review.mkv"

[ -n "$MKA" ]  || { echo "ERROR: No .mka file found in $REC_DIR"; exit 1; }
[ -n "$WEBM" ] || { echo "ERROR: No .webm (composite video) in $REC_DIR — enable RECORD_VIDEO, or use 'just mixdown' for audio-only"; exit 1; }

echo "Audio: $MKA"
echo "Video: $WEBM"

# --- A/V offset from metadata (video_started_at - started_at) ---
OFFSET=0
if [ -f "$META" ]; then
    OFFSET=$(python3 -c "
import json
from datetime import datetime
m = json.load(open('$META'))
a, v = m.get('started_at'), m.get('video_started_at')
if a and v:
    print(f'{(datetime.fromisoformat(v) - datetime.fromisoformat(a)).total_seconds():.3f}')
else:
    print('0')
" 2>/dev/null || echo 0)
    echo "A/V offset: ${OFFSET}s (video started ${OFFSET}s after audio; video delayed to preserve all audio)"
else
    echo "WARNING: No metadata.json — using offset=0"
fi

# --- Speaker tracks: count + titles (from the MKA track titles, already 'endpoint - Name') ---
N=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$MKA" | wc -l)
[ "$N" -ge 1 ] || { echo "ERROR: No audio tracks in $MKA"; exit 1; }
echo "Speaker tracks: $N"

mapfile -t TITLES < <(python3 -c "
import json, subprocess
p = subprocess.run(['ffprobe','-v','error','-select_streams','a',
                    '-show_entries','stream=index:stream_tags=title',
                    '-print_format','json','$MKA'], capture_output=True, text=True)
for i, s in enumerate(json.loads(p.stdout)['streams']):
    print(s.get('tags',{}).get('title') or f'Speaker {i+1}')
")

# --- Composite video resolution (for the video track title) ---
VRES=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$WEBM" 2>/dev/null || echo "")
VTITLE="Screenshare${VRES:+ (composite $VRES)}"

# --- Build the ffmpeg invocation programmatically for N speakers ---
# amix over all speaker tracks → the mixdown (normalize=0 keeps per-track levels).
if [ "$N" -eq 1 ]; then
    FILTER="[1:a:0]anull[mix]"
else
    INPUTS=""; for i in $(seq 0 $((N-1))); do INPUTS="${INPUTS}[1:a:${i}]"; done
    FILTER="${INPUTS}amix=inputs=${N}:normalize=0[mix]"
fi

MAPS=(-map 0:v:0)
CODECS=(-c:v copy)
METAS=(-metadata:s:v:0 "title=$VTITLE")
DISPOS=()
for i in $(seq 0 $((N-1))); do
    MAPS+=(-map "1:a:${i}")
    CODECS+=(-c:a:${i} copy)                       # Opus passthrough per speaker
    METAS+=(-metadata:s:a:${i} "title=${TITLES[$i]}")
    DISPOS+=(-disposition:a:${i} 0)
done
MAPS+=(-map "[mix]")
CODECS+=(-c:a:${N} libopus -b:a:${N} 128k)         # only the mix is re-encoded
METAS+=(-metadata:s:a:${N} "title=Mixdown")
DISPOS+=(-disposition:a:${N} default)              # mixdown is the default track

echo ""
echo "=== Creating $(basename "$OUT") (1 video + $N speaker + 1 mixdown tracks) ==="
ffmpeg -y -v warning -stats \
    -itsoffset "$OFFSET" -i "$WEBM" \
    -i "$MKA" \
    -filter_complex "$FILTER" \
    "${MAPS[@]}" "${CODECS[@]}" "${METAS[@]}" "${DISPOS[@]}" \
    "$OUT"

echo ""
echo "Created: $OUT"
ffprobe -v error -show_entries stream=index,codec_type,codec_name:stream_tags=title:stream_disposition=default \
    -of default=noprint_wrappers=1 "$OUT"
