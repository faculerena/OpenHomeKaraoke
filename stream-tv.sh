#!/usr/bin/env bash
# Stream the karaoke to a TV's web browser (Wayland / Hyprland native, browser/HLS).
# The bundled screencapture.sh uses X11 x11grab, which captures a BLACK frame on Wayland;
# this uses wf-recorder (wlr-screencopy) + GPU VAAPI encode -> MPEG-TS -> HLS -> a tiny HTTP server.
# A browser keeps audio+video in sync (a couple seconds behind live, but locked together).
#
# Usage:  ./stream-tv.sh [-o OUTPUT|auto] [-p PORT] [-a AUDIO_SOURCE]
#                        [-q QP] [-b KBPS] [-s HEIGHT] [-r FPS] [-A KBPS] [-l SECONDS]
#   -o  Wayland output to capture   (default: first hyprctl monitor, e.g. DP-2;
#                                    'auto' = the sole output on $WAYLAND_DISPLAY, e.g. a cage compositor)
#   -p  HTTP port the TV opens      (default: 4000)
#   -a  Pulse/PipeWire audio source (default: the default sink's .monitor)
#
# Bandwidth (what actually goes over the wire / the Cloudflare tunnel). Measured on this
# machine at 720p30, video only: a busy music video ~1125 kbps and a static-image song with
# lyrics ~460 kbps at the default qp=28 — roughly 45% off the old no-rate-control encode
# (2045 / 787), with no visible difference on a TV.
#   -q  quality, QP 20-34           (default: 28. Higher = smaller + softer. Quality-based,
#                                    so an idle splash or a lyrics-only song stays cheap.)
#   -b  hard bitrate cap, kbps      (default: none. Switches the encoder to VBR and REPLACES
#                                    -q: it guarantees a ceiling, but the encoder then also
#                                    SPENDS that budget on cheap frames — at -b 1500 the
#                                    static song above costs 1355 instead of 461. Use it only
#                                    when a hard ceiling matters more than the average.)
#   -s  scale down to HEIGHT px     (default: none = native 720p. -s 540 takes the music
#                                    video to ~870 kbps and the static one to ~350; lyrics
#                                    stay readable.)
#   -r  framerate                   (default: 30)
#   -A  audio bitrate, kbps         (default: 128)
#   -l  segment/keyframe seconds    (default: 0.5. Bigger = fewer keyframes = less
#                                    bandwidth, but that much more delay on the TV.)
# Each flag also has an env default: OHK_TV_QUALITY, OHK_TV_BITRATE, OHK_TV_SCALE,
# OHK_TV_FPS, OHK_TV_ABITRATE, OHK_TV_SEG — that is how start-karaoke.sh -t passes them in.
#
# Then open  http://<this-ip>:<port>  in the TV's browser (e.g. TV Bro). Ctrl-C to stop.
set -u

OUTPUT=""; PORT=4000; AUDIO=""
VQ="${OHK_TV_QUALITY:-28}"; VKBPS="${OHK_TV_BITRATE:-}"; SCALE="${OHK_TV_SCALE:-}"
FPS="${OHK_TV_FPS:-30}"; AKBPS="${OHK_TV_ABITRATE:-128}"; SEG_SEC="${OHK_TV_SEG:-0.5}"
while getopts "o:p:a:q:b:s:r:A:l:h" opt; do
	case $opt in
		o) OUTPUT="$OPTARG";;
		p) PORT="$OPTARG";;
		a) AUDIO="$OPTARG";;
		q) VQ="$OPTARG";;
		b) VKBPS="$OPTARG";;
		s) SCALE="$OPTARG";;
		r) FPS="$OPTARG";;
		A) AKBPS="$OPTARG";;
		l) SEG_SEC="$OPTARG";;
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
    // sit 1 segment (~0.5s) behind the live edge instead of 2, and re-sync if we drift back
    var hls=new Hls({lowLatencyMode:true,liveSyncDurationCount:1,liveMaxLatencyDurationCount:6,
                     maxBufferLength:4,backBufferLength:4});
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

# Latency budget: a segment can only be published once it is COMPLETE, and the player then
# sits liveSyncDurationCount segments behind the edge. So end-to-end delay scales with
# SEGMENT length — 0.5s segments roughly halve it versus 1s. Every segment must start on a
# keyframe, so the GOP is derived from SEG_SEC (g = fps x seg) instead of being hardcoded:
# a longer -l then buys bandwidth back (keyframes are by far the most expensive frames, which
# is why an idle splash screen still costs ~1 Mbps at 2 keyframes/sec) at the cost of delay.
GOP="$(awk -v f="$FPS" -v s="$SEG_SEC" 'BEGIN{g=int(f*s+0.5); print (g<1?1:g)}')"
# Rate control. Left alone the VAAPI encoder runs constant-quality at its own (very generous)
# default QP; -q just moves that QP. Quality-based is the right default for karaoke because the
# picture is cheap most of the time (splash, a static album image, black + lyrics) and only a
# real music video costs anything — a bitrate TARGET would hand those cheap frames a budget to
# spend. -b is there for when a hard ceiling matters more. NOTE wf-recorder's own -b means
# BFRAMES, so both paths go through -p (options on the codec context).
if [ -n "$VKBPS" ]; then
	RC=(-p rc_mode=VBR -p b=$((VKBPS * 1000)) -p maxrate=$((VKBPS * 1250)) -p bufsize=$((VKBPS * 2000)))
	RCDESC="VBR ${VKBPS}k (peak $((VKBPS * 5 / 4))k)"
