"""Git's push and commit hooks, their installation, and the shared decision used by a live push preview.
Ordinary repository checks run first. Destination rules and transfer hooks require inspection first."""
import os
import shlex
import shutil
import subprocess
import sys

from . import NAME, count, fingerprint, listed, short_path
from .destinations import destinations, endpoint, label, named_endpoint
from .receipts import inspection_record, save_receipt
from .scan import (OBJECT_ID, OLD, GitError, ListError, advertised, cleaner, config, env, own_words_path, present,
                   read_commit, read_push, read_words, setting, words_path)

HOOKS = ('pre-push', 'pre-commit', 'commit-msg')
MARK = 'Telonion pre-push hook'
CHAINED = 'pre-push.chained'                       # a repository's own pre-push hook, kept beside Telonion's
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
    r = subprocess.run(['git', '--no-replace-objects', '-C', repo, 'merge-base', '--is-ancestor', older, newer],
                       capture_output=True,
                       stdin=subprocess.DEVNULL)
    if r.returncode not in (0, 1):
        raise GitError('git could not compare the two commits')
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
    except OSError:
        print(f"{NAME}: could not run the repository's hook", file=sys.stderr)
        return 1


def _lists(repo):
    """The word lists `repo` is read against, as one: (words, stops, notes). Words is None when there is no list,
    or when a list exists and cannot be read, which is a stop."""
    try:
        words = read_words(repo)
    except ListError as e:
        return None, [('error', str(e))], []
    except OSError:
        return None, [('error', 'a word list could not be read')], []
    if words is None:
        return None, [], ['no private word list: credentials were checked, private words were not']
    if words_path(repo) not in words.paths:
        return words, [], ["only this repository's own word list was read"]
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


def _read_updates(repo, refs, remote, url, words, stops, notes):
    """The exact updates Git supplied. A failed remote listing broadens the scan to the full history."""
    rewrite_ok = env('ALLOW_REWRITE') == '1' or setting(repo, 'allowRewrite', '--type=bool')[-1:] == ['true']
    tips, stop, names = [], [], []
    for line in refs.split('\n'):
        if not line:
            continue
        f = line.split()
        if len(f) != 4 or not OBJECT_ID.fullmatch(f[1]) or not OBJECT_ID.fullmatch(f[3]) or len(f[1]) != len(f[3]):
            raise GitError('a proposed ref update could not be read')
        _, lsha, rref, rsha = f
        zero = '0' * len(lsha)
        if lsha == zero:
            if rref.startswith('refs/heads/') and not rewrite_ok:
                stops.append(('rewrite', f'the push deletes {rref} on {remote}'))
            continue
        if rsha != zero:
            stop.append(rsha)
            if not rewrite_ok and not present(repo, [rsha]):
                stops.append(('rewrite', f'{remote} holds {rsha[:7]} on {rref}, which this checkout does not have: '
                                         f'fetch and look at it first'))
            elif not rewrite_ok and rref.startswith('refs/heads/') and not _ancestor(repo, rsha, lsha):
                stops.append(('rewrite', f'the push rewrites {rref} on {remote} (a force push)'))
        tips.append(lsha)
        names.append(rref)
    if tips:
        try:
            stop += advertised(repo, url)
        except GitError:
            stop = []
            notes.append('could not list the remote refs; the full outgoing history was read')
    reading = read_push(repo, tips, stop, words, setting(repo, 'allowCode', both=True), tag_refs=(), ref_names=names)
    reading['ref_updates'] = len(refs.splitlines())
    return reading


def _check_files(repo, r, name, key, mode, stops, notes):
    opaque = r['opaque']
    if not opaque:
        return
    notes.append(f"{count(len(opaque), 'file version')} checked by name only")
    approvals = set(config(repo, 'telonion.approvedFile', '--local')) if mode == 'release' else set()
    approved = 0
    for path, version, sha, kind in opaque:
        if kind == 'LFS' and mode:
            stops.append(('LFS', f'{sha[:7]} {path}: the separate LFS transfer has not been inspected'))
        elif mode == 'release':
            if kind == 'submodule':
                stops.append(('file', f'{sha[:7]} {path}: the submodule contents are outside this inspection'))
            elif fingerprint(name, key, version) in approvals:
                approved += 1
            else:
                stops.append(('file', f'{sha[:7]} {path}: this version has no approval for release'))
    r['approved_files'] = approved
    if approved:
        notes.append(f"{count(approved, 'file version')} approved for this release destination")
    if not mode and any(kind == 'LFS' for _, _, _, kind in opaque):
        notes.append('LFS pointer text read; the separate LFS payload was not inspected')


