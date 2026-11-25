# Long-running library jobs, run by the panel as transient systemd units (ohk-job-*):
#   python -m panel.jobs gen-missing    queue a color-wipe build for every song without one
# Builds go through the running voice/GPU server, which already has the models loaded and
# runs one build at a time; this just queues them and reports progress until it drains.
import json
import os
import sys
import time
import urllib.parse
import urllib.request

from panel import config as C
from panel import library


def _asr(cfg, path, data = None):
	url = f"http://127.0.0.1:{cfg['asr_port']}{path}"
	body = urllib.parse.urlencode(data).encode() if data else None
	with urllib.request.urlopen(url, data = body, timeout = 10) as r:
		return r.read()


def gen_missing():
	cfg = C.load()
	try:
		_asr(cfg, '/status')
	except Exception:
		sys.exit('The voice/GPU server is not running. Start karaoke from the panel first.')
	songs = library.scan()['missing_colorwipe']
	print(f'{len(songs)} songs without a color-wipe', flush = True)
	if not songs:
		return
	root = C.song_dir(cfg)
	for m in songs:
		_asr(cfg, '/make_karaoke', {'path': os.path.join(root, m)})
	# wait for the server's queue to drain, reporting as it goes
	last = None
	while True:
		time.sleep(5)
		act = json.loads(_asr(cfg, '/status'))['activity']
		now = (act['karaoke'], act['karaoke_waiting'])
		if now != last:
			print(f"building: {act['karaoke'] or '-'}   queued: {act['karaoke_waiting']}", flush = True)
			last = now
		if not act['karaoke'] and not act['karaoke_waiting']:
			break
	left = library.scan()['missing_colorwipe']
	print(f'done: {len(songs) - len(left)} built, {len(left)} still without one '
	      '(usually: no synced lyrics found for that song)', flush = True)


if __name__ == '__main__':
	{'gen-missing': gen_missing}[sys.argv[1]]()
