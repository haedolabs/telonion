"""git's pre-push hook: the checks on every push, what the remote holds asked at push time, and the rewrite rule;
then the hook's place in a repository."""
import os
import shutil
import subprocess
import unittest

from _helpers import TOKEN, Box
from pushgate import hook
from pushgate.scan import ZERO


class PrePush(Box):
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

    def test_a_clean_push_goes(self):
        code, out = self.push(self.commit(self.r, {'c.txt': 'fine\n'}), self.base)
        self.assertEqual(code, 0, out)
        self.assertIn('1 commit, 1 added line, and 1 new file name read for origin: nothing private and no credentials', out)

    def test_a_private_word_stops_it_and_is_not_shown(self):
        code, out = self.push(self.commit(self.r, {'d.txt': 'the zephyr notes\n'}), self.base)
        self.assertEqual(code, 1, out)
        self.assertIn('the [private] notes', out)
        self.assertNotIn('zephyr', out)

    def test_a_credential_stops_it_and_is_not_shown(self):
        code, out = self.push(self.commit(self.r, {'e.txt': f'{TOKEN}\n'}), self.base)
        self.assertEqual(code, 1, out)
        self.assertIn('a GitHub token', out)
        self.assertNotIn(TOKEN, out)

    def test_rewrites_and_deletions(self):
        pushed = self.commit(self.r, {'f.txt': 'x\n'})
        self.git(self.r, 'push', '-q', 'origin', 'main')
        self.git(self.r, 'reset', '-q', '--hard', 'HEAD~1')
        other = self.commit(self.r, {'g.txt': 'y\n'})
        code, out = self.push(other, pushed)
        self.assertEqual(code, 1, out)
        self.assertIn('force push', out)
        os.environ['PUSHGATE_ALLOW_REWRITE'] = '1'
        self.assertEqual(self.push(other, pushed)[0], 0, 'one rewrite on purpose')
        del os.environ['PUSHGATE_ALLOW_REWRITE']
        self.git(self.r, 'config', 'pushgate.allowRewrite', 'true')
        self.assertEqual(self.push(other, pushed)[0], 0, 'the rule turned off for this repository')
        self.git(self.r, 'config', '--unset', 'pushgate.allowRewrite')
        code, out = self.push(other, 'ab' * 20)
        self.assertEqual(code, 1, out)
        self.assertIn('fetch and look at it first', out)
        code, out = hook.prepush(['origin', self.origin], f'(delete) {ZERO} refs/heads/main {pushed}\n', repo=self.r)
        self.assertEqual(code, 1, '\n'.join(out))

    def test_a_remote_made_again_empty_is_read_as_empty(self):
        # A word reached the remote once, by a push with no hook. The remote is then made again, empty, while this
        # checkout's remote-tracking ref still names the old commit: the hook asks the remote, so it reads them all.
        self.commit(self.r, {'old.txt': 'the zephyr notes\n'})
        self.git(self.r, 'push', '-q', 'origin', 'main')
        shutil.rmtree(self.origin)
        self.bare()
        tip = self.commit(self.r, {'new.txt': 'fine\n'})
        self.assertTrue(self.head(self.r, 'origin/main'), 'the checkout still remembers the old remote')
        code, out = self.push(tip, ZERO)
        self.assertEqual(code, 1, out)
        self.assertIn('old.txt:1', out)

    def test_ref_names_and_tags_pushed_by_name(self):
        code, out = self.push(self.base, ZERO, 'refs/heads/zephyr-plans')
        self.assertEqual(code, 1, out)
        self.assertNotIn('zephyr', out)
        self.git(self.r, 'tag', '-a', 'v1', '-m', 'the zephyr release')
        code, out = self.push(self.head(self.r, 'refs/tags/v1'), ZERO, 'refs/tags/v1')
        self.assertEqual(code, 1, out)
        self.assertIn('tag v1: the [private] release', out)

    def test_no_word_list_is_said(self):
        os.remove(self.words_file)
        code, out = self.push(self.commit(self.r, {'h.txt': 'zephyr\n'}), self.base)
        self.assertEqual(code, 0, out)
        self.assertIn('credentials were checked, private words were not', out)

    def own_hook(self, code):
        """A pre-push hook of the repository's own: it writes what it was given to a log, then exits with `code`."""
        path, log = os.path.join(self.box, 'own-hook'), os.path.join(self.box, 'own-hook.log')
        with open(path, 'w') as f:
            f.write(f'#!/bin/sh\n{{ echo "args: $*"; cat; }} > "{log}"\nexit {code}\n')
        os.chmod(path, 0o755)
        return path, log

    def test_the_repositorys_own_check_runs_first_with_what_git_gave(self):
        own, log = self.own_hook(0)
        tip = self.commit(self.r, {'c.txt': 'fine\n'})
        refs = f'refs/heads/main {tip} refs/heads/main {self.base}\n'
        code, lines = hook.prepush(['origin', self.origin], refs, repo=self.r, first=own)
        self.assertEqual(code, 0, lines)
        self.assertEqual(self.read(log), f'args: origin {self.origin}\n{refs}')
        self.assertIn('ran first and passed', '\n'.join(lines))

    def test_when_the_repositorys_own_check_stops_it_nothing_is_read(self):
        own, _ = self.own_hook(3)
        tip = self.commit(self.r, {'d.txt': 'the zephyr notes\n'})
        code, lines = hook.prepush(['origin', self.origin], f'refs/heads/main {tip} refs/heads/main {self.base}\n',
                                   repo=self.r, first=own)
        self.assertEqual(code, 3, lines)
        self.assertIn('did not read it', '\n'.join(lines))

    def test_a_hook_file_that_is_not_executable_is_skipped_as_git_skips_it(self):
        own, log = self.own_hook(1)
        os.chmod(own, 0o644)
        tip = self.commit(self.r, {'e.txt': 'fine\n'})
        code, lines = hook.prepush(['origin', self.origin], f'refs/heads/main {tip} refs/heads/main {self.base}\n',
                                   repo=self.r, first=own)
        self.assertEqual(code, 0, lines)
        self.assertFalse(os.path.exists(log))

    def test_a_list_that_cannot_be_read_stops_it(self):
        os.remove(self.words_file)
        os.makedirs(self.words_file)
        code, out = self.push(self.commit(self.r, {'h.txt': 'fine\n'}), self.base)
        self.assertEqual(code, 1, out)
        self.assertIn('could not be read', out)


