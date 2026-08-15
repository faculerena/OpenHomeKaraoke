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

# Give the karaoke its own audio sink, and render app.py + the VLC it spawns into it.
# Without this the stream captures the DEFAULT sink's monitor — and a browser playing this
# very stream renders to that same sink, so its audio is re-captured and folded back in on
# a ~2s delay, stacking the song on itself indefinitely.
# Nothing comes out of the speakers: you hear the karaoke from the TV/browser, in sync with
# the picture. To also monitor it locally:
#   pactl load-module module-loopback source=ohk_karaoke.monitor sink=$(pactl get-default-sink)
OHK_SINK="${OHK_SINK:-ohk_karaoke}"
SINK_MODULE=""
if ! pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -qx "$OHK_SINK"; then
	SINK_MODULE="$(pactl load-module module-null-sink sink_name="$OHK_SINK" \
		sink_properties=device.description=OpenHomeKaraoke 2>/dev/null)" || SINK_MODULE=""
fi
export PULSE_SINK="$OHK_SINK"
export OHK_SINK

CLEANED=0
cleanup(){ [ "$CLEANED" = 1 ] && return; CLEANED=1; pkill -TERM -P $$ 2>/dev/null; sleep 0.5; pkill -KILL -P $$ 2>/dev/null
	[ -n "${SINK_MODULE:-}" ] && pactl unload-module "$SINK_MODULE" 2>/dev/null; }
trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT

PARENT_WL="$(basename "${WAYLAND_DISPLAY:-none}")"   # the real compositor's socket — never ours
echo "[headless] starting cage + app.py $*"
# headless wlroots backend, no input devices; cage launches XWayland and sets DISPLAY for the app
env -u WAYLAND_DISPLAY -u DISPLAY WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 \
	cage -- "$PY" app.py "$@" &
CAGE=$!

# wait for cage to create its wayland socket
# Find cage's socket by ELIMINATION, not by diffing before/after: a previous cage leaves its
# socket file behind and the new one binds that SAME name, so a diff sees nothing new and we'd
# wrongly declare failure while the app is running fine. Anything that isn't the parent
# compositor's socket is ours.
SOCK=""
for _ in $(seq 1 120); do    # generous: a previous cage may still be tearing down its socket
	kill -0 "$CAGE" 2>/dev/null || { echo "[headless] cage/app exited early"; exit 1; }
	for s in "$XDG_RUNTIME_DIR"/wayland-*; do
		[ -S "$s" ] || continue                      # sockets only (skips .lock)
		b="$(basename "$s")"
		case "$b" in *-*.sock) continue;; esac       # e.g. wayland-1-awww-daemon.sock
		[ "$b" = "$PARENT_WL" ] && continue
		SOCK="$b"; break
	done
	[ -n "$SOCK" ] && break
	sleep 0.5
done
[ -z "$SOCK" ] && { echo "[headless] no cage wayland socket appeared"; exit 1; }
echo "[headless] cage on WAYLAND_DISPLAY=$SOCK — starting TV stream on :$PORT"
sleep 2   # let the splash render before the stream connects

# stream cage's sole output (no hyprctl) to the TV browser
WAYLAND_DISPLAY="$SOCK" ./stream-tv.sh -o auto -p "$PORT" &

wait "$CAGE"
