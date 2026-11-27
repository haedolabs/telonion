"""The Telonion command: local checks, approvals, and Git hooks."""
import argparse
import json
import os
import sys

from . import NAME, VERSION, count as _count, listed, short_path as _home
from .destinations import approve_file, describe_destinations, label, set_destination, set_publish_destination
from .directory import approve_directory_file, incomplete, inspect_directory
from .hook import HOOKS, commit_hook, inspect_push, install, prepush, state, template_off, template_on, template_state, uninstall
from .preview import live_preview
from .scan import (GitError, ListError, Words, cleaner, fetched, own_words_path, read_commit, read_push,
                   read_words, setting, words_path)

ABOUT = (f'{NAME} checks Git commits, pushes, and prepared publish directories for private words and credentials. '
         'Destination and file approvals bind a release to what was inspected.')
WORDS_HELP = """The word list: $TELONION_WORDS, else `git config telonion.words`, else ~/.config/telonion/words.txt. One
pattern a line (a regular expression, capitals and small letters alike; a line that is not a valid one is read as plain text),
`allow: <pattern>` for text that may appear though it holds a word, `include: <path>` for another list read as part of it
(a path from ~, or from the list's own folder; a file it names that is missing or cannot be read stops every push and
commit), and # for notes. An explicitly selected main list is required; the unconfigured default is optional.
In a repository list, `publish-exact: "text"` permits one complete original line or relative path for directory
private-word checks. Capitalization and whitespace must match. Credential checks and Git checks still apply.
No hit is printed in full: each names its place, with the word or credential masked.
Telonion was Push Gate: `pushgate` still runs it, and Push Gate's settings, variables, and files are read where the
new ones are not set (telonion install moves a repository's over)."""
TEMPLATE = """# Telonion's private word list. It lives outside every repository, and its lines are never printed.
# One pattern a line: a regular expression, capitals and small letters alike (a line that is not a valid one is read
# as plain text).
# `allow: <pattern>` marks text that may appear though it holds a word. A line that starts with # is a note.
# `include: <path>` reads another list as part of this one, under the same rules: a path from ~, or from this file's
# folder. A file it names that is missing or cannot be read stops every push and every commit.
"""
OWN_TEMPLATE = """# This repository's own word list for Telonion. It sits among git's own files, so it is never committed.
# Its patterns add to the main list, and its `allow:` lines apply to this repository alone. It can include other lists.
# `publish-exact: "text"` is for one complete line or relative path in a prepared directory. Use a JSON string.
"""


def _report(r, words, path):
    if words is None:
        print(f'  private words: not read (no word list at {_home(path)}; telonion words --init makes one)')
    else:
        print(f'  private words: {len(r["private"]) or "none"}')
        for where, text in r['private']:
            print(f'    {where}: {text}')
    print(f'  credentials: {len(r["credentials"]) or "none"}')
    for where, what, text in r['credentials']:
        print(f'    {what}: {where}: {text}')
    if 'code' in r:
        print(f'  new files that run code on a host or on install: {len(r["code"]) or "none"}')
        for where, name in r['code']:
            print(f'    {where}: {name}')
    return 1 if r['private'] or r['credentials'] or r.get('code') else 0


def _directory_result(record, messages, as_json):
    if as_json:
        print(json.dumps(record))
    else:
        print(f'{NAME}: directory {record["decision"]}; {_count(record["files"], "file")}, '
              f'{record["binary_approved"]} of {record["binary"]} binary files approved')
        if record['tree_digest']:
            print(f'  {record["tree_digest"]}')
        if record['reasons']:
            print('  ' + ', '.join(reason.replace('_', ' ') for reason in record['reasons']))
        for line in messages:
            print(line)
    return {'passed': 0, 'held': 1, 'incomplete': 2}[record['decision']]


