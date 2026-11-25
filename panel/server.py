# OHK admin panel: http://127.0.0.1:12345 here, http://<this-machine>.<tailnet>:12345 from
# your own devices on the tailnet. Run as the ohk-panel user service (scripts/ohk-panel).
#
# Who gets in:
#   * this machine (loopback), and
#   * tailnet peers logged in as the same Tailscale user as this machine (tailscale whois).
# It listens ONLY on loopback and the Tailscale addresses, so the LAN can't even connect.
# Requests that came through a proxy (Cloudflare tunnel headers) are refused outright,
# because the tunnel's traffic arrives from loopback too.
#
# Because loopback is trusted, any web page open in a local browser could try to reach us.
# So: the Host header must be one of ours (DNS rebinding), every state change is a JSON
# POST (a cross-site form can't send that without a CORS preflight we never answer), the
# Origin, when sent, must be ours too, and GETs never change anything.
import io
import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.serving import make_server

from panel import config as C
from panel import library, services as S, updates

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
app = Flask(__name__, static_folder = None)

JOBS = {
	'split':        'Re-split one song',
	'presplit':     'Pre-split vocals for every song',
	'gen-missing':  'Generate missing color-wipes',
	'ytdlp-update': 'Update yt-dlp',
}

# ---- tailscale identity ---------------------------------------------------------------
_TS = {'self_user': None, 'ips': [], 'names': [], 'at': 0}
_WHOIS = {}           # ip -> (allowed, checked_at)
TS_NETS = [ipaddress.ip_network('100.64.0.0/10'), ipaddress.ip_network('fd7a:115c:a1e0::/48')]


def _ts_json(cmd, *args):
	# --json must come right after the subcommand: Go's flag parser stops at the first
	# positional argument, so 'tailscale whois <ip> --json' fails with 'too many arguments'.
	try:
		r = subprocess.run(['tailscale', cmd, '--json', *args], capture_output = True, text = True, timeout = 5)
		return json.loads(r.stdout) if r.returncode == 0 else None
	except Exception:
		return None


def ts_self(refresh = False):
	if refresh or time.time() - _TS['at'] > 300:
		st = _ts_json('status', '--self', '--peers=false')
		if st and st.get('Self'):
			me = st['Self']
			dns = (me.get('DNSName') or '').rstrip('.')
			_TS.update(self_user = me.get('UserID'), ips = me.get('TailscaleIPs') or [],
			           names = [n for n in (dns, dns.split('.')[0]) if n], at = time.time())
	return _TS


def tailnet_peer_allowed(ip):
	hit = _WHOIS.get(ip)
	if hit and time.time() - hit[1] < 300:
		return hit[0]
	who = _ts_json('whois', ip)
	me = ts_self()['self_user']
	ok = bool(who and me is not None and (who.get('UserProfile') or {}).get('ID') == me)
	_WHOIS[ip] = (ok, time.time())
	return ok


def _allowed_hosts():
	hosts = {'127.0.0.1', 'localhost', '::1', '[::1]'}
	ts = ts_self()
	for h in ts['ips'] + ts['names']:
		hosts.add(f'[{h}]' if ':' in h else h)
	return hosts


def _hostname(hostport):
	"""'127.0.0.1:12345' -> '127.0.0.1', '[::1]:12345' -> '[::1]', 'atenea' -> 'atenea'."""
	hostport = hostport or ''
	if hostport.startswith('['):
		return hostport.split(']', 1)[0] + ']'
	return hostport.rsplit(':', 1)[0] if hostport.count(':') == 1 else hostport


@app.before_request
def gate():
	if any(h in request.headers for h in ('Cf-Connecting-Ip', 'Cf-Ray', 'X-Forwarded-For', 'Forwarded')):
		abort(403)                                     # came through a proxy/tunnel
	peer = ipaddress.ip_address(request.remote_addr)  # the socket's address, not a header
	if not peer.is_loopback:
		if not any(peer in n for n in TS_NETS) or not tailnet_peer_allowed(str(peer)):
			abort(403)
	if _hostname(request.host) not in _allowed_hosts():
		abort(403)
	if request.method not in ('GET', 'HEAD'):
		if not request.is_json:
			abort(415)
		origin = request.headers.get('Origin')
		if origin and _hostname(origin.split('://', 1)[-1]) not in _allowed_hosts():
			abort(403)


