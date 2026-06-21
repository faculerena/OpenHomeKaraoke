# YouTube Music search: returns the clean official AUDIO track for a song (no music-video
# intros / long silences / extended cuts). Public search, no login required. Downloading the
# returned videoId via the normal YouTube flow gets the album/single audio.
_yt = None


def _client():
	global _yt
	if _yt is None:
		from ytmusicapi import YTMusic
		_yt = YTMusic()
	return _yt


def search(query, n=4):
	out = []
	try:
		for r in _client().search(query, filter="songs", limit=n):
			vid = r.get('videoId')
			if not vid:
				continue
			out.append({
				'videoId': vid,
				'title': r.get('title', ''),
				'artist': ", ".join(a['name'] for a in (r.get('artists') or []) if a.get('name')),
				'duration': r.get('duration') or '',
			})
			if len(out) >= n:
				break
	except Exception:
		pass
	return out


def label(r):
	return (f'{r["artist"]} - {r["title"]}').strip(' -')
