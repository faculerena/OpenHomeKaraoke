# Shared builder: Whisper word-timestamp segments -> ASS karaoke (\kf color-wipe).
# Used by make-karaoke.py (standalone) and asr_server.py (/make_karaoke, auto-on-download).

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KAR,Noto Sans CJK JP,54,&H0000FFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(t):
	cs = max(0, int(round(t * 100)))
	return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def segments_to_ass(segments):
	lines = [ASS_HEADER]
	for seg in segments:
		words = [w for w in (seg.get('words') or []) if w.get('word', '').strip()]
		if not words:
			continue
		start, end = words[0]['start'], words[-1]['end']
		text, prev = "", start
		for w in words:
			gap = w['start'] - prev
			if gap > 0.08:
				text += "{\\kf%d}" % round(gap * 100)          # pause before the word (no text)
			dur = max(1, round((w['end'] - w['start']) * 100))
			tok = w['word'].strip().replace('{', '(').replace('}', ')')
			text += "{\\kf%d}%s " % (dur, tok)
			prev = w['end']
		lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},KAR,,0,0,0,,{text.strip()}")
	return "\n".join(lines) + "\n"
