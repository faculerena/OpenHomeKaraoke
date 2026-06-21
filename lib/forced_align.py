# Build karaoke timing from the REAL lyrics when possible: fetch line-synced lyrics from
# LRCLIB (via syncedlyrics) and FORCE-ALIGN them to the vocal track with torchaudio MMS_FA
# -> correct words + accurate per-word timing (held notes). Falls back to Whisper transcription
# (which can mishear lyrics) only when no lyrics are found.
import os, re

_M = {}  # lazily-loaded MMS_FA model/tokenizer/aligner cache


def song_query(media):
	# media filename -> "<artist> - <title>" for a lyrics search
	base = os.path.splitext(os.path.basename(media))[0].rsplit('---', 1)[0]
	base = re.sub(r'\([^)]*\)|\[[^\]]*\]|【[^】]*】', ' ', base)            # drop (Official…)/[…]/【…】
	base = re.sub(r'(?i)\b(official|music|video|audio|lyrics?|colou?r\s*coded|hd|hq|mv|full|ver\.?|version|live|remaster(ed)?)\b', ' ', base)
	return re.sub(r'\s+', ' ', base).strip(' -–—')


def _ytmusic_lyrics(name):
	# Fallback lyrics source: YouTube Music (Musixmatch) time-synced lyrics -> LRC string.
	try:
		from ytmusicapi import YTMusic
		yt = YTMusic()
		hits = yt.search(name, filter="songs", limit=1)
		if not hits:
			return None
		bid = (yt.get_watch_playlist(hits[0]['videoId']) or {}).get('lyrics')
		if not bid:
			return None
		lines = (yt.get_lyrics(bid, timestamps=True) or {}).get('lyrics')
		if not isinstance(lines, list):
			return None                          # only timed lyrics are usable for alignment
		out = []
		for ln in lines:
			t, txt = getattr(ln, 'start_time', None), (getattr(ln, 'text', '') or '').strip()
			if t is None or not txt:
				continue
			s = t / 1000.0
			out.append(f"[{int(s // 60):02d}:{s % 60:05.2f}]{txt}")
		return "\n".join(out) if out else None
	except Exception:
		return None


def _canonical_name(name):
	# Resolve a (possibly title-only) name to "Artist - Title" via YouTube Music, so the lyrics
	# search isn't ambiguous (e.g. "Dragostea din tei" -> "O-Zone - Dragostea Din Tei").
	try:
		from ytmusicapi import YTMusic
		hits = YTMusic().search(name, filter="songs", limit=1)
		if hits:
			arts = ", ".join(a['name'] for a in (hits[0].get('artists') or []) if a.get('name'))
			title = hits[0].get('title', '')
			cn = (f"{arts} - {title}").strip(' -')
			if cn and title:
				return cn
	except Exception:
		pass
	return name


def fetch_lyrics(name):
	cn = _canonical_name(name)
	queries = [cn] + ([name] if cn.lower() != name.lower() else [])
	for q in queries:
		try:
			import syncedlyrics
			lrc = syncedlyrics.search(q)
			if lrc and '[' in lrc:
				return lrc
		except Exception:
			pass
	return _ytmusic_lyrics(cn) or _ytmusic_lyrics(name)   # fallback: YouTube Music synced lyrics


# Songwriter/credit/metadata lines that some sources (esp. NetEase) put in the LRC and which
# must NOT be treated as lyrics (otherwise they get force-aligned onto intros/instrumentals).
_META_RE = re.compile(
	r'作词|作曲|编曲|制作|和声|录音|混音|母带|监制|出品|提供|演唱|歌词|'
	r'produc(ător|tor|er|ed|tion)|compo[sz]it|versuri|paroles|letra\b|'
	r'(written|composed|arranged|produced|mixed|mastered|performed|recorded)\s+by\b|'
	r'\b(lyrics?|music|vocals?|composer|lyricist|producer|arranger|guitars?|bass|drums?|keyboards?)\s*[:：]',
	re.I)