def body():
	return request.get_json(silent = True) or {}


def result(err, **extra):
	return (jsonify(ok = False, error = err), 400) if err else jsonify(ok = True, **extra)


# ---- tonight's timeline (the dial) ------------------------------------------------------
# The app only knows the current song and the queue, so the panel remembers what has been
# sung since it started: a background poll notes each song change.
TIMELINE = {'history': [], 'current': None}
_tl_lock = threading.Lock()


def _watch_app():
	while True:
		st = S.http_json(f'http://127.0.0.1:{C.APP_PORT}/ohk_status', timeout = 2)
		now = time.time()
		with _tl_lock:
			cur = TIMELINE['current']
			key = (st or {}).get('now_playing_file') or (st or {}).get('now_playing')
			if cur and cur['key'] != key:
				# the previous song ended (or was skipped) at about now
				TIMELINE['history'].append({'title': cur['title'], 'user': cur['user'],
				                            'start': cur['start'], 'end': now})
				TIMELINE['history'] = TIMELINE['history'][-40:]
				TIMELINE['current'] = cur = None
			if st and key:
				# start = now - position on every poll: follows seeks, and while paused the
				# rest of the song (and everything after it) slides later, as it really does
				pos = st.get('position') or 0
				TIMELINE['current'] = {'key': key, 'title': st['now_playing'], 'user': st.get('now_playing_user'),
				                       'start': now - pos, 'length': st.get('length'), 'position': pos,
				                       'paused': st.get('is_paused')}
		time.sleep(3)


def _durations_for(queue):
	"""Lengths of queued songs, from the library's ffprobe cache. Old app builds report only
	titles, so fall back to matching the title."""
	root = C.song_dir(C.load())
	try:
		media = [f for f in os.listdir(root) if library._is_media(f)]
	except OSError:
		return [None] * len(queue)
	by_title = {}
	for m in media:
		by_title.setdefault(library.split_name(m)[0], m)
	names = [q.get('file') if q.get('file') in media else by_title.get(q.get('title')) for q in queue]
	d = library._durations(root, [n for n in names if n])
	return [d.get(n) if n else None for n in names]


def timeline(app_st):
	with _tl_lock:
		hist = list(TIMELINE['history'])
		cur = dict(TIMELINE['current']) if TIMELINE['current'] else None
	queue = (app_st or {}).get('queue') or []
	durs = _durations_for(queue) if queue else []
	return {
		'now': time.time(),
		'history': hist,
		'current': cur and {k: cur[k] for k in ('title', 'user', 'start', 'length', 'position', 'paused')},
		'queue': [{'title': q['title'], 'user': q['user'], 'duration': d} for q, d in zip(queue, durs)],
	}


# ---- status ---------------------------------------------------------------------------
def lan_ip():
	try:
		out = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'scope', 'global'],
		                     capture_output = True, text = True, timeout = 3).stdout
	except Exception:
		return None
	for line in out.splitlines():
		parts = line.split()
		dev, addr = parts[1], parts[3].split('/')[0]
		if dev.startswith(('tailscale', 'docker', 'br-', 'virbr', 'veth', 'lo')):
			continue
		return addr
	return None


def _health(key, st, cfg, live):
	"""ok | starting | degraded | failed | stopped, plus a short note."""
	a = st['active']
	if a in ('inactive', None) or not st['loaded']:
		return ('failed', 'exited with an error') if st['result'] not in (None, 'success') else ('stopped', None)
	if a == 'failed':
		return 'failed', f"exited (status {st['exit_status']})"
	if a in ('activating', 'deactivating'):
		return 'starting' if a == 'activating' else 'stopping', None
	if key == 'asr':
		return ('ok', None) if live['asr'] is not None else ('starting', 'loading models')
	if key in ('app', 'app-tv'):
		if live['app'] is None:
			return 'starting', 'web UI not answering yet'
		if key == 'app-tv' and not live['tv_stream']:
			return 'degraded', 'TV stream not answering on :%d' % C.TV_PORT
		return 'ok', None
	return 'ok', None


