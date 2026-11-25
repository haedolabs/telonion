"""git's hooks: Telonion's pre-push, pre-commit, and commit-msg hooks, their place in a repository, and in git's
template for the repositories made after it.

Each hook runs the repository's own hook of the same name first, when it has one (kept beside Telonion's as
<name>.chained). The pre-push hook then reads what the push sends (scan.read_push) against what the remote holds now,
asked at push time. It stops the push for a private word, a credential, or a new file that runs code, and it refuses a
push that rewrites or deletes a branch on the remote, or lands on a remote commit this checkout has never seen. The
pre-commit and commit-msg hooks read what the next commit adds (scan.read_commit), and stop the commit for a private
word or a credential.
"""
import os
import shlex
import shutil
import subprocess
import sys

from . import NAME, count, listed, short_path
from .scan import (OLD, GitError, ZERO, advertised, cleaner, config, env, own_words_path, present, read_commit,
                   read_push, read_words, setting, words_path)

HOOKS = ('pre-push', 'pre-commit', 'commit-msg')
MARK = 'Telonion pre-push hook'
CHAINED = 'pre-push.chained'                       # a repository's own pre-push hook, kept beside Telonion's, run first
LAUNCHER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin', 'telonion')
PY = shutil.which('python3') or sys.executable or '/usr/bin/python3'   # the PATH's python3, a stable link, not a
                                                                       # versioned path that an upgrade removes
LIMIT = 30                                         # hits listed for each kind; the rest are counted
CUT = '------------------------ >8 ------------------------'           # git's scissors line, after its comment string


def mark(name):
    """The words that mark a hook as Telonion's."""
    return f'Telonion {name} hook'


def old_mark(name):
    """The words that marked a hook as Telonion's under its old name, Push Gate: such a hook is Telonion's, out of
    date, and still runs it (bin/pushgate is the old name of bin/telonion)."""
    return f'Push Gate {name} hook'


def _ancestor(repo, older, newer):
    r = subprocess.run(['git', '-C', repo, 'merge-base', '--is-ancestor', older, newer], capture_output=True,
                       stdin=subprocess.DEVNULL)
    if r.returncode not in (0, 1):
        raise GitError(f'git merge-base: {r.stderr.decode(errors="replace").strip()[:300]}')
    return r.returncode == 0


def run_first(path, argv, stdin=None):
    """The repository's own hook, run as git runs one: the same arguments, the same input (`stdin`, or what this
    process was given), and its output where git's goes. -> its exit code, or None when there is none to run (git
    skips a hook file that is not executable, and so does this)."""
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        return None
    path = os.path.abspath(path)
    try:
        return subprocess.run([path, *argv], input=stdin, text=True).returncode
    except OSError as e:
        print(f'{NAME}: could not run {short_path(path)}: {e}', file=sys.stderr)
        return 1


def _lists(repo):
    """The word lists `repo` is read against, as one: (words, stops, notes). Words is None when there is no list,
    or when a list exists and cannot be read, which is a stop."""
    path = words_path(repo)
    try:
        words = read_words(repo)
    except OSError as e:
        return None, [('error', f'a word list could not be read ({e})')], []
    if words is None:
        return None, [], [f'no private word list at {short_path(path)}: credentials were checked, private words were not']
    if path not in words.paths:
        return words, [], [f"no word list at {short_path(path)}: only this repository's own list was read"]
    return words, [], []


def _hits(r):
    """A reading's hits as stops, (kind, words): LIMIT of each kind listed, and the rest counted."""
    stops = []
    for kind, items, say in (('private', r['private'], lambda h: f'private word: {h[0]}: {h[1]}'),
                             ('credential', r['credentials'], lambda h: f'{h[1]}: {h[0]}: {h[2]}'),
                             ('code', r.get('code', []),
                              lambda h: f'a file that runs code on a host or on install: {h[0]}: {h[1]}')):
        stops += [(kind, say(h)) for h in items[:LIMIT]]
        if len(items) > LIMIT:
            stops.append((kind, f'... and {len(items) - LIMIT} more'))
    return stops


