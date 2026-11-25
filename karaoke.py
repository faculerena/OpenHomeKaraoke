import os, sys, io, random, time, json, datetime, tempfile, math
from urllib.parse import urlparse
import logging, socket, subprocess, threading
import multiprocessing as mp
import shutil, psutil, traceback, tarfile, requests
from subprocess import check_output
from collections import *

import numpy as np

from constants import media_types

import pygame
import qrcode
import arabic_reshaper
from bidi.algorithm import get_display
from unidecode import unidecode
from flask import request
from lib import omxclient, vlcclient
from lib.get_platform import *
from lib.NLP import *
from app import getString

if get_platform() != "windows":
	from signal import SIGALRM, alarm, signal, SIGTERM
	signal(SIGTERM, lambda signum, stack_frame: os.K.stop())

STD_VOL = 65536/8/np.sqrt(2)
ip2websock, ip2pane = {}, {}

# ip2websock: client IP -> SET of its open websockets (a phone can hold several: a reconnect, a
# second tab). See ws_init in app.py.
ip2ws_lock = threading.Lock()

def ws_send(ip, msg):
	"""Send to every open socket of one client; drop the ones that fail."""
	with ip2ws_lock:
		socks = list(ip2websock.get(ip, ()))
	for ws in socks:
		try:
			ws.send(msg)
		except Exception:
			with ip2ws_lock:
				ip2websock.get(ip, set()).discard(ws)

def flash(message: str, category: str = "message", client_ip = ''):
	ws_send(client_ip or request.remote_addr, f'showNotification("{message}", "{category}")')

def cleanse_modules(name):
	try:
		for module_name in sorted(sys.modules.keys()):
			if module_name.startswith(name):
				del sys.modules[module_name]
		del globals()[name]
	except:
		pass