@app.get('/api/status')
def api_status():
	cfg = C.load()
	units = [v['unit'] for v in S.SERVICES.values()] + [S.job_unit(j) for j in JOBS]
	states = S.unit_states(units)
	live = {
		'asr': S.http_json(f"http://127.0.0.1:{cfg['asr_port']}/status"),
		'app': S.http_json(f'http://127.0.0.1:{C.APP_PORT}/ohk_status'),
		'tv_stream': S.http_ok(f'http://127.0.0.1:{C.TV_PORT}/'),
	}
	svc = {}
	for key, meta in S.SERVICES.items():
		st = states[meta['unit']]
		health, note = _health(key, st, cfg, live)
		svc[key] = dict(label = meta['label'], unit = meta['unit'], health = health, note = note,
		                uptime = st['uptime'], restarts = st['restarts'],
		                error = S.last_error(meta['unit']) if health in ('failed', 'degraded') else None)

	up = lambda k: svc[k]['health'] not in ('stopped', 'failed')
	mode = ('public' if up('tunnel') else 'tv') if up('app-tv') else ('monitor' if up('app') else None)

	lan = lan_ip()
	ts = ts_self()
	app_url = (live['app'] or {}).get('url') or (f'http://{lan}:{C.APP_PORT}' if lan else None)
	join = []
	if mode:
		join.append({'label': 'Phone (same Wi-Fi)', 'url': app_url, 'qr': True})
		if lan:
			join.append({'label': 'Phone with voice search (https, accept the certificate)',
			             'url': f'https://{lan}:{C.APP_PORT + 1}', 'qr': True})
		if mode in ('tv', 'public') and lan:
			join.append({'label': 'TV browser', 'url': f'http://{lan}:{C.TV_PORT}', 'qr': True})
		if mode == 'public':
			join.append({'label': 'Guests, from anywhere', 'url': cfg['public_url'], 'qr': True})
			join.append({'label': 'TV, public', 'url': cfg['public_tv_url'], 'qr': False})
		if ts['names']:
			join.append({'label': 'You, over the tailnet', 'url': f"http://{ts['names'][0]}:{C.APP_PORT}", 'qr': False})

	jobs = {}
	for name, label in JOBS.items():
		st = states[S.job_unit(name)]
		if not st['loaded'] or st['active'] == 'inactive':
			state = 'failed' if st['result'] not in (None, 'success') else 'idle'
		elif st['active'] == 'activating' or st['sub'] == 'running':
			state = 'running'
		elif st['exit_status'] == '0':
			state = 'done'
		else:
			state = 'failed'
		jobs[name] = {'label': label, 'state': state}

	return jsonify(
		timeline = timeline(live['app']),
		mode = mode, last_mode = cfg['mode'], services = svc, join = join,
		activity = {'app': live['app'], 'gpu': live['asr']}, jobs = jobs,
		legacy_session = S.legacy_session(),
		host = socket.gethostname(),
	)


@app.post('/api/start')
def api_start():
	return result(S.start(body().get('mode')))


@app.post('/api/stop')
def api_stop():
	return result(S.stop())


@app.post('/api/restart')
def api_restart():
	return result(S.restart(body().get('service')))


@app.get('/api/logs')
def api_logs():
	name = request.args.get('unit', '')
	if name in S.SERVICES:
		unit = S.SERVICES[name]['unit']
	elif name == 'panel':
		unit = 'ohk-panel.service'
	elif name.startswith('job:') and name[4:] in JOBS:
		unit = S.job_unit(name[4:])
	else:
		abort(404)
	return jsonify(unit = unit, text = S.logs(unit, int(request.args.get('lines', 120))))


# ---- settings -------------------------------------------------------------------------
def public_settings(cfg):
	out = {k: v for k, v in cfg.items() if k != 'admin_password'}
	out['admin_password_set'] = bool(cfg['admin_password'])
	out['whisper_models'] = C.WHISPER_MODELS
	return out


@app.get('/api/settings')
def api_settings():
	return jsonify(public_settings(C.load()))


@app.post('/api/settings')
def api_settings_save():
	cfg, err = C.validate(body(), C.load())
	if err:
		return result(err)
	C.save(cfg)
	return result(None, settings = public_settings(cfg))


# ---- library --------------------------------------------------------------------------
def _downloads_active():
	app_st = S.http_json(f'http://127.0.0.1:{C.APP_PORT}/ohk_status')
	return (app_st or {}).get('downloading', 0)