def transfer_hook(repo, path):
    """Recognize the standard LFS uploader or one marked with telonion.transferHook."""
    if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
        return False
    if config(repo, 'telonion.transferHook', '--type=bool')[-1:] == ['true']:
        return True
    with open(path, 'rb') as f:
        body = f.read(65536)
    return b'git lfs pre-push' in body or b'git-lfs pre-push' in body


def _push_lines(repo, remote, r, words, stops, notes):
    kinds = {k for k, _ in stops}
    read = (f"{count(r['commits'], 'commit')}, {count(r['lines'], 'added line')}, and "
            f"{count(r['files'], 'new file name')}") if r is not None else None
    if not stops:
        found = 'no private-word or credential matches' if words is not None else 'no credential matches'
        return [f'{NAME}: {read or "nothing new"} read for {remote}: {found}', *('  ' + n for n in notes)]
    lines = [f'{NAME}: the push to {remote} is stopped']
    if read:
        lines.append(f'  {read} read')
    lines += [f'  {w}' for _, w in stops[:LIMIT * 3]]
    if len(stops) > LIMIT * 3:
        lines.append(f'  ... and {len(stops) - LIMIT * 3} more')
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
    return lines + [f'  {n}' for n in notes]


def inspect_push(argv, refs, repo, first=None, preview=False):
    """One decision for the negotiated push, whether called by Git or its dry-run preview."""
    remote, words, r, policy = 'the destination', None, None, 'unread'
    stops, notes, code = [], [], 0
    try:
        rules = destinations(repo)
        policy = 'unapproved' if rules else 'default'
        transfer = transfer_hook(repo, first)
        deferred = bool(rules) or transfer
        if not preview and not deferred:
            own = run_first(first, argv, refs)
            if own:
                code = own
                stops.append(('hook', f"this repository's own pre-push check ({CHAINED}) stopped the push, "
                                      f'so {NAME} did not read it'))
            elif own == 0:
                notes.append(f"this repository's own pre-push check ran first and passed ({CHAINED})")
        if not stops:
            words, stops, more = _lists(repo)
        if not stops:
            if len(argv) != 2:
                raise GitError('Git did not identify the push destination')
            name, url = argv
            remote = label(name) if name != url else 'the destination'
            key = endpoint(repo, url)
            mode, bound = rules.get(name, (None, None))
            if rules and (mode in (None, 'removed') or bound != key or named_endpoint(repo, name) != key):
                stops.append(('destination', 'the destination is not approved; review its push URL'))
            else:
                if mode:
                    policy = mode
                    notes.append(f'approved destination ({mode})')
                r = _read_updates(repo, refs, remote, url, words, stops, notes)
                notes += more
                stops += _hits(r)
                _check_files(repo, r, name, key, mode, stops, notes)
                if mode and transfer:
                    stops.append(('transfer', 'the separate upload hook has no destination approval'))
        if not stops and not preview and deferred:
            own = run_first(first, argv, refs)
            if own:
                code = own
                stops.append(('hook', "the repository's own pre-push hook stopped the push after inspection"))
            elif own == 0:
                notes.append("the repository's own pre-push hook passed after inspection")
    except (GitError, OSError) as e:
        stops.append(('error', str(e) if isinstance(e, GitError) else 'the inspection could not be completed'))
    code = code or int(bool(stops))
    clean = cleaner(words)
    lines = [clean(line) for line in _push_lines(repo, remote, r, words, stops, notes)]
    record = inspection_record('preview' if preview else 'hook', clean(remote), code, {k for k, _ in stops}, r,
                               policy, words is not None)
    return code, lines, record


def prepush(argv, refs, repo=None, first=None, save=False):
    repo = repo or os.getcwd()
    code, lines, record = inspect_push(argv, refs, repo, first)
    if save:
        try:
            save_receipt(repo, record)
        except (OSError, GitError):
            return 1, lines + [f'{NAME}: the requested receipt could not be saved; the push is stopped']
    return code, lines


def kept_message(text, repo):
    """A commit message as git keeps it. With default cleanup and an editor, git cuts at its scissors line and drops
    comments; with none (GIT_EDITOR=:), it keeps comments by default. Explicit verbatim, whitespace, and strip cleanup
    do not cut at scissors; scissors does. Other commit.cleanup changes follow git."""
    editor = os.environ.get('GIT_EDITOR') != ':'
    configured = (config(repo, 'commit.cleanup') or ['default'])[-1].lower()
    mode = configured
    if mode == 'default':
        mode = 'strip' if editor else 'whitespace'
    comment = (config(repo, 'core.commentString') or config(repo, 'core.commentChar') or ['#'])[-1]
    if comment == 'auto':
        comment = '#'
    lines = text.split('\n')
    cut = f'{comment} {CUT}'
    if (configured == 'scissors' or (configured == 'default' and editor)) and cut in lines:
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
    if stops:
        return 1, [f'{NAME}: the commit is stopped', *('  ' + reason for _, reason in stops)]
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
    except OSError:
        stops.append(('error', 'could not read the commit message'))
    if r:
        stops += _hits(r)
        notes += more
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
    return 1, [clean(line) for line in lines + [f'  {n}' for n in notes]]


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
                f'# The repository keeps its own pre-push hook beside this file as {CHAINED}.\n'
                f'exec {shlex.quote(PY)} {shlex.quote(LAUNCHER)} hook --first "$(dirname "$0")/{CHAINED}" -- "$@"\n')
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


