# Extract a song's plain lyrics from whatever subtitle it ships with, so the mobile web UI
# can show them as a scrollable list (see /lyrics in app.py and the Lyrics panel in
# templates/f_home.html).
#
# Source priority mirrors what the TV player actually renders (karaoke.py play_file):
#   <base>.ass / .ssa   -> syllable color-wipe karaoke (Karaoke Mugen / make-karaoke.py)
#   <base>.romaji.srt   -> romanized Japanese (romanize_subs.py)
#   <base>.srt/.vtt/.lrc/.txt
#   embedded track 0    -> whatever shipped inside the video, pulled out with ffmpeg
#
# Every source except .txt carries timestamps, so the UI can offer a synced mode for free.

import hashlib
import os
import re
import subprocess
import tempfile

# Ordered: first hit wins. '' means the media's own embedded subtitle track.
SIDECAR_EXTS = ('.ass', '.ssa', '.romaji.srt', '.srt', '.vtt', '.lrc', '.txt')

_ASS_OVERRIDE = re.compile(r'\{[^}]*\}')            # {\k42}, {\pos(...)}, ...
_ASS_DRAWING = re.compile(r'^[mnlbspc\d\s.+-]+$')   # vector drawing commands, not lyrics
_SRT_TIME = re.compile(r'(\d+):(\d{2}):(\d{2})[.,](\d{1,3})')
_LRC_TIME = re.compile(r'\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]')
_LRC_TAG = re.compile(r'^\[[a-z]{2,}:.*\]$', re.I)  # [ar:...], [ti:...] and friends


def _read(path):
	with open(path, 'rb') as f:
		data = f.read()
	for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
		try:
			return data.decode(enc)
		except UnicodeDecodeError:
			continue
	return data.decode('utf-8', 'ignore')


def _clean(text):
	"""Turn one subtitle cue into displayable plain text (or '' if it isn't lyrics)."""
	text = _ASS_OVERRIDE.sub('', text)
	text = re.sub(r'\\[Nn]', '\n', text).replace('\\h', ' ')
	text = re.sub(r'<[^>]+>', '', text)                 # SRT/VTT markup: <i>, <font ...>
	text = re.sub(r'[ \t]+', ' ', text)
	lines = [L.strip() for L in text.split('\n')]
	text = '\n'.join(L for L in lines if L)
	return '' if _ASS_DRAWING.match(text) else text


def _ass_time(val):
	m = _SRT_TIME.match(val.strip())
	if not m:
		return None
	h, mi, s, frac = m.groups()
	return int(h) * 3600 + int(mi) * 60 + int(s) + int(frac) / 10 ** len(frac)


def parse_ass(data):
	cues, fields = [], None
	for line in data.splitlines():
		line = line.strip()
		if line.lower().startswith('format:') and fields is None and 'text' in line.lower():
			fields = [f.strip().lower() for f in line.split(':', 1)[1].split(',')]
		elif line.startswith('Dialogue:'):
			if fields is None:                          # malformed header: assume the standard layout
				fields = ['layer', 'start', 'end', 'style', 'name',
				          'marginl', 'marginr', 'marginv', 'effect', 'text']
			# Text is always last and may itself contain commas, hence the bounded split.
			parts = line.split(':', 1)[1].split(',', len(fields) - 1)
			if len(parts) < len(fields):
				continue
			row = dict(zip(fields, parts))
			start, end = _ass_time(row.get('start', '')), _ass_time(row.get('end', ''))
			text = _clean(row.get('text', ''))
			if text and start is not None:
				cues.append((start, end, text))
	return cues


def parse_srt(data):
	cues = []
	for block in re.split(r'\n\s*\n', data.replace('\r\n', '\n')):
		lines = [L for L in block.split('\n') if L.strip()]
		idx = next((i for i, L in enumerate(lines) if '-->' in L), None)
		if idx is None:
			continue
		stamps = _SRT_TIME.findall(lines[idx])
		if not stamps:
			continue
		to_sec = lambda t: int(t[0]) * 3600 + int(t[1]) * 60 + int(t[2]) + int(t[3]) / 10 ** len(t[3])
		start = to_sec(stamps[0])
		end = to_sec(stamps[1]) if len(stamps) > 1 else None
		text = _clean('\n'.join(lines[idx + 1:]))
		if text:
			cues.append((start, end, text))
	return cues


