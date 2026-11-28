"""Credit lines: a Co-Authored-By or Assisted-by trailer, or a "Generated with" line, in a message that a push or a
commit makes public. Off unless telonion.holdCredits is true; the names here are made up."""
import os
import subprocess
import sys
import unittest

from _helpers import BIN, Box
from telonion import credits, hook
from telonion.scan import ZERO

CO = 'Co-Authored-By: Helper Bot <helper@example.org>'


class Lines(unittest.TestCase):
    def test_what_counts(self):
        text = '\n'.join(['Add the page', '', 'Explain the Co-Authored-By trailer in the guide.', CO,
                          'assisted-by: Some Model', '\U0001F916 Generated with [A Tool](https://example.org)',
                          'Generated-by: a tool', 'Generated files are kept.', '  co-authored-by : Someone'])
        self.assertEqual(credits.in_message(text), [
            ('commit message line 4', 'a Co-Authored-By line'), ('commit message line 5', 'an Assisted-by line'),
            ('commit message line 6', 'a "Generated" line'), ('commit message line 7', 'a "Generated" line'),
            ('commit message line 9', 'a Co-Authored-By line')])

    def test_nothing_in_an_ordinary_message(self):
        self.assertEqual(credits.in_message('Fix the gate\n\nThe co-author rule is explained in the guide.'), [])


class Push(Box):
    def setUp(self):
        super().setUp()
        self.words('zephyr\n')
        self.r, self.origin = self.repo(), self.bare()
        self.base = self.commit(self.r, {'a.txt': 'start\n'}, 'start')
        self.git(self.r, 'remote', 'add', 'origin', self.origin)
        self.git(self.r, 'push', '-q', 'origin', 'main')

    def push(self, lsha, rsha, lref='refs/heads/main', rref=None):
        code, lines = hook.prepush(['origin', self.origin], f'{lref} {lsha} {rref or lref} {rsha}\n', repo=self.r)
        return code, '\n'.join(lines)

    def credited(self, name='b.txt'):
        return self.commit(self.r, {name: 'b\n'}, f'Add {name}\n\n{CO}')

    def test_off_by_default(self):
        code, out = self.push(self.credited(), self.base)
        self.assertEqual(code, 0, out)
        self.assertNotIn('credit', out)

    def test_on_a_credit_line_stops_the_push(self):
        self.git(self.r, 'config', 'telonion.holdCredits', 'true')
        sha = self.credited()
        code, out = self.push(sha, self.base)
        self.assertEqual(code, 1, out)
        self.assertIn(f'commit {sha[:7]} message line 3: a Co-Authored-By line credits an assistant', out)
        self.assertIn('git config telonion.holdCredits false', out)
        self.assertNotIn('helper@example.org', out)

    def test_on_a_clean_push_says_so(self):
        self.git(self.r, 'config', 'telonion.holdCredits', 'true')
        code, out = self.push(self.commit(self.r, {'c.txt': 'c\n'}, 'c'), self.base)
        self.assertEqual(code, 0, out)
        self.assertIn('no private-word or credential matches, and no credit lines', out)

    def test_on_for_every_repository(self):
        self.git(self.r, 'config', '--global', 'telonion.holdCredits', 'true')
        self.assertEqual(self.push(self.credited(), self.base)[0], 1)

    def test_off_in_one_repository(self):
        self.git(self.r, 'config', '--global', 'telonion.holdCredits', 'true')
        self.git(self.r, 'config', 'telonion.holdCredits', 'false')
        self.assertEqual(self.push(self.credited(), self.base)[0], 0)

    def test_a_tag_message(self):
        self.git(self.r, 'config', 'telonion.holdCredits', 'true')
        self.git(self.r, 'tag', '-a', 'v1', '-m', 'v1\n\nGenerated with A Tool', self.base)
        code, out = self.push(self.head(self.r, 'refs/tags/v1'), ZERO, 'refs/tags/v1')
        self.assertEqual(code, 1, out)
        self.assertIn('tag v1 message line 3: a "Generated" line credits an assistant', out)

    def test_what_the_remote_holds_is_not_read_again(self):
        self.git(self.r, 'config', 'telonion.holdCredits', 'true')
        old = self.credited()
        self.git(self.r, 'push', '-q', '--no-verify', 'origin', 'main')
        code, out = self.push(self.commit(self.r, {'c.txt': 'c\n'}, 'c'), old)
        self.assertEqual(code, 0, out)


class Commit(Box):
    def setUp(self):
        super().setUp()
        self.words('zephyr\n')
        self.r = self.repo()
        self.commit(self.r, {'a.txt': 'start\n'}, 'start')

    def commit_msg(self, text):
        path = os.path.join(self.r, '.git', 'COMMIT_EDITMSG')
        with open(path, 'w') as f:
            f.write(text)
        code, lines = hook.commit_hook('commit-msg', [path], repo=self.r)
        return code, '\n'.join(lines)

    def test_off_by_default(self):
        self.assertEqual(self.commit_msg(f'b\n\n{CO}\n')[0], 0)

    def test_on_the_commit_is_stopped(self):
        self.git(self.r, 'config', 'telonion.holdCredits', 'true')
        code, out = self.commit_msg(f'b\n\n{CO}\n')
        self.assertEqual(code, 1, out)
        self.assertIn('commit message line 3: a Co-Authored-By line credits an assistant', out)
        self.assertIn('Nothing was committed: take it out of the message, then commit again.', out)

    def test_on_a_clean_message_says_so(self):
        self.git(self.r, 'config', 'telonion.holdCredits', 'true')
        code, out = self.commit_msg('b\n')
        self.assertEqual(code, 0, out)
        self.assertIn('the commit message read: nothing private, no credentials, and no credit lines', out)


class Check(Box):
    def run_command(self, *args):
        return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, cwd=self.box)

    def test_an_offline_estimate_and_a_staged_message(self):
        self.words('zephyr\n')
        r = self.repo()
        self.commit(r, {'a.txt': 'fine\n'}, f'a\n\n{CO}')
        self.assertNotIn('credit lines', self.run_command('check', '--all', '-C', r).stdout)
        self.git(r, 'config', 'telonion.holdCredits', 'true')
        p = self.run_command('check', '--all', '-C', r)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('credit lines: 1', p.stdout)
        self.assertIn('message line 3: a Co-Authored-By line', p.stdout)
        p = self.run_command('check', '--staged', '-C', r, '-m', f'b\n\n{CO}')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('commit message line 3: a Co-Authored-By line', p.stdout)


if __name__ == '__main__':
    unittest.main()