def parse_lrc(lrc):
	lines = []
	for ln in (lrc or '').splitlines():
		m = re.match(r'\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)', ln)
		if not (m and m.group(3).strip()):
			continue
		text = m.group(3).strip()
		if _META_RE.search(text):            # skip songwriter/credit/metadata lines
			continue
		lines.append((int(m.group(1)) * 60 + float(m.group(2)), text))
	lines.sort()
	return lines


def _load(device):
	if 'model' not in _M:
		from torchaudio.pipelines import MMS_FA as B
		_M['model'] = B.get_model().to(device)
		_M['tok'] = B.get_tokenizer()
		_M['al'] = B.get_aligner()
	return _M


def _romanizer(text):
	# The MMS_FA aligner expects romanized text, and we also DISPLAY the romanization so non-Latin
	# songs are singable. Pick by dominant script (uroman misreads Japanese kanji, so use pykakasi).
	if re.search(r'[぀-ヿ]', text):                          # kana -> Japanese
		import pykakasi
		kks = pykakasi.kakasi()
		return lambda w: ' '.join(x['hepburn'] for x in kks.convert(w)).strip()
	if re.search(r'[가-힯]', text):                          # Hangul -> Korean
		import uroman
		uro = uroman.Uroman()
		return lambda w: uro.romanize_string(w).strip()
	if re.search(r'[一-鿿]', text):                          # Han only -> Chinese
		try:
			import pinyin
			return lambda w: pinyin.get(w, format='strip', delimiter=' ').strip()
		except Exception:
			import uroman
			uro = uroman.Uroman()
			return lambda w: uro.romanize_string(w).strip()
	return None                                                      # Latin / no romanization needed


def align(audio_path, lrc, device='cuda'):
	"""Force-align line-synced LRC lyrics to audio. Returns Whisper-style segments
	[{'words':[{'word','start','end'}]}] or None if it can't."""
	import torch, whisper
	lines = parse_lrc(lrc)
	if not lines:
		return None
	M = _load(device)
	rom = _romanizer(" ".join(t for _, t in lines))    # romanizer for non-Latin scripts (or None)
	audio = whisper.load_audio(audio_path)        # ffmpeg -> 16kHz mono float32
	sr = 16000
	total = len(audio) / sr
	segs = []
	for i, (start, text) in enumerate(lines):
		end = min(lines[i + 1][0] if i + 1 < len(lines) else start + 8.0, total)
		if end - start < 0.2:
			continue
		clip = audio[int(start * sr):int(end * sr)]
		# per word: display the romanized form for non-Latin (singable), align on its tokens
		pairs = []
		for w in text.split():
			d = rom(w) or w if (rom and re.search(r'[^\x00-\x7f]', w)) else w
			n = re.sub(r"[^a-z']", "", d.lower())
			if n:
				pairs.append((d, n))
		if not pairs:
			continue
		disp, norm = [d for d, _ in pairs], [n for _, n in pairs]
		try:
			with torch.inference_mode():
				emission, _ = M['model'](torch.from_numpy(clip).unsqueeze(0).to(device))
			spans = M['al'](emission[0].cpu(), M['tok'](norm))      # align on CPU (ROCm-safe)
			ratio = len(clip) / emission.size(1)
			words = []
			for sp, w in zip(spans, disp):
				st = start + sp[0].start * ratio / sr
				en = start + sp[-1].end * ratio / sr
				words.append({'word': w, 'start': st, 'end': max(en, st + 0.05)})
			if words:
				segs.append({'words': words})
		except Exception:
			continue
	return segs or None


def make_segments(media, audio_path, whisper_model, device='cuda', lang=None):
	"""Preferred: real lyrics force-aligned. Fallback: Whisper transcription.
	Returns (segments, method_description)."""
	name = song_query(media)
	lrc = fetch_lyrics(name)
	if lrc and ('[' in lrc):                       # need line timestamps to anchor alignment
		segs = align(audio_path, lrc, device)
		if segs:
			return segs, f"aligned real lyrics ({name})"
	res = whisper_model.transcribe(audio_path, word_timestamps=True, language=lang, fp16=(device == 'cuda'))
	return res['segments'], "whisper transcription (no synced lyrics found)"