def cmd_check(a):
    repo = a.C
    if a.directory is not None or a.destination is not None or a.json:
        if (a.directory is None or a.destination is None or a.refs or a.follow_tags or a.remote is not None
                or a.message is not None or a.file is not None):
            return _directory_result(incomplete('invalid_arguments'), [], a.json)
        record, messages = inspect_directory(repo, a.directory, a.destination, save=a.receipt, details=not a.json)
        return _directory_result(record, messages, a.json)
    if (a.receipt or a.follow_tags) and not a.live:
        print('--receipt needs --live or --directory; --follow-tags needs --live')
        return 2
    if a.staged and a.refs:
        print('--staged reads what is staged for the next commit: it takes no tip')
        return 2
    if not a.staged and (a.message is not None or a.file):
        print('-m and -F go with --staged: a message is read with what the next commit adds')
        return 2
    if a.live:
        code, lines = live_preview(repo, a.remote, a.refs, a.follow_tags, a.receipt)
        print('\n'.join(lines))
        return code
    if len(a.refs) > 1:
        print('an offline check takes one tip')
        return 2
    path = words_path(repo)
    try:
        words = read_words(repo)
    except ListError as e:
        print(str(e))
        return 2
    except OSError:
        print('a word list could not be read')
        return 2
    if a.staged:
        message = a.message
        if a.file:
            try:
                with open(a.file, encoding='utf-8', errors='replace') as f:
                    message = f.read()
            except OSError:
                print('the message file could not be read')
                return 2
        try:
            r = read_commit(repo, words, message=message)
        except GitError as e:
            print(f'nothing read: {e}')
            return 2
        print(f'{NAME}: the next commit, as staged: {_count(r["lines"], "added line")} and '
              f'{_count(r["files"], "new file name")}' + (', and its message' if message is not None else ''))
        return _report(r, words, path)
    tip = a.refs[0] if a.refs else 'HEAD'
    remote = a.remote or 'origin'
    try:
        if a.all:
            stop, against = [], f'every commit {tip} reaches'
        else:
            stop = fetched(repo, remote)
            against = (f'what this checkout last fetched from {label(remote)}' if stop
                       else f'every commit {tip} reaches (nothing was fetched from {label(remote)})')
        r = read_push(repo, [tip], stop, words, setting(repo, 'allowCode', both=True))
    except GitError as e:
        print(f'nothing read: {e}')
        return 2
    clean = cleaner(words)
    print(clean(f'{NAME}: offline estimate for {tip}, against {against}: {_count(r["commits"], "commit")}, '
                f'{_count(r["lines"], "added line")}, and {_count(r["files"], "new file name")}'))
    if r['opaque']:
        print(f'  {_count(len(r["opaque"]), "file version")} checked by name only')
    return _report(r, words, path)


def cmd_destination(a):
    if a.publish is not None:
        if a.remote is not None or a.release:
            print('--publish takes a publish target, with optional --remove')
            return 2
        set_publish_destination(a.C, a.publish, a.remove)
        print('Publish destination approval withdrawn.' if a.remove else 'Publish destination approved.')
        return 0
    if a.remote is None:
        print('supply a remote name or --publish TARGET')
        return 2
    mode = 'removed' if a.remove else 'release' if a.release else 'allow'
    set_destination(a.C, a.remote, mode)
    print('Destination approval removed.' if a.remove else f'Destination approved ({mode}).')
    return 0


def cmd_approve(a):
    if a.directory is not None or a.destination is not None:
        if a.directory is None or a.destination is None or a.remote is not None or a.at is not None:
            print('directory approval needs --directory DIR, --destination TARGET, and one relative file path')
            return 2
        approve_directory_file(a.C, a.directory, a.destination, a.path, a.remove)
        print('File approval withdrawn.' if a.remove else 'These file bytes are approved for the publish destination.')
        return 0
    if a.remote is None:
        print('supply a release remote or use --directory and --destination')
        return 2
    approve_file(a.C, a.remote, a.path, 'HEAD' if a.at is None else a.at, remove=a.remove)
    print('File approval withdrawn.' if a.remove else 'This committed file version is approved for the release destination.')
    return 0


def _diagnostics(repo):
    """Paths and labels may be shown only if all applicable private words are available for masking."""
    try:
        return cleaner(read_words(repo)), None
    except ListError as e:
        return None, f'word list: {e}'
    except OSError:
        return None, 'word list: a word list could not be read'


def _say(repo, message, fallback):
    clean, problem = _diagnostics(repo)
    print(clean(message) if clean else f'{fallback}; {problem}')


def cmd_install(a):
    done, words = install(a.C, update=a.update)
    _say(a.C, words, 'Hook installation checked' if done else 'Hook installation stopped')
    return 0 if done else 1


def cmd_uninstall(a):
    done, words = uninstall(a.C)
    _say(a.C, words, 'Hook removal checked' if done else 'Hook removal stopped')
    return 0 if done else 1


