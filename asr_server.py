#!/usr/bin/env python3
# Local GPU "cloud" server for OpenHomeKaraoke (replaces the OpenSmartLight cloud).
# Implements the endpoints app.py talks to via --cloud:
#   POST /run_asr      multipart 'file' (webm)  -> {"text": ..., "language": ...}   (Whisper)
#   POST /split_vocal  multipart 'file' (m4a)   -> tar.gz {nonvocal.m4a, vocal.m4a} (vocal-remover DNN)
#   POST /make_karaoke  form 'path'             -> 'ok'        (app shares our disk)
#                       multipart 'file'+'name' -> {"job": id} (app is on another machine)
#   GET  /karaoke_result/<job>                  -> 202 pending | tar.gz {karaoke.ass, vocal.m4a, nonvocal.m4a}
#
# Run:    .venv/bin/python asr_server.py [-p 5005] [-m small] [-g 0] [--host 0.0.0.0]
# Then launch the app with:    --cloud http://localhost:5005
#
# SPLIT DEPLOYMENT (app on a laptop, GPU work here): bind --host to a reachable address
# (a Tailscale IP is ideal — this server has NO authentication, so never bind it to a
# public interface) and point the laptop at  --cloud http://<that-ip>:5005
#
# Whisper model (-m / $ASR_MODEL): tiny|base|small|medium|large-v3 (bigger = more accurate, slower).
# Keep responses under app.py's 8s ASR timeout; "small" or "medium" are good on this GPU.

import os, io, sys, uuid, tempfile, tarfile, argparse, threading, shutil, logging, time
import torch
from types import SimpleNamespace
from flask import Flask, request, jsonify, Response
import whisper

# Reuse the project's own splitter pipeline (ffmpeg helpers + DNN split + model net)
from lib import nets
import vocal_splitter as VS

app = Flask(__name__)
G = SimpleNamespace()
asr_lock = threading.Lock()      # serialize Whisper calls
split_lock = threading.Lock()    # serialize DNN splits (independent of ASR so a long split never blocks voice search)
# One song build at a time. Overlapping two (one splitting while the other aligns) was tried
# and measured SLOWER on this Radeon: both GPU stages slow each other down (2 songs: 30s
# overlapped vs ~19s one after the other). The lyrics download still overlaps the split.
gen_lock = threading.Semaphore(1)
jobs = {}                        # remote karaoke jobs: id -> {'state': pending|done|error, 'dir': tmpdir}
jobs_lock = threading.Lock()

# What the GPU is busy with, for the admin panel's /status (names are song filenames).
# karaoke_waiting counts builds queued behind gen_lock; the panel shows it as a backlog.
activity = {'split': None, 'karaoke': None, 'karaoke_waiting': 0, 'asr_running': 0}
activity_lock = threading.Lock()


class _doing:
	"""with _doing('split', name): mark the GPU as busy with `name` for the duration."""
	def __init__(self, kind, name):
		self.kind, self.name = kind, name
	def __enter__(self):
		with activity_lock:
			activity[self.kind] = self.name
	def __exit__(self, *exc):
		with activity_lock:
			activity[self.kind] = None


class _gen_slot:
	"""with _gen_slot(): take one of the build slots, counting the wait as backlog. Which song
	is splitting / aligning right now is reported by _doing() inside the stages."""
	def __init__(self, name=None):
		self.name = name
	def __enter__(self):
		with activity_lock:
			activity['karaoke_waiting'] += 1
		gen_lock.acquire()
		with activity_lock:
			activity['karaoke_waiting'] -= 1
	def __exit__(self, *exc):
		gen_lock.release()


def _prefetch_lyrics(media):
	"""Start fetching the song's synced lyrics (network: LRCLIB / YouTube Music) in the
	background, so they are ready by the time the vocal split is done."""
	from lib import forced_align
	box = {}
	def run():
		try:
			box['lrc'] = forced_align.fetch_lyrics(forced_align.song_query(media))
		except Exception as e:
			print(f'karaoke: lyrics fetch failed for {os.path.basename(media)}: {e}', file=sys.stderr, flush=True)
			box['lrc'] = None
	t = threading.Thread(target=run, daemon=True)
	t.start()
	def result():
		t.join(30)
		return box.get('lrc')
	return result


