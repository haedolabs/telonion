"""The direct publisher's contract, exercised without a Git remote or a publishing service."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from _helpers import BIN, TOKEN, Box


ACCOUNT = 'a' * 32
TARGET = f'cloudflare-pages/{ACCOUNT}/example/production/main'


class Directory(Box):
    def setUp(self):
        super().setUp()
        self.repo_dir = self.repo()
        self.root = Path(self.box, 'prepared')
        self.root.mkdir()
        self.words('quokka\n')
        self.saved = Path(self.repo_dir, '.git/info/telonion-receipts')

    def command(self, *args):
        return subprocess.run([sys.executable, BIN, *args], cwd=self.box, capture_output=True, text=True, timeout=20)

    def enroll(self, target=TARGET, *options):
        result = self.command('destination', '-C', self.repo_dir, '--publish', target, *options)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def approve(self, name, *options, target=TARGET):
        return self.command('approve', '-C', self.repo_dir, '--directory', 'prepared', '--destination', target,
                            *options, '--', name)

    def check(self, code, *options, target=TARGET, repo=None, directory='prepared'):
        p = self.command('check', '-C', repo or self.repo_dir, '--directory', directory, '--destination', target,
                         '--json', *options)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        self.assertEqual(p.stderr, '')
        self.assertEqual(len(p.stdout.splitlines()), 1)
        record = json.loads(p.stdout)
        self.assertEqual(record['decision'], ('passed', 'held', 'incomplete')[code])
        if code == 2:
            self.assertIsNone(record['tree_digest'])
        else:
            self.assertRegex(record['tree_digest'], r'^tree-v1:sha256:[0-9a-f]{64}$')
        return record

    def test_stage_is_independent_of_git_and_destination_enrollment(self):
        self.stage(self.repo_dir, {'index.html': 'quokka\n'})
        (self.root / 'index.html').write_text('ready')
        held = self.check(1)
        self.assertEqual(held['reasons'], ['destination_unapproved'])
        self.enroll()
        self.enroll()
        passed = self.check(0)
        self.assertEqual(passed['files'], 1)
        self.assertEqual(passed['tree_digest'], held['tree_digest'])
        self.assertRegex(passed['destination_id'], r'^sha256:[0-9a-f]{64}$')
        self.assertFalse(self.saved.exists())
        self.assertEqual(self.git(self.repo_dir, 'remote'), '')
        self.assertEqual(self.git(self.repo_dir, 'config', '--name-only', '--get-regexp', '^telonion\\.'),
                         'telonion.publishdestination\n')
        self.enroll(TARGET, '--remove')
        self.assertEqual(self.check(1)['reasons'], ['destination_unapproved'])

    def test_words_come_from_the_selected_repository_including_its_own_list(self):
        self.enroll()
        own = Path(self.repo_dir, '.git/info/telonion-words')
        included = Path(self.box, 'included')
        included.write_text('sandpiper\n')
        own.write_text(f'include: {included}\nallow: quokka guide\n')
        (self.root / '.gitignore').write_text('.hidden\n')
        page = self.root / '.hidden'
        page.write_text('quokka guide\n')
        self.assertEqual(self.check(0)['files'], 2)
        page.write_text('sandpiper')
        self.assertEqual(self.check(1)['reasons'], ['private_word'])
        included.unlink()
        self.assertEqual(self.check(2)['reasons'], ['policy_unavailable'])
        own.unlink()
        del os.environ['TELONION_WORDS']
        self.assertEqual(self.check(0)['reasons'], [])

    def test_exact_publish_text_uses_the_original_line_in_its_repository_only(self):
        from telonion.scan import read_words

        self.words('quokka\nallow: public label\n')
        line = '  Public label: quokka [2].\t'
        included = Path(self.box, 'local-list')
        included.write_text('publish-exact: ' + json.dumps(line) + '\n')
        own = Path(self.repo_dir, '.git/info/telonion-words')
        own.write_text(f'include: {included}\n')
        page = self.root / 'page.txt'
        page.write_bytes((line + '\r\n').encode())
        self.enroll()
        self.check(0)
        self.assertTrue(read_words(self.repo_dir).spans(line), 'Git and diagnostic masking must still see the word')
        self.assertIn('private_word', self.check(1, repo=self.repo('other'))['reasons'])
        for changed in (line.strip(), line.lower(), line + ' extra', 'prefix ' + line, line + '\nquokka'):
            with self.subTest(changed=changed):
                page.write_text(changed)
                self.assertEqual(self.check(1)['reasons'], ['private_word'])

    def test_exact_publish_path_and_line_do_not_approve_a_binary_or_a_credential(self):
        own = Path(self.repo_dir, '.git/info/telonion-words')
        name = 'quokka.png'
        text = 'quokka ' + TOKEN
        own.write_text(''.join('publish-exact: ' + json.dumps(s) + '\n' for s in (name, text)))
        asset = self.root / name
        asset.write_text(text)
        self.enroll()
        self.assertEqual(self.check(1)['reasons'], ['binary_unapproved', 'credential'])
        self.assertEqual(self.approve(name).returncode, 0)
        self.assertEqual(self.check(1)['reasons'], ['credential'])
        asset.rename(self.root / ('other-' + name))
        self.assertIn('private_word', self.check(1)['reasons'])

    def test_exact_publish_entries_require_a_local_list_and_a_single_json_string(self):
        own = Path(self.repo_dir, '.git/info/telonion-words')
        self.enroll()
        for value in ('quokka', '["quokka"]', '""', '"one\\ntwo"', '"one\\u0000two"'):
            with self.subTest(value=value):
                own.write_text('publish-exact: ' + value + '\n')
                self.assertEqual(self.check(2)['reasons'], ['policy_unavailable'])
        own.unlink()
        self.words('publish-exact: "quokka"\n')
        self.assertEqual(self.check(2)['reasons'], ['policy_unavailable'])

    def test_relative_configured_list_and_inherited_git_directory_use_the_selected_repository(self):
        self.enroll()
        del os.environ['TELONION_WORDS']
        self.git(self.repo_dir, 'config', 'telonion.words', 'list.txt')
        Path(self.repo_dir, 'list.txt').write_text('sandpiper\n')
        Path(self.box, 'list.txt').write_text('unrelated\n')
        nested = Path(self.repo_dir, 'nested')
        nested.mkdir()
        other = self.repo('another-repo')
        os.environ['GIT_DIR'] = str(Path(other, '.git'))
        (self.root / 'index.html').write_text('sandpiper\n')
        self.assertEqual(self.check(1, repo=nested)['reasons'], ['private_word'])
        self.enroll(TARGET, '--remove')
        self.assertNotIn('publishdestination', Path(other, '.git/config').read_text().lower())

    def test_git_and_publish_approvals_do_not_authorize_each_other(self):
        self.git(self.repo_dir, 'remote', 'add', 'origin', self.bare())
        self.assertEqual(self.command('destination', '-C', self.repo_dir, '--release', 'origin').returncode, 0)
        self.commit(self.repo_dir, {'asset.pdf': 'unchanged'})
        self.assertEqual(self.command('approve', '-C', self.repo_dir, 'origin', 'asset.pdf').returncode, 0)
        (self.root / 'asset.pdf').write_text('unchanged')
        self.assertIn('destination_unapproved', self.check(1)['reasons'])
        self.enroll()
        self.assertEqual(self.check(1)['reasons'], ['binary_unapproved'])
        self.assertEqual(self.approve('asset.pdf').returncode, 0)
        self.assertEqual(self.command('approve', '-C', self.repo_dir, '--remove', 'origin', 'asset.pdf').returncode, 0)
        self.assertEqual(self.check(0)['binary_approved'], 1)
        p = self.command('check', '-C', self.repo_dir, '--live', 'main')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('no approval for release', p.stdout)

    def test_binary_approval_binds_the_account_project_environment_branch_path_and_bytes(self):
        self.enroll()
        asset = self.root / 'asset.bin'
        asset.write_bytes(b'\0one')
        first = self.check(1)
        self.assertEqual((first['binary'], first['binary_approved'], first['reasons']), (1, 0, ['binary_unapproved']))
        for _ in range(2):
            self.assertEqual(self.approve('asset.bin').returncode, 0)
        self.assertEqual(self.check(0)['binary_approved'], 1)
        for other in (TARGET.replace(ACCOUNT, 'b' * 32), TARGET.replace('example', 'another'),
                      TARGET.replace('production', 'preview'), TARGET.replace('main', 'topic/One')):
            self.assertNotEqual(self.check(1, target=other)['destination_id'], first['destination_id'])
            self.enroll(other)
            self.assertEqual(self.check(1, target=other)['reasons'], ['binary_unapproved'])
        asset.rename(self.root / 'other.bin')
        self.assertEqual(self.check(1)['binary_approved'], 0)
        (self.root / 'other.bin').rename(asset)
        asset.write_bytes(b'\0two')
        self.assertNotEqual(self.check(1)['tree_digest'], first['tree_digest'])
        asset.write_bytes(b'\0one')
        self.assertEqual(self.check(0)['tree_digest'], first['tree_digest'])
        self.assertEqual(self.approve('asset.bin', '--remove').returncode, 0)
        self.assertEqual(self.check(1)['binary_approved'], 0)

    def test_destination_id_can_be_computed_from_the_upload_settings(self):
        branch = 'Feature/café'
        parts = ['publish-destination-v1', 'cloudflare-pages', ACCOUNT, 'example', 'preview', branch]
        key = hashlib.sha256(b'\0'.join(s.encode('utf-8') for s in parts)).hexdigest()
        target = '/'.join(parts[1:])
        self.enroll(target.replace(ACCOUNT, ACCOUNT.upper()))
        self.assertEqual(self.check(0, target=target)['destination_id'], 'sha256:' + key)
        self.assertNotEqual(self.check(1, target=target.lower())['destination_id'], 'sha256:' + key)

    def test_approval_uses_the_exact_path_listed_in_the_tree(self):
        self.enroll()
        folder = self.root / 'assets'
        folder.mkdir()
        (folder / 'logo.png').write_bytes(b'\0asset')
        for other in ('ASSETS/logo.png', 'assets/Logo.png'):
            self.assertNotEqual(self.approve(other).returncode, 0)
        self.assertEqual(self.approve('assets/logo.png').returncode, 0)
        self.assertEqual(self.check(0)['binary_approved'], 1)

    def test_directory_digest_has_independent_framing_and_ignores_machine_metadata(self):
        self.enroll()
        empty = self.check(0)['tree_digest']
        entries = {b'.dot': b'one\r\n', b'a': None, b'a/x\ny': b'', b'a-': b'two', b'empty': None}
        expected = hashlib.sha256(b'telonion-tree-v1\0')
        for path, body in sorted(entries.items()):
            file = self.root / os.fsdecode(path)
            if body is None:
                file.mkdir()
            else:
                file.write_bytes(body)
            expected.update((b'D' if body is None else b'F') + len(path).to_bytes(8, 'big') + path)
            if body is not None:
                expected.update(hashlib.sha256(body).digest())
        digest = self.check(0)['tree_digest']
        self.assertNotEqual(digest, empty)
        self.assertEqual(digest, 'tree-v1:sha256:' + expected.hexdigest())
        copy = Path(self.box, 'second-stage')
        shutil.copytree(self.root, copy)
        (copy / '.dot').chmod(0o400)
        os.utime(copy / 'a-')
        self.assertEqual(self.check(0, directory=copy)['tree_digest'], digest)
        (copy / 'empty').rmdir()
        self.assertNotEqual(self.check(0, directory=copy)['tree_digest'], digest)

    def test_publication_receipt_is_private_for_held_passed_and_incomplete(self):
        target = TARGET.replace('example', 'quokka-site')
        self.enroll(target)
        name = 'quokka-private.pdf'
        (self.root / name).write_text('some unpublished context ' + TOKEN)
        self.assertEqual(self.approve(name, target=target).returncode, 0)
        held = self.check(1, '--receipt', target=target)
        self.assertEqual(held['reasons'], ['credential', 'private_word'])
        self.assertEqual(held['binary_approved'], 1)
        (self.root / name).unlink()
        passed = self.check(0, '--receipt', target=target)
        os.unlink(self.words_file)
        incomplete = self.check(2, '--receipt', target=target)
        records = list(self.saved.glob('*.json'))
        self.assertCountEqual([json.loads(path.read_text()) for path in records], [held, passed, incomplete])
        for path in records:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            for text in ('quokka', TOKEN, ACCOUNT, 'unpublished', self.box, 'example', '.pdf'):
                self.assertNotIn(text, path.read_text())
        config = Path(self.repo_dir, '.git/config').read_text()
        for text in ('quokka', name, ACCOUNT, TARGET):
            self.assertNotIn(text, config)

    def test_text_and_name_checks_cannot_be_waived_by_file_approval(self):
        self.enroll()
        hidden_dir = self.root / 'quokka'
        hidden_dir.mkdir()
        (self.root / '.env').write_bytes(b'\0')
        self.assertEqual(self.approve('.env').returncode, 0)
        self.assertEqual(self.check(1)['reasons'], ['credential', 'private_word'])
        hidden_dir.rmdir()
        (self.root / '.env').rename(self.root / '.env.example')
        self.assertEqual(self.check(1)['reasons'], ['binary_unapproved'])
        (self.root / '.env.example').unlink()
        (self.root / 'page.svg').write_text('A' * (128 * 1024 - 3) + 'quokka\rpublic\n')
        self.assertEqual(self.check(1)['reasons'], ['private_word'])
        (self.root / 'page.svg').unlink()
        (self.root / 'Makefile').write_text('all:\n')
        self.assertEqual(self.check(1)['reasons'], ['code_file'])
        self.git(self.repo_dir, 'config', 'telonion.allowCode', 'Makefile')
        self.assertEqual(self.check(0)['binary'], 0)

    def test_non_utf8_and_control_bytes_need_approval_even_at_the_end_of_a_file(self):
        self.enroll()
        file = self.root / 'data'
        for tail in (b'\xff', b'\x00', b'\x01', b'\xf0\x9f'):
            file.write_bytes(b'a\n' * 70000 + tail)
            self.assertEqual(self.check(1)['binary'], 1)
            self.assertEqual(self.approve('data').returncode, 0)
            self.assertEqual(self.check(0)['binary_approved'], 1)
        file.write_bytes(b'x' * (128 * 1024 - 1) + 'é'.encode())
        self.assertEqual(self.check(0)['binary'], 0)

    def test_mixed_binary_files_keep_text_findings_after_approval(self):
        self.enroll()
        file = self.root / 'data'
        token = TOKEN.encode('ascii')
        bodies = (
            token + b' quokka\n\x00',
            token + b' quokka\n' + b'x' * (128 * 1024) + b'\xff',
        )
        for body in bodies:
            with self.subTest(size=len(body)):
                file.write_bytes(body)
                self.assertEqual(self.check(1)['reasons'], ['binary_unapproved', 'credential', 'private_word'])
                self.assertEqual(self.approve('data').returncode, 0)
                self.assertEqual(self.check(1)['reasons'], ['credential', 'private_word'])
        own = Path(self.repo_dir, '.git/info/telonion-words')
        own.write_text('publish-exact: "quokka"\n')
        file.write_bytes(b'quokka\xff\n')
        self.assertEqual(self.check(1)['reasons'], ['binary_unapproved', 'private_word'])
        self.assertEqual(self.approve('data').returncode, 0)
        self.assertEqual(self.check(1)['reasons'], ['private_word'])

    def test_symlinks_and_special_files_are_incomplete_and_never_approved(self):
        self.enroll()
        outside = Path(self.box, 'outside')
        outside.mkdir()
        (outside / 'photo.png').write_bytes(b'\0')
        entry = self.root / 'nested'
        entry.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.check(2)['reasons'], ['unsupported_entry'])
        self.assertNotEqual(self.approve('nested/photo.png').returncode, 0)
        entry.unlink()
        entry.symlink_to(outside / 'photo.png')
        self.assertEqual(self.check(2)['reasons'], ['unsupported_entry'])
        self.assertNotEqual(self.approve('nested').returncode, 0)
        entry.unlink()
        os.mkfifo(entry)
        self.assertEqual(self.check(2)['reasons'], ['unsupported_entry'])
        self.assertNotEqual(self.approve('nested').returncode, 0)
        root_link = Path(self.box, 'root-link')
        root_link.symlink_to(outside)
        self.assertEqual(self.check(2, directory=str(root_link) + '/')['reasons'], ['unsupported_entry'])
        for path in ('../outside/photo.png', str(outside / 'photo.png'), './photo.png', 'a//b'):
            self.assertNotEqual(self.approve(path).returncode, 0)

    def test_a_change_to_a_previously_read_file_invalidates_the_whole_digest(self):
        from telonion import directory

        self.enroll()
        first = self.root / 'a.txt'
        first.write_text('first')
        (self.root / 'z.txt').write_text('last')
        read_file = directory.read_file

        def change_after_read(parent, name, *args, **kwargs):
            result = read_file(parent, name, *args, **kwargs)
            if name == 'z.txt':
                first.write_text('other')
            return result

        with patch.object(directory, 'read_file', change_after_read):
            record, _ = directory.inspect_directory(self.repo_dir, self.root, TARGET)
        self.assertEqual((record['decision'], record['tree_digest']), ('incomplete', None))
        self.assertEqual(record['reasons'], ['directory_changed'])

    def test_an_entry_added_during_the_inspection_invalidates_the_digest(self):
        from telonion import directory

        self.enroll()
        (self.root / 'first').write_text('ready')
        read_file = directory.read_file

        def add_after_read(*args, **kwargs):
            result = read_file(*args, **kwargs)
            (self.root / '.late').touch()
            return result

        with patch.object(directory, 'read_file', add_after_read):
            record, _ = directory.inspect_directory(self.repo_dir, self.root, TARGET)
        self.assertEqual((record['decision'], record['tree_digest']), ('incomplete', None))
        self.assertEqual(record['reasons'], ['directory_changed'])

    def test_an_unreadable_entry_discards_all_partial_results(self):
        from telonion import directory

        self.enroll()
        (self.root / 'file').write_text('quokka')
        with patch.object(directory, 'read_file', side_effect=PermissionError('quokka-unreadable')):
            record, messages = directory.inspect_directory(self.repo_dir, self.root, TARGET, details=True)
        self.assertEqual((record['decision'], record['tree_digest'], record['files']), ('incomplete', None, 0))
        self.assertEqual((record['reasons'], messages), (['directory_unreadable'], []))

    def test_bad_target_repository_policy_and_receipt_errors_are_machine_readable(self):
        self.enroll()
        for invalid in ('origin', 'https://example.invalid', TARGET + '\n', TARGET.replace('production/', ''),
                        TARGET.replace('/main', '/'), TARGET.replace('main', 'a//b')):
            result = self.check(2, target=invalid)
            self.assertIsNone(result['destination_id'])
        self.check(2, repo=str(self.root))
        self.check(2, repo=str(self.root / 'absent'))
        self.check(2, directory=self.root / 'missing')
        invalid = self.check(2, '--receipt', target='origin')
        receipt, = self.saved.glob('*.json')
        self.assertEqual(json.loads(receipt.read_text()), invalid)
        receipt.unlink()
        self.saved.rmdir()
        self.git(self.repo_dir, 'config', '--add', 'telonion.publishFile', 'invalid-quokka')
        self.assertEqual(self.check(2)['reasons'], ['policy_unavailable'])
        self.git(self.repo_dir, 'config', '--unset-all', 'telonion.publishFile')
        self.saved.write_text('occupied')
        self.assertEqual(self.check(2, '--receipt')['reasons'], ['receipt_unavailable'])
        self.assertEqual(self.saved.read_text(), 'occupied')
        self.saved.unlink()
        self.check(2, '--receipt', directory=self.repo_dir)
        self.assertFalse(self.saved.exists())

    def test_checks_reject_conflicting_modes_without_echoing_arguments(self):
        for options in (('--staged',), ('--live',), ('--remote', 'quokka'), ('HEAD',), ('-m', 'quokka')):
            p = self.command('check', '--directory', 'prepared', '--json', '--destination', TARGET, *options)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(json.loads(p.stdout)['decision'], 'incomplete')
            self.assertNotIn('quokka', p.stdout + p.stderr)
        p = self.command('approve', '-C', self.repo_dir, '--at', 'HEAD', '--directory', 'prepared',
                         '--destination', TARGET, 'asset')
        self.assertEqual(p.returncode, 2)
        self.assertNotEqual(self.command('destination', '-C', self.repo_dir, '--publish', TARGET, 'origin').returncode, 0)

    def test_receipt_inside_stage_via_filesystem_alias_is_refused(self):
        self.enroll()
        info = Path(self.repo_dir, '.git/info')
        for spelling in (info, info.with_name('INFO')):
            if spelling.is_dir():
                self.assertEqual(self.check(2, '--receipt', directory=spelling)['reasons'], ['receipt_unavailable'])
                self.assertFalse(self.saved.exists())
