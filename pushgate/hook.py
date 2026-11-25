"""git's pre-push hook: its place in a repository, and in git's template for the repositories made after it.

The hook runs the repository's own pre-push hook first, when it has one (kept beside Push Gate's as pre-push.chained),
then reads what the push sends (scan.read_push) against what the remote holds now, asked at push time. It stops the
push for a private word, a credential, or a new file that runs code, and it refuses a push that rewrites or deletes a
branch on the remote, or lands on a remote commit this checkout has never seen.
"""
import os
import shlex
import shutil
import subprocess
import sys

from . import NAME, count, short_path
from .scan import (GitError, ZERO, advertised, cleaner, config, own_words_path, present, read_push, read_words,
                   words_path)

MARK = 'Push Gate pre-push hook'
CHAINED = 'pre-push.chained'                       # a repository's own pre-push hook, kept beside Push Gate's, run first
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


def run_first(path, argv, refs):
    """The repository's own pre-push hook, run as git runs one: the same arguments, the same lines on stdin, and its
    output where git's goes. -> its exit code, or None when there is none to run (git skips a hook file that is not
    executable, and so does this)."""
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        return None
    path = os.path.abspath(path)
    try:
        return subprocess.run([path, *argv], input=refs, text=True).returncode
    except OSError as e:
        print(f'{NAME}: could not run {short_path(path)}: {e}', file=sys.stderr)
        return 1


def prepush(argv, refs, repo=None, first=None):
    """git's pre-push hook. git passes the remote's name and URL as arguments, and one line a ref on stdin:
    <local ref> <local object> <remote ref> <remote object>. `first` is the repository's own pre-push hook, run before
    anything is read; when it stops the push, nothing is read. -> (code, lines): 0 lets the push go."""
    own = run_first(first, argv, refs)
    if own:
        return own, [f"{NAME}: this repository's own pre-push check ({CHAINED}) stopped the push, so {NAME} did not read it"]
    remote = argv[0] if argv else 'origin'
    url = argv[1] if len(argv) > 1 and argv[1] else remote
    repo = repo or os.getcwd()
    rewrite_ok = os.environ.get('PUSHGATE_ALLOW_REWRITE') == '1' or 'true' in config(repo, 'pushgate.allowRewrite', '--type=bool')
    stops = []                                     # (kind, words)
    notes = [f"this repository's own pre-push check ran first and passed ({CHAINED})"] if own == 0 else []
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
    path, own = words_path(repo), own_words_path(repo)
    try:
        words = read_words(repo)
    except OSError as e:
        words = None
        stops.append(('error', f'a word list could not be read ({e})'))
    else:
        if words is None:
            notes.append(f'no private word list at {short_path(path)}: credentials were checked, private words were not')
        elif path not in words.paths:
            notes.append(f"no word list at {short_path(path)}: only this repository's own list was read")
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
        lines.append(f'  Text that may be public gets an `allow:` line in the word list ({short_path(path)})'
                     + (f", or, for this repository alone, in its own ({short_path(own)})." if own else '.'))
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
            f'# A pre-push hook the repository had of its own runs first: {CHAINED}, beside this file.\n'
            f'exec {shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook --first "$(dirname "$0")/{CHAINED}" "$@"\n')


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except FileNotFoundError:
        return None


def _kind(text):
    return ('none' if text is None else 'in place' if text == hook_body() else 'out of date' if MARK in text
            else "another tool's")


