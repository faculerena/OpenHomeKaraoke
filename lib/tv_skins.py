# The TV between songs, in six skins (picked in the admin panel, panel/config.py TV_SKINS).
#
# karaoke.py builds a View (what to show) and calls draw(); each skin only decides how it
# looks. Rules every skin keeps:
#   - a song is always named before the person who asked for it, and the person's name is
#     never bigger than the song's;
#   - the join info (QR + address) is always there unless the app hides it (--hide-ip);
#   - the frame is static: the TV stream only pays for it once.
# Sizes are given for a 1920-wide screen and scaled to the real one.
import math
import os
import random
import unicodedata
from dataclasses import dataclass, field

import arabic_reshaper
import numpy as np
import pygame
import pygame.freetype
from bidi.algorithm import get_display

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(BASE, 'font')
FACES = {
	'heavyc': 'FiraSansCompressed-Heavy.ttf',
	'xboldc': 'FiraSansCompressed-ExtraBold.ttf',
	'heavy': 'FiraSans-Heavy.ttf',
	'xbold': 'FiraSans-ExtraBold.ttf',
	'semi': 'FiraSans-SemiBold.ttf',
	'semic': 'FiraSansCondensed-SemiBold.ttf',
}
FALLBACKS = ['arial-unicode-ms.ttf', 'unifont.ttf']   # other scripts (CJK, Arabic, ...)
REF_W = 1920


@dataclass
class View:
	title: str                                  # the big title (panel setting)
	state: str                                  # 'idle' | 'next' | 'playing' (audio-only song)
	song: str = None                            # the featured song: playing now, or next
	singer: str = None                          # who asked for it
	later: list = field(default_factory = list)  # [(song, singer)] after the featured one
	url: str = None                             # where phones join; None hides the join block
	tv_url: str = None
	qr: pygame.Surface = None
	T: dict = field(default_factory = dict)     # labels: upnext, later, sings, scan, playing


def hex2rgb(h):
	h = h.lstrip('#')
	return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- text

_fonts = {}


def _font(file, px):
	key = (file, px)
	if key not in _fonts:
		path = os.path.join(FONT_DIR, file)
		f = pygame.freetype.Font(path, px)
		f.origin = True       # render_to() places the baseline
		_fonts[key] = f
	return _fonts[key]


def _has(f, ch):
	m = f.get_metrics(ch)
	return bool(m) and m[0] is not None


def clean(text):
	"""Drop what no font here can draw (emoji above all) and invisible joiners; tidy spaces."""
	out = []
	probe = [_font(FACES['semi'], 20)] + [_font(f, 20) for f in FALLBACKS]
	for ch in str(text or ''):
		cat = unicodedata.category(ch)
		if cat in ('Cf', 'Cs', 'Co', 'Cn') or (cat == 'Mn' and 0xFE00 <= ord(ch) <= 0xFE0F):
			continue
		# symbols and emoji only when a real outline font has them: unifont's pixel glyphs
		# look broken at TV sizes
		fonts = probe[:2] if cat.startswith('S') else probe
		if ch.isspace() or any(_has(f, ch) for f in fonts):
			out.append(' ' if ch.isspace() else ch)
	return ' '.join(''.join(out).split())


