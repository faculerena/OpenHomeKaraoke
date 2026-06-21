#!/usr/bin/env python3
# Generate a ROMAJI subtitle from a video's Japanese subtitle track.
# YouTube doesn't offer romanized subs, so this extracts the Japanese (jpn) track and
# transliterates it to Hepburn romaji with pykakasi, writing "<basename>.romaji.srt".
# The app prefers that file automatically when it plays the song (see karaoke.py play_file).
#
# Usage:
#   ./romanize_subs.py <media_file> [<media_file> ...]
#   ./romanize_subs.py <songs_dir>          # process every media file in a folder
#   ./romanize_subs.py ~/pikaraoke-songs    # e.g. your whole library

import os, sys, re, subprocess, tempfile
import pykakasi

MEDIA_EXT = ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4a', '.mp3', '.ts')
JP_RE = re.compile(r'[぀-ヿ一-鿿ｦ-ﾟ]')   # kana + kanji + half-width kana
_kks = pykakasi.kakasi()


def has_jpn_sub(path):
	out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 's',
		'-show_entries', 'stream_tags=language', '-of', 'csv=p=0', path],
		capture_output=True, text=True).stdout
	return 'jpn' in out.lower()


def extract_jpn_srt(path, dst):
	r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', path,
		'-map', '0:s:m:language:jpn', '-c:s', 'subrip', dst], capture_output=True, text=True)
	return r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0


def romanize(text):
	return ' '.join(w['hepburn'] for w in _kks.convert(text)).strip()


def romanize_srt_text(data):
	out = []
	for line in data.splitlines():
		if '-->' in line or line.strip().isdigit() or not line.strip():
			out.append(line)
		elif JP_RE.search(line):
			out.append(romanize(line))
		else:
			out.append(line)
	return '\n'.join(out)


def process(path):
	base, _ = os.path.splitext(path)
	dst = base + '.romaji.srt'
	if not has_jpn_sub(path):
		print(f"skip (no Japanese sub track): {os.path.basename(path)}")
		return
	with tempfile.NamedTemporaryFile(suffix='.srt', delete=False) as tmp:
		tmpsrt = tmp.name
	try:
		if not extract_jpn_srt(path, tmpsrt):
			print(f"skip (could not extract jpn sub): {os.path.basename(path)}")
			return
		data = open(tmpsrt, encoding='utf-8', errors='ignore').read()
		open(dst, 'w', encoding='utf-8').write(romanize_srt_text(data))
		print(f"wrote {os.path.basename(dst)}")
	finally:
		try: os.remove(tmpsrt)
		except OSError: pass


def main(argv):
	if not argv:
		print(__doc__); return 1
	targets = []
	for a in argv:
		if os.path.isdir(a):
			targets += [os.path.join(a, f) for f in sorted(os.listdir(a))
			            if f.lower().endswith(MEDIA_EXT)]
		elif os.path.isfile(a):
			targets.append(a)
	for t in targets:
		process(t)
	return 0


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
