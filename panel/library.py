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


# ---- per-song management (the panel's Library tab) ------------------------------------
import concurrent.futures
import json
import re
import subprocess

KM_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
DURATIONS = os.path.expanduser('~/.cache/ohk/durations.json')


def split_name(media):
	"""'Title---id.ext' -> (title, id, ext). The app shows only the title."""
	stem, ext = os.path.splitext(media)
	title, sep, vid = stem.partition('---')
	return title, (vid if sep else ''), ext


def _durations(root, names):
	"""Song lengths via ffprobe, cached by (name, size, mtime) so only new files get probed."""
	try:
		cache = json.load(open(DURATIONS))
	except (OSError, ValueError):
		cache = {}
	key = lambda n: (lambda st: f'{n}|{st.st_size}|{int(st.st_mtime)}')(os.stat(os.path.join(root, n)))
	todo = [n for n in names if key(n) not in cache]

	def probe(n):
		r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
		                    'file:' + os.path.join(root, n)], capture_output = True, text = True, timeout = 20)
		try:
			return n, round(float(r.stdout.strip()))
		except ValueError:
			return n, None
	if todo:
		with concurrent.futures.ThreadPoolExecutor(8) as ex:
			for n, d in ex.map(probe, todo):
				cache[key(n)] = d
		os.makedirs(os.path.dirname(DURATIONS), exist_ok = True)
		live = {key(n) for n in names}
		json.dump({k: v for k, v in cache.items() if k in live}, open(DURATIONS, 'w'))
	return {n: cache.get(key(n)) for n in names}


def assoc_files(root, media, all_media):
	"""Every file that belongs to one song, relative to the library: the media itself, its
	vocal/nonvocal stems (also the '.X.m4a' in-progress form), and its subtitle sidecars.
	Sidecars belong to the STEM, which a second download of the same song in another format
	can share; those come back separately as `shared` so a delete can leave them alone.
	Returns (own, shared, owned_sidecars)."""
	stem = os.path.splitext(media)[0]
	own = [media]
	for sub in ('vocal', 'nonvocal'):
		for n in (media + '.m4a', '.' + media + '.m4a', media + '.f0.npz'):
			if os.path.isfile(os.path.join(root, sub, n)):
				own.append(f'{sub}/{n}')
	sidecars = [f for f in os.listdir(root)
	            if f.startswith(stem + '.') and f != media and not _is_media(f) and not f.endswith(PARTIAL_EXTS)
	            and f[len(stem):].lower().endswith(SIDECAR_EXTS) and os.path.isfile(os.path.join(root, f))]
	siblings = [m for m in all_media if m != media and os.path.splitext(m)[0] == stem]
	if siblings:
		return own, sidecars, []          # (own, shared, owned sidecars)
	return own, [], sidecars


def songs():
	cfg = C.load()
	root = C.song_dir(cfg)
	files = [f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f))]
	all_media = sorted(f for f in files if _is_media(f) and not f.endswith(PARTIAL_EXTS))
	durs = _durations(root, all_media)
	out = []
	for m in all_media:
		title, vid, ext = split_name(m)
		stem = os.path.splitext(m)[0]
		st = os.stat(os.path.join(root, m))
		has = lambda p: os.path.isfile(os.path.join(root, p))
		wipe = has(stem + '.ass') or has(stem + '.ssa')
		out.append({
			'name': m, 'title': title, 'id': vid, 'ext': ext.lstrip('.'),
			'size_mb': round(st.st_size / 1e6, 1), 'added': int(st.st_mtime), 'duration': durs.get(m),
			'colorwipe': ('karaoke-mugen' if KM_ID.match(vid) else 'generated') if wipe else None,
			'romaji': has(stem + '.romaji.srt'),
			'stems': has(f'vocal/{m}.m4a') and has(f'nonvocal/{m}.m4a'),
			'duplicate': any(o != m and os.path.splitext(o)[0] == stem for o in all_media),
			'hidden': m.startswith('.'),
		})
	return {'root': root, 'songs': out}


def _trash_batch():
	return os.path.join(TRASH, datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))