def _hooks_words(kinds, command, chained=()):
    """Telonion's hooks in a repository or in git's template ({name: kind}), in words: 'the hooks are in place', or
    'the pre-push hook is in place (after the repository's own), no pre-commit or commit-msg hook (telonion install
    puts them in place)'. `chained` names the hooks that run the repository's own first."""
    by = {}
    for n in HOOKS:
        by.setdefault(kinds[n], []).append(n)

    def after(names):
        own = [n for n in names if n in chained]
        if not own:
            return ''
        if len(names) == 1:
            return " (after the repository's own)"
        return f" (after the repository's own {listed(own)} {'hook' if len(own) == 1 else 'hooks'})"

    if by.get('in place') == list(HOOKS):
        return 'the hooks are in place' + after(HOOKS)
    if by.get('none') == list(HOOKS):
        return f'no hooks ({command} writes them)'
    parts = []
    for kind in ('in place', 'out of date', 'not executable', 'command unavailable'):
        if by.get(kind):
            parts.append(f"the {listed(by[kind])} {'hook is' if len(by[kind]) == 1 else 'hooks are'} {kind}"
                         + after(by[kind]))
    other = by.get("another tool's")
    if other:
        parts.append(f"another tool's {listed(other)} {'hook' if len(other) == 1 else 'hooks'}")
    if by.get('none'):
        parts.append(f"no {listed(by['none'], 'or')} hook")
    return f"{', '.join(parts)} ({command} puts them in place" + (", keeping another tool's to run first)" if other
                                                                  else ')')


def cmd_status(a):
    first_clean, first_problem = None, None
    for index, repo in enumerate(a.repos or ['.']):
        clean, problem = _diagnostics(repo)
        if index == 0:
            first_clean, first_problem = clean, problem
        place = clean(_home(os.path.abspath(repo))) if clean else 'repository'
        s = state(repo)
        if s['path'] is None:
            print(f'{place}: not a git repository')
            continue
        chained = [n for n, h in s['hooks'].items() if h['chained']]
        rules = describe_destinations(repo)
        deferred = bool(rules) or s['transfer']
        hooks = _hooks_words({n: h['hook'] for n, h in s['hooks'].items()}, 'telonion install',
                             [n for n in chained if n != 'pre-push' or not deferred])
        if deferred and 'pre-push' in chained:
            hooks += '; the chained pre-push hook waits for inspection'
        if not s['commits']:
            hooks += '; the commit check is off here (telonion.checkCommits)'
        remotes = ', '.join(clean(label(n)) if clean else '[remote]' for n in s['remotes'])
        remotes = f'remotes: {remotes}' if remotes else 'no remote'
        sent = f'; core.hooksPath: {clean(_home(s["hooks_path"])) if clean else "[path]"}' if s['hooks_path'] else ''
        own = _own_words(repo) if clean else None
        old = (f"; under Push Gate's names: {listed(s['old'])} (telonion install moves them)" if s['old'] else '')
        print(f'{place}: {hooks}; {remotes}{sent}' + (f'; its own word list: {clean(own)}' if own else '') + old
              + (f'; destinations: {clean(rules) if clean else "[configured]"}' if rules else ''))
        if index and problem:
            print(problem)
    print(first_problem or first_clean(_words_line(words_path(a.repos[0] if a.repos else '.'))))
    print(_template_line(first_clean))
    return 0


def _template_line(clean):
    t = template_state()
    kinds, where = t['hooks'], clean(_home(t['dir'] or '')) if clean else 'configured folder'
    other = [n for n in HOOKS if kinds[n] == "another tool's"]
    if other:
        return (f"new repositories: git's template ({where}) has another tool's {listed(other)} "
                f"{'hook' if len(other) == 1 else 'hooks'}")
    if all(k == 'in place' for k in kinds.values()):
        return f"new repositories: get the hooks from git's template ({where})"
    if all(k == 'none' for k in kinds.values()):
        return "new repositories: no hooks (telonion template puts them in git's template)"
    return f"new repositories: git's template ({where}): {_hooks_words(kinds, 'telonion template')}"


def cmd_template(a):
    done, words = template_off() if a.off else template_on(update=a.update)
    _say('.', words, 'Template checked' if done else 'Template update stopped')
    return 0 if done else 1


def _counts(words):
    """'3 patterns and 1 allow line', and what included files gave: ', 2 patterns of them from 1 included file'."""
    text = f'{_count(len(words.words), "pattern")} and {_count(len(words.allows) + len(words.publish_exact), "allow line")}'
    files, patterns, allows = words.included
    if files:
        text += (f', {_count(patterns, "pattern")}' + (f' and {_count(allows, "allow line")}' if allows else '')
                 + f' of them from {_count(files, "included file")}')
    return text