def load_models(args):
	G.device = torch.device(f'cuda:{args.gpu}') if (args.gpu >= 0 and torch.cuda.is_available()) else torch.device('cpu')
	print(f'Loading Whisper "{args.model}" on {G.device} ...', flush=True)
	G.whisper = whisper.load_model(args.model, device=G.device)
	G.model_name = args.model

	print('Loading vocal-remover DNN (models/baseline.pth) ...', flush=True)
	vmodel = nets.CascadedNet(2048, 1024, 32, 128, True)
	vmodel.load_state_dict(torch.load('models/baseline.pth', map_location='cpu'))
	vmodel.to(G.device).eval()
	# args object expected by vocal_splitter.split_vocal_by_dnn()
	G.split_args = SimpleNamespace(model=vmodel, device=G.device, batchsize=4, cropsize=256,
	                               sr=44100, hop_length=1024, n_fft=2048, tta=False)
	print(f'Ready. GPU mem: {round(torch.cuda.memory_allocated()/1e6,1)} MB', flush=True)


class _QuietPanelPolls(logging.Filter):
	# the admin panel polls /status every 2s; keep that out of the journal it displays
	def filter(self, record):
		return 'GET /status ' not in record.getMessage()


logging.getLogger('werkzeug').addFilter(_QuietPanelPolls())


@app.route('/status')
def status():
	# Read by the admin panel (panel/). Local-only like the rest of this server.
	with activity_lock:
		act = dict(activity)
	gpu_mb = None
	if G.device.type == 'cuda':
		try: gpu_mb = round(torch.cuda.memory_allocated() / 1e6)
		except Exception: pass
	return jsonify({'ready': True, 'model': G.model_name, 'device': str(G.device),
	                'gpu_mem_mb': gpu_mb, 'activity': act})


@app.route('/run_asr', methods=['POST'])
def run_asr():
	f = request.files.get('file') or (request.data and SimpleNamespace(save=lambda p: open(p, 'wb').write(request.data)))
	if not f:
		return jsonify({}), 400
	with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
		path = tmp.name
	f.save(path)
	try:
		with activity_lock:
			activity['asr_running'] += 1
		try:
			with asr_lock:
				res = G.whisper.transcribe(path, fp16=(G.device.type == 'cuda'))
		finally:
			with activity_lock:
				activity['asr_running'] -= 1
		return jsonify({'text': (res.get('text') or '').strip(), 'language': res.get('language', '')})
	except Exception as e:
		print(f'ASR error: {e}', file=sys.stderr, flush=True)
		return jsonify({}), 500
	finally:
		try: os.remove(path)
		except OSError: pass


@app.route('/split_vocal', methods=['POST'])
def split_vocal():
	f = request.files.get('file')
	if not f:
		return 'no file', 400
	d = tempfile.mkdtemp(prefix='ohk_split_')
	in_m4a, in_wav = f'{d}/in.m4a', f'{d}/in.wav'
	nv_wav, v_wav = f'{d}/nonvocal.wav', f'{d}/vocal.wav'
	nv_m4a, v_m4a = f'{d}/nonvocal.m4a', f'{d}/vocal.m4a'
	try:
		f.save(in_m4a)
		VS.ffm_video2wav(in_m4a, in_wav)
		with split_lock, _doing('split', os.path.basename(request.form.get('name') or f.filename or 'song')):
			VS.split_vocal_by_dnn(in_wav, nv_wav, v_wav, G.split_args)
		VS.encode_stems([(nv_wav, nv_m4a), (v_wav, v_m4a)])
		buf = io.BytesIO()
		with tarfile.open(fileobj=buf, mode='w:gz') as tar:
			tar.add(nv_m4a, arcname='nonvocal.m4a')
			tar.add(v_m4a, arcname='vocal.m4a')
		buf.seek(0)
		return Response(buf.read(), mimetype='application/gzip')
	except Exception as e:
		print(f'split_vocal error: {e}', file=sys.stderr, flush=True)
		return 'split error', 500
	finally:
		shutil.rmtree(d, ignore_errors=True)