class Karaoke:
	ref_W, ref_H = 1920, 1080      # reference screen size, control drawing scale

	queue = []
	queue_json = '[]'      # valid JSON from the start: the Queue page ignores an empty reply, so it never drew its empty state
	available_songs = []
	rename_history = {}
	songname_trans = {} # transliteration is used for sorting and initial letter search
	now_playing = None
	now_playing_filename = None
	now_playing_user = None
	now_playing_transpose = 0
	now_playing_slave = ''
	audio_delay = 0
	has_video = True
	has_subtitle = False
	subtitle_delay = 0
	play_speed = 1.0
	show_subtitle = True
	last_vocal_info = 0
	last_vocal_time = 0
	use_DNN_vocal = True
	vocal_process = None
	vocal_device = None
	vocal_mode = 'mixed'
	is_paused = True
	firstSongStarted = False
	switchingSong = False
	qr_code_path = None
	base_path = os.path.dirname(__file__)
	volume_offset = 0
	default_logo_path = os.path.join(base_path, "logo.jpg")
	# TV splash: the "Radio de living" palette and type (DESIGN.md), same as the phones and the panel
	C_WALNUT, C_CAB, C_LINE = (29, 20, 16), (38, 26, 19), (74, 51, 38)
	C_PRINT, C_DIM, C_FAINT = (241, 227, 196), (196, 173, 142), (160, 138, 109)
	C_AMBER, C_NEEDLE, C_EYE = (242, 181, 68), (217, 71, 47), (111, 195, 159)
	SINGER_COLORS = ['#9fd0f0', '#e9a6c9', '#b9d98a', '#f0a77a', '#c6b3f5', '#8fd6c8', '#f5d77a', '#f28b82']
	splash_fonts_dir = os.path.join(base_path, "static", "fonts")
	logical_volume = None   # for normalized volume
	status_dirty = True
	event_dirty = threading.Event()

	def __init__(self, args):

		# override with supplied constructor args if provided
		self.__dict__.update(args.__dict__)
		self.omxplayer_adev = 'both'
		self.download_path = args.dl_path
		self.volume_offset = self.volume = args.volume
		self.logo_path = self.default_logo_path if args.logo_path == None else args.logo_path

		# other initializations
		self.platform = get_platform()
		self.vlcclient = None
		self.omxclient = None
		self.screen = None
		self.player_state = {}
		self.downloading_songs = {}
		self.log_level = int(args.log_level)

		logging.basicConfig(
			format = "[%(asctime)s] %(levelname)s: %(message)s",
			datefmt = "%Y-%m-%d %H:%M:%S",
			level = self.log_level,
		)

		logging.debug(vars(args))

		if self.save_delays:
			self.init_save_delays()

		# Generate connection URL and QR code, retry in case pi is still starting up
		# and doesn't have an IP yet (occurs when launched from /etc/rc.local)
		end_time = int(time.time()) + 30

		if self.platform == "raspberry_pi":
			while int(time.time()) < end_time:
				addresses_str = check_output(["hostname", "-I"]).strip().decode("utf-8")
				addresses = addresses_str.split(" ")
				self.ip = addresses[0]
				if not self.is_network_connected():
					logging.debug("Couldn't get IP, retrying....")
				else:
					break
		else:
			self.ip = self.get_ip()

		logging.debug("IP address (for QR code and splash screen): " + self.ip)

		# --url wins (e.g. a public hostname served through a tunnel); otherwise use the LAN IP.
		# NOTE: self.url may already be set from args via __dict__.update() above.
		if not getattr(self, 'url', None):
			self.url = "%s://%s:%s" % (('https' if self.ssl else 'http'), self.ip, self.port)

		# get songs from download_path
		self.get_available_songs()
		self.get_youtubedl_version()
		self.song2vol = Try(lambda: json.load(Open(self.download_path+'/.mp3_volume.json.gz')), {})
		
		# Automatically upgrade yt-dlp if using pip
		if not args.youtubedl_path:
			threading.Thread(target=self._upgrade_yt_dlp).start()

		# clean up old sessions
		self.kill_player()

		self.generate_qr_code()
		if self.use_vlc:
			self.vlcclient = vlcclient.VLCClient(port = self.vlc_port, path = self.vlc_path,
			                                     qrcode = (self.qr_code_path if self.show_overlay else None), url = self.url)
		else:
			self.omxclient = omxclient.OMXClient(path = self.omxplayer_path, adev = self.omxplayer_adev,
			                                     dual_screen = self.dual_screen, volume_offset = self.volume_offset)

		if not self.hide_splash_screen:
			self.initialize_screen(not args.windowed)
			self.render_splash_screen()

		self.cloud = args.cloud
		if args.cloud:
			self.cloud_trigger = threading.Event()
			self.cloud_tasks = []
			threading.Thread(target=self._cloud_thread).start()

	def _upgrade_yt_dlp(self):
		import pip, yt_dlp
		fn = '.yt-dlp.last-update'
		date_today = datetime.datetime.today().isoformat()[:10]
		date_last = Try(lambda: open(fn).read().strip(), '')
		if date_today == date_last:
			logging.info(f"yt-dlp is up-to-date at {date_today}")
			return

		self.upgrade_youtubedl()
		self.get_youtubedl_version()
		with open(fn, 'w') as fp:
			print(date_today, file=fp)


	def _cloud_thread(self):
		while True:
			self.cloud_trigger.wait()
			self.cloud_trigger.clear()
			if not self.running: return
			while self.cloud_tasks:
				try:
					fn = self.cloud_tasks.pop(0)
					bn, dn = os.path.basename(fn), os.path.dirname(fn)
					if os.path.isfile(f'{self.download_path}nonvocal/{bn}.m4a') and os.path.isfile(f'{self.download_path}vocal/{bn}.m4a'):
						continue
					# file: — a ':' in the song name is otherwise read as an ffmpeg protocol.
					# matroska — YouTube audio is usually opus, which CANNOT be copied into an
					# .m4a ("Could not find tag for codec opus"), so this silently produced
					# nothing and the song never got its stems. The server probes by content.
					os.system(f'ffmpeg -y -v error -i "file:{fn}" -vn -c copy -f matroska "{self.tmp_dir}/input.m4a"')
					with open(f'{self.tmp_dir}/input.m4a', 'rb') as f:
						# name: only for the admin panel's "now splitting" line
						r = requests.post(self.cloud+'/split_vocal', files={'file': f},
						                  data={'name': os.path.basename(fn)})
					with open(f'{self.tmp_dir}/output.tar.gz', 'wb') as f:
						f.write(r.content)
					with tarfile.open(f'{self.tmp_dir}/output.tar.gz') as tar:
						tar.extract('nonvocal.m4a', f'{self.download_path}nonvocal')
						os.rename(f'{self.download_path}nonvocal/nonvocal.m4a', f'{self.download_path}nonvocal/{bn}.m4a')
						tar.extract('vocal.m4a', f'{self.download_path}vocal')
						os.rename(f'{self.download_path}vocal/vocal.m4a', f'{self.download_path}vocal/{bn}.m4a')
				except:
					traceback.print_exc()


	# Other ip-getting methods are unreliable and sometimes return 127.0.0.1
	# https://stackoverflow.com/a/28950776
	def get_ip(self):
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			# doesn't even have to be reachable
			s.connect(("8.8.8.8", 1))
			IP = s.getsockname()[0]
		except Exception:
			IP = "127.0.0.1"
		finally:
			s.close()
		return IP

	def get_youtubedl_version(self):
		self.youtubedl_version = self.call_yt_dlp(['--version'], True).strip()
		return self.youtubedl_version

	def upgrade_youtubedl(self):
		logging.info("Upgrading youtube-dl, current version: %s" % self.youtubedl_version)
		if self.youtubedl_path:
			self.call_yt_dlp(['-U'])
		else:
			try:
				import pip
				# [default] keeps yt-dlp-ejs (the JS challenge solver) at the version this yt-dlp expects
				pip.main(['install', 'yt-dlp[default]', '-U'])
				cleanse_modules('yt_dlp')
				import yt_dlp
			except:
				pass
		logging.info("Done. New version: %s" % self.get_youtubedl_version())

	def is_network_connected(self):
		return not len(self.ip) < 7

	def generate_qr_code(self):
		logging.debug("Generating URL QR code")
		qr = qrcode.QRCode(version = 1, box_size = 1, border = 4, error_correction = qrcode.constants.ERROR_CORRECT_H)
		qr.add_data(self.url)
		qr.make()
		img = qr.make_image()
		self.qr_code_path = os.path.join(self.base_path, "qrcode.png")
		img.save(self.qr_code_path)

	def get_default_display_mode(self):
		if self.use_vlc:
			if self.platform == "raspberry_pi":
				# HACK apparently if display mode is fullscreen the vlc window will be at the bottom of pygame
				os.environ["SDL_VIDEO_CENTERED"] = "1"
				return pygame.NOFRAME
			else:
				return pygame.FULLSCREEN
		else:
			return pygame.FULLSCREEN

	def initialize_screen(self, fullscreen=True):
		if not self.hide_splash_screen:
			logging.debug("Initializing pygame")
			pygame.init()
			pygame.display.set_caption("pikaraoke")
			pygame.mouse.set_visible(0)
			self.fonts = {}
			self.WIDTH = pygame.display.Info().current_w
			self.HEIGHT = pygame.display.Info().current_h
			logging.debug("Initializing screen mode")

			if self.platform != "raspberry_pi":
				self.toggle_full_screen(fullscreen)
			else:
				# this section is an unbelievable nasty hack - for some reason Pygame
				# needs a keyboardinterrupt to initialise in some limited circumstances
				# source: https://stackoverflow.com/questions/17035699/pygame-requires-keyboard-interrupt-to-init-display
				class Alarm(Exception):
					pass

				def alarm_handler(signum, frame):
					raise Alarm

				signal(SIGALRM, alarm_handler)
				alarm(3)
				try:
					self.toggle_full_screen(fullscreen)
					alarm(0)
				except Alarm:
					raise KeyboardInterrupt
			logging.debug("Done initializing splash screen")

	def toggle_full_screen(self, fullscreen=None):
		if not self.hide_splash_screen:
			logging.debug("Toggling fullscreen...")
			self.full_screen = not self.full_screen if fullscreen is None else fullscreen
			if self.full_screen:
				self.screen = pygame.display.set_mode([self.WIDTH, self.HEIGHT], self.get_default_display_mode())
			else:
				self.screen = pygame.display.set_mode([self.WIDTH*3//4, self.HEIGHT*3//4], pygame.RESIZABLE)
			if self.is_file_playing():
				self.play_transposed(self.now_playing_transpose)
			else:
				self.render_splash_screen()

	def normalize(self, v):
		r = self.screen.get_width()/self.ref_W
		if type(v) is list:
			return [i*r for i in v]
		elif type(v) is tuple:
			return tuple(i * r for i in v)
		return v*r

	def render_splash_screen(self):
		"""The TV between songs. Tonight's name, or the song coming up; a tuning dial with the queue
		on it as stations; and how to join (QR + URL). Static on purpose: the TV stream stays cheap."""
		if self.hide_splash_screen:
			return
		# the run loop calls this on every pass: redraw only when something on it changed
		playing = (not self.has_video) and self.now_playing
		key = (self.screen.get_size(), playing and (self.now_playing, self.now_playing_user),
				tuple((q.get('title'), q.get('user')) for q in self.queue), self.firstSongStarted,
				len(self.available_songs), self.url, getattr(self, 'tv_url', None), self.hide_ip,
				self.streamer_alive() if not self.hide_ip else None, self.party_title())
		if key == getattr(self, '_splash_key', None) and self.is_network_connected():
			self.screen.blit(self._splash_frame, (0, 0))
			return
		self.draw_splash_screen()
		self._splash_key, self._splash_frame = key, self.screen.copy()

	def draw_splash_screen(self):
		logging.debug("Rendering splash screen")
		W, H = self.screen.get_size()
		r = W / self.ref_W
		M = 120 * r     # side margin
		self.screen.blit(self.splash_backdrop(), (0, 0))

		# top: the wordmark (or a custom --logo-path) and the library size
		if self.logo_path != self.default_logo_path:
			if not hasattr(self, 'logo'):
				self.logo = pygame.image.load(self.logo_path)
			lh = 72 * r
			lw = self.logo.get_width() * lh / self.logo.get_height()
			self.screen.blit(pygame.transform.smoothscale(self.logo, (round(lw), round(lh))), (M, 40 * r))
		else:
			pygame.draw.circle(self.screen, self.C_EYE, (M + 7 * r, 76 * r), 7 * r)
			self.splash_text(getString(136).upper(), 26, self.C_DIM, (M + 28 * r, 76 * r), track=4, anchor='midleft')
		if not self.firstSongStarted:
			self.splash_text(f"{getString(197)}: {len(self.available_songs)}", 24, self.C_FAINT,
					(W - M, 76 * r), face='barlow-500', anchor='midright')

		# the headline: what is playing (audio-only songs show this screen), what is next, or the party
		playing = (not self.has_video) and self.now_playing
		nxt = self.queue[0] if len(self.queue) else None
		if playing:
			kicker, title, singer = getString(58), self.now_playing, self.now_playing_user
		elif nxt:
			kicker, title, singer = getString(56), nxt['title'], nxt['user']
		else:
			kicker, title, singer = None, self.party_title(), None
		dial_y = H - 420 * r
		size, lines = self.splash_fit(title, [124, 108, 92, 78, 66], W - 2 * M, 2)
		def headline(y, draw):
			top = y
			if kicker:
				y = self.splash_text(kicker.strip().rstrip(':').upper(), 30, self.C_AMBER, (M, y), track=3, draw=draw).bottom + 4 * r
			for L in lines:
				y = self.splash_text(L, size, self.C_PRINT, (M, y), max_w=W - 2 * M, draw=draw).bottom - size * 0.12 * r
			if singer:
				c = self.singer_color(singer)
				rect = self.splash_text(singer, 44, c, (M + 34 * r, y + 10 * r), face='barlow-500', max_w=W - 2 * M - 34 * r, draw=draw)
				if draw:
					pygame.draw.circle(self.screen, c, (M + 10 * r, rect.centery), 10 * r)
				y = rect.bottom
			if playing and nxt:
				y = self.splash_text(f"{getString(56).strip().rstrip(':')}: {nxt['title']}  ·  {nxt['user']}", 30, self.C_DIM,
						(M, y + 18 * r), face='barlow-500', max_w=W - 2 * M, draw=draw).bottom
			return y - top
		band_top, band_bottom = 120 * r, dial_y - 40 * r
		headline(band_top + max(0, (band_bottom - band_top - headline(0, False)) / 2), True)

		# the dial: tonight's singers as stations, the needle on whoever is up
		stations = [u for u in ([self.now_playing_user] if playing else []) + [q.get('user') for q in self.queue] if u]
		self.splash_dial(M, dial_y, W - 2 * M, 104 * r, stations)

		# bottom: how to join
		if not self.hide_ip:
			if not hasattr(self, 'p_image'):
				self.p_image = pygame.image.load(self.qr_code_path)
			# whole pixels per module, so the code stays crisp and scannable
			qr, pad = max(1, round(196 * r / self.p_image.get_width())) * self.p_image.get_width(), 16 * r
			plate = pygame.Rect(M, H - 60 * r - qr - 2 * pad, qr + 2 * pad, qr + 2 * pad)
			# the light plate is the code's quiet zone, so it scans off the dark screen
			pygame.draw.rect(self.screen, (251, 243, 226), plate, border_radius=round(12 * r))
			self.screen.blit(pygame.transform.scale(self.p_image, (round(qr), round(qr))), (plate.x + pad, plate.y + pad))
			tx = plate.right + 44 * r
			if not self.is_network_connected():
				self.splash_text(getString(48), 34, self.C_PRINT, (tx, plate.centery), face='barlow-500', anchor='midleft')
				pygame.display.update()
				time.sleep(10)
				logging.info("No IP found. Network/Wifi configuration required. For wifi config, try: sudo raspi-config or the desktop GUI: startx")
				self.stop()
			else:
				max_w = W - M - tx
				y = self.splash_text(getString(49).strip(), 30, self.C_DIM, (tx, plate.top + 14 * r), face='barlow-500', max_w=max_w).bottom
				y = self.splash_text(self.url, 64, self.C_PRINT, (tx, y + 2 * r), max_w=max_w).bottom
				# Windows and Mac-OS should use screen projection and AirPlay
				if self.streamer_alive():
					# --tv-url wins; the fallback swaps the port, which only works on a host:port URL
					tv_url = getattr(self, 'tv_url', None) or (self.url.rsplit(":", 1)[0] + ":4000")
					self.splash_text(self.label(50) + tv_url, 26, self.C_FAINT, (tx, y + 12 * r), face='barlow-500', max_w=max_w)
		if not self.firstSongStarted:
			self.splash_text(getString(51), 22, self.C_FAINT, (W - M, H - 60 * r - 30 * r), face='barlow-500', anchor='bottomright')
			self.splash_text(getString(52), 22, self.C_FAINT, (W - M, H - 60 * r), face='barlow-500', anchor='bottomright')

	def splash_dial(self, x0, y0, w, h, stations):
		"""The tuning scale from the panel and the phones, drawn on the TV."""
		r = self.screen.get_width() / self.ref_W
		glass = pygame.Rect(round(x0), round(y0), round(w), round(h))
		pygame.draw.rect(self.screen, self.C_CAB, glass, border_radius=round(10 * r))
		pygame.draw.rect(self.screen, self.C_LINE, glass, width=max(1, round(2 * r)), border_radius=round(10 * r))
		step, top = 24 * r, y0 + 14 * r
		for i in range(int((w - 40 * r) // step) + 1):
			x = x0 + 20 * r + i * step
			major = i % 5 == 0
			pygame.draw.line(self.screen, self.C_FAINT if major else self.C_LINE, (x, top), (x, top + (26 if major else 12) * r), max(1, round(2 * r)))
		needle = x0 + w * 0.18
		gap = 250 * r
		for i, who in enumerate(stations):
			x = needle + i * gap
			if x > x0 + w - 60 * r:
				break
			c = self.singer_color(who)
			pygame.draw.rect(self.screen, c, pygame.Rect(round(x - 3 * r), round(top), max(2, round(6 * r)), round(36 * r)))
			self.splash_text(who, 26, c, (x + 14 * r, y0 + h - 12 * r), face='barlowcondensed-500', anchor='bottomleft', max_w=gap - 40 * r)
		# the needle overhangs the glass, like the real thing
		pygame.draw.line(self.screen, self.C_NEEDLE, (needle, y0 - 16 * r), (needle, y0 + h + 10 * r), max(2, round(4 * r)))
		pygame.draw.circle(self.screen, self.C_NEEDLE, (needle, y0 - 16 * r), 7 * r)

	def splash_backdrop(self):
		"""Walnut, warmed by a lamp up and to the right, darker at the edges. A little grain keeps the
		stream's encoder from banding the gradient. Built once per screen size."""
		size = self.screen.get_size()
		if getattr(self, '_backdrop_size', None) != size:
			W, H = size
			y, x = np.mgrid[0:H, 0:W].astype(np.float32)
			glow = np.clip(1 - np.hypot(x / W - 0.70, (y / H - 0.28) * H / W) / 0.8, 0, 1) ** 2
			vignette = np.clip(np.hypot(x / W - 0.5, y / H - 0.5) - 0.4, 0, 1) * 1.6
			base = np.array(self.C_WALNUT, np.float32)
			img = base * (1 - vignette[..., None]) + glow[..., None] * np.array([34, 19, 8], np.float32)
			img += np.random.default_rng(1).normal(0, 1.3, (H, W, 1)).astype(np.float32)
			arr = np.clip(img, 0, 255).astype(np.uint8)
			self._backdrop = pygame.surfarray.make_surface(arr.swapaxes(0, 1)).convert()
			self._backdrop_size = size
		return self._backdrop

	def party_title(self):
		"""Tonight's name: the welcome title from the panel while the welcome popup is on (emoji
		dropped, the TV fonts have none), else the app's name."""
		import unicodedata
		try:
			from panel import config as ohk_config
			mtime = os.path.getmtime(ohk_config.CONFIG_PATH) if os.path.exists(ohk_config.CONFIG_PATH) else None
			if getattr(self, '_party_mtime', 0) == mtime:
				return self._party_title
			cfg = ohk_config.load()
			t = cfg['welcome_title'] if cfg.get('welcome_enabled') else ''
		except Exception:
			mtime, t = None, ''
		t = ''.join(ch for ch in (t or '') if unicodedata.category(ch) not in ('So', 'Cf', 'Mn', 'Cs') and ch != '️')
		self._party_mtime, self._party_title = mtime, ' '.join(t.split()) or getString(136)
		return self._party_title

	def singer_color(self, name):
		"""The singer's colour, the same hash as singerColor() on the phones."""
		x = 0
		for ch in str(name or '?'):
			x = (x * 31 + ord(ch)) & 0xFFFFFFFF
		return pygame.Color(self.SINGER_COLORS[x % len(self.SINGER_COLORS)])

	@staticmethod
	def label(ii):
		"""A translated "connect at" label with a space before the URL (some translations end in "a")."""
		t = getString(ii)
		return t if not t or t[-1].isspace() else t + ' '

	def splash_font(self, face, px):
		fonts = self.__dict__.setdefault('_splash_fonts', {})
		if (face, px) not in fonts:
			path = os.path.join(self.splash_fonts_dir, face + '.woff2') if face.startswith('barlow') else f'font/{face}.ttf'
			f = pygame.freetype.Font(path, px)
			f.origin = True     # render_to() places the baseline
			fonts[(face, px)] = f
		return fonts[(face, px)]

	def splash_text(self, text, size, color, pos, face='barlowcondensed-600', track=0, anchor='topleft', max_w=None, draw=True):
		"""Draw one line of Barlow (falling back to the unicode fonts for other scripts) at a size
		given for a 1920-wide screen; `track` is letter-spacing in the same units. Long lines end
		in an ellipsis at max_w. Returns the rect drawn."""
		r = self.screen.get_width() / self.ref_W
		px = max(8, round(size * r))
		font, text = self.splash_pick(str(text), face, px)
		text = get_display(arabic_reshaper.reshape(text))
		gap = track * r
		width = lambda t: sum(m[4] for m in font.get_metrics(t) if m) + gap * max(0, len(t) - 1)
		if max_w and width(text) > max_w:
			while len(text) > 1 and width(text + '…') > max_w:
				text = text[:-1]
			text = text.rstrip() + '…'
		asc, desc = font.get_sized_ascender(), font.get_sized_descender()
		if not draw:
			return pygame.Rect(0, 0, math.ceil(width(text)), asc - desc).move(round(pos[0]), round(pos[1]))
		surf = pygame.Surface((max(1, math.ceil(width(text))), asc - desc), pygame.SRCALPHA)
		if gap:
			x = 0
			for ch in text:
				font.render_to(surf, (x, asc), ch, color)
				x += (font.get_metrics(ch)[0] or (0, 0, 0, 0, 0))[4] + gap
		else:
			font.render_to(surf, (0, asc), text, color)
		rect = surf.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
		self.screen.blit(surf, rect)
		return rect

	def splash_pick(self, text, face, px):
		"""Barlow when it has every glyph, else the first unicode font that does, else a transliteration."""
		for name in (face, 'arial-unicode-ms', 'unifont'):
			f = self.splash_font(name, px)
			if None not in f.get_metrics(text):
				return f, text
		return self.splash_font(face, px), unidecode(text)

	def splash_fit(self, text, sizes, max_w, max_lines):
		"""The biggest size at which `text` wraps into max_lines lines (the last one may end in …)."""
		r = self.screen.get_width() / self.ref_W
		words = str(text).split()
		for size in sizes:
			font, _ = self.splash_pick(str(text), 'barlowcondensed-600', max(8, round(size * r)))
			w = lambda t: sum(m[4] for m in font.get_metrics(t) if m)
			lines, cur = [], ''
			for word in words:
				if cur and w(cur + ' ' + word) > max_w:
					lines.append(cur)
					cur = word
				else:
					cur = (cur + ' ' + word).strip()
			lines.append(cur)
			if len(lines) <= max_lines:
				return size, lines
			if size == sizes[-1]:
				return size, lines[:max_lines - 1] + [' '.join(lines[max_lines - 1:])]
		return sizes[-1], [str(text)]

	def render_font(self, sizes, text, *kargs):
		if type(sizes) != list:
			sizes = [sizes]

		# normalize font size
		sizes = [s*self.screen.get_width()/self.ref_W for s in sizes]

		# initialize fonts if not found
		for size in sizes:
			if size not in self.fonts:
				self.fonts[size] = [pygame.freetype.SysFont(pygame.freetype.get_default_font(), size)] \
						+ [pygame.freetype.Font(f'font/{name}', size) for name in ['arial-unicode-ms.ttf', 'unifont.ttf']]

		# find a font that contains all characters of the song title, if cannot find, then display transliteration instead
		found = None
		for ii, font in enumerate(self.fonts[size]):
			if None not in font.get_metrics(text):
				found = ii
				break
		if found is None:
			text = unidecode(text)
			found = 0

		# reshape Arabic text
		text = get_display(arabic_reshaper.reshape(text))

		# draw the font, if too wide, half the string
		width = self.screen.get_width()
		for size in sorted(sizes, reverse = True):
			font = self.fonts[size][found]
			render = font.render(text, *kargs)
			# reduce font size if text too long
			if render[1].width > width and size != min(sizes):
				continue
			while render[1].width >= width:
				text = text[:int(len(text) * min(width / render[1].width, 0.618))] + '…'
				del render
				render = font.render(text, *kargs)
			break
		return render

	def call_yt_dlp(self, argv, get_stdout = False):
		if self.youtubedl_path:
			if get_stdout:
				return subprocess.check_output([self.youtubedl_path]+argv).decode("utf-8")
			else:
				return subprocess.call([self.youtubedl_path]+argv)
		ret_code = 0
		if get_stdout:
			old_stdout = sys.stdout
			sys.stdout = io.StringIO()
		try:
			import yt_dlp
			yt_dlp.main(argv)
		except SystemExit as e:
			ret_code = e.code
		if get_stdout:
			ret_stdout = sys.stdout
			sys.stdout = old_stdout
			return ret_stdout.getvalue()
		return ret_code

	def get_search_results(self, textToSearch):
		# Karaoke Mugen first: ready-made, hand-timed color-wipe karaoke (anime/J-pop/game/Vocaloid).
		# Downloading one of these pulls its media + .ass instead of a YouTube rip.
		km_results = []
		try:
			from lib import karamugen
			for r in karamugen.search(textToSearch.replace(' karaoke', '').strip(), 6)[:3]:
				km_results.append(['🎤 ' + karamugen.label(r) + '  [Karaoke Mugen]',
				                   'karamugen:' + r['kid'], r['kid'], sec2hhmmss(r['duration'])])
		except Exception as e:
			logging.debug("Karaoke Mugen search failed: " + str(e))

		# YouTube Music: clean official audio (no music-video intros / long silences)
		ytm_results = []
		try:
			from lib import ytmusic
			for r in ytmusic.search(textToSearch.replace(' karaoke', '').strip(), 4):
				ytm_results.append(['🎵 ' + ytmusic.label(r) + '  [YT Music · clean audio]',
				                    'https://www.youtube.com/watch?v=' + r['videoId'], r['videoId'], r['duration']])
		except Exception as e:
			logging.debug("YouTube Music search failed: " + str(e))

		logging.info("Searching YouTube for: " + textToSearch)
		num_results = 10
		yt_search = 'ytsearch%d:%s' % (num_results, textToSearch)
		cmd = ["-j", "--no-playlist", "--flat-playlist"] + self.cookies_opt + [yt_search]
		logging.debug("Youtube-dl search command: " + " ".join(cmd))
		rc = []
		try:
			output = self.call_yt_dlp(cmd, True)
			logging.debug("Search results: " + output)
			for each in output.split("\n"):
				if len(each) > 2:
					j = json.loads(each)
					if (not "title" in j) or (not "url" in j):
						continue
					rc.append([j["title"], j["url"], j["id"], sec2hhmmss(j.get("duration", 0))])
		except Exception as e:
			logging.debug("Error while executing search: " + str(e))
		return km_results + ytm_results + rc

	def get_yt_dlp_json(self, url):
		# out_json = subprocess.check_output([self.youtubedl_path, '-j', url])
		out_json = self.call_yt_dlp(['-j', url], True)
		return json.loads(out_json)

	def get_downloaded_file_basename(self, url):
		try:
			youtube_id = url.split("watch?v=")[1].split('&')[0]
		except:
			try:
				info_json = self.get_yt_dlp_json(url)
				youtube_id = info_json['id']
			except:
				logging.error("Error parsing video id from url: " + url)
				return None

		try:
			return [i for i in os.listdir(self.download_path+'tmp/') if youtube_id in i][0]
		except:
			pass

		filename = f"{info_json['title']}---{info_json['id']}.{info_json['ext']}"
		return filename if os.path.isfile(self.download_path+'tmp/'+filename) else None

	def download_video(self, client_lang='', client_ip='', song_url = '', enqueue = False, song_added_by = "Pikaraoke", include_subtitles = False, high_quality = False):
		if song_url.startswith('karamugen:'):
			return self._download_karamugen(song_url, client_lang, client_ip, enqueue, song_added_by)
		logging.info("Downloading video: " + song_url)
		getString2 = lambda ii: os.langs.get(client_lang, os.langs['en_US'])[ii]
		self.downloading_songs[song_url] = 1
		dl_path = "%(title)s---%(id)s.%(ext)s"
		opt_quality = ['-f', 'bestvideo[height<=1080]+bestaudio[abr<=160]'] if high_quality else ['-f', 'mp4+m4a']
		opt_sub = ['--sub-langs', 'all', '--embed-subs'] if include_subtitles else []
		cmd = ['--fixup', 'force', '--socket-timeout', '3', '-R', 'infinite', '--remux-video', 'mp4'] + self.cookies_opt + opt_quality +\
			["-o", self.download_path+'tmp/'+dl_path] + opt_sub + [song_url]
		logging.info("Youtube-dl command: " + " ".join(cmd))
		rc = self.call_yt_dlp(cmd)
		if rc != 0:
			logging.error("Error code while downloading, retrying without format options ...")
			cmd = ['--fixup', 'force', '--socket-timeout', '3', '-R', 'infinite', '--remux-video', 'mp4'] + self.cookies_opt + \
				["-o", self.download_path + 'tmp/' + dl_path] + opt_sub + [song_url]
			logging.debug("Youtube-dl command: " + " ".join(cmd))
			rc = self.call_yt_dlp(cmd)
		if rc == 0:
			logging.debug("Song successfully downloaded: " + song_url)
			self.downloading_songs[song_url] = 0
			bn = self.get_downloaded_file_basename(song_url)
			if bn:
				shutil.move(self.download_path+'tmp/'+bn, self.download_path+bn)
				self.get_available_songs()
				song_path = self.download_path + bn
				generating = self._autogen_karaoke(song_path)
				if generating and enqueue:
					# Defer the enqueue until the color-wipe .ass is ready, so the song never
					# reaches the queue (and gets played) without its karaoke subtitles.
					self.downloading_songs[song_url] = '00'
					flash(getString2(189) + ' — generating karaoke…', client_ip = client_ip)
					ws_send(client_ip, 'download_ended()')
					ass = os.path.splitext(song_path)[0] + '.ass'
					for _ in range(180):                       # wait up to ~3 min for the .ass
						if os.path.isfile(ass) or not getattr(self, 'running', True):
							break
						time.sleep(1)
					self.enqueue(song_path, song_added_by)
					flash('🎤 Karaoke ready — added to queue!' if os.path.isfile(ass)
					      else getString2(189) + ' ' + getString2(191), client_ip = client_ip)
					return
				if enqueue:
					self.enqueue(song_path, song_added_by)
					self.downloading_songs[song_url] = '00'
					flash(getString2(189)+' '+getString2(191), client_ip = client_ip)
				else:
					flash(getString2(189), client_ip = client_ip)
			else:
				logging.error("Error queueing song: " + song_url)
				self.downloading_songs[song_url] = '01'
				flash(getString2(189)+' '+getString2(192), client_ip = client_ip)
		else:
			logging.error("Error downloading song: " + song_url)
			self.downloading_songs[song_url] = -1
			flash(getString2(190), client_ip = client_ip)
		return ws_send(client_ip, 'download_ended()')

	def _autogen_karaoke(self, media_path):
		# Ask the cloud (asr_server) to auto-generate a color-wipe <base>.ass for a freshly
		# downloaded song. Returns True if generation was kicked off (so callers can wait for it).
		if not self.cloud or os.path.isfile(os.path.splitext(media_path)[0] + '.ass'):
			return False
		if urlparse(self.cloud).hostname not in ('localhost', '127.0.0.1', '::1', None):
			return self._autogen_karaoke_remote(media_path)     # server can't see our disk
		try:
			requests.post(self.cloud + '/make_karaoke', data = {'path': media_path}, timeout = 5)
			logging.info("Requested auto color-wipe for: " + os.path.basename(media_path))
			return True
		except Exception as e:
			logging.debug("Karaoke auto-gen request failed: " + str(e))
			return False

	def _autogen_karaoke_remote(self, media_path):
		"""Split deployment (app here, GPU box elsewhere): upload the song's audio, then poll
		for the color-wipe .ass and the vocal/nonvocal stems and drop them into our library.
		Runs in a thread; the caller's wait-for-.ass loop picks the result up off the disk."""
		def work():
			tmp = tempfile.mkdtemp(prefix = 'ohk_up_')
			try:
				base = os.path.basename(media_path)
				audio = os.path.join(tmp, base + '.m4a')
				# audio only: ~1.5 MB for a 4-minute song, vs ~50 MB for the video
				subprocess.call(['ffmpeg', '-y', '-v', 'error', '-i', 'file:' + media_path,
				                 '-vn', '-c', 'copy', '-f', 'matroska', audio])
				if not os.path.isfile(audio):
					return
				with open(audio, 'rb') as f:
					r = requests.post(self.cloud + '/make_karaoke',
					                  files = {'file': f}, data = {'name': base}, timeout = 180)
				job = r.json().get('job') if r.status_code == 200 else None
				if not job:
					return
				for _ in range(600):              # GPU-bound, and queued behind other songs
					time.sleep(2)
					g = requests.get(f'{self.cloud}/karaoke_result/{job}', timeout = 60)
					if g.status_code == 202:
						continue
					if g.status_code != 200:
						return logging.info("Remote karaoke failed for: " + base)
					open(f'{tmp}/out.tar.gz', 'wb').write(g.content)
					self._unpack_karaoke(f'{tmp}/out.tar.gz', media_path)
					return logging.info("Remote color-wipe ready for: " + base)
			except Exception as e:
				logging.debug("Remote karaoke generation failed: " + str(e))
			finally:
				shutil.rmtree(tmp, ignore_errors = True)

		threading.Thread(target = work, daemon = True).start()
		logging.info("Uploading for remote color-wipe: " + os.path.basename(media_path))
		return True

	def _unpack_karaoke(self, targz, media_path):
		"""Install a remote job's results into our library."""
		base = os.path.basename(media_path)
		d = os.path.dirname(media_path) or '.'
		with tarfile.open(targz) as tar:
			names = tar.getnames()
			for stem in ('vocal', 'nonvocal'):
				if f'{stem}.m4a' in names:
					sd = f'{self.download_path}{stem}'
					os.makedirs(sd, exist_ok = True)
					tar.extract(f'{stem}.m4a', sd)
					os.replace(f'{sd}/{stem}.m4a', f'{sd}/{base}.m4a')
			if 'karaoke.ass' in names:
				# extract beside the media, then rename: the enqueue loop polls for this file,
				# so it must appear complete (same filesystem => atomic replace)
				tar.extract('karaoke.ass', d)
				os.replace(f'{d}/karaoke.ass', os.path.splitext(media_path)[0] + '.ass')

	def _download_karamugen(self, song_url, client_lang, client_ip, enqueue, song_added_by):
		# Pull a ready-made karaoke (media + hand-timed color-wipe .ass) from Karaoke Mugen.
		from lib import karamugen
		getString2 = lambda ii: os.langs.get(client_lang, os.langs['en_US'])[ii]
		kid = song_url.split(':', 1)[1]
		logging.info("Downloading from Karaoke Mugen: " + kid)
		self.downloading_songs[song_url] = 1
		try:
			r = karamugen.get(kid)
			title = (r['series'] + ' - ' if r['series'] else '') + (r['title'] or kid)
			if r['types']:
				title += ' [' + '/'.join(r['types']) + ']'
			name = ''.join('_' if c in '/\\\n\r\t' else c for c in title).strip() + '---' + kid
			tmp = self.download_path + 'tmp'
			os.makedirs(tmp, exist_ok = True)
			media_tmp, ass_tmp = karamugen.download(r, tmp, name)
			media_bn = os.path.basename(media_tmp)
			shutil.move(media_tmp, self.download_path + media_bn)
			shutil.move(ass_tmp, self.download_path + os.path.basename(ass_tmp))
			self.downloading_songs[song_url] = 0
			self.get_available_songs()
			if enqueue:
				self.enqueue(self.download_path + media_bn, song_added_by)
				self.downloading_songs[song_url] = '00'
				flash(getString2(189) + ' ' + getString2(191), client_ip = client_ip)
			else:
				flash(getString2(189), client_ip = client_ip)
		except Exception as e:
			logging.error("Karaoke Mugen download failed: " + str(e))
			traceback.print_exc()
			self.downloading_songs[song_url] = -1
			flash(getString2(190), client_ip = client_ip)
		return ws_send(client_ip, 'download_ended()')

	def get_available_songs(self):
		logging.info("Fetching available songs in: " + self.download_path)
		files_grabbed = []
		self.songname_trans = {}
		for bn in os.listdir(self.download_path):
			fn = self.download_path + bn
			if not bn.startswith('.') and os.path.isfile(fn):
				if os.path.splitext(fn)[1].lower() in media_types:
					files_grabbed.append(fn)
					trans = unidecode(self.filename_from_path(fn)).lower()
					# strip leading non-transliterable symbols
					while trans and not trans[0].islower() and not trans[0].isdigit():
						trans = trans[1:]
					self.songname_trans[fn] = trans

		# self.available_songs = sorted(files_grabbed, key = lambda f: str.lower(os.path.basename(f)))
		self.available_songs = sorted(self.songname_trans, key = self.songname_trans.get)

	def get_all_assoc_files(self, song_path):
		basename = os.path.basename(song_path)
		basestem = os.path.splitext(basename)
		files = [self.download_path + basename,
				self.download_path + basestem[0] + '.cdg',
				self.download_path + 'nonvocal/' + basename + '.m4a',
				self.download_path + 'nonvocal/.' + basename + '.m4a',
				self.download_path + 'vocal/' + basename + '.m4a',
				self.download_path + 'vocal/.' + basename + '.m4a']
		# Subtitle sidecars (color-wipe .ass, romaji, lyrics) go with the song too, or deleting
		# and renaming leaves them orphaned. They belong to the STEM, though, which a second
		# download of the same song in another format can share: then leave them to that one.
		# Appended last so rename()'s zip(old, new) pairing of the lists above is unaffected.
		if not any(os.path.isfile(self.download_path + basestem[0] + e) for e in media_types if e != basestem[1]):
			files += [self.download_path + basestem[0] + e for e in ('.ass', '.ssa', '.romaji.srt', '.srt', '.vtt', '.lrc')]
		return files

	def delete_if_exist(self, filename):
		if os.path.isfile(filename):
			try:
				os.remove(filename)
			except:
				pass

	def delete(self, song_path):
		logging.info("Deleting song: " + song_path)

		# delete all associated cdg/vocal/nonvocal files if exist
		for fn in self.get_all_assoc_files(song_path):
			self.delete_if_exist(fn)

		self.get_available_songs()

	def rename_if_exist(self, old_path, new_path):
		if os.path.isfile(old_path):
			try:
				shutil.move(old_path, new_path)
			except:
				pass

	def rename(self, song_path, new_basestem):
		logging.info("Renaming song: '" + song_path + "' to: " + new_basestem)
		ext = os.path.splitext(song_path)
		if len(ext) < 2:
			ext += ['']
		new_basename = new_basestem + ext[1]

		# can handle the case while the file is being processed by vocal splitter, it has been renamed multiple times
		old_basename = os.path.basename(song_path)
		self.rename_history[old_basename] = new_basename
		for k, v in self.rename_history.items():
			if v == old_basename:
				self.rename_history[k] = new_basename

		# rename all associated cdg/vocal/nonvocal files if exist
		for src, tgt in zip(self.get_all_assoc_files(song_path), self.get_all_assoc_files(new_basename)):
			self.rename_if_exist(src, tgt)

		# rename queue entry if inside queue
		for item in self.queue:
			if item['file'] == song_path:
				item['file'] = self.download_path + new_basename
				item['title'] = self.filename_from_path(item['file'])
				break

		self.get_available_songs()

	def filename_from_path(self, file_path):
		rc = os.path.basename(file_path)
		rc = os.path.splitext(rc)[0]
		rc = rc.split("---")[0]  # removes youtube id if present
		return rc

	def kill_player(self):
		if self.use_vlc:
			logging.debug("Killing old VLC processes")
			if self.vlcclient != None:
				self.vlcclient.kill()
		elif self.omxclient != None:
				self.omxclient.kill()

	def play_file(self, file_path, extra_params = []):
		self.switchingSong = True
		if self.use_vlc:
			if self.save_delays:
				saved_delays = self.delays.get(os.path.basename(file_path), {})
				self.audio_delay = self.audio_delay if self.audio_delay else saved_delays.get('audio_delay', 0)
				self.subtitle_delay = self.subtitle_delay if self.subtitle_delay else saved_delays.get('subtitle_delay', 0)
				self.show_subtitle = False if self.show_subtitle==False else saved_delays.get('show_subtitle', True)
			extra_params1 = []
			logging.info("Playing video in VLC: " + file_path)
			if self.platform != 'osx':
				extra_params1 += ['--drawable-hwnd' if self.platform == 'windows' else '--drawable-xid',
				                  hex(pygame.display.get_wm_info()['window'])]
			self.now_playing_slave = self.try_set_vocal_mode(self.vocal_mode, file_path)
			if os.path.isfile(self.now_playing_slave):
				extra_params1 += [f'--input-slave={self.now_playing_slave}', '--audio-track=1']
			if self.audio_delay:
				extra_params1 += [f'--audio-desync={self.audio_delay * 1000}']
			if self.subtitle_delay:
				extra_params1 += [f'--sub-delay={self.subtitle_delay * 10}']
			if self.show_subtitle:
				# Prefer an external subtitle next to the media, in priority order:
				#   <base>.ass        -> syllable color-wipe karaoke (Karaoke Mugen / make-karaoke.py)
				#   <base>.romaji.srt -> romanized Japanese (romanize_subs.py)
				#   embedded track 0  -> whatever shipped in the video
				stem = os.path.splitext(file_path)[0]
				ext_sub = next((stem + e for e in ('.ass', '.romaji.srt') if os.path.isfile(stem + e)), None)
				if ext_sub:
					extra_params1 += [f'--sub-file={ext_sub}']
				else:
					extra_params1 += ['--sub-track=0']
			if self.play_speed != 1:
				extra_params1 += [f'--rate={self.play_speed}']
			self.now_playing = self.filename_from_path(file_path)
			self.now_playing_filename = file_path
			self.is_paused = ('--start-paused' in extra_params1)
			if self.normalize_vol and self.logical_volume is not None:
				self.volume = self.logical_volume / np.sqrt(self.get_mp3_volume(file_path))
			if self.now_playing_transpose == 0:
				xml = self.vlcclient.play_file(file_path, self.volume, extra_params + extra_params1)
			else:
				xml = self.vlcclient.play_file_transpose(file_path, self.now_playing_transpose, self.volume, extra_params + extra_params1)
			self.has_subtitle = "<info name='Type'>Subtitle</info>" in xml
			self.has_video = "<info name='Type'>Video</info>" in xml
			self.volume = round(float(self.vlcclient.get_val_xml(xml, 'volume')))
			if self.normalize_vol:
				self.media_vol = self.get_mp3_volume(self.now_playing_filename)
				self.logical_volume = self.volume * np.sqrt(self.media_vol)
		else:
			logging.info("Playing video in omxplayer: " + file_path)
			self.omxclient.play_file(file_path)

		self.switchingSong = False
		self.status_dirty = True
		self.render_splash_screen()  # remove old previous track

	def play_transposed(self, semitones):
		if self.use_vlc:
			self.now_playing_transpose = semitones
			status_xml = self.vlcclient.command().text if self.is_paused else self.vlcclient.pause(False).text
			info = self.vlcclient.get_info_xml(status_xml)
			posi = info['position']*info['length']
			self.play_file(self.now_playing_filename, [f'--start-time={posi}'] + (['--start-paused'] if self.is_paused else []))
		else:
			logging.error("Not using VLC. Can't transpose track.")

	def is_file_playing(self):
		client = self.vlcclient if self.use_vlc else self.omxclient
		if client is not None and client.is_running():
			return True
		elif self.now_playing_filename:
			self.now_playing = self.now_playing_filename = None
		return False

	def is_song_in_queue(self, song_path):
		return song_path in map(lambda t: t['file'], self.queue)

	def enqueue(self, song_path, user = "Pikaraoke"):
		if (self.is_song_in_queue(song_path)):
			logging.warn("Song is already in queue, will not add: " + song_path)
			return False
		else:
			logging.info("'%s' is adding song to queue: %s" % (user, song_path))
			self.queue.append({"user": user, "file": song_path, "title": self.filename_from_path(song_path)})
			self.update_queue()
			return True

	def queue_add_random(self, amount):
		logging.info("Adding %d random songs to queue" % amount)
		songs = list(self.available_songs)  # make a copy
		if len(songs) == 0:
			logging.warn("No available songs!")
			return False
		i = 0
		while i < amount:
			r = random.randint(0, len(songs) - 1)
			if self.is_song_in_queue(songs[r]):
				logging.warn("Song already in queue, trying another... " + songs[r])
			else:
				self.queue.append({"user": "Random", "file": songs[r], "title": self.filename_from_path(songs[r])})
				i += 1
			songs.pop(r)
			if len(songs) == 0:
				self.update_queue()
				logging.warn("Ran out of songs!")
				return False
		self.update_queue()
		return True

	def update_queue(self):
		self.queue_json = json.dumps(self.queue)
		self.status_dirty = True

	def queue_clear(self):
		logging.info("Clearing queue!")
		self.queue = []
		self.update_queue()
		self.skip()

	def queue_edit(self, song_file, action, **kwargs):
		if action == "move":
			try:
				src, tgt, size = [int(kwargs[n]) for n in ['src', 'tgt', 'size']]
				if size > len(self.queue):
					# new songs have started while dragging the list
					diff = size - len(self.queue)
					src -= diff
					tgt -= diff
				song = self.queue.pop(src)
				self.queue.insert(tgt, song)
			except:
				logging.error("Invalid move song request: " + str(kwargs))
				return False
		else:
			match = [(ii,each) for ii,each in enumerate(self.queue) if song_file in each["file"]]
			index, song = match[0] if match else (-1, None)
			if song == None:
				logging.error("Song not found in queue: " + song["file"])
				return False
			if action == "up":
				if index < 1:
					logging.warn("Song is up next, can't bump up in queue: " + song["file"])
					return False
				else:
					logging.info("Bumping song up in queue: " + song["file"])
					del self.queue[index]
					self.queue.insert(index - 1, song)
			elif action == "down":
				if index == len(self.queue) - 1:
					logging.warn("Song is already last, can't bump down in queue: " + song["file"])
					return False
				else:
					logging.info("Bumping song down in queue: " + song["file"])
					del self.queue[index]
					self.queue.insert(index + 1, song)
			elif action == "delete":
				logging.info("Deleting song from queue: " + song["file"])
				del self.queue[index]
			else:
				logging.error("Unrecognized direction: " + action)
				return False
		self.update_queue()
		return True

	def skip(self):
		if self.is_file_playing():
			logging.info("Skipping: " + self.now_playing)
			if self.use_vlc:
				self.vlcclient.stop()
			else:
				self.omxclient.stop()
			self.reset_now_playing()
			return True
		logging.warning("Tried to skip, but no file is playing!")
		return False

	def seek(self, seek_sec):
		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.seek(seek_sec)
			else:
				logging.warning("OMXplayer cannot seek track!")
			return True
		logging.warning("Tried to seek, but no file is playing!")
		return False

	def set_delays_dict(self, filename, key, val, dft_val=0):
		basename = os.path.basename(filename)
		delays = self.delays.get(basename, {})
		if val == dft_val:
			delays.pop(key, None)
		else:
			delays[key] = val
		if delays:
			self.delays[basename] = delays
		else:
			self.delays.pop(basename, {})
		self.delays_dirty = True

	def set_audio_delay(self, delay):
		if delay == '+':
			self.audio_delay += 0.1
		elif delay == '-':
			self.audio_delay -= 0.1
		elif delay == '':
			self.audio_delay = 0
		else:
			try:
				self.audio_delay = float(delay)
			except:
				logging.warning(f"Tried to set audio delay to an invalid value {delay}, ignored!")
				return False

		if self.save_delays:
			self.set_delays_dict(self.now_playing_filename, 'audio_delay', self.audio_delay)

		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.command(f"audiodelay&val={self.audio_delay}")
			else:
				logging.warning("OMXplayer cannot set audio delay!")
			self.status_dirty = True
			return self.audio_delay
		logging.warning("Tried to set audio delay, but no file is playing!")
		return False

	def set_subtitle_delay(self, delay):
		if delay == '+':
			self.subtitle_delay += 0.1
		elif delay == '-':
			self.subtitle_delay -= 0.1
		elif delay == '':
			self.subtitle_delay = 0
		else:
			try:
				self.subtitle_delay = float(delay)
			except:
				logging.warning(f"Tried to set subtitle delay to an invalid value {delay}, ignored!")
				return False

		if self.save_delays:
			self.set_delays_dict(self.now_playing_filename, 'subtitle_delay', self.subtitle_delay)

		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.command(f"subdelay&val={self.subtitle_delay}")
			else:
				logging.warning("OMXplayer cannot set subtitle delay!")
			self.status_dirty = True
			return self.subtitle_delay
		logging.warning("Tried to set subtitle delay, but no file is playing!")
		return False

	def toggle_subtitle(self):
		self.show_subtitle = not self.show_subtitle
		if self.save_delays:
			self.set_delays_dict(self.now_playing_filename, 'show_subtitle', self.show_subtitle, True)
		self.play_vocal(force=True)

	def pause(self):
		if self.is_file_playing():
			logging.info("Toggling pause: " + self.now_playing)
			if self.use_vlc:
				if self.vlcclient.is_playing():
					self.vlcclient.pause()
					self.is_paused = True
				else:
					self.vlcclient.play()
					self.is_paused = False
			else:
				if self.omxclient.is_playing():
					self.omxclient.pause()
					self.is_paused = True
				else:
					self.omxclient.play()
					self.is_paused = False
			self.status_dirty = True
			return True
		else:
			logging.warning("Tried to pause, but no file is playing!")
			return False

	def vol_up(self):
		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.vol_up()
				xml = self.vlcclient.command().text
				self.volume = int(self.vlcclient.get_val_xml(xml, 'volume'))
			else:
				self.volume = self.omxclient.vol_up()
			self.update_logical_vol()
			return self.volume
		else:
			logging.warning("Tried to volume up, but no file is playing!")
			return False

	def vol_down(self):
		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.vol_down()
				xml = self.vlcclient.command().text
				self.volume = int(self.vlcclient.get_val_xml(xml, 'volume'))
			else:
				self.volume = self.omxclient.vol_down()
			self.update_logical_vol()
			return self.volume
		else:
			logging.warning("Tried to volume down, but no file is playing!")
			return False

	def vol_set(self, volume):
		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.vol_set(volume)
				xml = self.vlcclient.command().text
				self.volume = int(self.vlcclient.get_val_xml(xml, 'volume'))
			else:
				logging.warning("Only VLC player can set volume, ignored!")
				self.volume = self.omxclient.volume_offset
			self.update_logical_vol()
			return self.volume
		else:
			logging.warning("Tried to set volume, but no file is playing!")
			return False

	def play_speed_set(self, speed):
		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.playspeed_set(speed)
				xml = self.vlcclient.command().text
				self.play_speed = float(self.vlcclient.get_val_xml(xml, 'rate'))
				logging.info(f"Playback speed set to {self.play_speed}")
			else:
				logging.warning("Only VLC player can set playback speed, ignored!")
			return self.play_speed
		else:
			logging.warning("Tried to set play speed, but no file is playing!")
			return False

	def try_set_vocal_mode(self, mode, now_playing_filename):
		if mode not in ['mixed', 'vocal', 'nonvocal']:
			mode = {1: 'nonvocal', 2: 'mixed', 3: 'vocal'}[self.get_vocal_mode()]
		play_slave = '' if mode == 'mixed' else self.download_path + mode + '/' + ('' if self.use_DNN_vocal else '.') \
		                                       + os.path.basename(now_playing_filename) + '.m4a'
		if os.path.isfile(play_slave):
			self.vocal_mode = mode
		else:
			play_slave = ''
			self.vocal_mode = 'mixed'
		return play_slave

	def play_vocal(self, mode = None, force = False):
		# mode=vocal/nonvocal/mixed, or else (use current)
		if self.use_vlc:
			play_slave = self.try_set_vocal_mode(mode, self.now_playing_filename)
			if not force and self.now_playing_slave == play_slave:
				return
			status_xml = self.vlcclient.command().text if self.is_paused else self.vlcclient.pause(False).text
			info = self.vlcclient.get_info_xml(status_xml)
			posi = info['position']*info['length']
			self.play_file(self.now_playing_filename, [f'--start-time={posi}'] + (['--start-paused'] if self.is_paused else []))
			self.get_vocal_info(True)
		else:
			logging.error("Not using VLC. Can't play vocal/nonvocal.")

	def get_vocal_mode(self):
		if '/nonvocal/' in self.now_playing_slave.replace('\\', '/'):
			return 1
		elif '/vocal/' in self.now_playing_slave.replace('\\', '/'):
			return 3
		return 2

	def get_vocal_info(self, force_update=False):
		tm = time.time()
		if not force_update and tm-self.last_vocal_time < 2:
			return self.last_vocal_info
		if not self.now_playing_filename:
			return 0
		mask = 0
		bn = os.path.basename(self.now_playing_filename)
		if os.path.isfile(f'{self.download_path}nonvocal/{bn}.m4a'):
			mask |= 0b00000001
		if os.path.isfile(f'{self.download_path}vocal/{bn}.m4a'):
			mask |= 0b00000010
		if os.path.isfile(f'{self.download_path}nonvocal/.{bn}.m4a'):
			mask |= 0b00000100
		if os.path.isfile(f'{self.download_path}vocal/.{bn}.m4a'):
			mask |= 0b00001000
		if 'vocal/.' in self.now_playing_slave:
			mask |= 0b10000000
		if self.use_DNN_vocal:
			mask |= 0b01000000
		mask |= (self.get_vocal_mode() << 4)
		self.last_vocal_info = mask
		self.last_vocal_time = tm
		return mask

	def get_state(self):
		if self.use_vlc and self.vlcclient.is_transposing:
			return defaultdict(lambda: None, self.player_state)
		if not self.is_file_playing():
			self.player_state['now_playing'] = None
			return defaultdict(lambda: None, self.player_state)
		new_state = self.vlcclient.get_info_xml() if self.use_vlc else {
			'volume': self.omxclient.volume_offset,
			'state': ('paused' if self.omxclient.paused else 'playing')
		}
		self.player_state.update(new_state)
		return defaultdict(lambda: None, self.player_state)

	def restart(self):
		if self.is_file_playing():
			if self.use_vlc:
				self.vlcclient.restart()
			else:
				self.omxclient.restart()
			self.is_paused = False
			return True
		else:
			logging.warning("Tried to restart, but no file is playing!")
			return False

	def stop(self):
		self.running = False

	def handle_run_loop(self):
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				logging.warn("Window closed: Exiting pikaraoke...")
				self.running = False
			elif event.type == pygame.KEYDOWN:
				if event.key == pygame.K_ESCAPE:
					logging.warn("ESC pressed: Exiting pikaraoke...")
					self.running = False
				if event.key == pygame.K_f:
					self.toggle_full_screen()
		if not self.is_file_playing() or not self.has_video:
			self.render_splash_screen()
			pygame.display.update()
		pygame.time.wait(100)

	# Use this to reset the screen in case it loses focus
	# This seems to occur in windows after playing a video
	def pygame_reset_screen(self):
		if not self.hide_splash_screen:
			logging.debug("Resetting pygame screen...")
			pygame.display.quit()
			self.initialize_screen()
			self.render_splash_screen()

	def reset_now_playing(self):
		self.auto_save_delays()
		self.now_playing = None
		self.now_playing_filename = None
		self.now_playing_user = None
		self.is_paused = True
		self.now_playing_transpose = 0
		self.now_playing_slave = ''
		self.audio_delay = 0
		self.subtitle_delay = 0
		self.show_subtitle = True
		self.has_subtitle = False
		self.has_video = True
		self.last_vocal_info = 0
		self.play_speed = 1

	def streamer_alive(self):
		try:
			return bool([1 for p in psutil.process_iter() if './screencapture.sh' in p.cmdline()])
		except:
			return None

	def streamer_restart(self, delay=0):
		if self.platform in ['windows', 'osx']:
			return
		os.system(f"sleep {delay} && tmux send-keys -t PiKaraoke:0.3 C-c && tmux send-keys -t PiKaraoke:0.3 Up Enter")

	def streamer_stop(self, delay=0):
		if self.platform in ['windows', 'osx']:
			return
		os.system(f"sleep {delay} && tmux send-keys -t PiKaraoke:0.3 C-c")

	def vocal_coverage(self):
		"""(songs with BOTH stems, total songs). Both are needed before the
		MUSIC | MIXED | VOICE toggle lights up for a song."""
		try:
			n = 0
			for f in self.available_songs:
				bn = os.path.basename(f)
				if os.path.isfile(f'{self.download_path}nonvocal/{bn}.m4a') \
				   and os.path.isfile(f'{self.download_path}vocal/{bn}.m4a'):
					n += 1
			return n, len(self.available_songs)
		except:
			return 0, 0

	def vocal_alive(self):
		try:
			return bool(self.vocal_process and self.vocal_process.is_alive())\
					or bool([1 for p in psutil.process_iter() if 'vocal_splitter.py' in p.cmdline()])
		except:
			return None

	def vocal_restart(self):
		if self.platform == 'windows' or self.run_vocal:
			import vocal_splitter
			if self.vocal_process is not None and self.vocal_process.is_alive():
				self.vocal_process.kill()
			if shutil.which('ffmpeg'):
				self.vocal_process = mp.Process(target=vocal_splitter.main, args=(['-p', '-d', self.download_path],))
				self.vocal_process.start()
		else:
			os.system(f"tmux send-keys -t PiKaraoke:0.4 C-c && tmux send-keys -t PiKaraoke:0.4 Up Enter")

	def vocal_stop(self):
		if self.vocal_process is not None and self.vocal_process.is_alive():
			self.vocal_process.kill()
		elif self.platform != 'windows':
			os.system(f"tmux send-keys -t PiKaraoke:0.4 C-c")

	def get_mp3_volume(self, filename):
		try:
			basename, md5, fsize = os.path.basename(filename), md5sum(filename), os.stat(filename).st_size
			vol_fsize_md5 = self.song2vol.get(basename, [0]*3)
			if fsize == vol_fsize_md5[1] and md5 == vol_fsize_md5[2]:
				return vol_fsize_md5[0]
			pcm_data = subprocess.check_output(['ffmpeg', '-i', 'file:' + filename, '-vn', '-f', 's16le', '-acodec', 'pcm_s16le', '-'], stderr = subprocess.DEVNULL)
			volume_val = np.clip(np.sqrt(np.std(np.frombuffer(pcm_data, dtype = np.int16))/STD_VOL), 1/16, 16)
			self.song2vol[basename] = [volume_val, fsize, md5]
			with Open(self.download_path+'/.mp3_volume.json.gz', 'wb') as fp:
				json.dump(self.song2vol, fp, indent=1)
			return volume_val
		except:
			self.normalize_vol = False
			return 1

	def update_logical_vol(self):
		if hasattr(self, 'media_vol'):
			self.logical_volume = self.volume * self.media_vol

	def enable_vol_norm(self, enable):
		self.normalize_vol = enable
		if enable and shutil.which('ffmpeg') is None:
			self.normalize_vol = enable = False
		if enable and self.now_playing_filename:
			self.volume = self.vlcclient.get_info_xml()['volume']
			self.media_vol = self.get_mp3_volume(self.now_playing_filename)
			self.update_logical_vol()
		return str(self.logical_volume)

	def init_save_delays(self):
		self.delays_dirty = False
		try:
			self.delays = eval(open(self.save_delays).read())
		except:
			self.delays = {}
			with open(self.save_delays, 'w') as fp:
				fp.write(str(self.delays))

	def set_save_delays(self, state):
		if state != bool(self.save_delays):
			if state:
				self.save_delays = self.dft_delays_file
				self.init_save_delays()
			else:
				self.save_delays = None
				self.delete_if_exist(self.dft_delays_file)

	def auto_save_delays(self):
		if self.save_delays and self.delays_dirty:
			self.delays_dirty = False
			with open(self.save_delays, 'w') as fp:
				fp.write(str(self.delays))

	def run(self):
		logging.info("Starting PiKaraoke!")
		self.running = True

		# Windows does not have tmux, vocal splitter can only be invoked from the main program
		if self.platform == 'windows' or self.run_vocal:
			Try(lambda: self.vocal_restart())

		while self.running:
			try:
				if not self.is_file_playing() and self.now_playing != None:
					self.reset_now_playing()
				if self.queue:
					if not self.is_file_playing():
						self.reset_now_playing()
						self.render_splash_screen()
						tm = time.time()
						while time.time()-tm < self.splash_delay:
							self.handle_run_loop()
						head = self.queue.pop(0)
						self.play_file(head['file'])
						if self.cloud:
							self.cloud_tasks += [head['file']]
							self.cloud_trigger.set()
						if not self.firstSongStarted:
							if self.streamer_alive():
								self.streamer_restart(1)
							self.firstSongStarted = True
						self.now_playing_user = head["user"]
						self.update_queue()
				self.handle_run_loop()
			except KeyboardInterrupt:
				logging.warn("Keyboard interrupt: Exiting pikaraoke...")
				self.running = False

		# Clean up before quit
		self.streamer_stop()
		self.vocal_stop()
		vplayer = self.vlcclient if self.use_vlc else self.omxclient
		if vplayer is not None: vplayer.stop()
		self.auto_save_delays()
		time.sleep(1)
		if vplayer is not None: vplayer.kill()
