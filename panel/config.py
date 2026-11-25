# Settings shared by the admin panel and the services it runs (panel/run.py reads them at
# each start). Lives outside the repo, mode 600, because it holds the admin password.
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, '.venv', 'bin', 'python')
CONFIG_DIR = os.path.expanduser('~/.config/ohk')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')
PANEL_PORT = 12345
APP_PORT = 5000          # app.py's default; its https twin (phone mic) is APP_PORT + 1
TV_PORT = 4000

MODES = ('monitor', 'tv', 'public')
WHISPER_MODELS = ('tiny', 'base', 'small', 'medium', 'large-v3')

WELCOME_DEFAULT_TITLE = '🎂 MEGACUMPLEAÑOS!! 🎂'
WELCOME_DEFAULT_TEXT = '''Agreguen canciones en la lupita o en la carpeta si ya están descargadas.
Prioricen que las canciones sean de **KARAOKE MUGEN** (🎤) o que sean versiones **Karaoke** (🎵).
No pausen canciones de otros.
Pueden tocar **MUSIC | MIXED | VOICE** para sacarle la voz a alguna canción.
Díganle feliz cumple a Mega 🥳'''

DEFAULTS = {
	'mode': 'tv',                         # last mode started; the panel preselects it
	'whisper_model': 'medium',
	'song_dir': '~/pikaraoke-songs',
	'asr_port': 5005,
	'tv_quality': None,                   # QP 20-34; None = stream-tv.sh default (28)
	'tv_scale': None,                     # output height in px; None = native 720p
	'admin_password': '',
	'public_url': 'https://karaoke.timbear.gratis',
	'public_tv_url': 'https://tv.timbear.gratis',
	'cf_config': '~/.cloudflared/karaoke-config.yml',
	# the popup phones see when they first open the karaoke page (also behind its "?")
	'welcome_enabled': True,              # show it automatically on a phone's first visit
	'welcome_title': WELCOME_DEFAULT_TITLE,
	'welcome_text': WELCOME_DEFAULT_TEXT,  # one rule per line; **bold** works
	'welcome_name_label': 'Tu nombre:',
}


def load():
	cfg = dict(DEFAULTS)
	try:
		with open(CONFIG_PATH) as f:
			cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
	except FileNotFoundError:
		pass
	return cfg


def save(cfg):
	os.makedirs(CONFIG_DIR, exist_ok = True)
	tmp = CONFIG_PATH + '.tmp'
	fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	with os.fdopen(fd, 'w') as f:
		json.dump({k: cfg[k] for k in DEFAULTS}, f, indent = 2)
	os.replace(tmp, CONFIG_PATH)


def song_dir(cfg):
	return os.path.expanduser(cfg['song_dir']).rstrip('/')


def validate(new, old):
	"""Merge a settings form into the config. Returns (cfg, error)."""
	cfg = dict(old)
	try:
		if 'whisper_model' in new:
			if new['whisper_model'] not in WHISPER_MODELS:
				return None, 'unknown Whisper model'
			cfg['whisper_model'] = new['whisper_model']
		if 'song_dir' in new:
			d = str(new['song_dir']).strip()
			if not d or not os.path.isdir(os.path.expanduser(d)):
				return None, f'song folder does not exist: {d}'
			cfg['song_dir'] = d
		if 'asr_port' in new:
			p = int(new['asr_port'])
			if not 1024 <= p <= 65535 or p in (APP_PORT, APP_PORT + 1, TV_PORT, PANEL_PORT):
				return None, 'ASR port must be 1024-65535 and not used by the app, TV or panel'
			cfg['asr_port'] = p
		if 'tv_quality' in new:
			q = new['tv_quality']
			q = None if q in (None, '') else int(q)
			if q is not None and not 20 <= q <= 34:
				return None, 'TV quality (QP) must be 20-34'
			cfg['tv_quality'] = q
		if 'tv_scale' in new:
			h = new['tv_scale']
			h = None if h in (None, '') else int(h)
			if h is not None and not 240 <= h <= 1080:
				return None, 'TV height must be 240-1080 px'
			cfg['tv_scale'] = h
		for k in ('public_url', 'public_tv_url'):
			if k in new:
				u = str(new[k]).strip().rstrip('/')
				if u and not u.startswith(('https://', 'http://')):
					return None, f'{k} must start with https://'
				cfg[k] = u
		if 'welcome_enabled' in new:
			cfg['welcome_enabled'] = bool(new['welcome_enabled'])
		for k, limit in (('welcome_title', 200), ('welcome_text', 4000), ('welcome_name_label', 100)):
			if k in new:
				v = str(new[k]).replace('\r\n', '\n').strip()
				if len(v) > limit:
					return None, f'{k} is too long (max {limit} characters)'
				cfg[k] = v
		if 'cf_config' in new:
			cfg['cf_config'] = str(new['cf_config']).strip()
		# write-only: a blank field keeps the current password; clearing is explicit
		if new.get('admin_password_clear'):
			cfg['admin_password'] = ''
		elif new.get('admin_password'):
			cfg['admin_password'] = str(new['admin_password'])
	except (TypeError, ValueError):
		return None, 'invalid number'
	return cfg, None


def welcome_version(cfg):
	"""Changes whenever the message does, so phones that dismissed an old one see the new one.
	The original text keeps '1': the cookie value phones already have from before."""
	parts = (cfg['welcome_title'], cfg['welcome_text'], cfg['welcome_name_label'])
	if parts == (WELCOME_DEFAULT_TITLE, WELCOME_DEFAULT_TEXT, DEFAULTS['welcome_name_label']):
		return '1'
	import hashlib
	return hashlib.sha1('\0'.join(parts).encode('utf-8')).hexdigest()[:10]