def _own_words(repo):
    """A repository's own list, counted ('2 patterns and 1 allow line'), or None when it has none."""
    path = own_words_path(repo)
    try:
        words = Words.read(path, 'repository word list', repository=True) if path else None
    except ListError as e:                         # its words name the list and the line
        return str(e)
    except OSError:
        return "the repository's word list could not be read"
    return f'{_home(path)}: {_counts(words)}' if words else None


def _words_line(path):
    try:
        words = Words.read(path, 'main word list')
    except ListError as e:
        return f'word list: {e}'
    except OSError:
        return 'word list: the main word list could not be read'
    if words is None:
        return f'word list: none at {_home(path)} (telonion words --init makes one)'
    return f'word list: {_home(path)}: {_counts(words)} (its lines are never printed)'


def cmd_words(a):
    path = own_words_path(a.C) if a.here else words_path(a.C)
    if a.init:
        if path is None:
            print('not a git repository')
            return 2
        if os.path.exists(path):
            _say(a.C, f'a word list is already at {_home(path)}: left as it is', 'A word list already exists')
            return 1
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(OWN_TEMPLATE if a.here else TEMPLATE)
        _say(a.C, f'word list made at {_home(path)}, readable by you alone: add one word or pattern a line',
             'Word list created')
        return 0
    clean, problem = _diagnostics(a.C)
    if problem:
        print(problem)
        return 0
    print(clean(_words_line(words_path(a.C))))
    own = _own_words(a.C)
    if own:
        print(clean(f"this repository's own: {own}"))
    return 0


def cmd_hook(a):
    if a.kind == 'pre-push':
        refs = sys.stdin.read()
        if a.preview_output:
            result = inspect_push(a.args, refs, os.getcwd(), first=a.first, preview=True)
            with open(a.preview_output, 'a', encoding='utf-8') as f:
                f.write(json.dumps(result) + '\n')
            return result[0]
        save = a.receipt or os.environ.get('TELONION_RECEIPT') == '1'
        code, lines = prepush(a.args, refs, first=a.first, save=save)
    else:
        code, lines = commit_hook(a.kind, a.args, first=a.first)
    for line in lines:
        print(line, file=sys.stderr)
    return code


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's message may repeat a URL, a ref, or a message supplied on the command line.
        raise _UsageError(self)


