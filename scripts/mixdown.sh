#!/usr/bin/env bash
# Produce a single combined-audio track (all participants mixed) from a
# multitrack recording. On-demand: the .mka keeps the separate per-participant
# tracks; this derives one listenable file next to them.
#
# Recording dirs are written root-owned by the recorder/controller containers,
# so if the host user can't write into the dir we run ffmpeg in a throwaway
# container (writing as root, consistent with the existing files) — no sudo.
#
# Usage: mixdown.sh <recording-dir | recording.mka> [opus|wav|mp3]
#   default format: opus ;  override image via MIXDOWN_IMAGE
set -euo pipefail

SRC="${1:?usage: mixdown.sh <recording-dir | recording.mka> [opus|wav|mp3]}"
FMT="${2:-opus}"
IMAGE="${MIXDOWN_IMAGE:-ffmpeg-multitrack-controller:local}"

if [ -d "$SRC" ]; then DIR="$SRC"; else DIR="$(dirname "$SRC")"; fi
DIR="$(cd "$DIR" && pwd)"                     # absolute
[ -f "$DIR/recording.mka" ] || { echo "No recording.mka in: $DIR" >&2; exit 1; }

# Host ffmpeg when the dir is writable; else containerized ffmpeg.
if [ -w "$DIR" ] && command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
    MODE=host ; MKA="$DIR/recording.mka" ; OUT="$DIR/mixdown.$FMT"
    PROBE=(ffprobe) ; ENC=(ffmpeg)
else
    MODE=docker ; MKA="/work/recording.mka" ; OUT="/work/mixdown.$FMT"
    PROBE=(docker run --rm --entrypoint ffprobe -v "$DIR":/work "$IMAGE")
    ENC=(docker run --rm --entrypoint ffmpeg  -v "$DIR":/work "$IMAGE")
fi

N=$("${PROBE[@]}" -v error -select_streams a -show_entries stream=index -of csv=p=0 "$MKA" | wc -l)
[ "$N" -ge 1 ] || { echo "No audio tracks in $DIR/recording.mka" >&2; exit 1; }

echo "=== Mixing $N track(s) → $DIR/mixdown.$FMT (mode: $MODE) ==="
if [ "$N" -eq 1 ]; then
    "${ENC[@]}" -y -v error -i "$MKA" -map 0:a:0 "$OUT"      # nothing to mix; just transcode
else
    # normalize=0 preserves per-track levels (matches merge-av.sh's mixdown).
    "${ENC[@]}" -y -v error -i "$MKA" \
        -filter_complex "amix=inputs=${N}:normalize=0[mixed]" -map "[mixed]" "$OUT"
fi
echo "Created: $DIR/mixdown.$FMT"
