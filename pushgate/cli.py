"""The command: pushgate check, install, uninstall, status, words, and hook (what git's pre-push hook runs)."""
import argparse
import os
import sys

from . import NAME, VERSION, count as _count, short_path as _home
from .hook import install, prepush, state, uninstall
from .scan import GitError, Words, advertised, config, fetched, read_push, words_path

ABOUT = f'{NAME} reads what a git push would make public, and stops a push that holds a private word or a credential.'
WORDS_HELP = """The word list: $PUSHGATE_WORDS, else `git config pushgate.words`, else ~/.config/pushgate/words.txt. One
pattern a line (a regular expression, capitals and small letters alike; a line that is not a valid one is read as plain text),
`allow: <pattern>` for text that may appear though it holds a word, and # for notes. No hit is printed in full:
each names its place, with the word or credential masked."""
TEMPLATE = """# Push Gate's private word list. It lives outside every repository, and its lines are never printed.
# One pattern a line: a regular expression, capitals and small letters alike (a line that is not a valid one is read
# as plain text).
# `allow: <pattern>` marks text that may appear though it holds a word. A line that starts with # is a note.
"""


def cmd_check(a):
    repo = a.C
    path = words_path(repo)
    try:
        words = Words.read(path)
    except OSError as e:
        print(f'the word list at {_home(path)} could not be read ({e})')
        return 2
    try:
        if a.all:
            stop, against = [], f'every commit {a.tip} reaches'
        elif a.live:
            stop, against = advertised(repo, a.remote), f'what {a.remote} holds now'
        else:
            stop = fetched(repo, a.remote)
            against = (f'what this checkout last fetched from {a.remote}' if stop
                       else f'every commit {a.tip} reaches (nothing was fetched from {a.remote})')
        r = read_push(repo, [a.tip], stop, words, config(repo, 'pushgate.allowCode'))
    except GitError as e:
        print(f'nothing read: {e}')
        return 2
    print(f'{NAME}: {a.tip}, against {against}: {_count(r["commits"], "commit")}, {_count(r["lines"], "added line")}, '
          f'and {_count(r["files"], "new file name")}')
    if words is None:
        print(f'  private words: not read (no word list at {_home(path)}; pushgate words --init makes one)')
    else:
        print(f'  private words: {len(r["private"]) or "none"}')
        for where, text in r['private']:
            print(f'    {where}: {text}')
    print(f'  credentials: {len(r["credentials"]) or "none"}')
    for where, what, text in r['credentials']:
        print(f'    {what}: {where}: {text}')
    print(f'  new files that run code on a host or on install: {len(r["code"]) or "none"}')
    for where, name in r['code']:
        print(f'    {where}: {name}')
    return 1 if r['private'] or r['credentials'] or r['code'] else 0


def cmd_install(a):
    done, words = install(a.C)
    print(words)
    return 0 if done else 1


def cmd_uninstall(a):
    done, words = uninstall(a.C)
    print(words)
    return 0 if done else 1


def cmd_status(a):
    for repo in a.repos or ['.']:
        s = state(repo)
        if s['path'] is None:
            print(f'{_home(os.path.abspath(repo))}: not a git repository')
            continue
        hook = {'in place': 'the hook is in place', 'out of date': 'the hook is out of date (pushgate install renews it)',
                "another tool's": "another tool's pre-push hook", 'none': 'no hook'}[s['hook']]
        remotes = f"remotes: {', '.join(s['remotes'])}" if s['remotes'] else 'no remote'
        sent = f'; core.hooksPath: {_home(s["hooks_path"])}' if s['hooks_path'] else ''
        print(f'{_home(os.path.abspath(repo))}: {hook}; {remotes}{sent}')
    print(_words_line(words_path(a.repos[0] if a.repos else '.')))
    return 0


def _words_line(path):
    try:
        words = Words.read(path)
    except OSError as e:
        return f'word list: {_home(path)} could not be read ({e})'
    if words is None:
        return f'word list: none at {_home(path)} (pushgate words --init makes one)'
    return (f'word list: {_home(path)}: {_count(len(words.words), "pattern")} and '
            f'{_count(len(words.allows), "allow line")} (its lines are never printed)')


def cmd_words(a):
    path = words_path('.')
    if a.init:
        if os.path.exists(path):
            print(f'a word list is already at {_home(path)}: left as it is')
            return 1
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(TEMPLATE)
        print(f'word list made at {_home(path)}, readable by you alone: add one word or pattern a line')
        return 0
    print(_words_line(path))
    return 0


def cmd_hook(a):
    code, lines = prepush(a.args, sys.stdin.read())
    for line in lines:
        print(line, file=sys.stderr)
    return code


def main(argv):
    p = argparse.ArgumentParser(prog='pushgate', description=ABOUT, epilog=WORDS_HELP)
    p.add_argument('--version', action='version', version=f'{NAME} {VERSION}')
    sub = p.add_subparsers(dest='command', metavar='command')
    c = sub.add_parser('check', help='what the next push would make public, read now')
    c.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    c.add_argument('--remote', default='origin', help='the remote the push goes to (default: origin)')
    how = c.add_mutually_exclusive_group()
    how.add_argument('--live', action='store_true', help='ask the remote what it holds (git ls-remote)')
    how.add_argument('--all', action='store_true', help='read every commit the tip reaches, as before a first push')
    c.add_argument('tip', nargs='?', default='HEAD', help='what is pushed (default: HEAD)')
    c.set_defaults(run=cmd_check)
    i = sub.add_parser('install', help="the pre-push hook in a repository (its worktrees share it)")
    i.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    i.set_defaults(run=cmd_install)
    u = sub.add_parser('uninstall', help="Push Gate's hook taken out of a repository")
    u.add_argument('-C', default='.', metavar='DIR', help='the repository (default: here)')
    u.set_defaults(run=cmd_uninstall)
    s = sub.add_parser('status', help='each repository: the hook, the remotes; and the word list')
    s.add_argument('repos', nargs='*', metavar='DIR')
    s.set_defaults(run=cmd_status)
    w = sub.add_parser('words', help='where the word list is, and how many lines it holds')
    w.add_argument('--init', action='store_true', help='make the word list, readable by you alone')
    w.set_defaults(run=cmd_words)
    h = sub.add_parser('hook', help="what git's pre-push hook runs (refs on stdin)")
    h.add_argument('args', nargs='*', metavar='REMOTE URL')
    h.set_defaults(run=cmd_hook)
    a = p.parse_args(argv)
    if not getattr(a, 'run', None):
        p.print_help()
        return 2
    return a.run(a)