def main(argv):
    p = _Parser(prog='telonion', description=ABOUT, epilog=WORDS_HELP)
    p.add_argument('--version', action='version', version=f'{NAME} {VERSION}')
    sub = p.add_subparsers(dest='command', metavar='command')
    c = sub.add_parser('check', help='inspect a prepared directory, a live push, staged changes, or an offline estimate')
    c.add_argument('-C', default='.', metavar='DIR', help='the repository supplying policy and approvals (default: here)')
    c.add_argument('--remote', help='the remote to preview (Git’s default on a live check without refspecs; else origin)')
    how = c.add_mutually_exclusive_group()
    how.add_argument('--live', action='store_true', help='inspect the refs Git negotiates in a dry run; no upload hooks')
    how.add_argument('--all', action='store_true', help='read every commit the tip reaches, as before a first push')
    how.add_argument('--staged', action='store_true', help='read what is staged for the next commit, and who it is by, '
                                                           'as the pre-commit hook does')
    how.add_argument('--directory', metavar='DIR', help='inspect this exact prepared directory, relative to the caller')
    c.add_argument('--destination', metavar='TARGET', help='with --directory: the publish target from the upload settings')
    c.add_argument('--json', action='store_true', help='with --directory: one JSON result; exit 0 passed or 1 held '
                                                       '(with a tree digest), 2 incomplete (null digest)')
    said = c.add_mutually_exclusive_group()
    said.add_argument('-m', dest='message', metavar='MESSAGE', help='with --staged: a commit message to read too')
    said.add_argument('-F', dest='file', metavar='FILE', help='with --staged: a commit message to read too, from a file')
    c.add_argument('--receipt', action='store_true', help='save the live or directory decision in Git’s info/telonion-receipts/; '
                                                          'TELONION_RECEIPT=1 also saves receipts for live previews and Git pushes')
    c.add_argument('--follow-tags', action='store_true', help='include the tags Git would send with --follow-tags')
    c.add_argument('refs', nargs='*', metavar='REF', help='one tip for an offline estimate, or Git refspecs with --live')
    c.set_defaults(run=cmd_check)
    d = sub.add_parser('destination', help='approve a Git push endpoint or a direct publish destination')
    d.add_argument('-C', default='.', metavar='DIR', help='the repository')
    d.add_argument('remote', metavar='REMOTE', nargs='?')
    d.add_argument('--publish', metavar='TARGET', help='cloudflare-pages/ACCOUNT/PROJECT/production/BRANCH '
                                                       '(or preview/BRANCH); independent of Git remotes')
    mode = d.add_mutually_exclusive_group()
    mode.add_argument('--release', action='store_true', help='require approval for each name-only file version; '
                                                            'hold new or updated submodule pointers')
    mode.add_argument('--remove', action='store_true', help='withdraw this approval; unknown destinations remain held')
    d.set_defaults(run=cmd_destination)
    f = sub.add_parser('approve', help='approve one committed Git file or the exact bytes of a binary publish file')
    f.add_argument('-C', default='.', metavar='DIR', help='the repository')
    f.add_argument('--at', metavar='REV', help='commit containing the reviewed Git version (default: HEAD)')
    f.add_argument('--directory', metavar='DIR', help='prepared directory containing the reviewed file')
    f.add_argument('--destination', metavar='TARGET', help='with --directory: the enrolled publish target')
    f.add_argument('--remove', action='store_true', help='withdraw approval for this version at this destination')
    f.add_argument('remote', metavar='REMOTE', nargs='?')
    f.add_argument('path', metavar='PATH', help='file path relative to the repository or prepared directory root')
    f.set_defaults(run=cmd_approve)
    i = sub.add_parser('install', help="install pre-push, pre-commit, and commit-msg, keeping the repository's own hooks")
    i.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    i.add_argument('--update', action='store_true', help='the pre-push hook in place, and the commit hooks brought up '
                                                         'to date only where the repository has them: no commit check '
                                                         'is added (for moving repositories over to a new version)')
    i.set_defaults(run=cmd_install)
    u = sub.add_parser('uninstall', help="Telonion's hooks taken out of a repository, and its own put back")
    u.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    u.set_defaults(run=cmd_uninstall)
    s = sub.add_parser('status', help='hook health, remote names, destination approvals, and word-list counts')
    s.add_argument('repos', nargs='*', metavar='DIR')
    s.set_defaults(run=cmd_status)
    t = sub.add_parser('template', help="the hooks in git's template, for every repository made or cloned from now on")
    t.add_argument('--off', action='store_true', help="take them out of git's template again")
    t.add_argument('--update', action='store_true', help='the pre-push hook in place, and the commit hooks brought up '
                                                         "to date only where the template has them")
    t.set_defaults(run=cmd_template)
    w = sub.add_parser('words', help="where the word lists are (the main one and the repository's own), and how many "
                                     "lines each holds, with the files it includes", epilog=WORDS_HELP)
    w.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    w.add_argument('--init', action='store_true', help='make the word list, readable by you alone')
    w.add_argument('--here', action='store_true', help="with --init: make the repository's own list instead")
    w.set_defaults(run=cmd_words)
    h = sub.add_parser('hook', help="what git's hooks run: pre-push (refs on stdin), pre-commit, and commit-msg")
    h.add_argument('--as', dest='kind', choices=HOOKS, default='pre-push', help='which hook git runs (default: pre-push)')
    h.add_argument('--first', metavar='HOOK', help="the repository's own hook; push destination and transfer checks take precedence")
    h.add_argument('--preview-output', help=argparse.SUPPRESS)
    h.add_argument('--receipt', action='store_true', help='save the local decision, as with TELONION_RECEIPT=1')
    h.add_argument('args', nargs='*', metavar='ARG', help="what git gives the hook: the remote's name and URL "
                                                         "(pre-push), or the message file (commit-msg)")
    h.set_defaults(run=cmd_hook)
    try:
        a = p.parse_args(argv)
    except _UsageError as e:
        if argv[:1] == ['check'] and '--json' in argv:
            return _directory_result(incomplete('invalid_arguments'), [], True)
        parser = e.args[0]
        parser.print_usage(sys.stderr)
        print(f'{parser.prog}: invalid arguments; see --help', file=sys.stderr)
        return 2
    if not getattr(a, 'run', None):
        p.print_help()
        return 2
    try:
        return a.run(a)
    except (GitError, ListError) as e:
        print(f'{NAME}: {e}', file=sys.stderr)
    except (OSError, UnicodeError):
        print(f'{NAME}: the operation could not be completed', file=sys.stderr)
    return 2
