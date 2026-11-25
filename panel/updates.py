# yt-dlp and git status for the panel's Updates card.
#
# Git updates are fast-forward only, from your fork's branch: anything that needs a merge
# (upstream commits, local work) is shown but left to a human.
import importlib.metadata
import os
import subprocess

from panel import config as C


def _git(*args, timeout = 30):
	r = subprocess.run(['git', '-C', C.REPO, *args], capture_output = True, text = True, timeout = timeout)
	return r.stdout.strip() if r.returncode == 0 else None


def ytdlp():
	try:
		version = importlib.metadata.version('yt-dlp')
	except importlib.metadata.PackageNotFoundError:
		version = None
	try:
		ejs = importlib.metadata.version('yt-dlp-ejs')
	except importlib.metadata.PackageNotFoundError:
		ejs = None
	try:
		last = open(os.path.join(C.REPO, '.yt-dlp.last-update')).read().strip()
	except OSError:
		last = None
	deno = any(os.access(os.path.join(p, 'deno'), os.X_OK) for p in os.environ.get('PATH', '').split(':'))
	return {'version': version, 'solver': ejs, 'last_auto_update': last, 'deno': deno}


def _log(rng):
	out = _git('log', '--format=%h\t%ad\t%s', '--date=short', rng)
	return [dict(zip(('sha', 'date', 'subject'), L.split('\t', 2))) for L in out.splitlines()] if out else []


def git(fetch = False):
	if fetch:
		for remote in ('fork', 'origin'):
			_git('fetch', '--quiet', remote, timeout = 60)
	branch = _git('rev-parse', '--abbrev-ref', 'HEAD')
	dirty = bool(_git('status', '--porcelain', '--untracked-files=no'))
	has_fork = _git('rev-parse', '--verify', '--quiet', f'fork/{branch}') is not None
	return {
		'branch': branch,
		'head': _git('log', '-1', '--format=%h %s'),
		'dirty': dirty,
		'fork_branch': f'fork/{branch}' if has_fork else None,
		'incoming': _log(f'HEAD..fork/{branch}') if has_fork else [],      # can fast-forward
		'unpushed': _log(f'fork/{branch}..HEAD') if has_fork else [],
		'upstream_new': _log('HEAD..origin/master'),                        # needs a manual merge
		'last_fetch': _fetch_time(),
	}


def _fetch_time():
	path = os.path.join(C.REPO, '.git', 'FETCH_HEAD')
	try:
		return int(os.path.getmtime(path))
	except OSError:
		return None


def pull():
	info = git()
	if info['dirty']:
		return 'The working tree has uncommitted changes; not touching it.'
	if not info['fork_branch']:
		return f"No fork/{info['branch']} to update from."
	if not info['incoming']:
		return 'Already up to date.'
	r = subprocess.run(['git', '-C', C.REPO, 'merge', '--ff-only', info['fork_branch']],
	                   capture_output = True, text = True, timeout = 60)
	return None if r.returncode == 0 else (r.stderr.strip() or 'fast-forward failed')
