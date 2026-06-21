#!/usr/bin/env python3
# Local GPU "cloud" server for OpenHomeKaraoke (replaces the OpenSmartLight cloud).
# Implements the two endpoints app.py talks to via --cloud:
#   POST /run_asr      multipart 'file' (webm)  -> {"text": ..., "language": ...}   (Whisper)
#   POST /split_vocal  multipart 'file' (m4a)   -> tar.gz {nonvocal.m4a, vocal.m4a} (vocal-remover DNN)
#
# Run:    .venv/bin/python asr_server.py [-p 5005] [-m small] [-g 0]
# Then launch the app with:    --cloud http://localhost:5005
#
# Whisper model (-m / $ASR_MODEL): tiny|base|small|medium|large-v3 (bigger = more accurate, slower).
# Keep responses under app.py's 8s ASR timeout; "small" or "medium" are good on this GPU.

import os, io, sys, tempfile, tarfile, argparse, threading, shutil
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
gen_lock = threading.Lock()      # serialize karaoke .ass generation (one heavy Whisper run at a time)


def load_models(args):
	G.device = torch.device(f'cuda:{args.gpu}') if (args.gpu >= 0 and torch.cuda.is_available()) else torch.device('cpu')
	print(f'Loading Whisper "{args.model}" on {G.device} ...', flush=True)
	G.whisper = whisper.load_model(args.model, device=G.device)

	print('Loading vocal-remover DNN (models/baseline.pth) ...', flush=True)
	vmodel = nets.CascadedNet(2048, 1024, 32, 128, True)
	vmodel.load_state_dict(torch.load('models/baseline.pth', map_location='cpu'))
	vmodel.to(G.device).eval()
	# args object expected by vocal_splitter.split_vocal_by_dnn()
	G.split_args = SimpleNamespace(model=vmodel, device=G.device, batchsize=4, cropsize=256,
	                               sr=44100, hop_length=1024, n_fft=2048, tta=False)
	print(f'Ready. GPU mem: {round(torch.cuda.memory_allocated()/1e6,1)} MB', flush=True)


@app.route('/run_asr', methods=['POST'])
def run_asr():
	f = request.files.get('file') or (request.data and SimpleNamespace(save=lambda p: open(p, 'wb').write(request.data)))
	if not f:
		return jsonify({}), 400
	with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
		path = tmp.name
	f.save(path)
	try:
		with asr_lock:
			res = G.whisper.transcribe(path, fp16=(G.device.type == 'cuda'))
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
		with split_lock:
			VS.split_vocal_by_dnn(in_wav, nv_wav, v_wav, G.split_args)
		VS.ffm_wav2m4a(nv_wav, nv_m4a)
		VS.ffm_wav2m4a(v_wav, v_m4a)
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
	media = (request.form.get('path') or '').strip()
	if not media or not os.path.isfile(media):
		return 'bad path', 400
	threading.Thread(target=_gen_karaoke, args=(media,), daemon=True).start()
	return 'ok'


def _gen_karaoke(media):
	from lib.karaoke_ass import segments_to_ass
	dst = os.path.splitext(media)[0] + '.ass'
	if os.path.isfile(dst):
		return
	with gen_lock:                      # one karaoke build at a time (avoids GPU OOM under bursts)
		if os.path.isfile(dst):
			return
		try:
			d, base = os.path.dirname(media), os.path.basename(media)
			vocal = os.path.join(d, 'vocal', base + '.m4a')
			# split vocals first for clean alignment (also populates the track for playback)
			if not os.path.isfile(vocal) and os.path.isdir(os.path.join(d, 'vocal')):
				try:
					tmp = tempfile.mkdtemp(prefix='ohk_gk_')
					VS.ffm_video2wav(media, tmp + '/in.wav')
					with split_lock:
						VS.split_vocal_by_dnn(tmp + '/in.wav', tmp + '/nv.wav', tmp + '/v.wav', G.split_args)
					VS.ffm_wav2m4a(tmp + '/v.wav', vocal)
					shutil.rmtree(tmp, ignore_errors=True)
				except Exception as e:
					print(f'karaoke: split failed, using full mix: {e}', file=sys.stderr, flush=True)
			audio = vocal if os.path.isfile(vocal) else media
			print(f'karaoke: building for {base} ...', flush=True)
			from lib import forced_align
			with asr_lock:
				segs, method = forced_align.make_segments(media, audio, G.whisper, G.device.type)
			open(dst, 'w', encoding='utf-8').write(segments_to_ass(segs))
			print(f'karaoke: wrote {os.path.basename(dst)} [{method}]', flush=True)
		except Exception as e:
			print(f'karaoke: failed for {media}: {e}', file=sys.stderr, flush=True)


if __name__ == '__main__':
	p = argparse.ArgumentParser()
	p.add_argument('-p', '--port', type=int, default=5005)
	p.add_argument('-m', '--model', default=os.environ.get('ASR_MODEL', 'small'),
	               help='Whisper model: tiny|base|small|medium|large-v3 (default: small)')
	p.add_argument('-g', '--gpu', type=int, default=0, help='GPU id, -1 for CPU')
	args = p.parse_args()
	load_models(args)
	app.run(host='127.0.0.1', port=args.port, threaded=True)
