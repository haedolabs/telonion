"""What the tests share: a fresh folder for each test, with git's global and system settings replaced and a made-up
word list, so no test reads or changes anything of the machine's."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BIN = os.path.join(ROOT, 'bin', 'telonion')
TOKEN = 'gh' + 'p_' + 'A1b2C3d4' * 5               # built here, so no file in this repository holds a token


class Box(unittest.TestCase):
    def setUp(self):
        self.box = os.path.realpath(tempfile.mkdtemp(prefix='telonion-test-'))
        self.addCleanup(shutil.rmtree, self.box, True)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        for key in [k for k in os.environ if k.startswith(('GIT_', 'TELONION_', 'PUSHGATE_'))]:
            del os.environ[key]
        gitconfig = os.path.join(self.box, 'gitconfig')
        open(gitconfig, 'w').close()
        self.words_file = os.path.join(self.box, 'words.txt')
        os.environ.update(HOME=self.box, GIT_CONFIG_GLOBAL=gitconfig, GIT_CONFIG_NOSYSTEM='1',
                          TELONION_WORDS=self.words_file, GIT_TERMINAL_PROMPT='0')

    def words(self, text):
        with open(self.words_file, 'w') as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def git(self, repo, *args):
        r = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(f'git {" ".join(args)}: {r.stderr.strip()}')
        return r.stdout

    def repo(self, name='repo'):
        path = os.path.join(self.box, name)
        os.makedirs(path)
        self.git(path, 'init', '-q', '-b', 'main')
        for key, value in (('user.email', 't@example.org'), ('user.name', 'T'), ('commit.gpgsign', 'false'),
                           ('tag.gpgsign', 'false')):
            self.git(path, 'config', key, value)
        return path

    def bare(self, name='origin.git'):
        path = os.path.join(self.box, name)
        subprocess.run(['git', 'init', '-q', '--bare', path], check=True)
        return path

    def stage(self, repo, files):
        """`files` written and staged for the next commit."""
        for name, text in files.items():
            path = os.path.join(repo, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write(text)
        self.git(repo, 'add', '-A')

    def commit(self, repo, files, message='c'):
        self.stage(repo, files)
        self.git(repo, 'commit', '-q', '--no-verify', '-m', message)
        return self.head(repo)

    def head(self, repo, ref='HEAD'):
        return self.git(repo, 'rev-parse', ref).strip()
