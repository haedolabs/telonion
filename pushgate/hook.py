"""git's pre-push hook, and its place in a repository.

The hook reads what the push sends (scan.read_push) against what the remote holds now, asked at push time, and stops
the push for a private word, a credential, or a new file that runs code; it also refuses a push that rewrites or
deletes a branch on the remote, or lands on a remote commit this checkout has never seen.
"""
import os
import shlex
import shutil
import subprocess
import sys

from . import NAME, count, short_path
from .scan import GitError, Words, ZERO, advertised, cleaner, config, present, read_push, words_path

MARK = 'Push Gate pre-push hook'
LAUNCHER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin', 'pushgate')
PY = shutil.which('python3') or sys.executable or '/usr/bin/python3'   # the PATH's python3, a stable link, not a
                                                                       # versioned path that an upgrade removes
LIMIT = 30                                         # hits listed for each kind; the rest are counted


def _ancestor(repo, older, newer):
    r = subprocess.run(['git', '-C', repo, 'merge-base', '--is-ancestor', older, newer], capture_output=True,
                       stdin=subprocess.DEVNULL)
    if r.returncode not in (0, 1):
        raise GitError(f'git merge-base: {r.stderr.decode(errors="replace").strip()[:300]}')
    return r.returncode == 0


def prepush(argv, refs, repo=None):
    """git's pre-push hook. git passes the remote's name and URL as arguments, and one line a ref on stdin:
    <local ref> <local object> <remote ref> <remote object>. -> (code, lines): 0 lets the push go, 1 stops it."""
    remote = argv[0] if argv else 'origin'
    url = argv[1] if len(argv) > 1 and argv[1] else remote
    repo = repo or os.getcwd()
    rewrite_ok = os.environ.get('PUSHGATE_ALLOW_REWRITE') == '1' or 'true' in config(repo, 'pushgate.allowRewrite', '--type=bool')
    stops, notes = [], []                          # stops: (kind, words)
    tips, stop, tag_refs, names = [], [], [], []
    for line in refs.split('\n'):
        f = line.split()
        if len(f) != 4:
            continue
        lref, lsha, rref, rsha = f
        if lsha == ZERO:                           # a deletion sends nothing, but it changes the remote
            if rref.startswith('refs/heads/') and not rewrite_ok:
                stops.append(('rewrite', f'the push deletes {rref} on {remote}'))
            continue
        try:
            if rsha != ZERO:
                stop.append(rsha)
                if not rewrite_ok and not present(repo, [rsha]):
                    stops.append(('rewrite', f'{remote} holds {rsha[:7]} on {rref}, which this checkout does not have: '
                                             f'fetch and look at it first'))
                elif not rewrite_ok and rref.startswith('refs/heads/') and not _ancestor(repo, rsha, lsha):
                    stops.append(('rewrite', f'the push rewrites {rref} on {remote} (a force push)'))
        except GitError as e:
            stops.append(('error', f'could not compare {rref} with {remote}: {e}'))
        tips.append(lsha)
        names.append(rref)
        if lref.startswith('refs/tags/'):
            tag_refs.append(lref)
    path = words_path(repo)
    try:
        words = Words.read(path)
    except OSError as e:
        words = None
        stops.append(('error', f'the word list at {short_path(path)} could not be read ({e})'))
    else:
        if words is None:
            notes.append(f'no private word list at {short_path(path)}: credentials were checked, private words were not')
    clean = cleaner(words)
    r = None
    if tips:
        try:
            stop += advertised(repo, url)
        except GitError as e:
            notes.append(f'could not list what {remote} holds ({e}), so more history was read than usual')
        try:
            r = read_push(repo, tips, stop, words, config(repo, 'pushgate.allowCode'), tag_refs, names)
        except GitError as e:
            stops.append(('error', f'could not read what the push sends: {e}'))
    if r:
        for kind, items, say in (('private', r['private'], lambda h: f'private word: {h[0]}: {h[1]}'),
                                 ('credential', r['credentials'], lambda h: f'{h[1]}: {h[0]}: {h[2]}'),
                                 ('code', r['code'], lambda h: f'a file that runs code on a host or on install: {h[0]}: {h[1]}')):
            stops += [(kind, say(h)) for h in items[:LIMIT]]
            if len(items) > LIMIT:
                stops.append((kind, f'... and {len(items) - LIMIT} more'))
    if not stops:
        read = (f"{count(r['commits'], 'commit')}, {count(r['lines'], 'added line')}, and "
                f"{count(r['files'], 'new file name')}") if r else 'nothing new'
        found = 'nothing private and no credentials' if words is not None else 'no credentials'
        return 0, [f'{NAME}: {read} read for {remote}: {found}'] + [f'  {n}' for n in notes]
    kinds = {k for k, _ in stops}
    lines = [f'{NAME}: the push to {remote} is stopped'] + [f'  {clean(w)}' for _, w in stops]
    if kinds & {'private', 'credential', 'code'}:
        lines.append('  A hit stays in the commit that added it, and a later commit does not remove it: amend, squash, '
                     'or rebase that commit before it leaves.')
    if 'private' in kinds:
        lines.append(f'  Text that may be public gets an `allow:` line in the word list ({short_path(path)}).')
    if 'credential' in kinds:
        lines.append('  A credential that was ever pushed anywhere is revoked, not only removed.')
    if 'code' in kinds:
        lines.append('  A file meant to run code: git config --add pushgate.allowCode <path or pattern>')
    if 'rewrite' in kinds:
        lines.append('  A rewrite or a deletion on purpose: PUSHGATE_ALLOW_REWRITE=1 for one push.')
    return 1, lines + [f'  {n}' for n in notes]