class Ink:
	"""Draws text on one screen at that screen's scale."""

	def __init__(self, screen):
		self.s = screen
		self.W, self.H = screen.get_size()
		self.r = self.W / REF_W

	def px(self, v):
		return v * self.r

	def _runs(self, text, face, size):
		"""Split text into runs drawn by the first font that has each character."""
		n = max(6, round(size * self.r))
		chain = [_font(FACES[face], n)] + [_font(f, n) for f in FALLBACKS]
		runs = []
		for ch in text:
			f = chain[0] if ch == ' ' else next((f for f in chain if _has(f, ch)), None)
			if f is None:
				continue
			if runs and runs[-1][0] is f:
				runs[-1][1].append(ch)
			else:
				runs.append([f, [ch]])
		return chain[0], [(f, ''.join(cs)) for f, cs in runs]

	@staticmethod
	def _adv(f, s):
		return sum(m[4] for m in f.get_metrics(s) if m)

	def width(self, text, face, size, track = 0):
		_, runs = self._runs(text, face, size)
		n = sum(len(s) for _, s in runs)
		return sum(self._adv(f, s) for f, s in runs) + track * self.r * max(0, n - 1)

	def fit(self, text, face, size, max_w, track = 0):
		"""The text, cut with an ellipsis if it is wider than max_w."""
		if not max_w or self.width(text, face, size, track) <= max_w:
			return text
		while len(text) > 1 and self.width(text + '…', face, size, track) > max_w:
			text = text[:-1]
		return text.rstrip() + '…'

	def render(self, text, face, size, color, max_w = None, track = 0):
		text = get_display(arabic_reshaper.reshape(clean(text)))
		text = self.fit(text, face, size, max_w, track)
		main, runs = self._runs(text, face, size)
		asc = max([main.get_sized_ascender()] + [f.get_sized_ascender() for f, _ in runs])
		desc = min([main.get_sized_descender()] + [f.get_sized_descender() for f, _ in runs])
		gap = track * self.r
		w = math.ceil(self.width(text, face, size, track)) + 2
		surf = pygame.Surface((max(1, w), max(1, asc - desc)), pygame.SRCALPHA)
		x = 0
		for f, s in runs:
			if gap:
				for ch in s:
					f.render_to(surf, (x, asc), ch, color)
					x += self._adv(f, ch) + gap
			else:
				f.render_to(surf, (x, asc), s, color)
				x += self._adv(f, s)
		return surf

	def place(self, surf, pos, anchor = 'topleft', target = None):
		rect = surf.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
		(target or self.s).blit(surf, rect)
		return rect

	def draw(self, text, face, size, color, pos, anchor = 'topleft', max_w = None, track = 0):
		return self.place(self.render(text, face, size, color, max_w, track), pos, anchor)

	def wrap(self, text, face, sizes, max_w, max_lines):
		"""The biggest size at which text fits in max_lines lines, and those lines (the last
		one ends in … when even the smallest size does not fit)."""
		text = clean(text)
		words = text.split()
		for size in sizes:
			lines, cur = [], ''
			for word in words:
				if cur and self.width(cur + ' ' + word, face, size) > max_w:
					lines.append(cur)
					cur = word
				else:
					cur = (cur + ' ' + word).strip()
			lines.append(cur)
			if len(lines) <= max_lines and all(self.width(L, face, size) <= max_w for L in lines):
				return size, lines
		size = sizes[-1]
		if len(lines) > max_lines:
			lines = lines[:max_lines - 1] + [' '.join(lines[max_lines - 1:])]
		return size, [self.fit(L, face, size, max_w) for L in lines]

	def line_h(self, face, size, k = 1.0):
		f = _font(FACES[face], max(6, round(size * self.r)))
		return (f.get_sized_ascender() - f.get_sized_descender()) * k

	def outlined(self, text, face, size, color, stroke, outline = (0, 0, 0), max_w = None, wipe = None):
		"""Karaoke lettering: a thick outline under the fill; wipe = (fraction, colour) paints the
		left part of the fill like a lyric line being sung."""
		k = max(1, round(stroke * self.r))
		fill = self.render(text, face, size, color, max_w and max_w - 2 * k)
		base = self.render(text, face, size, outline, max_w and max_w - 2 * k)
		out = pygame.Surface((fill.get_width() + 2 * k, fill.get_height() + 2 * k), pygame.SRCALPHA)
		steps = 24
		for rr in (k, k * 0.6):
			for i in range(steps):
				a = 2 * math.pi * i / steps
				out.blit(base, (k + rr * math.cos(a), k + rr * math.sin(a)))
		out.blit(fill, (k, k))
		if wipe:
			frac, wcol = wipe
			sung = self.render(text, face, size, wcol, max_w and max_w - 2 * k)
			w = round(sung.get_width() * frac)
			out.blit(sung, (k, k), pygame.Rect(0, 0, w, sung.get_height()))
		return out


# ---------------------------------------------------------------- surfaces and effects

_grounds = {}


def ground(name, size, make):
	"""A skin's static background, built once per screen size."""
	key = (name, size)
	if key not in _grounds:
		_grounds.clear() if len(_grounds) > 8 else None
		_grounds[key] = make(*size)
	return _grounds[key]


def from_array(arr):
	return pygame.surfarray.make_surface(np.ascontiguousarray(np.clip(arr, 0, 255).astype(np.uint8).swapaxes(0, 1)))


def noise(H, W, amount, seed = 1):
	return np.random.default_rng(seed).normal(0, amount, (H, W, 1)).astype(np.float32)