def _allow(repo):
    own = own_words_path(repo)
    return (f'  Text that may be public gets an `allow:` line in the word list ({short_path(words_path(repo))})'
            + (f", or, for this repository alone, in its own ({short_path(own)})." if own else '.'))


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
    rewrite_ok = env('ALLOW_REWRITE') == '1' or 'true' in setting(repo, 'allowRewrite', '--type=bool')
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
    words, errors, more = _lists(repo)
    stops += errors
    notes += more
    clean = cleaner(words)
    r = None
    if tips:
        try:
            stop += advertised(repo, url)
        except GitError as e:
            notes.append(f'could not list what {remote} holds ({e}), so more history was read than usual')
        try:
            r = read_push(repo, tips, stop, words, setting(repo, 'allowCode', both=True), tag_refs, names)
        except GitError as e:
            stops.append(('error', f'could not read what the push sends: {e}'))
    if r:
        stops += _hits(r)
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
        lines.append(_allow(repo))
    if 'credential' in kinds:
        lines.append('  A credential that was ever pushed anywhere is revoked, not only removed.')
    if 'code' in kinds:
        lines.append('  A file meant to run code: git config --add telonion.allowCode <path or pattern>')
    if 'rewrite' in kinds:
        lines.append('  A rewrite or a deletion on purpose: TELONION_ALLOW_REWRITE=1 for one push.')
    return 1, lines + [f'  {n}' for n in notes]


def kept_message(text, repo):
    """A commit message as git keeps it. With an editor, git cuts the message at its scissors line and, by default,
    drops its comment lines; with none (git tells hooks so with GIT_EDITOR=:), it keeps every line by default.
    commit.cleanup changes the default, as it does for git."""
    editor = os.environ.get('GIT_EDITOR') != ':'
    mode = (config(repo, 'commit.cleanup') or ['default'])[-1].lower()
    if mode == 'default':
        mode = 'strip' if editor else 'whitespace'
    comment = (config(repo, 'core.commentString') or config(repo, 'core.commentChar') or ['#'])[-1]
    if comment == 'auto':
        comment = '#'
    lines = text.split('\n')
    cut = f'{comment} {CUT}'
    if (editor or mode == 'scissors') and cut in lines:
        lines = lines[:lines.index(cut)]
    if mode == 'strip':
        lines = [line for line in lines if not line.startswith(comment)]
    return '\n'.join(lines)


def commit_hook(name, argv, repo=None, first=None):
    """git's pre-commit hook (`name` 'pre-commit': what the commit adds, as staged, and who it is by) or its commit-msg
    hook ('commit-msg': the message, in the file git names as the first argument), read against the word lists and
    the credential formats. `first` is the repository's own hook of that name, run before anything is read; when it
    stops the commit, nothing is read. Nothing is read either when the repository's telonion.checkCommits is false.
    -> (code, lines): 0 lets the commit go."""
    chained = f'{name}.chained'
    own = run_first(first, argv)
    if own:
        return own, [f"{NAME}: this repository's own {name} check ({chained}) stopped the commit, so {NAME} did not read it"]
    repo = repo or os.getcwd()
    if setting(repo, 'checkCommits', '--type=bool')[-1:] == ['false']:
        return 0, ([f'{NAME}: the commit check is off in this repository (telonion.checkCommits)']
                   if name == 'pre-commit' else [])
    notes = [f"this repository's own {name} check ran first and passed ({chained})"] if own == 0 else []
    words, stops, more = _lists(repo)
    notes += more
    r = None
    try:
        if name == 'pre-commit':
            r = read_commit(repo, words)
        else:
            if not argv:
                raise OSError('git named no message file')
            with open(argv[0], encoding='utf-8', errors='replace') as f:
                r = read_commit(repo, words, staged=False, message=kept_message(f.read(), repo))
    except GitError as e:
        stops.append(('error', f'could not read what the commit adds: {e}'))
    except OSError as e:
        stops.append(('error', f'could not read the commit message ({e.strerror or e})'))
    if r:
        stops += _hits(r)
    if not stops:
        read = (f"{count(r['lines'], 'added line')} and {count(r['files'], 'new file name')} read for the commit"
                if name == 'pre-commit' else 'the commit message read')
        found = 'nothing private and no credentials' if words is not None else 'no credentials'
        return 0, [f'{NAME}: {read}: {found}'] + [f'  {n}' for n in notes]
    clean = cleaner(words)
    kinds = {k for k, _ in stops}
    lines = [f'{NAME}: the commit is stopped'] + [f'  {clean(w)}' for _, w in stops]
    if kinds & {'private', 'credential'}:
        lines.append('  Nothing was committed: take it out of ' + ('what is staged' if name == 'pre-commit' else
                                                                   'the message') + ', then commit again.')
    if 'private' in kinds:
        lines.append(_allow(repo))
        lines.append('  A repository that holds private words on purpose, and is never made public: '
                     'git config telonion.checkCommits false (its pushes are still read).')
    if 'credential' in kinds:
        lines.append('  A credential belongs in no commit: keep it outside the repository.')
    return 1, lines + [f'  {n}' for n in notes]