@app.get('/api/library')
def api_library():
	return jsonify(library.scan(_downloads_active()))


@app.post('/api/library/cleanup')
def api_cleanup():
	files = body().get('files') or []
	if not isinstance(files, list):
		return result('files must be a list')
	return jsonify(ok = True, **library.cleanup([str(f) for f in files], _downloads_active()))


# ---- per-song management (Library tab) -------------------------------------------------
def _app_status():
	return S.http_json(f'http://127.0.0.1:{C.APP_PORT}/ohk_status')


def _busy(name):
	"""Why a song can't be touched right now (playing / queued), or None."""
	st = _app_status()
	if not st:
		return None
	title = library.split_name(name)[0]
	# an app started before /ohk_status reported file names only gives titles: match on those
	if st.get('now_playing_file') == name or (not st.get('now_playing_file') and st.get('now_playing') == title):
		return 'That song is playing right now.'
	if any(q.get('file') == name or ('file' not in q and q['title'] == title) for q in st['queue']):
		return 'That song is in the queue: remove it there first.'
	return None


def _app_rescan():
	"""Make a running app re-read the song folder (its /refresh is admin-only)."""
	if not _app_status():
		return
	pw = C.load()['admin_password']
	req = urllib.request.Request(f'http://127.0.0.1:{C.APP_PORT}/refresh',
	                             headers = {'Cookie': f'admin={pw}'} if pw else {})
	try:
		urllib.request.urlopen(req, timeout = 10).read()
	except Exception:
		pass


def _song_arg():
	name = str(body().get('name') or '')
	if not name or '/' in name or name in ('.', '..'):
		abort(400)
	return name


@app.get('/api/songs')
def api_songs():
	out = library.songs()
	st = _app_status() or {}
	out['playing'] = st.get('now_playing_file')
	out['queued'] = [q.get('file') for q in st.get('queue', [])]
	out['app_running'] = bool(st)
	return jsonify(out)


@app.post('/api/songs/delete')
def api_song_delete():
	name = _song_arg()
	err = _busy(name)
	if err:
		return result(err)
	res, err = library.delete_song(name)
	if not err:
		_app_rescan()
	return result(err, **(res or {}))


@app.post('/api/songs/rename')
def api_song_rename():
	name = _song_arg()
	err = _busy(name)
	if err:
		return result(err)
	res, err = library.rename_song(name, body().get('title', ''))
	if not err:
		_app_rescan()
	return result(err, **(res or {}))


@app.post('/api/songs/queue')
def api_song_queue():
	name = _song_arg()
	if not _app_status():
		return result('Karaoke is not running.')
	path = os.path.join(C.song_dir(C.load()), name)
	if not os.path.isfile(path):
		return result('no such song')
	q = urllib.parse.urlencode({'song': path, 'user': 'Panel'})
	try:
		r = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{C.APP_PORT}/enqueue?{q}', timeout = 10).read())
	except Exception as e:
		return result(f'enqueue failed: {e}')
	return result(None if r.get('success') else 'Already in the queue.')


@app.post('/api/songs/colorwipe')
def api_song_colorwipe():
	"""Rebuild one song's color-wipe: the old .ass goes to the trash first (the GPU server
	skips songs that already have one)."""
	name = _song_arg()
	cfg = C.load()
	if S.http_json(f"http://127.0.0.1:{cfg['asr_port']}/status") is None:
		return result('Needs the voice/GPU server: start karaoke first.')
	root = C.song_dir(cfg)
	path = os.path.join(root, name)
	if not os.path.isfile(path):
		return result('no such song')
	stem = os.path.splitext(name)[0]
	old = [f for f in (stem + '.ass', stem + '.ssa') if os.path.isfile(os.path.join(root, f))]
	if old:
		library._move(root, old, library._trash_batch())
	data = urllib.parse.urlencode({'path': path}).encode()
	try:
		urllib.request.urlopen(f"http://127.0.0.1:{cfg['asr_port']}/make_karaoke", data = data, timeout = 10).read()
	except Exception as e:
		return result(f'could not queue the build: {e}')
	return result(None, replaced = old)