def blur(surf, k):
	"""A soft blur: halve down to about 1/k, then double back up step by step (one big
	bilinear jump looks blocky)."""
	w, h = surf.get_size()
	sizes = []
	cw, ch = w, h
	while cw > w / k and cw > 2 and ch > 2:
		cw, ch = max(1, cw // 2), max(1, ch // 2)
		sizes.append((cw, ch))
	cur = surf
	for sz in sizes:
		cur = pygame.transform.smoothscale(cur, sz)
	for sz in reversed([(w, h)] + sizes[:-1]):
		cur = pygame.transform.smoothscale(cur, sz)
	return cur


def multiply(screen, surf, pos):
	"""Overprint like ink: white leaves the paper alone, colours darken what is under them."""
	paper = pygame.Surface(surf.get_size())
	paper.fill((255, 255, 255))
	paper.blit(surf, (0, 0))
	screen.blit(paper, pos, special_flags = pygame.BLEND_MULT)


def qr_block(qr, target_px):
	"""The QR scaled by a whole number of pixels per module, so it stays crisp."""
	n = max(1, round(target_px / qr.get_width()))
	return pygame.transform.scale(qr, (qr.get_width() * n, qr.get_height() * n))


def credit(song, singer):
	"""'Song · Singer': the song first, always."""
	return f"{song} · {singer}" if singer else str(song)


def featured(v):
	"""(kicker, headline, who) for the main block, by state."""
	if v.state == 'playing':
		return v.T['playing'], v.song, v.singer
	if v.state == 'next':
		return v.T['upnext'], v.song, v.singer
	return None, v.title, None


# ---------------------------------------------------------------- skins

def skin_karaoke(k, v):
	"""The 90s karaoke-bar video: blue field, outlined white letters, the lyric wipe."""
	W, H, r = k.W, k.H, k.r
	BLUE, YEL, WHITE, ORANGE, SKY = (11, 47, 168), (255, 242, 0), (255, 255, 255), (255, 122, 0), (191, 227, 255)

	def make(W, H):
		arr = np.empty((H, W, 3), np.float32)
		arr[:] = BLUE
		rows = (np.arange(H) % max(2, round(4 * r))) < max(1, round(2 * r))
		arr[rows] *= 0.86          # scanlines
		return from_array(arr + noise(H, W, 1.2)).convert()
	k.s.blit(ground('karaoke', (W, H), make), (0, 0))
	M = 90 * r

	kicker, head, who = featured(v)
	if v.state == 'next':
		kicker = f"♪ 1/{1 + len(v.later)} · {kicker.upper()}"
	elif v.state == 'playing':
		kicker = f"♪ {kicker.upper()}"
	else:
		kicker = f"♪ {v.T['scan']}"
	if v.state != 'idle':
		# the night's title, like the programme name in the corner of the screen
		k.place(k.outlined(v.title, 'xbold', 44, WHITE, 4, max_w = W - 2 * M - 760 * r), (M, 64 * r))
	k.place(k.outlined(kicker, 'xbold', 44, YEL, 4, max_w = W - 2 * M - (760 * r if v.state == 'idle' else 0)),
			(M, (64 if v.state == 'idle' else 172) * r))

	# the rest of the queue, top right, numbered on from the featured song
	later = v.later[1:4] if v.state == 'playing' else v.later[:3]
	y = 70 * r
	start = 3 if v.state == 'playing' else 2
	for i, (song, singer) in enumerate(later):
		y = k.place(k.outlined(f"{start + i}  {credit(song, singer)}", 'xbold', 34, WHITE, 3, max_w = 700 * r),
				(W - M, y), 'topright').bottom + 6 * r

	size, lines = k.wrap(head, 'heavy', [124, 108, 94, 82, 72], W - 2 * M, 2)
	y = 240 * r
	for i, L in enumerate(lines):
		surf = k.outlined(L, 'heavy', size, WHITE, 6, max_w = W - 2 * M + 12 * r, wipe = (0.46, ORANGE) if i == 0 else None)
		y = k.place(surf, (M - 6 * r, y)).bottom - size * 0.16 * r
	if who:
		y = k.place(k.outlined(f"▶ {v.T['sings']} {who.upper()}", 'xbold', min(64, size * 0.6), YEL, 5,
				max_w = W - 2 * M), (M, y + 24 * r)).bottom
	if v.state == 'playing' and v.later:
		k.place(k.outlined(f"{v.T['upnext']}: {credit(*v.later[0])}", 'semi', 40, SKY, 3, max_w = W - 2 * M),
				(M, y + 20 * r))

	if v.url:
		q = qr_block(v.qr, 170 * r) if v.qr else None
		top = H - 60 * r - (q.get_height() + 28 * r if q else 120 * r)
		x = M
		if q:
			pad = 14 * r
			plate = pygame.Rect(M, top, q.get_width() + 2 * pad, q.get_height() + 2 * pad)
			pygame.draw.rect(k.s, WHITE, plate)
			k.s.blit(q, (plate.x + pad, plate.y + pad))
			x = plate.right + 46 * r
		y = k.place(k.outlined(v.url, 'heavy', 60, WHITE, 5, max_w = W - x - M), (x, top + 10 * r)).bottom
		if v.state != 'idle':
			y = k.draw(v.T['scan'], 'xbold', 32, SKY, (x + 6 * r, y + 2 * r), max_w = W - x - M)
			y = y.bottom
		if v.tv_url:
			k.draw(f"TV: {v.tv_url}", 'semi', 26, SKY, (x + 6 * r, y + 8 * r), max_w = W - x - M)


def skin_cotillon(k, v):
	"""The title strung across the top as a paper letter garland, on crepe-paper red."""
	W, H, r = k.W, k.H, k.r
	RED, CREAM, YEL, TEAL, PINK, LIME = (138, 26, 31), (255, 244, 220), (255, 210, 63), (127, 224, 212), (255, 143, 177), (155, 227, 109)
	PAPERS = [YEL, TEAL, PINK, CREAM, LIME]
	INK = (27, 27, 27)
	M = 110 * r

	def make(W, H):
		x = np.arange(W, dtype = np.float32)
		crepe = (np.sin(x / (5.5 * r)) * 0.5 + 0.5) * 9 + np.random.default_rng(3).normal(0, 2.5, W)   # vertical crinkle
		arr = np.empty((H, W, 3), np.float32)
		arr[:] = RED
		arr -= crepe[None, :, None] * np.array([1, 0.35, 0.35], np.float32)
		arr += noise(H, W, 1.6)
		surf = from_array(arr).convert()
		# serpentinas: paper streamers curling in from the edges
		def curl(cx, cy, turns, r0, r1, col, width, a0 = 0.0, drift = (0, 0)):
			pts = []
			n = int(turns * 90)
			for i in range(n):
				t = i / n
				a = a0 + t * turns * 2 * math.pi
				rad = (r0 + (r1 - r0) * t) * r
				pts.append((cx * r + rad * math.cos(a) + drift[0] * t * r, cy * r + rad * math.sin(a) + drift[1] * t * r))
			for i in range(len(pts) - 1):
				pygame.draw.line(surf, col, pts[i], pts[i + 1], max(2, round(width * r)))
			for p in pts:
				pygame.draw.circle(surf, col, p, max(1, width * r / 2))
		curl(1855, 150, 1.6, 10, 46, TEAL, 9, a0 = -1.2, drift = (-30, 190))
		curl(1700, 1010, 1.4, 70, 20, YEL, 11, a0 = 0.4, drift = (160, -40))
		curl(30, 640, 1.2, 50, 12, PINK, 9, a0 = 2.0, drift = (10, 140))
		return surf
	k.s.blit(ground('cotillon', (W, H), make), (0, 0))

	# ---- the garland: one or two strings of pennants spelling the title
	title = clean(v.title).upper()
	words = title.split()
	step_l, step_s = 74, 34          # ref px per letter / per space

	def need(t):
		return sum(step_s if c == ' ' else step_l for c in t)
	avail = (W - 2 * M) / r
	strings = [title]
	if need(title) > avail and len(words) > 1:
		best = None
		for i in range(1, len(words)):
			a, b = ' '.join(words[:i]), ' '.join(words[i:])
			m = max(need(a), need(b))
			if best is None or m < best[0]:
				best = (m, [a, b])
		strings = best[1]
	f = min(1.0, avail / max(need(s) for s in strings))
	rng = random.Random(len(title))
	bottom = 0
	for row, text in enumerate(strings):
		y0, yc = (58 + row * 150) * r, (200 + row * 150) * r
		x0, x1 = -20 * r, W + 20 * r
		pts = [(x0 + (x1 - x0) * t / 60, y0 + 2 * (t / 60) * (1 - t / 60) * (yc - y0)) for t in range(61)]
		pygame.draw.lines(k.s, (243, 230, 200), False, pts, max(2, round(3 * r)))
		x = (W - need(text) * f * r) / 2
		pw, ph = 66 * f * r, 96 * f * r
		for i, ch in enumerate(text):
			if ch == ' ':
				x += step_s * f * r
				continue
			cx = x + step_l * f * r / 2
			t = (cx - x0) / (x1 - x0)
			cy = y0 + 2 * t * (1 - t) * (yc - y0)
			slope = 2 * (1 - 2 * t) * (yc - y0) / (x1 - x0)
			ang = -math.degrees(math.atan(slope)) + rng.uniform(-3.5, 3.5)
			pen = pygame.Surface((round(pw) + 4, round(ph) + 4), pygame.SRCALPHA)
			j = lambda: rng.uniform(-1.6, 1.6) * r
			poly = [(2 + j(), 2 + j()), (2 + pw + j(), 2 + j()), (2 + pw + j(), 2 + 0.74 * ph + j()),
					(2 + pw / 2 + j(), 2 + ph + j()), (2 + j(), 2 + 0.74 * ph + j())]
			pygame.draw.polygon(pen, PAPERS[i % len(PAPERS)], poly)
			pygame.draw.line(pen, (0, 0, 0, 40), (2, 3), (2 + pw, 3), max(1, round(2 * r)))   # the fold over the string
			glyph = k.render(ch, 'heavyc', 52 * f, INK)
			pen.blit(glyph, glyph.get_rect(center = (2 + pw / 2, 2 + ph * 0.40)))
			rot = pygame.transform.rotozoom(pen, ang, 1)
			off = pygame.math.Vector2(0, ph / 2).rotate(-ang)
			k.s.blit(rot, rot.get_rect(center = (cx + off.x, cy - 3 * r + off.y)))
			bottom = max(bottom, cy + ph)
			x += step_l * f * r

	# ---- the song coming up (left) and the rest of the queue (right)
	card_top = H - 70 * r - 240 * r
	top = bottom + 40 * r
	col_w = 560 * r
	kicker, head, who = featured(v)
	if v.state == 'idle':
		head = v.T['scan']
	size, lines = k.wrap(head, 'heavyc', [108, 96, 84, 72, 62], W - 2 * M - col_w - 60 * r, 2)
	block = (k.line_h('xbold', 44) if kicker else 0) + len(lines) * k.line_h('heavyc', size, 0.9) + (k.line_h('xbold', 46) if who else 0)
	y = top + max(0, (card_top - 30 * r - top - block) / 2)
	y0 = y
	if kicker:
		y = k.draw(kicker.upper(), 'xbold', 44, YEL, (M, y), track = 2).bottom - 6 * r
	for L in lines:
		y = k.draw(L, 'heavyc', size, CREAM, (M, y)).bottom - size * 0.12 * r
	if who:
		k.draw(who, 'xbold', min(46, size * 0.5), TEAL, (M, y + 10 * r), max_w = W - 2 * M - col_w)
	later = v.later[:3]
	if later:
		y = k.draw((v.T['upnext'] if v.state == 'playing' else v.T['later']).upper(), 'xbold', 32, YEL,
				(W - M, y0 + 8 * r), 'topright', track = 2).bottom + 8 * r
		for song, singer in later:
			y = k.draw(credit(song, singer), 'semic', 36, CREAM, (W - M, y), 'topright', max_w = col_w).bottom + 4 * r

	# ---- the QR as a card taped on, and the address
	if v.url:
		x = M
		if v.qr:
			q = qr_block(v.qr, 180 * r)
			pad = 18 * r
			card = pygame.Surface((q.get_width() + 2 * pad, q.get_height() + 2 * pad), pygame.SRCALPHA)
			card.fill(CREAM)
			card.blit(q, (pad, pad))
			card = pygame.transform.rotozoom(card, 2.5, 1)
			rect = k.s.blit(card, card.get_rect(bottomleft = (M, H - 60 * r)))
			tape = pygame.Surface((round(96 * r), round(30 * r)), pygame.SRCALPHA)
			tape.fill((255, 232, 150, 185))
			tape = pygame.transform.rotozoom(tape, -5, 1)
			k.s.blit(tape, tape.get_rect(center = (rect.centerx, rect.top + 6 * r)))
			x = rect.right + 40 * r
		y = k.draw(v.url, 'xbold', 58, CREAM, (x, H - 60 * r - 175 * r), max_w = W - x - M).bottom
		if v.state != 'idle':
			y = k.draw(v.T['scan'], 'semi', 32, (255, 217, 194), (x + 2 * r, y + 2 * r), max_w = W - x - M).bottom
		if v.tv_url:
			k.draw(f"TV: {v.tv_url}", 'semi', 26, (255, 217, 194), (x + 2 * r, y + 10 * r), max_w = W - x - M)


def skin_riso(k, v):
	"""Tonight's poster: the title in two misregistered inks on paper, the QR as a stamp."""
	W, H, r = k.W, k.H, k.r
	PAPER, PINK, BLUE = (205, 192, 164), (255, 79, 154), (43, 75, 209)
	M = 80 * r

	def make(W, H):
		arr = np.empty((H, W, 3), np.float32)
		arr[:] = PAPER
		rng = np.random.default_rng(5)
		arr += noise(H, W, 3.2, 5)
		fib = rng.normal(0, 1, (H // 6 + 1, W // 6 + 1)).astype(np.float32)   # coarse paper tooth
		arr += np.kron(fib, np.ones((6, 6), np.float32))[:H, :W, None] * 2.2
		return from_array(arr).convert()
	k.s.blit(ground('riso', (W, H), make), (0, 0))

	# the title, stacked huge: pink, then blue printed a hair off register
	size, lines = k.wrap(clean(v.title).upper(), 'heavyc', [250, 220, 190, 165, 140, 120, 100], W * 0.58, 3)
	lh = k.line_h('heavyc', size, 0.82)
	for ink, (dx, dy) in ((PINK, (0, 0)), (BLUE, (9, 7))):
		y = 30 * r
		for L in lines:
			multiply(k.s, k.render(L, 'heavyc', size, ink), (M + dx * r, y + dy * r))
			y += lh

	# the disc: what's next, song first
	R = 200 * r
	cx, cy = W - M - R - 20 * r, 70 * r + R
	disc = pygame.Surface((round(2 * R), round(2 * R)), pygame.SRCALPHA)
	pygame.draw.circle(disc, PINK, (R, R), R)
	multiply(k.s, disc, (cx - R, cy - R))
	kicker, head, who = featured(v)
	if v.state == 'idle':
		head = v.T['scan']
	inner = 2 * R * 0.78
	s2, lines2 = k.wrap(head, 'heavyc', [80, 70, 60, 52, 44], inner, 3)
	parts = []
	if kicker:
		parts.append(k.render(kicker.lower(), 'semi', 36, BLUE, inner))
	parts += [k.render(L, 'heavyc', s2, BLUE) for L in lines2]
	if who:
		parts.append(k.render(who, 'xbold', min(38, s2), BLUE, inner))
	total = sum(p.get_height() * (0.86 if i else 1) for i, p in enumerate(parts))
	y = cy - total / 2
	for i, p in enumerate(parts):
		multiply(k.s, p, p.get_rect(midtop = (cx, y)).topleft)
		y += p.get_height() * 0.86
	later = v.later[:3]
	if later:
		y = cy + R + 30 * r
		lab = k.render((v.T['upnext'] if v.state == 'playing' else v.T['later']).lower(), 'xbold', 30, PINK)
		multiply(k.s, lab, lab.get_rect(midtop = (cx, y)).topleft)
		y += lab.get_height()
		for song, singer in later:
			s = k.render(credit(song, singer), 'semic', 32, BLUE, 2 * R + 160 * r)
			multiply(k.s, s, s.get_rect(midtop = (cx, y)).topleft)
			y += s.get_height()

	# the QR stamped in blue, and the address
	if v.url:
		x = M
		if v.qr:
			q = qr_block(v.qr, 180 * r)
			pad, bw = 14 * r, max(3, round(8 * r))
			st = pygame.Surface((q.get_width() + 2 * (pad + bw), q.get_height() + 2 * (pad + bw)), pygame.SRCALPHA)
			pygame.draw.rect(st, BLUE, st.get_rect(), bw)
			st.blit(q, (pad + bw, pad + bw))
			st = pygame.transform.rotozoom(st, 4, 1)
			pos = st.get_rect(bottomleft = (M, H - 50 * r))
			multiply(k.s, st, pos.topleft)
			x = pos.right + 40 * r
		u = k.render(v.url, 'heavyc', 66, BLUE, W - x - M)
		multiply(k.s, u, (x, H - 50 * r - 170 * r))
		y = H - 50 * r - 170 * r + u.get_height()
		lab = k.render(v.T['scan'], 'semi', 32, PINK, W - x - M)
		multiply(k.s, lab, (x + 4 * r, y))
		if v.tv_url:
			t = k.render(f"TV: {v.tv_url}", 'semi', 26, BLUE, W - x - M)
			multiply(k.s, t, (x + 4 * r, y + lab.get_height() + 6 * r))


def skin_obi(k, v):
	"""A sleeve face holding only the QR; a crowded red band carries the queue like credits."""
	W, H, r = k.W, k.H, k.r
	FACE, OBI, CREAM, INK = (233, 228, 218), (232, 64, 28), (255, 247, 234), (34, 34, 34)

	def make(W, H):
		arr = np.empty((H, W, 3), np.float32)
		arr[:] = FACE
		return from_array(arr + noise(H, W, 1.4)).convert()
	k.s.blit(ground('obi', (W, H), make), (0, 0))
	band_top = H - 340 * r

	if v.url:
		if v.qr:
			q = qr_block(v.qr, 300 * r)
			rect = k.s.blit(q, q.get_rect(midtop = (W / 2, (band_top - q.get_height() - 110 * r) / 2 + 10 * r)))
			y = rect.bottom + 26 * r
		else:
			y = band_top / 2 - 40 * r
		y = k.draw(v.url, 'semi', 40, INK, (W / 2, y), 'midtop', max_w = W - 200 * r).bottom
		if v.tv_url:
			k.draw(f"TV: {v.tv_url}", 'semi', 24, (110, 104, 96), (W / 2, y + 8 * r), 'midtop', max_w = W - 200 * r)

	pygame.draw.rect(k.s, OBI, pygame.Rect(0, round(band_top), W, H - round(band_top)))
	M, pad = 60 * r, 30 * r
	lead_w = 600 * r
	kicker, head, who = featured(v)
	y = band_top + pad
	if kicker:
		y = k.draw(kicker.upper(), 'xbold', 30, CREAM, (M, y), track = 2, max_w = lead_w).bottom
	size, lines = k.wrap(head, 'heavyc', [92, 80, 70, 60, 52], lead_w, 2)
	for L in lines:
		y = k.draw(L, 'heavyc', size, CREAM, (M, y)).bottom - size * 0.14 * r
	if who:
		k.draw(who, 'xbold', min(42, size * 0.55), CREAM, (M, y + 8 * r), max_w = lead_w)
	elif v.state == 'idle':
		k.draw(v.T['scan'], 'xbold', 36, CREAM, (M, y + 8 * r), max_w = lead_w)

	# vertical credit columns: the rest of the queue, then the night's title
	cols = []
	n0 = 2 if v.state == 'next' else 1
	for i, (song, singer) in enumerate(v.later):
		cols.append((f"{n0 + i} · {credit(song, singer)}", 'semic'))
	if v.state != 'idle':
		cols.append((clean(v.title), 'xbold'))
	x = M + lead_w + 40 * r
	col_h = H - band_top - 2 * pad
	col_w = 62 * r
	for text, face in cols:
		if x + col_w > W - M:
			break
		s = k.render(text, face, 30, CREAM, col_h)
		s = pygame.transform.rotate(s, -90)
		pygame.draw.line(k.s, (255, 247, 234), (x, band_top + pad), (x, H - pad), max(1, round(2 * r)))
		k.s.blit(s, (x + (col_w - s.get_width()) / 2, band_top + pad))
		x += col_w


def skin_bare(k, v):
	"""Nothing but the essentials: a big QR, the address, the song, who sings it."""
	W, H, r = k.W, k.H, k.r
	WHITE, GREY, SOFT = (255, 255, 255), (154, 154, 154), (200, 200, 200)
	k.s.fill((0, 0, 0))
	x = 120 * r
	if v.url and v.qr:
		q = qr_block(v.qr, 440 * r)
		pad = 26 * r
		plate = pygame.Rect(120 * r, (H - q.get_height()) / 2 - pad, q.get_width() + 2 * pad, q.get_height() + 2 * pad)
		pygame.draw.rect(k.s, WHITE, plate)
		k.s.blit(q, (plate.x + pad, plate.y + pad))
		x = plate.right + 110 * r
	max_w = W - x - 100 * r
	kicker, head, who = featured(v)
	parts = []
	if v.state != 'idle':
		parts.append(('text', clean(v.title), 'semi', 34, GREY))
	if v.url:
		parts.append(('text', v.url, 'semi', 56, WHITE))
		parts.append(('gap', 80))
	if kicker:
		parts.append(('text', kicker, 'semi', 30, GREY))
	size, lines = k.wrap(head, 'heavy', [96, 84, 72, 62, 54], max_w, 2)
	parts += [('text', L, 'heavy', size, WHITE) for L in lines]
	if who:
		parts.append(('text', who, 'semi', min(46, size * 0.55), SOFT))
	elif v.state == 'idle':
		parts.append(('text', v.T['scan'], 'semi', 46, SOFT))
	if v.state == 'playing' and v.later:
		parts.append(('gap', 30))
		parts.append(('text', f"{v.T['upnext']}: {credit(*v.later[0])}", 'semi', 32, GREY))
	if v.tv_url:
		parts.append(('gap', 40))
		parts.append(('text', f"TV: {v.tv_url}", 'semi', 26, GREY))
	surfs = []
	for p in parts:
		if p[0] == 'gap':
			surfs.append(p[1] * r)
		else:
			surfs.append(k.render(p[1], p[2], p[3], p[4], max_w))
	total = sum(s if isinstance(s, float) else s.get_height() for s in surfs)
	y = (H - total) / 2
	for s in surfs:
		if isinstance(s, float):
			y += s
		else:
			k.s.blit(s, (x, y))
			y += s.get_height()


def skin_neon(k, v):
	"""The karaoke-lounge standard: glowing pink title on purple-black, QR on a glowing tile."""
	W, H, r = k.W, k.H, k.r
	PINK, CYAN, GREY = (255, 91, 216), (94, 243, 255), (221, 221, 221)

	def make(W, H):
		y, x = np.mgrid[0:H, 0:W].astype(np.float32)
		d = np.clip(np.hypot(x / W - 0.7, (y / H - 0.3) * H / W) / 0.75, 0, 1)
		a, b = np.array([58, 15, 94], np.float32), np.array([11, 4, 20], np.float32)
		arr = a * (1 - d[..., None]) + b * d[..., None]
		return from_array(arr + noise(H, W, 1.3)).convert()
	k.s.blit(ground('neon', (W, H), make), (0, 0))

	def glow(surf, pos, anchor, col):
		# the text on black, blurred, then added on: light, not a box
		pad = round(60 * r)
		big = pygame.Surface((surf.get_width() + 2 * pad, surf.get_height() + 2 * pad))
		big.fill((0, 0, 0))
		big.blit(surf, (pad, pad))
		rect = surf.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
		for kk, dim in ((8, (120, 120, 120)), (24, (150, 150, 150))):
			halo = blur(big, max(2, round(kk * r)))
			halo.fill(dim, special_flags = pygame.BLEND_RGB_MULT)
			k.s.blit(halo, (rect.x - pad, rect.y - pad), special_flags = pygame.BLEND_RGB_ADD)
		k.s.blit(surf, rect)
		return rect

	M = 100 * r
	size, lines = k.wrap(clean(v.title), 'heavy', [120, 104, 90, 78], W - 2 * M, 2)
	y = 110 * r
	for L in lines:
		y = glow(k.render(L, 'heavy', size, PINK), (W / 2, y), 'midtop', PINK).bottom - 10 * r
	if v.state == 'idle':
		line = v.T['scan']
	else:
		kicker, head, who = featured(v)
		line = f"{kicker}: {credit(head, who)}"
	y = glow(k.render(line, 'semi', 54, CYAN, W - 2 * M), (W / 2, y + 40 * r), 'midtop', CYAN).bottom
	if v.state == 'playing' and v.later:
		k.draw(f"{v.T['upnext']}: {credit(*v.later[0])}", 'semi', 34, GREY, (W / 2, y + 18 * r), 'midtop', max_w = W - 2 * M)
	if v.url:
		bottom = H - 50 * r
		join = f"{v.url}   ·   TV: {v.tv_url}" if v.tv_url else v.url
		u = k.draw(join, 'semi', 38, GREY, (W / 2, bottom), 'midbottom', max_w = W - 2 * M)
		if v.qr:
			q = qr_block(v.qr, 200 * r)
			pad = 16 * r
			tile = pygame.Rect(0, 0, q.get_width() + 2 * pad, q.get_height() + 2 * pad)
			tile.midbottom = (W / 2, u.top - 24 * r)
			halo = pygame.Surface((tile.w + 160 * r, tile.h + 160 * r))
			halo.fill((0, 0, 0))
			pygame.draw.rect(halo, (150, 50, 125), pygame.Rect(80 * r, 80 * r, tile.w, tile.h), border_radius = round(20 * r))
			halo = blur(halo, max(2, round(14 * r)))
			k.s.blit(halo, (tile.x - 80 * r, tile.y - 80 * r), special_flags = pygame.BLEND_RGB_ADD)
			pygame.draw.rect(k.s, (255, 255, 255), tile, border_radius = round(18 * r))
			k.s.blit(q, (tile.x + pad, tile.y + pad))


SKINS = {
	'karaoke': skin_karaoke,
	'cotillon': skin_cotillon,
	'riso': skin_riso,
	'obi': skin_obi,
	'bare': skin_bare,
	'neon': skin_neon,
}


def draw(screen, skin, view):
	"""Draw the splash. A skin that fails falls back to the plainest one: the party goes on."""
	ink = Ink(screen)
	try:
		SKINS.get(skin, skin_karaoke)(ink, view)
	except Exception:
		import logging
		logging.exception(f"TV skin {skin!r} failed; drawing 'bare' instead")
		skin_bare(ink, view)


def preview(spec, out_path):
	"""Render one skin to a PNG without the app (the panel's preview). spec: skin, state,
	title, url, tv_url, lang, queue [[song, singer], ...], size [w, h]."""
	os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
	os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
	from lib.get_platform import set_language
	set_language(spec.get('lang') or 'es')
	tr = lambda ii: os.texts[ii] or os.langs['en_US'][ii]
	pygame.display.init()
	pygame.freetype.init()
	W, H = spec.get('size') or (960, 540)
	screen = pygame.display.set_mode((W, H))
	qr_path = os.path.join(BASE, 'qrcode.png')
	qr = pygame.image.load(qr_path) if os.path.exists(qr_path) else None
	queue = [tuple(q) for q in spec.get('queue') or []]
	state = spec.get('state', 'idle') if queue else 'idle'
	song, singer = (queue[0] if queue else (None, None))
	v = View(title = clean(spec.get('title')) or tr(136), state = state, song = song, singer = singer,
			later = queue[1:] if state == 'next' else queue, url = spec.get('url'), tv_url = spec.get('tv_url'),
			qr = qr, T = {'upnext': tr(241), 'later': tr(242), 'sings': tr(243), 'scan': tr(244), 'playing': tr(245)})
	if state == 'playing':
		v.later = queue[1:]
	draw(screen, spec.get('skin'), v)
	pygame.image.save(screen, out_path)


if __name__ == '__main__':
	# python -m lib.tv_skins <out.png>  < spec.json
	import json
	import sys
	os.chdir(BASE)           # lang/ is repo-relative
	preview(json.load(sys.stdin), sys.argv[1])