# The hooks in a repository.

def hook_paths(repo):
    """Where git looks for each of Telonion's hooks in this repository (core.hooksPath and worktrees taken into
    account): {name: path}, or None when `repo` is not a git repository."""
    r = subprocess.run(['git', '-C', repo, 'rev-parse', *[a for n in HOOKS for a in ('--git-path', f'hooks/{n}')]],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    found = r.stdout.strip().split('\n') if r.returncode == 0 else []
    if len(found) != len(HOOKS):
        return None
    base = os.path.abspath(repo)
    return {n: p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p)) for n, p in zip(HOOKS, found)}


def hook_path(repo, name='pre-push'):
    """Where git looks for this repository's hook `name`, or None when `repo` is not a git repository."""
    paths = hook_paths(repo)
    return paths[name] if paths else None


def hook_body(name='pre-push'):
    """The hook Telonion writes as `name`."""
    if name == 'pre-push':
        return ('#!/bin/sh\n'
                f'# {MARK} (written by telonion install): every push from this repository is read before it leaves.\n'
                f'# A pre-push hook the repository had of its own runs first: {CHAINED}, beside this file.\n'
                f'exec {shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook --first "$(dirname "$0")/{CHAINED}" "$@"\n')
    what = {'pre-commit': 'what each commit adds is read before the commit is made',
            'commit-msg': "each commit's message is read before the commit is made"}[name]
    return ('#!/bin/sh\n'
            f'# {mark(name)} (written by telonion install): {what}.\n'
            f'# A {name} hook the repository had of its own runs first: {name}.chained, beside this file.\n'
            f'exec {shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook --as {name} --first "$(dirname "$0")/{name}.chained" '
            f'-- "$@"\n')


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except FileNotFoundError:
        return None


def _kind(text, name='pre-push'):
    return ('none' if text is None else 'in place' if text == hook_body(name)
            else 'out of date' if mark(name) in text or old_mark(name) in text else "another tool's")


