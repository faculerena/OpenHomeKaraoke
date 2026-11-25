# Entry point of each karaoke systemd user service (see panel/services.py):
#   python -m panel.run asr|app|app-tv|tunnel
# Reads ~/.config/ohk/config.json and execs the real program, so changing a setting in the
# panel takes effect at the next (re)start without rewriting any unit file.
#
# Commands are built as argv lists (no shell), and the admin password travels in the
# environment (OHK_ADMIN_PASSWORD), never on a command line: _headless.sh echoes its
# arguments into the journal, and the panel shows the journal.
import os
import sys

from panel import config as C


def _app_args(cfg):
	args = ['-d', C.song_dir(cfg), '-nv', '--cloud', f"http://localhost:{cfg['asr_port']}",
			'--lang', cfg['tv_lang']]
	if cfg['mode'] == 'public':
		# the splash/QR must point at the public hostnames, not the LAN IP
		args += ['--url', cfg['public_url'], '--tv-url', cfg['public_tv_url']]
	return args


def _env(cfg):
	env = dict(os.environ)
	env.pop('OHK_ADMIN_PASSWORD', None)
	if cfg['admin_password']:
		env['OHK_ADMIN_PASSWORD'] = cfg['admin_password']
	return env


def main(component):
	cfg = C.load()
	os.chdir(C.REPO)        # cert.pem, models/, .yt-dlp.last-update are repo-relative
	if component == 'asr':
		argv = [C.PY, 'asr_server.py', '-m', cfg['whisper_model'], '-p', str(cfg['asr_port'])]
		env = dict(os.environ)
	elif component == 'app':
		argv = [C.PY, 'app.py'] + _app_args(cfg)
		env = _env(cfg)
	elif component == 'app-tv':
		argv = [os.path.join(C.REPO, '_headless.sh')] + _app_args(cfg)
		env = _env(cfg)
		env['OHK_TV_PORT'] = str(C.TV_PORT)
		for key, var in (('tv_quality', 'OHK_TV_QUALITY'), ('tv_scale', 'OHK_TV_SCALE')):
			env.pop(var, None)
			if cfg[key] is not None:
				env[var] = str(cfg[key])
	elif component == 'tunnel':
		if not cfg['admin_password']:
			# same guard as start-karaoke.sh -c: the app's GET /shutdown would be public
			sys.exit('refusing to publish without an admin password (set one in the panel)')
		argv = ['cloudflared', 'tunnel', '--config', os.path.expanduser(cfg['cf_config']), 'run']
		env = dict(os.environ)
	else:
		sys.exit(f'unknown component {component!r}')
	sys.stdout.flush()
	os.execvpe(argv[0], argv, env)


if __name__ == '__main__':
	main(sys.argv[1] if len(sys.argv) > 1 else '')