@app.route('/make_karaoke', methods=['POST'])
def make_karaoke():
	# Auto-generate a color-wipe <base>.ass for a song (called by the app right after a download).
	# Two modes, because the app may or may not share a filesystem with us:
	#   local  — form 'path' : we read/write the song in place.
	#   remote — multipart 'file' (+ 'name') : the app uploaded the song's audio and will
	#            collect the result from /karaoke_result/<job>.
	f = request.files.get('file')
	if f:
		name = os.path.basename((request.form.get('name') or '').strip()) or 'song.m4a'
		d = tempfile.mkdtemp(prefix='ohk_job_')
		src = os.path.join(d, name)     # keep the real filename: song_query() searches lyrics by it
		f.save(src)
		job = uuid.uuid4().hex
		with jobs_lock:
			jobs[job] = {'state': 'pending', 'dir': d}
		threading.Thread(target=_run_job, args=(job, src, d), daemon=True).start()
		return jsonify({'job': job})

	media = (request.form.get('path') or '').strip()
	if not media or not os.path.isfile(media):
		return 'bad path', 400
	threading.Thread(target=_gen_karaoke, args=(media,), daemon=True).start()
	return 'ok'


def _run_job(job, src, d):
	"""Remote mode: split + align an uploaded song, then park the results for collection."""
	state = 'error'
	try:
		with _gen_slot():
			lyrics = _prefetch_lyrics(src)
			vocal, nonvocal = f'{d}/vocal.m4a', f'{d}/nonvocal.m4a'
			try:
				_split(src, nonvocal, vocal)
			except Exception as e:
				print(f'karaoke: split failed, using full mix: {e}', file=sys.stderr, flush=True)
			audio = vocal if os.path.isfile(vocal) else src
			ass = _karaoke_ass(src, audio, lyrics)
			open(f'{d}/karaoke.ass', 'w', encoding='utf-8').write(ass)
			state = 'done'
	except Exception as e:
		print(f'karaoke job {job} failed: {e}', file=sys.stderr, flush=True)
	with jobs_lock:
		if job in jobs:
			jobs[job]['state'] = state


@app.route('/karaoke_result/<job>')
def karaoke_result(job):
	with jobs_lock:
		j = jobs.get(job)
	if not j:
		return 'unknown job', 404
	if j['state'] == 'pending':
		return 'pending', 202
	d = j['dir']
	if j['state'] == 'error':
		with jobs_lock:
			jobs.pop(job, None)
		shutil.rmtree(d, ignore_errors=True)
		return 'failed', 500
	buf = io.BytesIO()
	with tarfile.open(fileobj=buf, mode='w:gz') as tar:
		for n in ('karaoke.ass', 'vocal.m4a', 'nonvocal.m4a'):
			if os.path.isfile(f'{d}/{n}'):
				tar.add(f'{d}/{n}', arcname=n)
	buf.seek(0)
	with jobs_lock:
		jobs.pop(job, None)
	shutil.rmtree(d, ignore_errors=True)
	return Response(buf.read(), mimetype='application/gzip')


def _split(media, nonvocal_m4a, vocal_m4a):
	"""Run the vocal-remover DNN over `media`, writing BOTH stems as m4a (encoded at once).
	Each stem appears in one step (written beside, then renamed), so the app never sees half
	a file. Temp files go to RAM (/dev/shm) when it exists."""
	tmp = tempfile.mkdtemp(prefix='ohk_gk_', dir='/dev/shm' if os.path.isdir('/dev/shm') else None)
	try:
		t0 = time.time()
		VS.ffm_video2wav(media, f'{tmp}/in.wav')
		t1 = time.time()
		with split_lock, _doing('split', os.path.basename(media)):
			t2 = time.time()
			VS.split_vocal_by_dnn(f'{tmp}/in.wav', f'{tmp}/nv.wav', f'{tmp}/v.wav', G.split_args)
		t3 = time.time()
		if not VS.encode_stems([(f'{tmp}/v.wav', f'{tmp}/v.m4a'), (f'{tmp}/nv.wav', f'{tmp}/nv.m4a')]):
			raise RuntimeError('stem encode failed')
		print(f'split: {os.path.basename(media)}: extract {t1-t0:.1f}s, waited {t2-t1:.1f}s, '
		      f'split {t3-t2:.1f}s, encode {time.time()-t3:.1f}s', flush=True)
		for src, dst in ((f'{tmp}/v.m4a', vocal_m4a), (f'{tmp}/nv.m4a', nonvocal_m4a)):
			os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
			shutil.move(src, dst + '.part')
			os.replace(dst + '.part', dst)
	finally:
		shutil.rmtree(tmp, ignore_errors=True)