def _write_hook(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.pushgate-new'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(hook_body())
    os.chmod(tmp, 0o755)
    os.replace(tmp, path)


def state(repo):
    """The hook in `repo`: 'in place', 'out of date' (Push Gate's, written for another place or Python), "another
    tool's", 'none', or 'not a repository'; with where it is, whether the repository's own hook is chained beside it,
    the repository's remotes, and core.hooksPath."""
    path = hook_path(repo)
    if path is None:
        return dict(hook='not a repository', path=None, chained=False, remotes=[], hooks_path=None)
    chained = os.path.join(os.path.dirname(path), CHAINED)
    remotes = subprocess.run(['git', '-C', repo, 'remote'], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL).stdout.split()
    hooks_path = config(repo, 'core.hooksPath')
    return dict(hook=_kind(_read(path)), path=path, chained=os.path.lexists(chained), remotes=remotes,
                hooks_path=hooks_path[-1] if hooks_path else None)


def install(repo):
    """The hook written into `repo`. A pre-push hook the repository has of its own is kept and run first: it moves
    beside Push Gate's as pre-push.chained. Nothing is written when core.hooksPath sends git to a shared folder.
    -> (done, words)."""
    s = state(repo)
    if s['path'] is None:
        return False, f'{repo} is not a git repository'
    if s['hooks_path']:
        return False, (f'core.hooksPath is set ({s["hooks_path"]}): git runs hooks from there for every repository that '
                       f'uses it, so nothing was written. A pre-push hook there can run: '
                       f'{shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook "$@"')
    chained = os.path.join(os.path.dirname(s['path']), CHAINED)
    after = f"; this repository's own pre-push hook runs first ({CHAINED})"
    if s['hook'] == 'in place':
        return True, f'the hook is in place ({s["path"]})' + (after if s['chained'] else '')
    if s['hook'] == "another tool's":
        if s['chained'] and _read(chained) != _read(s['path']):
            return False, (f"another tool's pre-push hook is at {s['path']}, and the {CHAINED} beside it is a different "
                           f'one: look at both, keep the one this repository needs as {CHAINED}, then run pushgate '
                           f'install again')
        if not s['chained']:
            os.replace(s['path'], chained)         # the same name, beside: its mode and its contents unchanged
        _write_hook(s['path'])                     # (or its tool wrote the same hook again: it stays chained)
        return True, f'the hook written ({s["path"]}){after}'
    _write_hook(s['path'])
    return True, (f'the hook {"updated" if s["hook"] == "out of date" else "written"} ({s["path"]}): every push from here '
                  f'is read first' + (after if s['chained'] else ''))


def uninstall(repo):
    """Push Gate's hook taken out of `repo`, and the repository's own hook put back in its place; another tool's
    hook is left. -> (done, words)."""
    s = state(repo)
    if s['path'] is None:
        return False, f'{repo} is not a git repository'
    if s['hook'] == 'none':
        return True, f'no pre-push hook here ({s["path"]})'
    if s['hook'] == "another tool's":
        return False, f"the pre-push hook at {s['path']} is another tool's: left as it is"
    os.remove(s['path'])
    if s['chained']:
        os.replace(os.path.join(os.path.dirname(s['path']), CHAINED), s['path'])
        return True, f"the hook taken out ({s['path']}), and this repository's own pre-push hook put back in its place"
    return True, f'the hook taken out ({s["path"]})'


# The hook in git's template, for every repository made or cloned after it.

def _global(key, *kind):
    r = subprocess.run(['git', 'config', '--global', *kind, '--get', key], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def own_template():
    """Push Gate's own template folder, made when git has none set."""
    return os.path.join(os.path.expanduser('~'), '.config', 'pushgate', 'template')


def _git_template():
    """git's default template folder (beside its programs), or None."""
    r = subprocess.run(['git', '--exec-path'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    d = os.path.normpath(os.path.join(r.stdout.strip(), '..', '..', 'share', 'git-core', 'templates'))
    return d if r.returncode == 0 and os.path.isdir(d) else None


def template_state():
    """Whether repositories made from now on get the hook: git's template folder (init.templateDir, a global
    setting), or None, and the hook there ('in place', 'out of date', "another tool's", or 'none')."""
    d = _global('init.templateDir', '--type=path')
    if not d:
        return dict(dir=None, hook='none')
    d = os.path.expanduser(d)
    return dict(dir=d, hook=_kind(_read(os.path.join(d, 'hooks', 'pre-push'))))


def template_on():
    """The hook in git's template, so `git init` and `git clone` give it to every repository from now on. When git
    has no template folder set, Push Gate makes its own from git's default template and sets init.templateDir.
    -> (done, words)."""
    t = template_state()
    if t['hook'] == "another tool's":
        return False, f"git's template ({short_path(t['dir'])}) has another tool's pre-push hook: left as it is"
    d = t['dir']
    if d is None:
        d = own_template()
        default = _git_template()
        if default and not os.path.exists(d):
            shutil.copytree(default, d, symlinks=True)
        r = subprocess.run(['git', 'config', '--global', 'init.templateDir', d], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode:
            return False, f'could not set init.templateDir: {r.stderr.strip()}'
    if t['hook'] != 'in place':
        _write_hook(os.path.join(d, 'hooks', 'pre-push'))
    return True, f"repositories made or cloned from now on get the hook from git's template ({short_path(d)})"


def template_off():
    """The hook taken out of git's template; Push Gate's own template folder is unset as well. -> (done, words)."""
    t = template_state()
    if t['hook'] == 'none':
        return True, "git's template has no Push Gate hook"
    if t['hook'] == "another tool's":
        return False, f"git's template ({short_path(t['dir'])}) has another tool's pre-push hook: left as it is"
    os.remove(os.path.join(t['dir'], 'hooks', 'pre-push'))
    if os.path.realpath(t['dir']) == os.path.realpath(own_template()):
        subprocess.run(['git', 'config', '--global', '--unset', 'init.templateDir'], capture_output=True,
                       stdin=subprocess.DEVNULL)
        return True, "the hook taken out of git's template, and git uses its default template again"
    return True, f"the hook taken out of git's template ({short_path(t['dir'])})"
