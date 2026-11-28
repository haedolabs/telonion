"""Destination rules, the inspection receipt, and the push as negotiated by Git."""
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _helpers import BIN, TOKEN, Box
from telonion import hook
from telonion.scan import ZERO, read_push, read_words


class Inspection(Box):
    def setUp(self):
        super().setUp()
        self.words('quokka\n')
        self.r, self.origin = self.repo(), self.bare()
        self.git(self.r, 'remote', 'add', 'origin', self.origin)
        self.base = self.commit(self.r, {'notes.txt': 'first\n'})

    def command(self, *args):
        return subprocess.run([sys.executable, BIN, *args], cwd=self.r, capture_output=True, text=True)

    def live(self, *refs, receipt=False):
        args = ['check', '--live']
        if receipt:
            args.append('--receipt')
        return self.command(*args, *refs)

    def push(self, *refs):
        return subprocess.run(['git', 'push', 'origin', *refs], cwd=self.r, capture_output=True, text=True)

    def enable(self, release=False):
        p = self.command('destination', 'origin', *(['--release'] if release else []))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_an_explicit_list_is_required_in_each_entry_point(self):
        os.remove(self.words_file)
        self.git(self.r, 'config', 'telonion.words', self.words_file)
        del os.environ['TELONION_WORDS']
        self.assertTrue(hook.install(self.r)[0])
        for p in (self.command('check', '--staged'), self.command('check', '--all'), self.live('main'),
                  self.push('main'), self.command('hook', '--as', 'pre-commit')):
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('configured word list', p.stdout + p.stderr)

    def test_remote_labels_and_git_failures_do_not_repeat_inputs(self):
        name = 'quokka'
        self.git(self.r, 'remote', 'add', name, self.origin)
        refs = f'refs/heads/main {self.base} refs/heads/main {ZERO}\n'
        for remote in (name, 'https://name:made-up-address@example.invalid/repo'):
            code, lines = hook.prepush([remote, self.origin], refs, repo=self.r)
            self.assertEqual(code, 0, lines)
            self.assertNotIn(remote, '\n'.join(lines))
        p = self.command('check', '--all', 'quokka-missing')
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('quokka', p.stdout + p.stderr)

    def test_status_and_update_check_execution(self):
        self.assertTrue(hook.install(self.r, update=True)[0])
        path = Path(hook.hook_path(self.r))
        path.chmod(0o644)
        self.assertIn('not executable', self.command('status').stdout)
        self.assertTrue(hook.install(self.r, update=True)[0])
        self.assertTrue(os.access(path, os.X_OK))
        self.assertEqual(hook.state(self.r)['hooks']['pre-commit']['hook'], 'none')
        with patch.object(hook, 'LAUNCHER', str(path.parent / 'missing')):
            path.write_text(hook.hook_body())
            self.assertEqual(hook.state(self.r)['hook'], 'command unavailable')

    def test_replacement_objects_never_change_what_is_inspected(self):
        original = self.commit(self.r, {'payload.txt': 'quokka\n'}, 'original')
        self.git(self.r, 'reset', '-q', '--hard', self.base)
        replacement = self.commit(self.r, {'payload.txt': 'clean\n'}, 'replacement')
        self.git(self.r, 'update-ref', 'refs/heads/main', original)
        self.git(self.r, 'replace', original, replacement)
        self.assertTrue(hook.install(self.r, update=True)[0])
        p = self.push('main')
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('[private]', p.stdout + p.stderr)
        self.assertNotIn('quokka', p.stdout + p.stderr)
        self.assertEqual(self.git(self.r, 'ls-remote', 'origin'), '')

    def test_preview_and_hook_read_only_outgoing_tags(self):
        self.git(self.r, 'tag', '-a', 'v1', '-m', 'quokka')
        self.assertTrue(hook.install(self.r)[0])
        preview = self.live('main:refs/heads/release')
        self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
        self.assertEqual(self.git(self.r, 'ls-remote', 'origin'), '', 'preview sent a ref')
        real = self.push('main:refs/heads/release')
        self.assertEqual(real.returncode, 0, real.stderr)
        for p in (self.live('refs/tags/v1:refs/tags/published'), self.push('refs/tags/v1:refs/tags/published')):
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('tag v1', p.stdout + p.stderr)
            self.assertNotIn('quokka', p.stdout + p.stderr)
        self.assertIn('estimate', self.command('check').stdout)

    def test_default_refspecs_follow_tags_and_push_urls(self):
        target = self.bare('published.git')
        self.git(self.r, 'remote', 'set-url', '--push', 'origin', target)
        self.git(self.r, 'config', 'remote.origin.push', 'refs/heads/main:refs/heads/release')
        self.git(self.r, 'config', 'push.followTags', 'true')
        self.git(self.r, 'tag', '-a', 'v1', '-m', 'quokka')
        self.enable()
        self.assertTrue(hook.install(self.r)[0])
        for p in (self.live(), self.push()):
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('tag v1', p.stdout + p.stderr)
        self.git(self.r, 'config', 'push.followTags', 'false')
        self.assertEqual(self.live().returncode, 0)
        self.assertEqual(self.push().returncode, 0)
        self.assertTrue(self.git(self.r, 'ls-remote', target, 'refs/heads/release'))
        self.assertEqual(self.git(self.r, 'ls-remote', self.origin), '')

    def test_repointed_and_unknown_remotes_require_a_decision(self):
        self.enable()
        self.assertTrue(hook.install(self.r)[0])
        second = self.bare('second.git')
        self.git(self.r, 'remote', 'set-url', '--push', 'origin', second)
        for p in (self.live('main'), self.push('main')):
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('destination is not approved', p.stdout + p.stderr)
        self.assertEqual(self.git(self.r, 'ls-remote', second), '')
        self.enable()
        self.assertEqual(self.live('main').returncode, 0)
        self.git(self.r, 'remote', 'add', 'other', self.origin)
        self.assertNotEqual(self.command('check', '--live', '--remote', 'other', 'main').returncode, 0)
        self.assertEqual(self.command('destination', '--remove', 'origin').returncode, 0)
        self.assertNotEqual(self.live('main').returncode, 0)

    def test_opaque_versions_in_history_and_receipts(self):
        name = 'guide notes.pdf'
        self.commit(self.r, {name: 'version one\n'})
        self.commit(self.r, {name: 'version two\n'})
        self.enable(release=True)
        self.assertTrue(hook.install(self.r)[0])
        for p in (self.live('main'), self.push('main')):
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('checked by name only', p.stdout + p.stderr)
        receipts = Path(self.r, '.git', 'info', 'telonion-receipts')
        self.assertFalse(receipts.exists())
        self.assertEqual(self.command('approve', 'origin', name).returncode, 0)
        self.assertNotEqual(self.live('main').returncode, 0, 'an earlier version is still outgoing')
        self.assertEqual(self.command('approve', '--at', 'HEAD^', 'origin', name).returncode, 0)
        self.assertEqual(self.live('main', receipt=True).returncode, 0)
        saved, = receipts.glob('*.json')
        record = json.loads(saved.read_text())
        self.assertEqual((record['decision'], record['name_only'], record['source']), ('passed', 2, 'preview'))
        self.assertEqual((record['policy'], record['approved_files'], record['word_list_loaded']), ('release', 2, True))
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(name, saved.read_text())
        os.environ['TELONION_RECEIPT'] = '1'
        self.assertEqual(self.push('main').returncode, 0)
        self.assertEqual({json.loads(f.read_text())['source'] for f in receipts.glob('*.json')}, {'preview', 'hook'})
        self.git(self.r, 'remote', 'set-url', '--push', 'origin', self.bare('other.git'))
        self.enable(release=True)
        self.assertNotEqual(self.live('main').returncode, 0, 'old file approvals reached a new endpoint')

    def test_binary_changes_renames_and_deletions(self):
        asset = Path(self.r, 'odd\tname')
        asset.write_bytes(b'\0abc')
        self.commit(self.r, {})
        self.git(self.r, 'mv', asset.name, 'moved')
        self.commit(self.r, {})
        self.git(self.r, 'rm', 'moved')
        self.commit(self.r, {})
        self.enable(release=True)
        p = self.live('main')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('2 file versions checked by name only', p.stdout)
        for rev, path in (('HEAD^^', asset.name), ('HEAD^', 'moved')):
            self.assertEqual(self.command('approve', 'origin', path, '--at', rev).returncode, 0)
        self.assertEqual(self.live('main').returncode, 0)

    def test_release_holds_lfs_before_a_transfer_hook_and_preview_never_runs_it(self):
        pointer = 'version https://git-lfs.github.com/spec/v1\noid sha256:' + '1' * 64 + '\nsize 12\n'
        self.commit(self.r, {'picture': pointer})
        marker = Path(self.r, '.git', 'uploader-called')
        chain = Path(hook.hook_path(self.r))
        chain.write_text('#!/bin/sh\ntouch .git/uploader-called\n')
        chain.chmod(0o755)
        self.assertTrue(hook.install(self.r)[0])
        self.enable(release=True)
        for p in (self.live('main'), self.push('main')):
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('LFS', p.stdout + p.stderr)
            self.assertFalse(marker.exists())
        self.assertNotEqual(self.command('approve', 'origin', 'picture').returncode, 0)
        self.assertEqual(self.git(self.r, 'ls-remote', 'origin'), '')

    def test_a_receipt_never_keeps_the_excerpt_or_private_inputs(self):
        self.commit(self.r, {'notes.txt': f'unique context quokka {TOKEN}\n'})
        p = self.live('main', receipt=True)
        self.assertNotEqual(p.returncode, 0)
        saved, = Path(self.r, '.git', 'info', 'telonion-receipts').glob('*.json')
        self.assertEqual(json.loads(saved.read_text())['decision'], 'held')
        for text in ('unique context', 'quokka', TOKEN, self.origin, 'notes.txt'):
            self.assertNotIn(text, saved.read_text())

    def test_status_and_management_diagnostics_mask_selected_words(self):
        self.git(self.r, 'remote', 'rename', 'origin', 'quokka')
        for args in (('status',), ('destination', 'quokka'), ('status',), ('unknown-quokka',)):
            p = self.command(*args)
            self.assertNotIn('quokka', p.stdout + p.stderr)
        self.git(self.r, 'remote', 'set-url', '--push', 'quokka', self.bare('changed.git'))
        self.assertIn('endpoint changed', self.command('status').stdout)
        path = Path(self.box, 'quokka-repo')
        os.rename(self.r, path)
        self.r = str(path)
        for args in (('install',), ('status',), ('uninstall',), ('words', '--here', '--init')):
            p = self.command(*args)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertNotIn('quokka', p.stdout + p.stderr)

    def test_the_preview_inspection_returns_the_real_decision(self):
        self.commit(self.r, {'notes.txt': 'quokka\n'})
        refs = f'refs/heads/main {self.head(self.r)} refs/heads/main {ZERO}\n'
        with TemporaryDirectory(dir=self.box) as folder:
            p = subprocess.run([sys.executable, BIN, 'hook', '--preview-output', folder + '/result',
                                '--', 'origin', self.origin], input=refs, cwd=self.r, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertNotIn('quokka', Path(folder, 'result').read_text())

    def test_a_dry_run_of_multiple_refs_and_a_deletion(self):
        self.git(self.r, 'branch', 'side')
        self.assertTrue(hook.install(self.r)[0])
        self.assertEqual(self.live('main', 'side').returncode, 0)
        self.assertEqual(self.push('main', 'side').returncode, 0)
        for p in (self.live(':refs/heads/side'), self.push(':refs/heads/side')):
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('deletes refs/heads/side', p.stdout + p.stderr)

    def test_an_upload_hook_is_deferred_and_its_refusal_still_counts(self):
        self.commit(self.r, {'notes.txt': 'quokka\n'})
        path = Path(hook.hook_path(self.r))
        path.write_text('#!/bin/sh\ncat > .git/upload-refs\nexit 3\n')
        path.chmod(0o755)
        self.git(self.r, 'config', 'telonion.transferHook', 'true')
        self.assertTrue(hook.install(self.r)[0])
        self.assertNotEqual(self.push('main').returncode, 0)
        log = Path(self.r, '.git', 'upload-refs')
        self.assertFalse(log.exists())
        ref = self.base + ':refs/heads/first'
        self.assertEqual(self.live(ref).returncode, 0)
        self.assertFalse(log.exists())
        self.assertNotEqual(self.push(ref).returncode, 0)
        self.assertIn('refs/heads/first', log.read_text())
        self.assertEqual(self.git(self.r, 'ls-remote', 'origin'), '')

    def test_file_approval_can_be_withdrawn_and_cannot_clear_a_private_name(self):
        self.commit(self.r, {'guide.pdf': 'test\n'})
        self.enable(release=True)
        for _ in range(2):
            self.assertEqual(self.command('approve', 'origin', 'guide.pdf').returncode, 0)
        self.assertEqual(self.live('main').returncode, 0)
        self.assertEqual(self.command('approve', '--remove', 'origin', 'guide.pdf').returncode, 0)
        self.assertNotEqual(self.live('main').returncode, 0)
        self.git(self.r, 'mv', 'guide.pdf', 'quokka.pdf')
        self.commit(self.r, {})
        self.assertEqual(self.command('approve', '--at', 'HEAD^', 'origin', 'guide.pdf').returncode, 0)
        self.assertEqual(self.command('approve', 'origin', 'quokka.pdf').returncode, 0)
        p = self.live('main')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('[private].pdf', p.stdout)

    def test_an_explicitly_missing_policy_never_renders_a_raw_location(self):
        missing = str(Path(self.box, 'quokka-missing'))
        os.environ['TELONION_WORDS'] = missing
        for args in (('status',), ('words',), ('check', '--staged'), ('check', '--live', 'main')):
            p = self.command(*args)
            self.assertIn('configured word list is missing', p.stdout + p.stderr)
            self.assertNotIn('quokka', p.stdout + p.stderr)

    def test_relative_endpoints_are_bound_in_repository_context(self):
        sub = Path(self.r, 'nested')
        sub.mkdir()
        self.git(self.r, 'remote', 'set-url', '--push', 'origin', '../origin.git')
        p = self.command('destination', '-C', str(sub), 'origin')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.live('main').returncode, 0)

    def test_adding_a_second_push_url_holds_the_first_transfer_too(self):
        self.git(self.r, 'remote', 'set-url', '--push', 'origin', self.origin)
        self.enable()
        self.assertTrue(hook.install(self.r)[0])
        second = self.bare('second.git')
        self.git(self.r, 'remote', 'set-url', '--add', '--push', 'origin', second)
        for p in (self.live('main'), self.push('main')):
            self.assertNotEqual(p.returncode, 0)
        for url in (self.origin, second):
            self.assertEqual(self.git(self.r, 'ls-remote', url), '')

    def test_a_transfer_setting_without_a_chained_hook_agrees_in_preview(self):
        self.assertTrue(hook.install(self.r)[0])
        self.git(self.r, 'config', 'telonion.transferHook', 'true')
        self.enable()
        self.assertEqual(self.live('main').returncode, 0)
        self.assertEqual(self.push('main').returncode, 0)

    def test_name_only_inventory_itself_contains_no_private_path(self):
        self.commit(self.r, {'quokka.pdf': 'picture\n'})
        r = read_push(self.r, ['HEAD'], words=read_words(self.r))
        self.assertTrue(r['opaque'])
        self.assertNotIn('quokka', repr(r))

    def test_an_unmodified_wrapper_from_before_destination_rules_still_checks(self):
        self.assertTrue(hook.install(self.r, update=True)[0])
        path = Path(hook.hook_path(self.r))
        path.write_text(f'#!/bin/sh\n# {hook.MARK}\nexec "{sys.executable}" "{BIN}" hook '
                        '--first "$(dirname "$0")/pre-push.chained" "$@"\n')
        self.assertEqual(hook.state(self.r)['hook'], 'out of date')
        self.enable()
        self.git(self.r, 'remote', 'set-url', '--push', 'origin', self.bare('other.git'))
        self.assertNotEqual(self.push('main').returncode, 0)
        self.assertTrue(hook.install(self.r, update=True)[0])
        self.assertEqual(hook.state(self.r)['hooks']['commit-msg']['hook'], 'none')

    def test_a_failed_negotiation_saves_only_an_incomplete_receipt(self):
        p = self.live('no-such-ref', receipt=True)
        self.assertNotEqual(p.returncode, 0)
        saved, = Path(self.r, '.git', 'info', 'telonion-receipts').glob('*.json')
        record = json.loads(saved.read_text())
        self.assertEqual(record['decision'], 'incomplete')
        self.assertFalse(record['inspected'])
        self.assertNotIn('no-such-ref', saved.read_text())

    def test_nested_tags_are_inspected_by_object(self):
        self.git(self.r, 'tag', '-a', 'inner', '-m', 'quokka')
        self.git(self.r, 'tag', '-a', 'outer', 'inner', '-m', 'ready')
        self.assertTrue(hook.install(self.r)[0])
        ref = self.head(self.r, 'refs/tags/outer') + ':refs/tags/release'
        for p in (self.live(ref), self.push(ref)):
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('tag inner', p.stdout + p.stderr)
            self.assertNotIn('quokka', p.stdout + p.stderr)
