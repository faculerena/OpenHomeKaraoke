# Song-library health: what is missing (stems, color-wipes) and what is left over.
#
# Cleanup never deletes. It MOVES files into ~/.local/share/ohk/trash/<timestamp>/, keeping
# their path relative to the library, so anything moved by mistake can be put back by hand.
import datetime
import os
import shutil
import sys
import time

from panel import config as C

sys.path.insert(0, C.REPO)
from constants import media_types     # the exact list app.py scans for  # noqa: E402

TRASH = os.path.expanduser('~/.local/share/ohk/trash')
SIDECAR_EXTS = ('.ass', '.ssa', '.srt', '.vtt', '.lrc', '.cdg', '.txt', '.npz')
PARTIAL_EXTS = ('.part', '.ytdl', '.temp')
RECENT_SEC = 3600            # never touch partials younger than this: a download may own them


def _is_media(name):
	return os.path.splitext(name)[1].lower() in media_types


def _belongs(name, stems):
	"""Does sidecar `name` (e.g. 'X.romaji.srt') belong to one of the media stems?"""
	return any(name.startswith(s + '.') for s in stems)


def scan(downloads_active = 0):
	cfg = C.load()
	root = C.song_dir(cfg)
	if not os.path.isdir(root):
		return {'error': f'song folder not found: {root}'}
	files = [f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f))]
	media = sorted(f for f in files if _is_media(f) and not f.startswith('.') and not f.endswith(PARTIAL_EXTS))
	hidden = sorted(f for f in files if _is_media(f) and f.startswith('.'))
	all_media = set(media) | set(hidden)
	stems = {os.path.splitext(m)[0] for m in all_media}
	now = time.time()

	orphans, partials, recent = [], [], []

	def partial(rel):
		path = os.path.join(root, rel)
		if downloads_active or now - os.path.getmtime(path) < RECENT_SEC:
			recent.append(rel)
		else:
			partials.append(rel)

	for f in files:
		if f.startswith('.') and not _is_media(f):
			continue                           # .delays, .mp3_volume.json.gz: app state
		if f.endswith(PARTIAL_EXTS) or '.part.' in f:
			partial(f)
		elif not _is_media(f) and f.lower().endswith(SIDECAR_EXTS) and not _belongs(f, stems):
			orphans.append(f)

	for sub in ('vocal', 'nonvocal'):
		d = os.path.join(root, sub)
		if not os.path.isdir(d):
			continue
		for f in os.listdir(d):
			name = f
			for suffix in ('.f0.npz', '.m4a'):
				if name.endswith(suffix):
					name = name[:-len(suffix)]
					break
			# '.X.m4a' is a stem still being written, but a song can itself start with '.'
			# ('...Baby One More Time'), so try the name both with and without the dot
			if name not in all_media and name[1:] not in all_media:
				(partial if '.part' in name else orphans.append)(f'{sub}/{f}')

	tmp = os.path.join(root, 'tmp')
	if os.path.isdir(tmp):
		for f in os.listdir(tmp):
			partial(f'tmp/{f}')

	by_stem = {}
	for m in all_media:
		by_stem.setdefault(os.path.splitext(m)[0], []).append(m)
	has = lambda sub, m: os.path.isfile(os.path.join(root, sub, m + '.m4a'))
	no_wipe = [m for m in media if not any(os.path.isfile(os.path.join(root, os.path.splitext(m)[0] + e))
	                                       for e in ('.ass', '.ssa'))]
	no_stems = [m for m in media if not (has('vocal', m) and has('nonvocal', m))]

	return {
		'root': root,
		'songs': len(media),
		'missing_colorwipe': no_wipe,
		'missing_stems': no_stems,
		'cleanable': sorted(orphans) + sorted(partials),
		'orphans': sorted(orphans),
		'partials': sorted(partials),
		'skipped_recent': sorted(recent),
		'duplicates': sorted(v for v in by_stem.values() if len(v) > 1),
		'hidden': hidden,            # media whose name starts with '.': app.py never lists them
		'size_mb': round(sum(os.path.getsize(os.path.join(root, r)) for r in sorted(orphans) + sorted(partials)
		                     if os.path.isfile(os.path.join(root, r))) / 1e6, 1),
	}


def cleanup(selected, downloads_active = 0):
	"""Move the selected files to the trash. Only paths the scan offers are accepted."""
	info = scan(downloads_active)
	if 'error' in info:
		return info
	allowed = set(info['cleanable'])
	picked = [r for r in selected if r in allowed]
	if not picked:
		return {'moved': [], 'trash': None}
	dest = os.path.join(TRASH, datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
	moved = []
	for rel in picked:
		src = os.path.join(info['root'], rel)
		dst = os.path.join(dest, rel)
		os.makedirs(os.path.dirname(dst), exist_ok = True)
		try:
			shutil.move(src, dst)
			moved.append(rel)
		except OSError:
			pass
	return {'moved': moved, 'trash': dest}