# The hook in a repository.

def hook_path(repo):
    """Where git looks for this repository's pre-push hook (core.hooksPath and worktrees taken into account), or None
    when `repo` is not a git repository."""
    r = subprocess.run(['git', '-C', repo, 'rev-parse', '--git-path', 'hooks/pre-push'], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    if r.returncode or not r.stdout.strip():
        return None
    p = r.stdout.strip()
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(os.path.abspath(repo), p))


def hook_body():
    return ('#!/bin/sh\n'
            f'# {MARK} (written by pushgate install): every push from this repository is read before it leaves.\n'
            f'exec {shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook "$@"\n')


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except FileNotFoundError:
        return None


def state(repo):
    """The hook in `repo`: 'in place', 'out of date' (Push Gate's, written for another place or Python), "another
    tool's", 'none', or 'not a repository'; with where it is, the repository's remotes, and core.hooksPath."""
    path = hook_path(repo)
    if path is None:
        return dict(hook='not a repository', path=None, remotes=[], hooks_path=None)
    cur = _read(path)
    hook = ('none' if cur is None else 'in place' if cur == hook_body() else 'out of date' if MARK in cur
            else "another tool's")
    remotes = subprocess.run(['git', '-C', repo, 'remote'], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL).stdout.split()
    hooks_path = config(repo, 'core.hooksPath')
    return dict(hook=hook, path=path, remotes=remotes, hooks_path=hooks_path[-1] if hooks_path else None)


def install(repo):
    """The hook written into `repo`, unless another tool's hook is there or core.hooksPath sends git elsewhere.
    -> (done, words)."""
    s = state(repo)
    if s['path'] is None:
        return False, f'{repo} is not a git repository'
    if s['hooks_path']:
        return False, (f'core.hooksPath is set ({s["hooks_path"]}): git runs hooks from there for every repository that '
                       f'uses it, so nothing was written. A pre-push hook there can run: '
                       f'{shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook "$@"')
    if s['hook'] == 'in place':
        return True, f'the hook is in place ({s["path"]})'
    if s['hook'] == "another tool's":
        return False, f'another pre-push hook is at {s["path"]}: left as it is, so pushes from here are not read'
    os.makedirs(os.path.dirname(s['path']), exist_ok=True)
    tmp = s['path'] + '.pushgate-new'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(hook_body())
    os.chmod(tmp, 0o755)
    os.replace(tmp, s['path'])
    return True, f'the hook {"updated" if s["hook"] == "out of date" else "written"} ({s["path"]}): every push from here is read first'


def uninstall(repo):
    """Push Gate's hook taken out of `repo`; another tool's is left. -> (done, words)."""
    s = state(repo)
    if s['path'] is None:
        return False, f'{repo} is not a git repository'
    if s['hook'] == 'none':
        return True, f'no pre-push hook here ({s["path"]})'
    if s['hook'] == "another tool's":
        return False, f'the pre-push hook at {s["path"]} is another tool\'s: left as it is'
    os.remove(s['path'])
    return True, f'the hook taken out ({s["path"]})'
