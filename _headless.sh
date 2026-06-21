#!/usr/bin/env bash
# Run app.py inside a hidden, GPU-accelerated micro-compositor (cage on the wlroots
# headless backend) and stream that off-screen output to the TV browser via stream-tv.sh.
# Your real monitor (Hyprland/DP-2) stays completely free.
#
# All arguments are passed through to app.py. The TV port is OHK_TV_PORT (default 4000).
# Used by start-karaoke.sh -t; can also be run directly:
#   ./_headless.sh -d ~/pikaraoke-songs -nv --cloud http://localhost:5005
set -u

cd "$(dirname "$(readlink -f "$0")")"
PY="$PWD/.venv/bin/python"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
PORT="${OHK_TV_PORT:-4000}"

CLEANED=0
cleanup(){ [ "$CLEANED" = 1 ] && return; CLEANED=1; pkill -TERM -P $$ 2>/dev/null; sleep 0.5; pkill -KILL -P $$ 2>/dev/null; }
trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT

before=$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | grep -v '\.lock')
echo "[headless] starting cage + app.py $*"
# headless wlroots backend, no input devices; cage launches XWayland and sets DISPLAY for the app
env -u WAYLAND_DISPLAY -u DISPLAY WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 \
	cage -- "$PY" app.py "$@" &
CAGE=$!

# wait for cage to create its wayland socket
SOCK=""
for _ in $(seq 1 40); do
	kill -0 "$CAGE" 2>/dev/null || { echo "[headless] cage/app exited early"; exit 1; }
	after=$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null | grep -v '\.lock')
	SOCK=$(comm -13 <(echo "$before" | sort) <(echo "$after" | sort) | head -1)
	[ -n "$SOCK" ] && { SOCK=$(basename "$SOCK"); break; }
	sleep 0.5
done
[ -z "$SOCK" ] && { echo "[headless] no cage wayland socket appeared"; exit 1; }
echo "[headless] cage on WAYLAND_DISPLAY=$SOCK — starting TV stream on :$PORT"
sleep 2   # let the splash render before the stream connects

# stream cage's sole output (no hyprctl) to the TV browser
WAYLAND_DISPLAY="$SOCK" ./stream-tv.sh -o auto -p "$PORT" &

wait "$CAGE"