def _move(root, rels, dest):
	moved = []
	for rel in rels:
		dst = os.path.join(dest, rel)
		os.makedirs(os.path.dirname(dst), exist_ok = True)
		try:
			shutil.move(os.path.join(root, rel), dst)
			moved.append(rel)
		except OSError:
			pass
	return moved


def _media_list(root):
	return [f for f in os.listdir(root) if os.path.isfile(os.path.join(root, f)) and _is_media(f)
	        and not f.endswith(PARTIAL_EXTS)]


def delete_song(name):
	root = C.song_dir(C.load())
	all_media = _media_list(root)
	if name not in all_media:
		return None, 'no such song'
	own, shared, sidecars = assoc_files(root, name, all_media)
	dest = _trash_batch()
	moved = _move(root, own + sidecars, dest)
	return {'moved': moved, 'kept_shared': shared, 'trash': os.path.basename(dest)}, None


def rename_song(name, new_title):
	root = C.song_dir(C.load())
	all_media = _media_list(root)
	if name not in all_media:
		return None, 'no such song'
	new_title = ' '.join(str(new_title).split())          # collapse whitespace/newlines
	if not new_title or new_title.startswith('.') or '/' in new_title or '---' in new_title or len(new_title) > 200:
		return None, "Title can't be empty, start with '.', or contain '/' or '---'"
	title, vid, ext = split_name(name)
	new_stem = new_title + (f'---{vid}' if vid else '')
	new_name = new_stem + ext
	if new_name == name:
		return {'name': name}, None
	if os.path.exists(os.path.join(root, new_name)):
		return None, f'A song named {new_name} already exists'
	own, shared, sidecars = assoc_files(root, name, all_media)
	old_stem = os.path.splitext(name)[0]
	pairs = [(rel, rel.replace(name, new_name, 1)) for rel in own]
	pairs += [(f, new_stem + f[len(old_stem):]) for f in sidecars]
	for src, dst in pairs:
		if os.path.exists(os.path.join(root, dst)):
			return None, f'{dst} already exists'
	for src, dst in pairs:
		os.replace(os.path.join(root, src), os.path.join(root, dst))
	for f in shared:     # a sibling format still uses these: give the renamed song its own copy
		shutil.copy2(os.path.join(root, f), os.path.join(root, new_stem + f[len(old_stem):]))
	return {'name': new_name}, None


def trash_batches():
	if not os.path.isdir(TRASH):
		return []
	out = []
	for b in sorted(os.listdir(TRASH), reverse = True):
		d = os.path.join(TRASH, b)
		files = [os.path.relpath(os.path.join(p, f), d) for p, _, fs in os.walk(d) for f in fs]
		if not files:
			shutil.rmtree(d, ignore_errors = True)
			continue
		size = sum(os.path.getsize(os.path.join(d, f)) for f in files)
		out.append({'id': b, 'files': sorted(files), 'size_mb': round(size / 1e6, 1),
		            'when': int(os.path.getmtime(d))})
	return out


def _batch_dir(batch):
	if not re.fullmatch(r'[0-9-]+', batch or '') or not os.path.isdir(os.path.join(TRASH, batch)):
		return None
	return os.path.join(TRASH, batch)


def restore_batch(batch):
	d = _batch_dir(batch)
	if not d:
		return None, 'no such trash batch'
	root = C.song_dir(C.load())
	restored, skipped = [], []
	for p, _, fs in os.walk(d):
		for f in fs:
			rel = os.path.relpath(os.path.join(p, f), d)
			dst = os.path.join(root, rel)
			if os.path.exists(dst):
				skipped.append(rel)
				continue
			os.makedirs(os.path.dirname(dst), exist_ok = True)
			shutil.move(os.path.join(p, f), dst)
			restored.append(rel)
	if not skipped:
		shutil.rmtree(d, ignore_errors = True)
	return {'restored': restored, 'skipped': skipped}, None


def empty_batch(batch):
	d = _batch_dir(batch)
	if not d:
		return 'no such trash batch'
	shutil.rmtree(d)
	return None
