"""Push Gate: reads what a git push would make public, and stops a push that holds a private word or a credential."""
import os

NAME = 'Push Gate'
VERSION = '0.2.0'


def count(n, one, many=None):
    """'1 commit', '2 commits'."""
    return f'{n} {one if n == 1 else (many or one + "s")}'


def short_path(path):
    """A path under the home folder, written from ~."""
    home = os.path.expanduser('~')
    return '~' + path[len(home):] if path == home or path.startswith(home + os.sep) else path
