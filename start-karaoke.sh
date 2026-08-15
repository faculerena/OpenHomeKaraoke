#!/usr/bin/env bash
# One-command launcher for this machine (venv + ROCm GPU + Hyprland).
# Starts everything in a tmux session "OHK":
#   pane 1: asr_server.py   (Whisper ASR + GPU vocal-split, on :PORT)
#   pane 2: the karaoke app
#             - default : app.py on your monitor (visible on DP-2)
#             - with -t : app.py hidden in a cage micro-compositor (off-screen) and streamed
#                         to the TV browser, so your real monitor stays free  (_headless.sh)
#
# Note: -V is intentionally NOT passed to app.py — the ASR server handles splitting
# via --cloud, so the in-app splitter would be redundant.
#
# Usage:  ./start-karaoke.sh [-t] [-c] [-a PASS] [-m WHISPER_MODEL] [-d SONG_DIR] [-p ASR_PORT]
#   -t  run karaoke hidden + stream only it to the TV browser (open http://<ip>:4000)
#   -c  also publish it through the Cloudflare tunnel:
#         karaoke.timbear.gratis -> the phone UI      (guests)
#         tv.timbear.gratis      -> the karaoke video (open fullscreen on the TV)
#       implies -t, since the TV hostname serves the stream.
#   -a  admin password. STRONGLY recommended with -c: without it every visitor is an
#       admin and GET /shutdown, /reboot and /files/delete are wide open to the internet.
#   -m  Whisper model: tiny|base|small|medium|large-v3   (default: medium)
#   -d  song download dir                                (default: ~/pikaraoke-songs)
#   -p  ASR server port                                  (default: 5005)
#
# Examples:
#   ./start-karaoke.sh           app + voice search only
#   ./start-karaoke.sh -t        + browser stream for the TV  (open http://<ip>:4000)
#   ./start-karaoke.sh -c -a s3cret   + published on the public hostnames
#
# Detach: Ctrl-b then d.   Stop everything:  tmux kill-session -t OHK
set -u

SESSION=OHK
MODEL=medium
DL="$HOME/pikaraoke-songs"
ASR_PORT=5005
WITH_TV=0
WITH_CF=0
ADMIN_PW=""
CF_CONFIG="$HOME/.cloudflared/karaoke-config.yml"
# public hostnames served by that tunnel (must match its ingress rules)
CF_URL="https://karaoke.timbear.gratis"
CF_TV_URL="https://tv.timbear.gratis"

while getopts "tca:m:d:p:h" opt; do
	case $opt in
		t) WITH_TV=1;;
		c) WITH_CF=1; WITH_TV=1;;
		a) ADMIN_PW="$OPTARG";;
		m) MODEL="$OPTARG";;
		d) DL="$OPTARG";;
		p) ASR_PORT="$OPTARG";;
		h) grep '^#' "$0" | sed 's/^# \?//'; exit 0;;
		*) exit 1;;
	esac
done

ADMIN_OPT=""
[ -n "$ADMIN_PW" ] && ADMIN_OPT="--admin-password '$ADMIN_PW'"
# with -c the splash/QR must point at the public hostnames, not the LAN IP
URL_OPT=""
[ "$WITH_CF" = 1 ] && URL_OPT="--url '$CF_URL' --tv-url '$CF_TV_URL'"
if [ "$WITH_CF" = 1 ] && [ -z "$ADMIN_PW" ]; then
	echo "REFUSING: -c publishes this to the internet, where an ungated GET /shutdown can" >&2
	echo "halt this machine. Pass an admin password too, e.g.  -c -a mysecret" >&2
	exit 1
fi

cd "$(dirname "$(readlink -f "$0")")"
PY="$PWD/.venv/bin/python"

# env fallbacks so panes work even if tmux didn't inherit them
export DISPLAY="${DISPLAY:-:1}"                                  # app's pygame/VLC (XWayland)
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"           # stream-tv (wf-recorder)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
	echo "Session '$SESSION' already running."
	echo "  attach:  tmux attach -t $SESSION"
	echo "  stop:    tmux kill-session -t $SESSION"
	exit 1
fi
if pgrep -f "$PWD/.venv/bin/python app.py" >/dev/null 2>&1; then
	echo "An app.py is already running outside tmux. Stop it first, then re-run." >&2
	exit 1
fi

# pane 1: ASR + vocal-split server
tmux new-session -d -s "$SESSION" -n karaoke "$PY asr_server.py -m '$MODEL' -p '$ASR_PORT'; echo; echo '[asr_server exited]'; exec bash"
# pane 2: the karaoke app (no -V). With -t: hidden in cage + streamed to the TV; else: on your monitor.
if [ "$WITH_TV" = 1 ]; then
	tmux split-window -t "$SESSION" "OHK_TV_PORT=4000 ./_headless.sh -d '$DL' -nv $ADMIN_OPT $URL_OPT --cloud http://localhost:$ASR_PORT; echo; echo '[headless karaoke exited]'; exec bash"
else
	tmux split-window -t "$SESSION" "$PY app.py -d '$DL' -nv $ADMIN_OPT $URL_OPT --cloud http://localhost:$ASR_PORT; echo; echo '[app exited]'; exec bash"
fi
# pane 3: the public tunnel (karaoke.* -> :5000, tv.* -> :4000)
if [ "$WITH_CF" = 1 ]; then
	tmux split-window -t "$SESSION" "cloudflared tunnel --config '$CF_CONFIG' run; echo; echo '[cloudflared exited]'; exec bash"
fi
tmux select-layout -t "$SESSION" tiled

IP="$(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -1)"
cat <<EOF
Started tmux session '$SESSION':
  - asr_server (Whisper '$MODEL' + vocal split) on :$ASR_PORT
  - app.py  ->  web UI at http://127.0.0.1:5000  (https on :5001 for phone mic)
$( [ "$WITH_TV" = 1 ] && echo "  - stream-tv  ->  TV browser (HLS): http://$IP:4000" )
Attach now... (detach: Ctrl-b then d ; stop all: tmux kill-session -t $SESSION)
EOF
sleep 1
tmux attach -t "$SESSION"