def parse_lrc(data):
	cues = []
	for line in data.splitlines():
		line = line.strip()
		if not line or (_LRC_TAG.match(line) and not _LRC_TIME.match(line)):
			continue
		stamps = _LRC_TIME.findall(line)
		text = _clean(_LRC_TIME.sub('', line))
		if not text:
			continue
		if not stamps:
			cues.append((None, None, text))
			continue
		for mi, s, frac in stamps:                      # one line can carry several timestamps
			t = int(mi) * 60 + int(s) + (int(frac) / 10 ** len(frac) if frac else 0)
			cues.append((t, None, text))
	return cues


def parse_txt(data):
	return [(None, None, L.strip()) for L in data.splitlines() if L.strip()]


def _parse(data, ext):
	if ext in ('.ass', '.ssa'):
		return parse_ass(data)
	if ext == '.lrc':
		return parse_lrc(data)
	if ext == '.txt':
		return parse_txt(data)
	return parse_srt(data)


def _tidy(cues):
	"""Sort by time, merge the repeats that rolling captions and multi-style .ass files produce."""
	timed = [c for c in cues if c[0] is not None]
	if timed:
		cues = sorted(timed, key = lambda c: (c[0], c[1] if c[1] is not None else c[0]))
	out = []
	for start, end, text in cues:
		if out and out[-1][2] == text:
			# Same words again back-to-back: one lyric line, not two. Keep the later end time.
			prev = out[-1]
			out[-1] = (prev[0], end if prev[1] is None or (end or 0) > prev[1] else prev[1], text)
			continue
		out.append((start, end, text))
	return out


def _embedded_srt(media, tmp_dir):
	"""Pull the video's own subtitle track out with ffmpeg, cached next to the other temp files."""
	try:
		stat = os.stat(media)
	except OSError:
		return None
	key = hashlib.md5(f'{media}|{stat.st_mtime_ns}|{stat.st_size}'.encode('utf-8')).hexdigest()
	cache = os.path.join(tmp_dir or tempfile.gettempdir(), f'lyrics-{key}.srt')
	if os.path.isfile(cache):
		return _read(cache) if os.path.getsize(cache) else None
	# 'file:' prefix: ffmpeg reads a leading "word:" as a protocol, so a song title
	# containing ':' would otherwise fail to open (same guard as vocal_splitter.py).
	r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', 'file:' + media,
	                    '-map', '0:s:0', '-c:s', 'subrip', '-f', 'srt', cache],
	                   capture_output = True)
	if r.returncode != 0 or not os.path.isfile(cache):
		open(cache, 'wb').close()                       # remember the miss; don't re-probe every open
		return None
	return _read(cache) if os.path.getsize(cache) else None


def find_source(media_path):
	"""Return (path, ext) of the sidecar subtitle the lyrics should come from, or None."""
	stem = os.path.splitext(media_path)[0]
	for ext in SIDECAR_EXTS:
		cand = stem + ext
		if os.path.isfile(cand) and os.path.getsize(cand):
			return cand, os.path.splitext(cand)[1].lower()
	return None


def get_lyrics(media_path, tmp_dir = None):
	"""Lyrics of one song as {available, synced, source, lines:[{t, e, s}]}."""
	empty = {'available': False, 'synced': False, 'source': None, 'lines': []}
	if not media_path or not os.path.isfile(media_path):
		return empty

	found = find_source(media_path)
	if found:
		path, ext = found
		cues, source = _parse(_read(path), ext), os.path.basename(path)
	else:
		data = _embedded_srt(media_path, tmp_dir)
		if not data:
			return empty
		cues, source = parse_srt(data), 'embedded'

	cues = _tidy(cues)
	if not cues:
		return empty
	return {
		'available': True,
		'synced': all(c[0] is not None for c in cues),
		'source': source,
		'lines': [{'t': c[0], 'e': c[1], 's': c[2]} for c in cues],
	}
