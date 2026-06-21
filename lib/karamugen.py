# Minimal Karaoke Mugen (kara.moe) client: search + download professionally hand-timed
# karaoke (media + ASS with per-syllable \k color-wipe). Used by OHK to offer ready-made
# karaoke for anime/J-pop/game/Vocaloid songs in the web search, instead of YouTube.
import os, json, urllib.request, urllib.parse

API = "https://kara.moe/api"
DL  = "https://kara.moe/downloads"
_HDRS = {"User-Agent": "OpenHomeKaraoke"}


def _get_json(url):
	req = urllib.request.Request(url, headers=_HDRS)
	with urllib.request.urlopen(req, timeout=15) as r:
		return json.load(r)


def _name(x):
	# KM names come as multilingual dicts ({'eng': ...}) or plain strings
	if isinstance(x, dict):
		return x.get("eng") or x.get("jpn") or next(iter(x.values()), "")
	return x or ""


def _parse(k):
	media = k.get("mediafile", "")
	return {
		"kid": k.get("kid", ""),
		"title": _name(k.get("titles")),
		"series": ", ".join(_name(s.get("name") if isinstance(s, dict) else s) for s in (k.get("series") or [])),
		"types": [t.get("short") or t.get("name") for t in (k.get("songtypes") or [])],
		"langs": [l.get("name") for l in (k.get("langs") or [])],
		"duration": k.get("duration", 0),
		"mediafile": media,
		"subfile": k.get("subfile") or (k.get("kid", "") + ".ass"),
		"is_video": media.lower().endswith((".mp4", ".mkv", ".webm", ".avi", ".mov")),
	}


def search(query, n=8):
	url = f"{API}/karas/search?filter={urllib.parse.quote(query)}&size={n}"
	out = [_parse(k) for k in (_get_json(url).get("content") or [])]
	# rank: real OP/ED/IN over covers/AMV/audio; video over audio-only
	out.sort(key=lambda r: -((5 if any(t in ("OP", "ED", "IN") for t in r["types"]) else 0) + (2 if r["is_video"] else 0)))
	return out


def get(kid):
	return _parse(_get_json(f"{API}/karas/{kid}"))


def label(r):
	t = "/".join(r["types"]) or "?"
	return f'{r["series"] or r["title"]} [{t}] - {r["title"]}'.strip()


def _download(url, dest):
	req = urllib.request.Request(url, headers=_HDRS)
	with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
		while True:
			chunk = r.read(1 << 16)
			if not chunk:
				break
			f.write(chunk)
	return os.path.getsize(dest)


def download(result, dest_dir, basename):
	"""Download media + ASS into dest_dir as <basename>.<ext> and <basename>.ass.
	Returns (media_path, ass_path)."""
	media_ext = os.path.splitext(result["mediafile"])[1] or ".mp4"
	media_dst = os.path.join(dest_dir, basename + media_ext)
	_download(f"{DL}/medias/{result['mediafile']}", media_dst)
	ass_dst = os.path.join(dest_dir, basename + ".ass")
	try:
		_download(f"{DL}/lyrics/{result['subfile']}", ass_dst)
	except Exception:
		_download(f"https://raw.githubusercontent.com/karamoe/karaokebase/master/lyrics/{result['subfile']}", ass_dst)
	return media_dst, ass_dst


if __name__ == "__main__":
	import sys
	q = " ".join(sys.argv[1:]) or "unravel"
	for i, r in enumerate(search(q)):
		print(f'{i}. {label(r)}  ({r["duration"]}s, {"video" if r["is_video"] else "audio"}, {",".join(r["langs"])})  kid={r["kid"][:8]}')