@app.post('/api/songs/split')
def api_song_split():
	name = _song_arg()
	cfg = C.load()
	if S.http_json(f"http://127.0.0.1:{cfg['asr_port']}/status") is None:
		return result('Needs the voice/GPU server: start karaoke first.')
	if not os.path.isfile(os.path.join(C.song_dir(cfg), name)):
		return result('no such song')
	return result(S.run_job('split', [C.PY, '-m', 'panel.jobs', 'split', name]))


@app.get('/api/trash')
def api_trash():
	return jsonify(batches = library.trash_batches())


@app.post('/api/trash/restore')
def api_trash_restore():
	res, err = library.restore_batch(str(body().get('batch') or ''))
	if not err:
		_app_rescan()
	return result(err, **(res or {}))


@app.post('/api/trash/empty')
def api_trash_empty():
	return result(library.empty_batch(str(body().get('batch') or '')))


@app.post('/api/jobs/<name>')
def api_job(name):
	cfg = C.load()
	if name == 'presplit':
		argv = [os.path.join(C.REPO, 'presplit-vocals.sh'), '-d', C.song_dir(cfg),
		        '-c', f"http://127.0.0.1:{cfg['asr_port']}"]
	elif name == 'gen-missing':
		argv = [C.PY, '-m', 'panel.jobs', 'gen-missing']
	elif name == 'ytdlp-update':
		argv = [C.PY, '-m', 'pip', 'install', '-U', 'yt-dlp[default]']
	else:
		abort(404)
	if name in ('presplit', 'gen-missing') and S.http_json(f"http://127.0.0.1:{cfg['asr_port']}/status") is None:
		return result('Needs the voice/GPU server: start karaoke first.')
	return result(S.run_job(name, argv))


# ---- updates --------------------------------------------------------------------------
_git_lock = threading.Lock()


@app.get('/api/updates')
def api_updates():
	return jsonify(ytdlp = updates.ytdlp(), git = updates.git())


@app.post('/api/updates/fetch')
def api_fetch():
	with _git_lock:
		return jsonify(ok = True, ytdlp = updates.ytdlp(), git = updates.git(fetch = True))


@app.post('/api/updates/pull')
def api_pull():
	with _git_lock:
		return result(updates.pull(), git = updates.git())


# ---- page + QR ------------------------------------------------------------------------
@app.get('/api/qr')
def api_qr():
	import qrcode
	import qrcode.image.svg
	data = request.args.get('data', '')[:300]
	img = qrcode.make(data, image_factory = qrcode.image.svg.SvgPathImage, box_size = 10, border = 2)
	buf = io.BytesIO()
	img.save(buf)
	return buf.getvalue(), 200, {'Content-Type': 'image/svg+xml', 'Cache-Control': 'max-age=3600'}


@app.get('/')
def index():
	return send_from_directory(STATIC, 'index.html')


@app.get('/static/<path:name>')
def static_file(name):
	resp = send_from_directory(STATIC, name)
	if name.startswith('fonts/'):
		resp.headers['Cache-Control'] = 'max-age=31536000, immutable'
	return resp


@app.after_request
def headers(resp):
	resp.headers['X-Frame-Options'] = 'DENY'
	resp.headers['Referrer-Policy'] = 'no-referrer'
	resp.headers['Cache-Control'] = resp.headers.get('Cache-Control', 'no-store')
	return resp


# ---- serving --------------------------------------------------------------------------
def _serve(host):
	"""Bind one address; Tailscale's may not exist yet at boot, so keep retrying it."""
	while True:
		try:
			srv = make_server(host, C.PANEL_PORT, app, threaded = True)
			print(f'panel listening on {host}:{C.PANEL_PORT}', flush = True)
			srv.serve_forever()
		except OSError as e:
			print(f'panel: cannot bind {host}:{C.PANEL_PORT} yet ({e}); retrying in 10s', flush = True)
			time.sleep(10)


def main():
	S.install()
	threading.Thread(target = _watch_app, daemon = True).start()
	hosts = ['127.0.0.1'] + ts_self(refresh = True)['ips']
	threads = [threading.Thread(target = _serve, args = (h,), daemon = True) for h in hosts]
	for t in threads:
		t.start()
	for t in threads:
		t.join()


if __name__ == '__main__':
	main()
