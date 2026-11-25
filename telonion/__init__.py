"""Telonion: reads what a git push would make public, and stops a push that holds a private word or a credential."""
import os

NAME = 'Telonion'
VERSION = '0.4.0'


def count(n, one, many=None):
    """'1 commit', '2 commits'."""
    return f'{n} {one if n == 1 else (many or one + "s")}'


def listed(items, word='and'):
    """'a', 'a and b', 'a, b, and c' (or with `word` 'or')."""
    items = list(items)
    if len(items) < 3:
        return f' {word} '.join(items)
    return f'{", ".join(items[:-1])}, {word} {items[-1]}'


def short_path(path):
    """A path under the home folder, written from ~."""
    home = os.path.expanduser('~')
    return '~' + path[len(home):] if path == home or path.startswith(home + os.sep) else path
