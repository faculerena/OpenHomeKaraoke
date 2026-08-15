#!/usr/bin/env bash
# Stream the karaoke to a TV's web browser (Wayland / Hyprland native, browser/HLS).
# The bundled screencapture.sh uses X11 x11grab, which captures a BLACK frame on Wayland;
# this uses wf-recorder (wlr-screencopy) + GPU VAAPI encode -> MPEG-TS -> HLS -> a tiny HTTP server.
# A browser keeps audio+video in sync (a couple seconds behind live, but locked together).
#
# Usage:  ./stream-tv.sh [-o OUTPUT|auto] [-p PORT] [-a AUDIO_SOURCE]
#   -o  Wayland output to capture   (default: first hyprctl monitor, e.g. DP-2;
#                                    'auto' = the sole output on $WAYLAND_DISPLAY, e.g. a cage compositor)
#   -p  HTTP port the TV opens      (default: 4000)
#   -a  Pulse/PipeWire audio source (default: the default sink's .monitor)
#
# Then open  http://<this-ip>:<port>  in the TV's browser (e.g. TV Bro). Ctrl-C to stop.
set -u

OUTPUT=""; PORT=4000; AUDIO=""
while getopts "o:p:a:h" opt; do
	case $opt in
		o) OUTPUT="$OPTARG";;
		p) PORT="$OPTARG";;
		a) AUDIO="$OPTARG";;
		h) grep '^#' "$0" | sed 's/^# \?//'; exit 0;;
		*) exit 1;;
	esac
done

cd "$(dirname "$(readlink -f "$0")")"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if [ "$OUTPUT" = "auto" ]; then
	WFOUT=(); OUTDESC="(sole output on $WAYLAND_DISPLAY)"    # cage: let wf-recorder pick the only output
else
	[ -z "$OUTPUT" ] && OUTPUT="$(hyprctl monitors -j 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)[0]["name"])' 2>/dev/null)"
	[ -z "$OUTPUT" ] && OUTPUT="DP-2"
	WFOUT=(-o "$OUTPUT"); OUTDESC="$OUTPUT"
fi
# Audio source. Prefer the karaoke's OWN sink when it exists (_headless.sh creates it and
# points app.py/VLC at it). Capturing the *default* sink's monitor is a feedback trap: a
# browser playing this very stream renders to that same sink, so its output gets re-captured
# and folded back in every ~2s, stacking the song on top of itself.
OHK_SINK="${OHK_SINK:-ohk_karaoke}"
if [ -z "$AUDIO" ]; then
	if pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -qx "$OHK_SINK"; then
		AUDIO="$OHK_SINK.monitor"
	else
		AUDIO="$(pactl get-default-sink 2>/dev/null).monitor"
	fi
fi
IP="$(ip -4 addr show scope global 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -1)"

D="$(mktemp -d /tmp/ohk-tvstream.XXXXXX)"
FIFO="$D/cap.ts"; mkfifo "$FIFO"
cp -f static/hls.min.js "$D/hls.min.js"

cat > "$D/index.html" <<'HTML'
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenHomeKaraoke TV</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
video{width:100vw;height:100vh;object-fit:contain;background:#000}
#tap{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
color:#fff;font:600 5vw sans-serif;background:rgba(0,0,0,.55);cursor:pointer}</style>
</head><body>
<video id="v" autoplay muted playsinline></video>
<div id="tap">Tap to start &amp; unmute</div>
<script src="hls.min.js"></script>
<script>
var v=document.getElementById('v'),tap=document.getElementById('tap'),url='index.m3u8';
function start(){
  if(window.Hls&&Hls.isSupported()){
    var hls=new Hls({lowLatencyMode:true,liveSyncDurationCount:2,maxBufferLength:6,backBufferLength:6});
    hls.loadSource(url);hls.attachMedia(v);
    hls.on(Hls.Events.ERROR,function(e,d){if(d.fatal){setTimeout(function(){try{hls.loadSource(url);hls.startLoad();}catch(_){}},1000);}});
  }else{v.src=url;}
}
start();
tap.onclick=function(){v.muted=false;v.play();tap.style.display='none';};
</script></body></html>
HTML

CLEANED=0
cleanup(){ [ "$CLEANED" = 1 ] && return; CLEANED=1; pkill -TERM -P $$ 2>/dev/null; sleep 0.4; pkill -KILL -P $$ 2>/dev/null; rm -rf "$D"; }
trap 'cleanup; exit 0' INT TERM
trap cleanup EXIT

echo "Capturing $OUTDESC with audio '$AUDIO'"
# 30fps, 1s keyframes, no B-frames, MPEG-TS (no Matroska cluster buffering)
wf-recorder "${WFOUT[@]}" -c h264_vaapi -d /dev/dri/renderD128 -r 30 -p g=30 -p bf=0 \
	--audio="$AUDIO" -C aac -m mpegts -f "$FIFO" 2>"$D/wf.log" &
WF=$!
# fast TS probe (-analyzeduration/-probesize) so ffmpeg opens immediately instead of analyzing ~5s
ffmpeg -hide_banner -loglevel error -analyzeduration 500000 -probesize 200000 -fflags +genpts -i "$FIFO" -c copy \
	-f hls -hls_time 1 -hls_list_size 4 -hls_flags delete_segments+independent_segments+omit_endlist \
	-hls_segment_type mpegts -hls_segment_filename "$D/seg_%05d.ts" "$D/index.m3u8" 2>"$D/ff.log" &
FF=$!
python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$D" >/dev/null 2>&1 &
SRV=$!

echo
echo "  ============================================================"
echo "    On the TV browser open:  http://$IP:$PORT"
echo "  ============================================================"
echo "    Capturing $OUTDESC. Ctrl-C to stop."
echo
wait $WF
