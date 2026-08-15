# Karaoke scoring: compare a singer's recording against the song's isolated vocal stem.
#
# We are in an unusually good position for this — the library already contains, per song:
#   vocal/<name>.m4a   the isolated vocals  -> the reference melody, no MIDI chart needed
#   <base>.ass         forced-aligned lyrics -> exactly WHEN singing should happen
#
# Method: extract f0 (pyin) from both, keep only frames inside a lyric line where the
# REFERENCE is voiced, and compare pitch CLASS (mod 12 semitones) so an octave difference
# — a man singing a woman's song — is not punished.
#
# The reference contour is cached next to the song (<base>.f0.npz), because pyin runs at
# roughly 5x realtime and the reference never changes.

import os, re, math
import numpy as np

SR          = 22050
FRAME       = 2048
HOP         = 512
FMIN, FMAX  = 65.0, 1000.0      # ~C2..C6, covers any human singer
TOL_SEMI    = 1.5               # within this many semitones counts as on-pitch
HOP_SEC     = HOP / SR


def _load_audio(path, sr=SR):
	import librosa
	# 'file:' — a ':' in the song name is otherwise parsed by ffmpeg as a protocol
	y, _ = librosa.load(path if os.sep in path else 'file:' + path, sr=sr, mono=True)
	return y


def f0_contour(path):
	"""pyin f0 for a whole file. Returns (f0 with NaN where unvoiced, hop seconds)."""
	import librosa
	y = _load_audio(path)
	f0, _, _ = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=SR,
	                        frame_length=FRAME, hop_length=HOP)
	return f0


def reference_f0(vocal_path, cache_path=None):
	"""f0 of the isolated vocal stem, cached to disk (it never changes)."""
	if cache_path and os.path.isfile(cache_path):
		try:
			return np.load(cache_path)['f0']
		except Exception:
			pass
	f0 = f0_contour(vocal_path)
	if cache_path:
		try:
			np.savez_compressed(cache_path, f0=f0)
		except Exception:
			pass
	return f0


_DIALOGUE = re.compile(r'^Dialogue:\s*[^,]*,([^,]+),([^,]+),')


def _ass_time(t):
	# H:MM:SS.cc
	try:
		h, m, s = t.strip().split(':')
		return int(h) * 3600 + int(m) * 60 + float(s)
	except Exception:
		return None


def lyric_windows(ass_path):
	"""[(start_sec, end_sec)] for each subtitle line — the spans where singing is expected."""
	out = []
	if not ass_path or not os.path.isfile(ass_path):
		return out
	with open(ass_path, encoding='utf-8', errors='replace') as fp:
		for line in fp:
			m = _DIALOGUE.match(line)
			if not m:
				continue
			a, b = _ass_time(m.group(1)), _ass_time(m.group(2))
			if a is not None and b is not None and b > a:
				out.append((a, b))
	return out


def _in_windows_mask(n_frames, windows, shift=0.0):
	"""Boolean mask over frames that fall inside any lyric window."""
	if not windows:
		return np.ones(n_frames, dtype=bool)     # no .ass: score the whole thing
	mask = np.zeros(n_frames, dtype=bool)
	for a, b in windows:
		i = max(0, int((a - shift) / HOP_SEC))
		j = min(n_frames, int(math.ceil((b - shift) / HOP_SEC)))
		if j > i:
			mask[i:j] = True
	return mask


def compare(ref_f0, sing_f0, windows, offset=0.0, tol=TOL_SEMI):
	"""Score the singer against the reference.

	offset — how many seconds into the song the recording started, so frame k of the
	         singer lines up with frame k + offset/HOP_SEC of the reference.

	Scored over reference-voiced frames inside lyric windows, so staying silent scores 0
	rather than being quietly skipped.
	"""
	# offset may be negative: the recording can start BEFORE the song's audio does, in which
	# case we drop the head of the recording instead of the head of the reference.
	shift = int(round(offset / HOP_SEC))
	ref_start, sing_start = (shift, 0) if shift >= 0 else (0, -shift)
	n = min(len(sing_f0) - sing_start, len(ref_f0) - ref_start)
	if n <= 0:
		return {'score': 0, 'reason': 'recording does not overlap the song'}

	ref  = ref_f0[ref_start:ref_start + n]
	sing = sing_f0[sing_start:sing_start + n]

	in_lyrics = _in_windows_mask(len(ref_f0), windows)[ref_start:ref_start + n]
	ref_voiced = ~np.isnan(ref) & in_lyrics          # every frame they were meant to sing
	total = int(ref_voiced.sum())
	if total == 0:
		return {'score': 0, 'reason': 'no reference vocals in range'}

	both = ref_voiced & ~np.isnan(sing)              # ...and actually did
	sung = int(both.sum())
	if sung == 0:
		return {'score': 0, 'sung_pct': 0, 'reason': 'no singing detected'}

	# pitch CLASS distance, wrapped to +/-6 semitones: octave-agnostic on purpose
	d = 12.0 * np.log2(sing[both] / ref[both])
	d = (d + 6.0) % 12.0 - 6.0
	hits = int((np.abs(d) <= tol).sum())

	return {
		'score':     int(round(100.0 * hits / total)),   # of everything they SHOULD have sung
		'pitch_pct': int(round(100.0 * hits / sung)),    # of what they did sing
		'sung_pct':  int(round(100.0 * sung / total)),   # how much of it they attempted
		'frames':    total,
		'median_off': round(float(np.median(np.abs(d))), 2),
	}


def best_compare(ref_f0, sing_f0, windows, offset_hint=0.0, search=3.0, step=4):
	"""compare() over a range of offsets, keeping the best.

	Necessary because the singer hears the HLS stream, which lags the true song position by
	a second or so, and the browser only knows stream time. Misalignment is brutal — a 2s
	error takes a perfect run from 100 to 26 — so instead of trusting a hint we scan around
	it. pyin has already run by this point; each additional offset is just array maths.
	"""
	best, best_off = None, offset_hint
	lo = offset_hint - search        # negative is legitimate — see compare()
	hi = offset_hint + search
	off = lo
	while off <= hi:
		r = compare(ref_f0, sing_f0, windows, off)
		if best is None or r.get('score', 0) > best.get('score', 0):
			best, best_off = r, off
		off += step * HOP_SEC
	best = dict(best or {'score': 0})
	best['offset'] = round(best_off, 2)
	return best


def score_recording(sing_path, vocal_path, ass_path=None, offset=0.0):
	"""Full path: singer file + reference stem (+ optional .ass) -> score dict."""
	if not os.path.isfile(vocal_path):
		return {'score': 0, 'reason': 'no vocal stem for this song'}
	cache = os.path.splitext(vocal_path)[0] + '.f0.npz'
	ref = reference_f0(vocal_path, cache)
	sing = f0_contour(sing_path)
	return best_compare(ref, sing, lyric_windows(ass_path), offset)