def _write_hook(path, name='pre-push'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.telonion-new'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(hook_body(name))
    os.chmod(tmp, 0o755)
    os.replace(tmp, path)


def _hooks(names):
    """'the pre-push hook', 'the pre-commit and commit-msg hooks'."""
    return f'the {listed(names)} {"hook" if len(names) == 1 else "hooks"}'


def state(repo):
    """Telonion's hooks in `repo`, or 'not a repository'. For each of HOOKS (`hooks`: {name: {hook, path,
    chained}}): 'in place', 'out of date' (Telonion's, written for another place or Python), "another tool's", or
    'none', with where it is and whether the repository's own hook of that name is chained beside it; the pre-push
    hook's are also at the top. Also the repository's remotes, core.hooksPath, and whether its commits are read
    (`commits`: telonion.checkCommits is not false)."""
    paths = hook_paths(repo)
    if paths is None:
        return dict(hook='not a repository', path=None, chained=False, hooks={}, remotes=[], hooks_path=None,
                    commits=False)
    hooks = {n: dict(hook=_kind(_read(p), n), path=p, chained=os.path.lexists(p + '.chained')) for n, p in paths.items()}
    remotes = subprocess.run(['git', '-C', repo, 'remote'], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL).stdout.split()
    hooks_path = config(repo, 'core.hooksPath')
    return dict(hooks['pre-push'], hooks=hooks, remotes=remotes, hooks_path=hooks_path[-1] if hooks_path else None,
                commits=setting(repo, 'checkCommits', '--type=bool')[-1:] != ['false'], old=old_names(repo))


def _local_keys(repo, section):
    r = subprocess.run(['git', '-C', repo, 'config', '--local', '--name-only', '--get-regexp', rf'^{section}\.'],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return r.stdout.split() if r.returncode == 0 else []


def old_names(repo):
    """What this repository keeps under Telonion's old name, Push Gate, and `telonion install` moves: its own word list
    (info/pushgate-words) and its own settings (pushgate.*). All are still read where the new names are not set."""
    found = []
    own = own_words_path(repo)
    if own and os.path.basename(own) == f'{OLD}-words':
        found.append(f'info/{OLD}-words')
    if _local_keys(repo, OLD):
        found.append(f'{OLD}.* settings')
    return found


def move_old_names(repo):
    """This repository's own word list and settings moved from Push Gate's names to Telonion's, in place: the list is
    renamed (its lines are not read), and the settings move when the repository has none of the new name yet (else
    the old ones stay, and are read where the new are not set). -> the names moved, in words."""
    moved = []
    own = own_words_path(repo)
    if own and os.path.basename(own) == f'{OLD}-words':
        new = os.path.join(os.path.dirname(own), 'telonion-words')
        if not os.path.lexists(new):
            os.rename(own, new)
            moved.append(f'info/{OLD}-words to info/telonion-words')
    if _local_keys(repo, OLD) and not _local_keys(repo, 'telonion'):
        r = subprocess.run(['git', '-C', repo, 'config', '--local', '--rename-section', OLD, 'telonion'],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if r.returncode == 0:
            moved.append(f'{OLD}.* settings to telonion.*')
    return moved


def install(repo, update=False):
    """Telonion's hooks written into `repo`: pre-push, pre-commit, and commit-msg. A hook of one of those names that
    the repository has of its own is kept and run first: it moves beside Telonion's as <name>.chained. Nothing is
    written when core.hooksPath sends git to a shared folder, or when another tool's hook stands where Telonion's
    was with a different one chained beside it. With `update`, the pre-push hook is put in place and the commit hooks
    only where Telonion's (or Push Gate's) already are: no commit check is added. -> (done, words)."""
    s = state(repo)
    if s['path'] is None:
        return False, f'{repo} is not a git repository'
    if s['hooks_path']:
        return False, (f'core.hooksPath is set ({s["hooks_path"]}): git runs hooks from there for every repository that '
                       f'uses it, so nothing was written. A pre-push, pre-commit, or commit-msg hook there can run: '
                       f'{shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook --as <its name> -- "$@"')
    for n, h in s['hooks'].items():
        if h['hook'] == "another tool's" and h['chained'] and _read(h['path'] + '.chained') != _read(h['path']):
            return False, (f"another tool's {n} hook is at {h['path']}, and the {n}.chained beside it is a different "
                           f'one: look at both, keep the one this repository needs as {n}.chained, then run telonion '
                           f'install again')
    written = []
    for n, h in s['hooks'].items():
        if h['hook'] == 'in place' or (update and n != 'pre-push' and h['hook'] != 'out of date'):
            continue
        if h['hook'] == "another tool's" and not h['chained']:
            os.replace(h['path'], h['path'] + '.chained')   # the same name, beside: its mode and contents unchanged
        _write_hook(h['path'], n)                  # (or its tool wrote the same hook again: it stays chained)
        written.append(n)
    folder = short_path(os.path.dirname(s['path']))
    present = [n for n in HOOKS if n in written or s['hooks'][n]['hook'] == 'in place']
    if written:
        words = (f'{_hooks(written)} written ({folder}): every push and every commit from here is read first'
                 if len(present) == len(HOOKS) else
                 f'{_hooks(written)} written ({folder}): every push from here is read first')
    else:
        words = (f'the hooks are in place ({folder})' if len(present) == len(HOOKS)
                 else f'{_hooks(present)} {"is" if len(present) == 1 else "are"} in place ({folder})')
    moved = move_old_names(repo)
    if moved:
        words += f'; moved to the new name: {listed(moved)}'

    chained = [n for n in HOOKS if os.path.lexists(s['hooks'][n]['path'] + '.chained')]
    if chained:
        words += (f"; this repository's own {listed(chained)} {'hook runs' if len(chained) == 1 else 'hooks run'} "
                  f"first ({', '.join(n + '.chained' for n in chained)})")
    return True, words


def uninstall(repo):
    """Telonion's hooks taken out of `repo`, and the repository's own hooks put back in their place; another tool's
    hook is left. -> (done, words): not done when another tool's hook stands where Telonion's was and the
    repository's own is still chained beside it, for a person to sort out."""
    s = state(repo)
    if s['path'] is None:
        return False, f'{repo} is not a git repository'
    out, back = [], []
    for n, h in s['hooks'].items():
        if h['hook'] in ('in place', 'out of date'):
            os.remove(h['path'])
            out.append(n)
            if h['chained']:
                os.replace(h['path'] + '.chained', h['path'])
                back.append(n)
    left = [n for n, h in s['hooks'].items() if h['hook'] == "another tool's"]
    stuck = [n for n in left if s['hooks'][n]['chained']]
    folder = short_path(os.path.dirname(s['path']))
    words = [f'{_hooks(out)} taken out ({folder})'] if out else []
    if back:
        words.append(f"this repository's own {listed(back)} {'hook' if len(back) == 1 else 'hooks'} put back in "
                     f"{'its place' if len(back) == 1 else 'their places'}")
    if left:
        words.append(f"another tool's {listed(left)} {'hook' if len(left) == 1 else 'hooks'} left as "
                     f"{'it is' if len(left) == 1 else 'they are'}")
    if stuck:
        words.append(f"{listed(n + '.chained' for n in stuck)} still beside {'it' if len(left) == 1 else 'them'}: "
                     f'look at both, and keep the one this repository needs')
    return not stuck, (', and '.join(words) if words else f'no Telonion hook here ({folder})')


# The hooks in git's template, for every repository made or cloned after them.

def _global(key, *kind):
    r = subprocess.run(['git', 'config', '--global', *kind, '--get', key], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def own_template():
    """Telonion's own template folder, made when git has none set."""
    return os.path.join(os.path.expanduser('~'), '.config', 'telonion', 'template')


def old_template():
    """The template folder Telonion made under its old name, Push Gate."""
    return os.path.join(os.path.expanduser('~'), '.config', OLD, 'template')


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def _git_template():
    """git's default template folder (beside its programs), or None."""
    r = subprocess.run(['git', '--exec-path'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    d = os.path.normpath(os.path.join(r.stdout.strip(), '..', '..', 'share', 'git-core', 'templates'))
    return d if r.returncode == 0 and os.path.isdir(d) else None


def template_state():
    """Whether repositories made from now on get Telonion's hooks: git's template folder (init.templateDir, a global
    setting), or None, and each hook there (`hooks`: {name: 'in place', 'out of date', "another tool's", or
    'none'}); the pre-push hook's is also `hook`."""
    d = _global('init.templateDir', '--type=path')
    if not d:
        return dict(dir=None, hook='none', hooks={n: 'none' for n in HOOKS})
    d = os.path.expanduser(d)
    hooks = {n: _kind(_read(os.path.join(d, 'hooks', n)), n) for n in HOOKS}
    return dict(dir=d, hook=hooks['pre-push'], hooks=hooks)


def template_on(update=False):
    """Telonion's hooks in git's template, so `git init` and `git clone` give them to every repository from now on.
    When git has no template folder set, Telonion makes its own from git's default template and sets
    init.templateDir. Nothing is written when another tool's hook of one of those names is there. With `update`, the
    pre-push hook is put in place and the commit hooks only where Telonion's (or Push Gate's) already are.
    -> (done, words)."""
    t = template_state()
    other = [n for n, k in t['hooks'].items() if k == "another tool's"]
    if other:
        return False, (f"git's template ({short_path(t['dir'])}) has another tool's {listed(other)} "
                       f"{'hook' if len(other) == 1 else 'hooks'}: nothing was written")
    d = t['dir']
    moved = False
    if d and _same(d, old_template()) and not os.path.lexists(own_template()):
        new = own_template()                       # Push Gate's own folder, moved to Telonion's name
        os.makedirs(os.path.dirname(new), exist_ok=True)
        os.rename(d, new)
        r = subprocess.run(['git', 'config', '--global', 'init.templateDir', new], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode:
            os.rename(new, d)
            return False, f'could not set init.templateDir: {r.stderr.strip()}'
        d, moved = new, True
    if d is None:
        d = own_template()
        default = _git_template()
        if default and not os.path.exists(d):
            shutil.copytree(default, d, symlinks=True)
        r = subprocess.run(['git', 'config', '--global', 'init.templateDir', d], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode:
            return False, f'could not set init.templateDir: {r.stderr.strip()}'
    for n, k in t['hooks'].items():
        if k != 'in place' and not (update and n != 'pre-push' and k != 'out of date'):
            _write_hook(os.path.join(d, 'hooks', n), n)
    return True, (f"repositories made or cloned from now on get the hooks from git's template ({short_path(d)})"
                  + (f' (moved from {short_path(old_template())})' if moved else ''))


def template_off():
    """Telonion's hooks taken out of git's template; Telonion's own template folder is unset as well, unless another
    tool's hook is there. -> (done, words)."""
    t = template_state()
    ours = [n for n, k in t['hooks'].items() if k in ('in place', 'out of date')]
    if not ours:
        return True, "git's template has no Telonion hook"
    for n in ours:
        os.remove(os.path.join(t['dir'], 'hooks', n))
    if ("another tool's" not in t['hooks'].values()
            and (_same(t['dir'], own_template()) or _same(t['dir'], old_template()))):
        subprocess.run(['git', 'config', '--global', '--unset', 'init.templateDir'], capture_output=True,
                       stdin=subprocess.DEVNULL)
        return True, "the hooks taken out of git's template, and git uses its default template again"
    return True, f"the hooks taken out of git's template ({short_path(t['dir'])})"