_NEEDS_UPDATE = ('out of date', 'not executable', 'command unavailable')


def _command_available():
    return (os.path.isfile(PY) and os.access(PY, os.X_OK) and
            os.path.isfile(LAUNCHER) and os.access(LAUNCHER, os.R_OK))


def hook_kind(path, name):
    text = _read(path)
    if text is None:
        return 'none'
    if text != hook_body(name):
        return 'out of date' if mark(name) in text or old_mark(name) in text else "another tool's"
    if not os.access(path, os.X_OK):
        return 'not executable'
    return 'in place' if _command_available() else 'command unavailable'


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
    hooks = {n: dict(hook=hook_kind(p, n), path=p, chained=os.path.lexists(p + '.chained')) for n, p in paths.items()}
    remotes = subprocess.run(['git', '-C', repo, 'remote'], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL).stdout.split()
    hooks_path = config(repo, 'core.hooksPath')
    return dict(hooks['pre-push'], hooks=hooks, remotes=remotes, hooks_path=hooks_path[-1] if hooks_path else None,
                commits=setting(repo, 'checkCommits', '--type=bool')[-1:] != ['false'], old=old_names(repo),
                transfer=transfer_hook(repo, paths['pre-push'] + '.chained'))


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
    the repository has of its own is kept beside Telonion's as <name>.chained. Nothing is
    written when core.hooksPath sends git to a shared folder, or when another tool's hook stands where Telonion's
    was with a different one chained beside it. With `update`, the pre-push hook is put in place and the commit hooks
    only where Telonion's (or Push Gate's) already are: no commit check is added. -> (done, words)."""
    s = state(repo)
    if s['path'] is None:
        return False, f'{repo} is not a git repository'
    if not _command_available():
        return False, 'the hook command is unavailable: restore Python and the Telonion launcher first'
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
        if h['hook'] == 'in place' or (update and n != 'pre-push' and h['hook'] not in _NEEDS_UPDATE):
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
        after = ('pre-push' in chained and
                 (destinations(repo) or transfer_hook(repo, s['hooks']['pre-push']['path'] + '.chained')))
        order = 'in the chain' if after else 'first'
        words += (f"; this repository's own {listed(chained)} {'hook runs' if len(chained) == 1 else 'hooks run'} "
                  f"{order} ({', '.join(n + '.chained' for n in chained)})")
        if after:
            words += '; the pre-push hook waits for inspection'
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
        if h['hook'] in ('in place', *_NEEDS_UPDATE):
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
    hooks = {n: hook_kind(os.path.join(d, 'hooks', n), n) for n in HOOKS}
    return dict(dir=d, hook=hooks['pre-push'], hooks=hooks)


def template_on(update=False):
    """Telonion's hooks in git's template, so `git init` and `git clone` give them to every repository from now on.
    When git has no template folder set, Telonion makes its own from git's default template and sets
    init.templateDir. Nothing is written when another tool's hook of one of those names is there. With `update`, the
    pre-push hook is put in place and the commit hooks only where Telonion's (or Push Gate's) already are.
    -> (done, words)."""
    t = template_state()
    if not _command_available():
        return False, 'the hook command is unavailable: restore Python and the Telonion launcher first'
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
            return False, 'could not set init.templateDir'
        d, moved = new, True
    if d is None:
        d = own_template()
        default = _git_template()
        if default and not os.path.exists(d):
            shutil.copytree(default, d, symlinks=True)
        r = subprocess.run(['git', 'config', '--global', 'init.templateDir', d], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode:
            return False, 'could not set init.templateDir'
    for n, k in t['hooks'].items():
        if k != 'in place' and not (update and n != 'pre-push' and k not in _NEEDS_UPDATE):
            _write_hook(os.path.join(d, 'hooks', n), n)
    return True, (f"repositories made or cloned from now on get the hooks from git's template ({short_path(d)})"
                  + (f' (moved from {short_path(old_template())})' if moved else ''))


def template_off():
    """Telonion's hooks taken out of git's template; Telonion's own template folder is unset as well, unless another
    tool's hook is there. -> (done, words)."""
    t = template_state()
    ours = [n for n, k in t['hooks'].items() if k in ('in place', *_NEEDS_UPDATE)]
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