class Install(Box):
    def test_the_hook_on_real_pushes(self):
        self.words('zephyr\n')
        r, origin = self.repo(), self.bare()
        self.commit(r, {'a.txt': 'start\n'})
        self.git(r, 'remote', 'add', 'origin', origin)
        done, words = hook.install(r)
        path = os.path.join(r, '.git', 'hooks', 'pre-push')
        self.assertTrue(done and 'written' in words, words)
        self.assertTrue(os.access(path, os.X_OK) and hook.MARK in self.read(path))
        self.assertIn('in place', hook.install(r)[1])
        self.commit(r, {'b.txt': f'{TOKEN}\n'})
        p = subprocess.run(['git', '-C', r, 'push', '-q', 'origin', 'main'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0, p.stderr)
        self.assertIn('stopped', p.stderr)
        self.assertNotIn(TOKEN, p.stderr)
        landed = subprocess.run(['git', '--git-dir', origin, 'rev-parse', '-q', '--verify', 'refs/heads/main'],
                                capture_output=True, text=True).stdout.strip()
        self.assertEqual(landed, '', 'something reached the remote')
        self.git(r, 'reset', '-q', '--hard', 'HEAD~1')
        p = subprocess.run(['git', '-C', r, 'push', '-q', 'origin', 'main'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Push Gate: 1 commit', p.stderr)

    def write(self, path, text):
        with open(path, 'w') as f:
            f.write(text)
        os.chmod(path, 0o755)

    def push(self, repo):
        return subprocess.run(['git', '-C', repo, 'push', '-q', 'origin', 'main'], capture_output=True, text=True)

    def test_the_repositorys_own_hook_is_kept_and_runs_first(self):
        self.words('zephyr\n')
        r, origin = self.repo(), self.bare()
        self.commit(r, {'a.txt': 'start\n'})
        self.git(r, 'remote', 'add', 'origin', origin)
        path, chained = (os.path.join(r, '.git', 'hooks', name) for name in ('pre-push', hook.CHAINED))
        log = os.path.join(self.box, 'own.log')
        own = f'#!/bin/sh\ncat > /dev/null\necho ran >> "{log}"\nexit 0\n'
        self.write(path, own)
        done, words = hook.install(r)
        self.assertTrue(done and 'runs first' in words, words)
        self.assertEqual(self.read(chained), own)
        self.assertTrue(os.access(chained, os.X_OK))
        self.assertEqual((hook.state(r)['hook'], hook.state(r)['chained']), ('in place', True))
        self.commit(r, {'b.txt': f'{TOKEN}\n'})
        p = self.push(r)
        self.assertNotEqual(p.returncode, 0, p.stderr)
        self.assertIn('stopped', p.stderr)
        self.assertEqual(self.read(log), 'ran\n', 'its own check ran first')
        self.git(r, 'reset', '-q', '--hard', 'HEAD~1')
        p = self.push(r)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('ran first and passed', p.stderr)
        self.assertEqual(self.read(log), 'ran\nran\n')
        self.write(chained, '#!/bin/sh\necho "refused by its own check" >&2\nexit 1\n')
        self.commit(r, {'c.txt': 'fine\n'})
        p = self.push(r)
        self.assertNotEqual(p.returncode, 0, p.stderr)
        self.assertIn('refused by its own check', p.stderr)
        self.assertIn('did not read it', p.stderr)
        done, words = hook.uninstall(r)
        self.assertTrue(done and 'put back' in words, words)
        self.assertFalse(os.path.lexists(chained))
        self.assertIn('refused by its own check', self.read(path))

    def test_the_tool_that_wrote_the_hook_writes_it_again(self):
        r = self.repo()
        path, chained = (os.path.join(r, '.git', 'hooks', name) for name in ('pre-push', hook.CHAINED))
        own = '#!/bin/sh\nexit 0\n'
        self.write(path, own)
        self.assertTrue(hook.install(r)[0])
        self.write(path, own)                      # the same hook, written again in its old place
        done, words = hook.install(r)
        self.assertTrue(done, words)
        self.assertEqual(hook.state(r)['hook'], 'in place')
        self.assertEqual(self.read(chained), own)
        self.write(path, '#!/bin/sh\nexit 2\n')    # a different one: nothing changes until a person keeps one
        done, words = hook.install(r)
        self.assertFalse(done)
        self.assertIn('look at both', words)
        self.assertEqual((self.read(path), self.read(chained)), ('#!/bin/sh\nexit 2\n', own))
        self.assertFalse(hook.uninstall(r)[0], "another tool's hook was taken out")

    def test_gits_template_gives_the_hook_to_new_repositories(self):
        self.assertEqual(hook.template_state()['hook'], 'none')
        done, words = hook.template_on()
        self.assertTrue(done, words)
        self.assertEqual(self.git(self.box, 'config', '--global', '--get', 'init.templateDir').strip(), hook.own_template())
        made, cloned = os.path.join(self.box, 'made'), os.path.join(self.box, 'cloned')
        subprocess.run(['git', 'init', '-q', made], check=True)
        subprocess.run(['git', 'clone', '-q', made, cloned], check=True, capture_output=True)
        self.assertEqual((hook.state(made)['hook'], hook.state(cloned)['hook']), ('in place', 'in place'))
        self.assertTrue(hook.template_on()[0], 'a second time changes nothing')
        done, words = hook.template_off()
        self.assertTrue(done, words)
        self.assertIsNone(hook.template_state()['dir'])
        later = os.path.join(self.box, 'later')
        subprocess.run(['git', 'init', '-q', later], check=True)
        self.assertEqual(hook.state(later)['hook'], 'none')

    def test_worktrees_and_folders_inside_share_the_hook(self):
        r = self.repo()
        self.commit(r, {'a.txt': 'x\n', 'sub/b.txt': 'y\n'})
        wt = os.path.join(self.box, 'wt')
        self.git(r, 'worktree', 'add', '-q', wt, '-b', 'side')
        self.assertTrue(hook.install(wt)[0])
        self.assertEqual(hook.state(r)['path'], os.path.join(r, '.git', 'hooks', 'pre-push'))
        self.assertEqual(hook.state(r)['hook'], 'in place')
        self.assertEqual(hook.state(os.path.join(r, 'sub'))['hook'], 'in place')

    def test_a_hooks_path_is_left_alone(self):
        r = self.repo()
        shared = os.path.join(self.box, 'shared-hooks')
        self.git(r, 'config', 'core.hooksPath', shared)
        done, words = hook.install(r)
        self.assertFalse(done)
        self.assertIn('core.hooksPath', words)
        self.assertFalse(os.path.exists(os.path.join(shared, 'pre-push')))

    def test_not_a_repository(self):
        self.assertEqual(hook.state(self.box)['hook'], 'not a repository')
        self.assertFalse(hook.install(self.box)[0])


if __name__ == '__main__':
    unittest.main()
