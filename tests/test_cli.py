"""The command, run as a person runs it."""
import os
import subprocess
import sys
import unittest

from _helpers import BIN, Box
from telonion import NAME, VERSION


class Command(Box):
    def run_command(self, *args):
        return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True, cwd=self.box)

    def test_the_word_list_is_counted_never_shown(self):
        self.assertIn('configured word list is missing', self.run_command('words').stdout)
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

    def test_a_repositorys_own_list(self):
        del os.environ['TELONION_WORDS']             # only the repository's list is selected
        r = self.repo()
        p = self.run_command('words', '--init', '--here', '-C', r)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        own = os.path.join(r, '.git', 'info', 'telonion-words')
        self.assertEqual(os.stat(own).st_mode & 0o777, 0o600)
        with open(own, 'a') as f:
            f.write('quokka\nallow: zephyr-notes\n')
        out = self.run_command('words', '-C', r).stdout
        self.assertIn("this repository's own: ", out)
        self.assertIn('1 pattern and 1 allow line', out)
        self.assertNotIn('quokka', out)
        self.assertIn('its own word list', self.run_command('status', r).stdout)

    def test_the_list_named_in_git_settings(self):
        del os.environ['TELONION_WORDS']
        listed = os.path.join(self.box, 'elsewhere', 'my words.txt')
        os.makedirs(os.path.dirname(listed))
        with open(listed, 'w') as f:
            f.write('zephyr\n')
        self.git(self.box, 'config', '--global', 'telonion.words', listed)
        out = self.run_command('status', os.path.join(self.box, 'no-such-folder')).stdout
        self.assertIn('not a git repository', out)
        self.assertIn('~/elsewhere/my words.txt: 1 pattern', out)

    def test_status_install_and_version(self):
        r = self.repo()
        out = self.run_command('status', r).stdout
        self.assertIn('no hooks (telonion install writes them); no remote', out)
        self.assertIn("new repositories: no hooks (telonion template puts them in git's template)", out)
        self.assertEqual(self.run_command('install', '-C', r).returncode, 0)
        self.assertIn('the hooks are in place; no remote', self.run_command('status', r).stdout)
        self.assertEqual(self.run_command('template').returncode, 0)
        self.assertIn("new repositories: get the hooks from git's template", self.run_command('status', r).stdout)
        self.assertEqual(self.run_command('--version').stdout.strip(), f'{NAME} {VERSION}')

    def test_status_names_each_hook(self):
        r = self.repo()
        own = os.path.join(r, '.git', 'hooks', 'pre-push')
        with open(own, 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(own, 0o755)
        self.assertEqual(self.run_command('install', '-C', r).returncode, 0)
        self.assertIn("the hooks are in place (after the repository's own pre-push hook); no remote",
                      self.run_command('status', r).stdout)
        for name in ('pre-commit', 'commit-msg'):
            os.remove(os.path.join(r, '.git', 'hooks', name))
        self.assertIn("the pre-push hook is in place (after the repository's own), no pre-commit or commit-msg hook "
                      "(telonion install puts them in place)", self.run_command('status', r).stdout)
        self.git(r, 'config', 'telonion.checkCommits', 'false')
        self.assertIn('the commit check is off here (telonion.checkCommits)', self.run_command('status', r).stdout)

    def test_status_strict_reports_unhealthy_protection(self):
        self.words('zephyr\n')
        r = self.repo()
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 1, 'no hooks')
        self.assertEqual(self.run_command('install', '-C', r).returncode, 0)
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 0)
        del os.environ['TELONION_WORDS']
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 0, 'credential-only policy is valid')
        os.environ['TELONION_WORDS'] = self.words_file
        os.remove(os.path.join(r, '.git', 'hooks', 'pre-commit'))
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 1, 'commit check without its hook')
        self.git(r, 'config', 'telonion.checkCommits', 'false')
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 0)
        self.git(r, 'config', '--unset', 'telonion.checkCommits')
        self.assertEqual(self.run_command('install', '-C', r).returncode, 0)
        os.remove(self.words_file)
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 1, 'selected policy is missing')
        self.words('zephyr\n')
        origin = self.bare()
        self.git(r, 'remote', 'add', 'origin', origin)
        self.assertEqual(self.run_command('destination', '-C', r, 'origin').returncode, 0)
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 0)
        self.git(r, 'remote', 'set-url', '--push', 'origin', self.bare('changed.git'))
        self.assertEqual(self.run_command('status', '--strict', r).returncode, 1, 'approved endpoint changed')
        self.assertEqual(self.run_command('status', r).returncode, 0, 'ordinary status remains a report')

    def test_check_staged(self):
        self.words('zephyr\n')
        r = self.repo()
        self.commit(r, {'a.txt': 'fine\n'})
        with open(os.path.join(r, 'b.txt'), 'w') as f:
            f.write('the zephyr notes\n')
        p = self.run_command('check', '--staged', '-C', r)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('the next commit, as staged: 0 added lines and 0 new file names', p.stdout)
        self.git(r, 'add', 'b.txt')
        p = self.run_command('check', '--staged', '-C', r)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('b.txt:1: the [private] notes', p.stdout)
        self.assertNotIn('zephyr', p.stdout)
        self.git(r, 'reset', '-q')
        p = self.run_command('check', '--staged', '-C', r, '-m', 'notes on zephyr')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('commit message: notes on [private]', p.stdout)
        message = os.path.join(self.box, 'message.txt')
        with open(message, 'w') as f:
            f.write('fine\n')
        self.assertEqual(self.run_command('check', '--staged', '-C', r, '-F', message).returncode, 0)
        self.assertEqual(self.run_command('check', '--staged', '-C', r, 'HEAD').returncode, 2, 'a tip with --staged')
        self.assertEqual(self.run_command('check', '-C', r, '-m', 'fine').returncode, 2, 'a message with no --staged')
        self.assertEqual(self.run_command('check', '--staged', '-C', self.box).returncode, 2, 'not a repository')

    def test_included_lines_are_counted_never_shown(self):
        names = os.path.join(self.box, 'quokka-lists', 'names.txt')
        os.makedirs(os.path.dirname(names))
        with open(names, 'w') as f:
            f.write('quokka\nwombat\nallow: quokka-free\n')
        self.words(f'zephyr\ninclude: {names}\n')
        out = self.run_command('words').stdout
        self.assertIn('3 patterns and 1 allow line, 2 patterns and 1 allow line of them from 1 included file', out)
        for hidden in ('quokka', 'wombat', 'zephyr'):
            self.assertNotIn(hidden, out)
        os.remove(names)
        r = self.repo()
        self.commit(r, {'a.txt': 'fine\n'})
        for args, code in ((['words'], 0), (['status', r], 0), (['check', '-C', r], 2), (['check', '--staged', '-C', r], 2)):
            p = self.run_command(*args)
            self.assertEqual(p.returncode, code, args)
            self.assertIn('main word list line 2: the file it includes is not there', p.stdout, args)
            self.assertNotIn('quokka', p.stdout, args)


if __name__ == '__main__':
    unittest.main()