def _karaoke_ass(media, audio, lyrics=None):
	"""Real lyrics (LRCLIB/YT Music) force-aligned to `audio` -> ASS color-wipe text.
	`lyrics`: a callable returning lyrics prefetched by _prefetch_lyrics(), if any."""
	from lib.karaoke_ass import segments_to_ass
	from lib import forced_align
	print(f'karaoke: building for {os.path.basename(media)} ...', flush=True)
	t0 = time.time()
	extra = {'lrc': lyrics()} if lyrics else {}
	t1 = time.time()
	with asr_lock, _doing('karaoke', os.path.basename(media)):
		t2 = time.time()
		segs, method = forced_align.make_segments(media, audio, G.whisper, G.device.type, **extra)
	print(f'karaoke: {os.path.basename(media)}: lyrics wait {t1-t0:.1f}s, align queue {t2-t1:.1f}s, '
	      f'align {time.time()-t2:.1f}s', flush=True)
	print(f'karaoke: built {os.path.basename(media)} [{method}]', flush=True)
	return segments_to_ass(segs)


def _gen_karaoke(media):
	from lib.karaoke_ass import segments_to_ass
	dst = os.path.splitext(media)[0] + '.ass'
	if os.path.isfile(dst):
		return
	with _gen_slot():
		if os.path.isfile(dst):
			return
		try:
			d, base = os.path.dirname(media), os.path.basename(media)
			lyrics = _prefetch_lyrics(media)       # network, runs while the split does
			vocal = os.path.join(d, 'vocal', base + '.m4a')
			nonvocal = os.path.join(d, 'nonvocal', base + '.m4a')
			# Split first, for clean alignment. Write BOTH stems: before, only the vocal one was
			# kept, so the app split the whole song a second time on its first play to get the
			# music-only stem (and the MUSIC / VOICE switch stayed greyed out until then).
			if not (os.path.isfile(vocal) and os.path.isfile(nonvocal)) and os.path.isdir(os.path.join(d, 'vocal')):
				try:
					_split(media, nonvocal, vocal)
				except Exception as e:
					print(f'karaoke: split failed, using full mix: {e}', file=sys.stderr, flush=True)
			audio = vocal if os.path.isfile(vocal) else media
			ass = _karaoke_ass(media, audio, lyrics)
			# build first, then appear in one step: the app polls for this file to decide a
			# freshly-added song is ready to enqueue, so it must never be seen half-written
			open(dst + '.part', 'w', encoding='utf-8').write(ass)
			os.replace(dst + '.part', dst)
			print(f'karaoke: wrote {os.path.basename(dst)}', flush=True)
		except Exception as e:
			print(f'karaoke: failed for {media}: {e}', file=sys.stderr, flush=True)


if __name__ == '__main__':
	p = argparse.ArgumentParser()
	p.add_argument('-p', '--port', type=int, default=5005)
	p.add_argument('-m', '--model', default=os.environ.get('ASR_MODEL', 'small'),
	               help='Whisper model: tiny|base|small|medium|large-v3 (default: small)')
	p.add_argument('-g', '--gpu', type=int, default=0, help='GPU id, -1 for CPU')
	p.add_argument('--host', default='127.0.0.1',
	               help='Bind address. Default 127.0.0.1 (local only). For a split deployment use '
	                    'the Tailscale/LAN IP the app machine can reach — there is NO auth here, '
	                    'so do not bind a public interface.')
	args = p.parse_args()
	load_models(args)
	app.run(host=args.host, port=args.port, threaded=True)