else
	RC=(-p rc_mode=CQP -p qp="$VQ")
	RCDESC="quality qp=$VQ"
fi
FILTER=()
[ -n "$SCALE" ] && FILTER=(-F "scale_vaapi=w=-2:h=$SCALE:format=nv12")

# The scrolling bar (OHK_TV_BAR, from _headless.sh): what's next and where to join, drawn into
# the stream while a song plays. wf-recorder can't draw text on GPU frames, so with the bar on,
# the HLS step decodes, draws (ffmpeg drawtext, re-reading the app's text files twice a
# second) and re-encodes on the GPU; wf-recorder then encodes finer, so the second pass costs
# no visible quality. A bar whose file is empty is moved off-screen. If the bar can't be set
# up on this machine, the stream goes out without it, as before.
BAR="${OHK_TV_BAR:-}"
BARF=""
if [ -n "$BAR" ] && [ -d "$BAR" ]; then
	if fc-list -q "Noto Sans CJK JP" 2>/dev/null; then FS="font=Noto Sans CJK JP\\\\:style=Bold"
	else FS="fontfile=$PWD/font/arial-unicode-ms.ttf"; fi
	bar(){  # $1 file, $2 y of the text; the first drawtext is only the full-width box
		local hide="if(eq(tw\\,0)\\,-9999\\,$2)"
		printf '%s' "drawtext=$FS:textfile=$BAR/$1:reload=15:fontsize=h/33:fontcolor=black@0:x=0:y=$hide:y_align=font:box=1:boxw=100000:boxcolor=0x0d0d0d@0.82:boxborderw=11,drawtext=$FS:textfile=$BAR/$1:reload=15:fontsize=h/33:fontcolor=0xffffff:x=w-mod(t*w/10\\,w+tw):y=$hide:y_align=font"
	}
	BARF="$(bar top.txt 11),$(bar bottom.txt 'h-11-h/33*1.45')"
	if ffmpeg -hide_banner -loglevel error -init_hw_device vaapi=va:/dev/dri/renderD128 -filter_hw_device va \
		-f lavfi -i color=c=black:s=320x240:d=0.3 -vf "$BARF,format=nv12,hwupload" -c:v h264_vaapi -f null - 2>"$D/bar-test.log"; then
		# the HLS step encodes at the asked quality; wf-recorder feeds it finer
		WQ=$(( VQ - 6 < 16 ? 16 : VQ - 6 ))
		if [ -n "$VKBPS" ]; then
			FRC=(-rc_mode VBR -b:v "${VKBPS}k" -maxrate "$((VKBPS * 5 / 4))k" -bufsize "$((VKBPS * 2))k")
		else
			FRC=(-rc_mode CQP -qp "$VQ")
		fi
		RC=(-p rc_mode=CQP -p qp="$WQ")
		RCDESC="$RCDESC, with the song bar"
	else
		echo "TV bar disabled: $(tail -1 "$D/bar-test.log")"
		BARF=""
	fi
fi

echo "Capturing $OUTDESC with audio '$AUDIO'"
echo "Video: ${SCALE:+${SCALE}p }$RCDESC @ ${FPS}fps, keyframe/segment ${SEG_SEC}s, audio ${AKBPS}k"
wf-recorder "${WFOUT[@]}" -c h264_vaapi -d /dev/dri/renderD128 -r "$FPS" \
	-p g="$GOP" -p bf=0 "${RC[@]}" "${FILTER[@]}" \
	--audio="$AUDIO" -C aac -P b="$((AKBPS * 1000))" -m mpegts -f "$FIFO" 2>"$D/wf.log" &
WF=$!
# fast TS probe (-analyzeduration/-probesize) so ffmpeg opens immediately instead of analyzing ~5s;
# nobuffer/low_delay stop it holding frames back. temp_file matters at this segment size: without
# it the HTTP server can hand the player a half-written .ts, which stalls playback.
if [ -n "$BARF" ]; then
	CODEC=(-init_hw_device vaapi=va:/dev/dri/renderD128 -filter_hw_device va)
	ENC=(-vf "$BARF,format=nv12,hwupload" -c:v h264_vaapi -g "$GOP" -bf 0 "${FRC[@]}"
		-force_key_frames "expr:gte(t,n_forced*$SEG_SEC)" -c:a copy)
else
	CODEC=(); ENC=(-c copy)
fi
ffmpeg -hide_banner -loglevel error -analyzeduration 500000 -probesize 200000 \
	-fflags +genpts+nobuffer -flags low_delay "${CODEC[@]}" -i "$FIFO" "${ENC[@]}" \
	-f hls -hls_time "$SEG_SEC" -hls_list_size 6 \
	-hls_flags delete_segments+independent_segments+omit_endlist+temp_file \
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
