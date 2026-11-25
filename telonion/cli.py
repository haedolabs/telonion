"""The command: telonion check, install, uninstall, status, template, words, and hook (what git's hooks run)."""
import argparse
import os
import sys

from . import NAME, VERSION, count as _count, listed, short_path as _home
from .hook import HOOKS, commit_hook, install, prepush, state, template_off, template_on, template_state, uninstall
from .scan import (GitError, ListError, Words, advertised, config, fetched, own_words_path, read_commit, read_push,
                   read_words, setting, words_path)

ABOUT = (f'{NAME} reads what a git push would make public, and stops a push that holds a private word or a credential. '
         'Before each commit, it reads what the commit adds the same way.')
WORDS_HELP = """The word list: $TELONION_WORDS, else `git config telonion.words`, else ~/.config/telonion/words.txt. One
pattern a line (a regular expression, capitals and small letters alike; a line that is not a valid one is read as plain text),
`allow: <pattern>` for text that may appear though it holds a word, `include: <path>` for another list read as part of it
(a path from ~, or from the list's own folder; a file it names that is missing or cannot be read stops every push and
commit), and # for notes. No hit is printed in full: each names its place, with the word or credential masked.
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
# Its patterns add to the main list, and its `allow:` lines apply to this repository alone. Same format as the main
# list, `include:` lines too.
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


def cmd_check(a):
    repo = a.C
    if a.staged and a.tip:
        print('--staged reads what is staged for the next commit: it takes no tip')
        return 2
    if not a.staged and (a.message is not None or a.file):
        print('-m and -F go with --staged: a message is read with what the next commit adds')
        return 2
    path = words_path(repo)
    try:
        words = read_words(repo)
    except OSError as e:
        print(f'a word list could not be read ({e})')
        return 2
    if a.staged:
        message = a.message
        if a.file:
            try:
                with open(a.file, encoding='utf-8', errors='replace') as f:
                    message = f.read()
            except OSError as e:
                print(f'the message could not be read ({e})')
                return 2
        try:
            r = read_commit(repo, words, message=message)
        except GitError as e:
            print(f'nothing read: {e}')
            return 2
        print(f'{NAME}: the next commit, as staged: {_count(r["lines"], "added line")} and '
              f'{_count(r["files"], "new file name")}' + (', and its message' if message is not None else ''))
        return _report(r, words, path)
    tip = a.tip or 'HEAD'
    try:
        if a.all:
            stop, against = [], f'every commit {tip} reaches'
        elif a.live:
            stop, against = advertised(repo, a.remote), f'what {a.remote} holds now'
        else:
            stop = fetched(repo, a.remote)
            against = (f'what this checkout last fetched from {a.remote}' if stop
                       else f'every commit {tip} reaches (nothing was fetched from {a.remote})')
        r = read_push(repo, [tip], stop, words, setting(repo, 'allowCode', both=True))
    except GitError as e:
        print(f'nothing read: {e}')
        return 2
    print(f'{NAME}: {tip}, against {against}: {_count(r["commits"], "commit")}, {_count(r["lines"], "added line")}, '
          f'and {_count(r["files"], "new file name")}')
    return _report(r, words, path)


def cmd_install(a):
    done, words = install(a.C, update=a.update)
    print(words)
    return 0 if done else 1


def cmd_uninstall(a):
    done, words = uninstall(a.C)
    print(words)
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
    for kind in ('in place', 'out of date'):
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
    for repo in a.repos or ['.']:
        s = state(repo)
        if s['path'] is None:
            print(f'{_home(os.path.abspath(repo))}: not a git repository')
            continue
        hooks = _hooks_words({n: h['hook'] for n, h in s['hooks'].items()}, 'telonion install',
                             [n for n, h in s['hooks'].items() if h['chained']])
        if not s['commits']:
            hooks += '; the commit check is off here (telonion.checkCommits)'
        remotes = f"remotes: {', '.join(s['remotes'])}" if s['remotes'] else 'no remote'
        sent = f'; core.hooksPath: {_home(s["hooks_path"])}' if s['hooks_path'] else ''
        own = _own_words(repo)
        old = (f"; under Push Gate's names: {listed(s['old'])} (telonion install moves them)" if s['old'] else '')
        print(f'{_home(os.path.abspath(repo))}: {hooks}; {remotes}{sent}' + (f'; its own word list: {own}' if own else '')
              + old)
    print(_words_line(words_path(a.repos[0] if a.repos else '.')))
    print(_template_line())
    return 0


def _template_line():
    t = template_state()
    kinds, where = t['hooks'], _home(t['dir'] or '')
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
    done, words = template_off() if a.off else template_on()
    print(words)
    return 0 if done else 1


def _counts(words):
    """'3 patterns and 1 allow line', and what included files gave: ', 2 patterns of them from 1 included file'."""
    text = f'{_count(len(words.words), "pattern")} and {_count(len(words.allows), "allow line")}'
    files, patterns, allows = words.included
    if files:
        text += (f', {_count(patterns, "pattern")}' + (f' and {_count(allows, "allow line")}' if allows else '')
                 + f' of them from {_count(files, "included file")}')
    return text


def _own_words(repo):
    """A repository's own list, counted ('2 patterns and 1 allow line'), or None when it has none."""
    path = own_words_path(repo)
    try:
        words = Words.read(path) if path else None
    except ListError as e:                         # its words name the list and the line
        return str(e)
    except OSError as e:
        return f'{_home(path)} could not be read ({e})'
    return f'{_home(path)}: {_counts(words)}' if words else None


