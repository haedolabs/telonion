"""The command, run as a person runs it."""
import os
import subprocess
import sys
import unittest

from _helpers import BIN, Box
from pushgate import NAME, VERSION


class Command(Box):
    def run_command(self, *args):
        return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, cwd=self.box)

    def test_the_word_list_is_counted_never_shown(self):
        self.assertIn('word list: none at', self.run_command('words').stdout)
        p = self.run_command('words', '--init')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(os.stat(self.words_file).st_mode & 0o777, 0o600)
        with open(self.words_file, 'a') as f:
            f.write('zephyr\nallow: zephyr-free\n')
        out = self.run_command('words').stdout
        self.assertIn('1 pattern and 1 allow line', out)
        self.assertNotIn('zephyr', out)
        self.assertEqual(self.run_command('words', '--init').returncode, 1, 'a list that exists was replaced')

    def test_check(self):
        self.words('zephyr\n')
        r = self.repo()
        self.commit(r, {'a.txt': 'fine\n'})
        p = self.run_command('check', '-C', r)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('nothing was fetched from origin', p.stdout)
        self.commit(r, {'b.txt': 'the zephyr notes\n'})
        p = self.run_command('check', '-C', r)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('the [private] notes', p.stdout)
        self.assertNotIn('zephyr', p.stdout)
        self.assertEqual(self.run_command('check', '-C', self.box).returncode, 2, 'not a repository')

    def test_the_list_named_in_git_settings(self):
        del os.environ['PUSHGATE_WORDS']
        listed = os.path.join(self.box, 'elsewhere', 'my words.txt')
        os.makedirs(os.path.dirname(listed))
        with open(listed, 'w') as f:
            f.write('zephyr\n')
        self.git(self.box, 'config', '--global', 'pushgate.words', listed)
        out = self.run_command('status', os.path.join(self.box, 'no-such-folder')).stdout
        self.assertIn('not a git repository', out)
        self.assertIn('~/elsewhere/my words.txt: 1 pattern', out)

    def test_status_install_and_version(self):
        r = self.repo()
        self.assertIn('no hook; no remote', self.run_command('status', r).stdout)
        self.assertEqual(self.run_command('install', '-C', r).returncode, 0)
        self.assertIn('the hook is in place', self.run_command('status', r).stdout)
        self.assertEqual(self.run_command('--version').stdout.strip(), f'{NAME} {VERSION}')


if __name__ == '__main__':
    unittest.main()
