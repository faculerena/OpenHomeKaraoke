#!/usr/bin/env bash
# Pre-generate the vocal/nonvocal stems for every song that is missing them, using the
# already-running ASR server (asr_server.py). Songs that already have both are skipped,
# so this is safe to re-run and cheap when there is nothing to do.
#
# Why you'd want this: stems are normally produced in the background the first time a song
# is PLAYED, so a freshly added song's MUSIC | MIXED | VOICE toggle stays greyed out for its
# whole first play. Running this ahead of a party means the toggle works from the first note.
#
# Usage:  ./presplit-vocals.sh [-d SONG_DIR] [-c ASR_URL]
#   -d  song library   (default: ~/pikaraoke-songs)
#   -c  ASR server URL (default: http://127.0.0.1:5005)
set -u

D="$HOME/pikaraoke-songs"
CLOUD="http://127.0.0.1:5005"
while getopts "d:c:h" opt; do
	case $opt in
		d) D="$OPTARG";;
		c) CLOUD="$OPTARG";;
		h) grep '^#' "$0" | sed 's/^# \?//'; exit 0;;
		*) exit 1;;
	esac
done
D="${D%/}"

if ! curl -s --max-time 5 -o /dev/null "$CLOUD"; then
	echo "ASR server unreachable at $CLOUD — start it first (start-karaoke.sh)." >&2
	exit 1
fi

mkdir -p "$D/vocal" "$D/nonvocal"
shopt -s nullglob
ok=0; fail=0; skip=0
for f in "$D"/*.mp4 "$D"/*.webm "$D"/*.mkv "$D"/*.avi; do
	bn=$(basename "$f")
	if [ -f "$D/nonvocal/$bn.m4a" ] && [ -f "$D/vocal/$bn.m4a" ]; then
		skip=$((skip+1)); continue
	fi
	echo "[split] $bn"
	t=$(mktemp -d)
	# file: — a ':' in the song name is otherwise parsed by ffmpeg as a protocol.
	# matroska — YouTube audio is usually opus, which an .m4a container cannot hold.
	# The server probes by content, so the file name it is saved under does not matter.
	if ! ffmpeg -y -v error -i "file:$f" -vn -c copy -f matroska "$t/in.m4a" 2>/dev/null; then
		echo "[FAIL]  $bn (audio extract)"; fail=$((fail+1)); rm -rf "$t"; continue
	fi
	if curl -s --max-time 1800 -F "file=@$t/in.m4a" "$CLOUD/split_vocal" -o "$t/out.tgz" \
	   && tar tzf "$t/out.tgz" >/dev/null 2>&1; then
		tar xzf "$t/out.tgz" -C "$t"
		mv -f "$t/nonvocal.m4a" "$D/nonvocal/$bn.m4a"
		mv -f "$t/vocal.m4a"    "$D/vocal/$bn.m4a"
		echo "[ok]    $bn"; ok=$((ok+1))
	else
		echo "[FAIL]  $bn (split)"; fail=$((fail+1))
	fi
	rm -rf "$t"
done
echo "done: $ok split, $skip already had stems, $fail failed"
