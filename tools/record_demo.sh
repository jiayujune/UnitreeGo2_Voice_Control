#!/usr/bin/env bash
# Record a screen + microphone demo to an MP4 (for UI close-ups).
#
# For the robot itself, film with a phone — this only captures the laptop screen.
# Captures the primary monitor + the default mic (PipeWire 'default', which is
# shareable, so the voice app can use the mic at the same time).
#
# Usage:
#   tools/record_demo.sh                  # record primary monitor + mic
#   tools/record_demo.sh out.mp4          # custom output path
#   tools/record_demo.sh --full           # record the whole X display (all monitors)
# Stop recording by pressing  q  in this terminal.

set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p runtime

OUT=""
FULL=0
for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    *) OUT="$arg" ;;
  esac
done
OUT="${OUT:-runtime/demo-$(date +%Y%m%d-%H%M%S).mp4}"

DISPLAY="${DISPLAY:-:0}"

if [ "$FULL" -eq 1 ]; then
  # Whole virtual screen (all monitors combined).
  SIZE=$(xrandr | grep -oP 'current \K[0-9]+ x [0-9]+' | tr -d ' ' | sed 's/x/x/')
  GRAB="${DISPLAY}"
  VIDEO_SIZE="$SIZE"
else
  # Primary monitor geometry, e.g. "1920x1080+1920+120".
  GEOM=$(xrandr | grep -oP 'primary \K[0-9]+x[0-9]+\+[0-9]+\+[0-9]+' || true)
  if [ -z "$GEOM" ]; then
    echo "Could not find a primary monitor; falling back to --full."
    SIZE=$(xrandr | grep -oP 'current \K[0-9]+ x [0-9]+' | tr -d ' ')
    GRAB="${DISPLAY}"; VIDEO_SIZE="$SIZE"
  else
    VIDEO_SIZE="${GEOM%%+*}"        # 1920x1080
    OFF="${GEOM#*+}"                # 1920+120
    X="${OFF%%+*}"; Y="${OFF#*+}"   # 1920 / 120
    GRAB="${DISPLAY}+${X},${Y}"
  fi
fi

echo "Recording ${VIDEO_SIZE} from ${GRAB} + mic (default) -> ${OUT}"
echo "Press  q  to stop."

exec ffmpeg -hide_banner \
  -f x11grab -framerate 30 -video_size "$VIDEO_SIZE" -i "$GRAB" \
  -f alsa -i default \
  -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  "$OUT"
