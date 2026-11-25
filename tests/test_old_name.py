"""Telonion's old name, Push Gate: the hooks, settings, variables, and files it set up are still read, and
`telonion install` and `telonion template` move them over, so no repository is left without the hooks."""
import os
import subprocess
import sys
import unittest

from _helpers import ROOT, TOKEN, Box
from telonion import hook
from telonion.scan import own_words_path, read_words, words_path


def old_body(name):
    """The hook as Push Gate wrote it: its own mark, and its own command, bin/pushgate."""
    return (hook.hook_body(name).replace('Telonion', 'Push Gate').replace('telonion install', 'pushgate install')
            .replace(os.path.join('bin', 'telonion'), os.path.join('bin', 'pushgate')))


class OldName(Box):
    def setUp(self):
        super().setUp()
        self.r, self.origin = self.repo(), self.bare()
        self.commit(self.r, {'a.txt': 'start\n'})
        self.git(self.r, 'remote', 'add', 'origin', self.origin)

    def old_hooks(self):
        for n in hook.HOOKS:
            path = os.path.join(self.r, '.git', 'hooks', n)
            with open(path, 'w') as f:
                f.write(old_body(n))
            os.chmod(path, 0o755)

    def push(self):
        return subprocess.run(['git', '-C', self.r, 'push', '-q', 'origin', 'main'], capture_output=True, text=True)

    def test_the_old_command_runs_telonion(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'bin', 'pushgate'), '--version'], capture_output=True,
                           text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Telonion', p.stdout)

    def test_a_hook_push_gate_wrote_still_stops_a_push(self):
        self.words('zephyr\n')
        self.old_hooks()
        self.commit(self.r, {'b.txt': f'the zephyr notes\n{TOKEN}\n'})
        p = self.push()
        self.assertNotEqual(p.returncode, 0, p.stderr)
        self.assertIn('Telonion: the push to origin is stopped', p.stderr)
        self.assertNotIn('zephyr', p.stderr)
        self.assertNotIn(TOKEN, p.stderr)

    def test_a_hook_push_gate_wrote_is_out_of_date_and_replaced_not_chained(self):
        self.old_hooks()
        self.assertEqual({n: h['hook'] for n, h in hook.state(self.r)['hooks'].items()},
                         {n: 'out of date' for n in hook.HOOKS})
        done, words = hook.install(self.r)
        self.assertTrue(done, words)
        s = hook.state(self.r)
        self.assertEqual({n: h['hook'] for n, h in s['hooks'].items()}, {n: 'in place' for n in hook.HOOKS})
        self.assertFalse(any(h['chained'] for h in s['hooks'].values()), 'the old hook was kept as the repository\'s own')

    def test_an_update_adds_no_commit_check(self):
        with open(os.path.join(self.r, '.git', 'hooks', 'pre-push'), 'w') as f:
            f.write(old_body('pre-push'))
        own = os.path.join(self.r, '.git', 'hooks', 'pre-commit')
        with open(own, 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        done, words = hook.install(self.r, update=True)
        self.assertTrue(done, words)
        self.assertIn('every push from here', words)
        self.assertEqual({n: h['hook'] for n, h in hook.state(self.r)['hooks'].items()},
                         {'pre-push': 'in place', 'pre-commit': "another tool's", 'commit-msg': 'none'})
        bare = self.repo('bare-of-hooks')
        self.assertTrue(hook.install(bare, update=True)[0])
        self.assertEqual({n: h['hook'] for n, h in hook.state(bare)['hooks'].items()},
                         {'pre-push': 'in place', 'pre-commit': 'none', 'commit-msg': 'none'})
        self.old_hooks()
        self.assertTrue(hook.install(self.r, update=True)[0])
        self.assertEqual({n: h['hook'] for n, h in hook.state(self.r)['hooks'].items()},
                         {n: 'in place' for n in hook.HOOKS}, 'commit hooks it had were not brought up to date')

    def test_a_chained_hook_beside_an_old_one_stays_chained(self):
        self.old_hooks()
        chained = os.path.join(self.r, '.git', 'hooks', hook.CHAINED)
        with open(chained, 'w') as f:
            f.write('#!/bin/sh\necho own check >&2\nexit 1\n')
        os.chmod(chained, 0o755)
        self.assertTrue(hook.install(self.r)[0])
        self.assertIn('own check', self.read(chained))
        p = self.push()
        self.assertNotEqual(p.returncode, 0, p.stderr)
        self.assertIn('own check', p.stderr)

    def test_old_settings_and_variables_are_read(self):
        self.words('zephyr\n')
        self.git(self.r, 'config', 'pushgate.checkCommits', 'false')
        self.stage(self.r, {'c.txt': 'zephyr\n'})
        code, lines = hook.commit_hook('pre-commit', [], repo=self.r)
        self.assertEqual(code, 0, lines)
        self.assertIn('the commit check is off', '\n'.join(lines))
        self.git(self.r, 'config', 'telonion.checkCommits', 'true')
        self.assertEqual(hook.commit_hook('pre-commit', [], repo=self.r)[0], 1, 'the new setting comes first')
        other = os.path.join(self.box, 'other.txt')
        del os.environ['TELONION_WORDS']
        os.environ['PUSHGATE_WORDS'] = other
        self.assertEqual(words_path(self.r), other)

    def test_old_files_are_read_and_install_moves_them(self):
        del os.environ['TELONION_WORDS']
        main = os.path.join(self.box, '.config', 'pushgate', 'words.txt')
        os.makedirs(os.path.dirname(main))
        with open(main, 'w') as f:
            f.write('zephyr\n')
        self.assertEqual(words_path(self.r), main)
        own = os.path.join(self.r, '.git', 'info', 'pushgate-words')
        with open(own, 'w') as f:
            f.write('quillon\n')
        self.git(self.r, 'config', '--add', 'pushgate.allowCode', 'Makefile')
        self.assertEqual(own_words_path(self.r), own)
        self.assertEqual(len(read_words(self.r).words), 2)
        self.assertEqual(hook.state(self.r)['old'], ['info/pushgate-words', 'pushgate.* settings'])
        done, words = hook.install(self.r)
        self.assertTrue(done, words)
        self.assertIn('moved to the new name', words)
        self.assertFalse(os.path.exists(own))
        self.assertEqual(self.read(own_words_path(self.r)), 'quillon\n')
        self.assertEqual(self.git(self.r, 'config', '--get-all', 'telonion.allowCode').split(), ['Makefile'])
        self.assertEqual(hook.state(self.r)['old'], [])
        self.assertEqual(len(read_words(self.r).words), 2)

    def test_a_new_list_beside_an_old_one_is_left_to_a_person(self):
        info = os.path.join(self.r, '.git', 'info')
        for name in ('pushgate-words', 'telonion-words'):
            with open(os.path.join(info, name), 'w') as f:
                f.write(name + '\n')
        self.assertTrue(hook.install(self.r)[0])
        self.assertTrue(os.path.exists(os.path.join(info, 'pushgate-words')), 'a list was overwritten')

    def test_the_template_push_gate_made_moves_over(self):
        old = hook.old_template()
        os.makedirs(os.path.join(old, 'hooks'))
        for n in hook.HOOKS:
            with open(os.path.join(old, 'hooks', n), 'w') as f:
                f.write(old_body(n))
        self.git(self.box, 'config', '--global', 'init.templateDir', old)
        self.assertEqual(hook.template_state()['hooks'], {n: 'out of date' for n in hook.HOOKS})
        done, words = hook.template_on()
        self.assertTrue(done, words)
        self.assertEqual(self.git(self.box, 'config', '--global', '--get', 'init.templateDir').strip(),
                         hook.own_template())
        self.assertFalse(os.path.exists(old))
        self.assertEqual(hook.template_state()['hooks'], {n: 'in place' for n in hook.HOOKS})
        made = os.path.join(self.box, 'made')
        subprocess.run(['git', 'init', '-q', made], check=True)
        self.assertEqual(hook.state(made)['hook'], 'in place')


if __name__ == '__main__':
    unittest.main()
