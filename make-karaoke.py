#!/usr/bin/env python3
# Auto-generate a word color-wipe karaoke subtitle (<basename>.ass) for any song that isn't
# in Karaoke Mugen (e.g. English pop). Runs Whisper WORD-timestamps on the ISOLATED VOCAL
# track (GPU/ROCm via the same torch as the app) — real per-word durations, so held notes
# come through. The app prefers <basename>.ass and VLC/libass renders the \kf wipe.
#
# Usage:
#   ./make-karaoke.py [-m MODEL] [-l LANG] [-f] <media_file> [<media_file> ...]
#   ./make-karaoke.py ~/pikaraoke-songs          # every song in a folder (skips ones with a .ass)
#   ./make-karaoke.py -l en song.mp4             # force English
#
# MODEL: tiny|base|small|medium|large-v3 (default medium). LANG: e.g. en, ja (default: auto).

import os, sys, argparse
from lib.karaoke_ass import segments_to_ass
from lib import forced_align


def find_vocal(media):
	# the DNN splitter writes vocal/<full-filename>.m4a (extension included)
	d = os.path.dirname(os.path.abspath(media))
	cand = os.path.join(d, 'vocal', os.path.basename(media) + '.m4a')
	return cand if os.path.isfile(cand) else media


def main(argv):
	ap = argparse.ArgumentParser()
	ap.add_argument('-m', '--model', default='medium')
	ap.add_argument('-l', '--lang', default=None, help='language code (default: auto-detect)')
	ap.add_argument('-f', '--force', action='store_true', help='regenerate even if a .ass already exists')
	ap.add_argument('paths', nargs='+')
	a = ap.parse_args(argv)

	media_ext = ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4a', '.mp3')
	targets = []
	for p in a.paths:
		if os.path.isdir(p):
			targets += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith(media_ext)]
		elif os.path.isfile(p):
			targets.append(p)
	if not a.force:
		kept = [t for t in targets if not os.path.isfile(os.path.splitext(t)[0] + '.ass')]
		if len(kept) < len(targets):
			print(f"skipping {len(targets) - len(kept)} song(s) that already have a .ass (use -f to redo)")
		targets = kept
	if not targets:
		print("nothing to do"); return 0

	import torch, whisper
	dev = 'cuda' if torch.cuda.is_available() else 'cpu'
	print(f"loading Whisper '{a.model}' on {dev} ...", flush=True)
	model = whisper.load_model(a.model, device=dev)

	for media in targets:
		audio = find_vocal(media)
		tag = "vocal track" if audio != media else "media audio"
		print(f"generating karaoke for '{os.path.basename(media)}' ({tag}) ...", flush=True)
		segs, method = forced_align.make_segments(media, audio, model, dev, a.lang)
		dst = os.path.splitext(media)[0] + '.ass'
		open(dst, 'w', encoding='utf-8').write(segments_to_ass(segs))
		print(f"  wrote {os.path.basename(dst)}  [{method}]", flush=True)
	return 0


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
