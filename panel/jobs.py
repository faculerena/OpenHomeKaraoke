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


def split(name):
	"""(Re)generate one song's vocal/nonvocal stems through the GPU server, replacing any
	old ones only once the new pair is ready (the old ones go to the trash)."""
	import shutil
	import subprocess
	import tarfile
	import tempfile
	cfg = C.load()
	root = C.song_dir(cfg)
	media = os.path.join(root, name)
	print(f'splitting {name}', flush = True)
	with tempfile.TemporaryDirectory(prefix = 'ohk_split_') as t:
		# matroska: YouTube audio is often opus, which an .m4a container can't hold;
		# 'file:' stops ffmpeg reading a ':' in the title as a protocol
		subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', 'file:' + media, '-vn', '-c', 'copy',
		                '-f', 'matroska', f'{t}/in.m4a'], check = True)
		import uuid
		boundary = uuid.uuid4().hex
		audio = open(f'{t}/in.m4a', 'rb').read()
		body = (f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'
		        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="in.m4a"\r\n'
		        'Content-Type: application/octet-stream\r\n\r\n').encode() + audio + f'\r\n--{boundary}--\r\n'.encode()
		req = urllib.request.Request(f"http://127.0.0.1:{cfg['asr_port']}/split_vocal", data = body,
		                             headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'})
		with urllib.request.urlopen(req, timeout = 1800) as r, open(f'{t}/out.tgz', 'wb') as f:
			f.write(r.read())
		with tarfile.open(f'{t}/out.tgz') as tar:
			tar.extractall(t, filter = 'data')
		old = [f'{sub}/{name}.m4a' for sub in ('vocal', 'nonvocal') if os.path.isfile(os.path.join(root, sub, f'{name}.m4a'))]
		if old:
			library._move(root, old, library._trash_batch())
		for sub in ('vocal', 'nonvocal'):
			os.makedirs(os.path.join(root, sub), exist_ok = True)
			shutil.move(f'{t}/{sub}.m4a', os.path.join(root, sub, f'{name}.m4a'))
	print('done', flush = True)


if __name__ == '__main__':
	cmd = sys.argv[1]
	if cmd == 'split':
		split(sys.argv[2])
	else:
		{'gen-missing': gen_missing}[cmd]()