def _words_line(path):
    try:
        words = Words.read(path)
    except ListError as e:
        return f'word list: {e}'
    except OSError as e:
        return f'word list: {_home(path)} could not be read ({e})'
    if words is None:
        return f'word list: none at {_home(path)} (telonion words --init makes one)'
    return f'word list: {_home(path)}: {_counts(words)} (its lines are never printed)'


def cmd_words(a):
    path = own_words_path(a.C) if a.here else words_path(a.C)
    if a.init:
        if path is None:
            print(f'{a.C} is not a git repository')
            return 2
        if os.path.exists(path):
            print(f'a word list is already at {_home(path)}: left as it is')
            return 1
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(OWN_TEMPLATE if a.here else TEMPLATE)
        print(f'word list made at {_home(path)}, readable by you alone: add one word or pattern a line')
        return 0
    print(_words_line(words_path(a.C)))
    own = _own_words(a.C)
    if own:
        print(f"this repository's own: {own}")
    return 0


def cmd_hook(a):
    if a.kind == 'pre-push':
        code, lines = prepush(a.args, sys.stdin.read(), first=a.first)
    else:
        code, lines = commit_hook(a.kind, a.args, first=a.first)
    for line in lines:
        print(line, file=sys.stderr)
    return code


def main(argv):
    p = argparse.ArgumentParser(prog='telonion', description=ABOUT, epilog=WORDS_HELP)
    p.add_argument('--version', action='version', version=f'{NAME} {VERSION}')
    sub = p.add_subparsers(dest='command', metavar='command')
    c = sub.add_parser('check', help='what the next push would make public, or (--staged) what the next commit adds, '
                                     'read now')
    c.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    c.add_argument('--remote', default='origin', help='the remote the push goes to (default: origin)')
    how = c.add_mutually_exclusive_group()
    how.add_argument('--live', action='store_true', help='ask the remote what it holds (git ls-remote)')
    how.add_argument('--all', action='store_true', help='read every commit the tip reaches, as before a first push')
    how.add_argument('--staged', action='store_true', help='read what is staged for the next commit, and who it is by, '
                                                           'as the pre-commit hook does')
    said = c.add_mutually_exclusive_group()
    said.add_argument('-m', dest='message', metavar='MESSAGE', help='with --staged: a commit message to read too')
    said.add_argument('-F', dest='file', metavar='FILE', help='with --staged: a commit message to read too, from a file')
    c.add_argument('tip', nargs='?', help='what is pushed (default: HEAD)')
    c.set_defaults(run=cmd_check)
    i = sub.add_parser('install', help="Telonion's hooks in a repository: pre-push, pre-commit, and commit-msg (its "
                                       "worktrees share them); a hook the repository has of its own is kept and runs "
                                       "first")
    i.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    i.add_argument('--update', action='store_true', help='the pre-push hook in place, and the commit hooks brought up '
                                                         'to date only where the repository has them: no commit check '
                                                         'is added (for moving repositories over to a new version)')
    i.set_defaults(run=cmd_install)
    u = sub.add_parser('uninstall', help="Telonion's hooks taken out of a repository, and its own put back")
    u.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    u.set_defaults(run=cmd_uninstall)
    s = sub.add_parser('status', help='each repository: the hooks, the remotes; and the word list')
    s.add_argument('repos', nargs='*', metavar='DIR')
    s.set_defaults(run=cmd_status)
    t = sub.add_parser('template', help="the hooks in git's template, for every repository made or cloned from now on")
    t.add_argument('--off', action='store_true', help="take them out of git's template again")
    t.set_defaults(run=cmd_template)
    w = sub.add_parser('words', help="where the word lists are (the main one and the repository's own), and how many "
                                     "lines each holds, with the files it includes")
    w.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    w.add_argument('--init', action='store_true', help='make the word list, readable by you alone')
    w.add_argument('--here', action='store_true', help="with --init: make the repository's own list instead")
    w.set_defaults(run=cmd_words)
    h = sub.add_parser('hook', help="what git's hooks run: pre-push (refs on stdin), pre-commit, and commit-msg")
    h.add_argument('--as', dest='kind', choices=HOOKS, default='pre-push', help='which hook git runs (default: pre-push)')
    h.add_argument('--first', metavar='HOOK', help="the repository's own hook of that name, run before anything is read")
    h.add_argument('args', nargs='*', metavar='ARG', help="what git gives the hook: the remote's name and URL "
                                                         "(pre-push), or the message file (commit-msg)")
    h.set_defaults(run=cmd_hook)
    a = p.parse_args(argv)
    if not getattr(a, 'run', None):
        p.print_help()
        return 2
    return a.run(a)
