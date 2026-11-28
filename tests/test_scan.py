"""The reading of a push: private words and credentials in every commit the remote does not hold, each on its own;
the reading of the next commit; and the word lists, with the files they include."""
import os
import unittest

from _helpers import TOKEN, Box
from telonion.scan import GitError, Words, credential_spans, fetched, own_words_path, read_commit, read_push, read_words

WORDS = '# a note\npat\nsample\n\\bzephyr\\b\nproject-x\nallow: zephyr-free\nallow: sample\\.org/pat\n'


class PrivateWords(Box):
    def setUp(self):
        super().setUp()
        self.words(WORDS)
        self.r, self.origin = self.repo(), self.bare()
        self.commit(self.r, {'a.txt': 'old line written by Pat Sample\n'}, 'first')

    def read(self, words=True):
        return read_push(self.r, ['HEAD'], fetched(self.r, 'origin'), Words.read(self.words_file) if words else None)

    def first_push(self):
        self.git(self.r, 'remote', 'add', 'origin', self.origin)
        self.git(self.r, 'push', '-q', 'origin', 'main')

    def test_before_the_first_push_every_commit_is_read(self):
        self.assertIn('old line written by [private] [private]', [x for _, x in self.read()['private']])

    def test_after_it_only_what_the_remote_lacks(self):
        self.first_push()
        with open(os.path.join(self.r, 'a.txt'), 'a') as f:
            f.write('this is zephyr-free and fine\nthe zephyr notes\nsee sample.org/pat for more\n')
        self.commit(self.r, {'project-x-notes.md': 'nothing here\n'}, 'notes for Pat')
        r = self.read()
        texts, wheres = [x for _, x in r['private']], [w for w, _ in r['private']]
        self.assertFalse(any('old line' in x for x in texts), 'a line already on the remote was read again')
        self.assertIn('the [private] notes', texts)
        self.assertFalse(any('free' in x or 'sample.org' in x for x in texts), 'allowed text was a hit')
        self.assertIn('[private]-notes.md', texts, 'a new file whose name holds a word')
        self.assertTrue(any(w.startswith('commit ') for w in wheres), 'the commit message')
        self.assertEqual((r['lines'], r['files'], r['commits']), (4, 1, 1))

    def test_no_list_is_no_reading(self):
        self.assertEqual(self.read(words=False)['private'], [])
        self.assertIsNone(Words.read(os.path.join(self.box, 'none.txt')))
        os.makedirs(os.path.join(self.box, 'a-folder'))
        with self.assertRaises(OSError):
            Words.read(os.path.join(self.box, 'a-folder'))

    def test_a_word_stays_in_the_commit_that_added_it(self):
        self.first_push()
        first = self.commit(self.r, {'b.txt': 'zephyr in one commit\n'}, 'add')
        self.commit(self.r, {'b.txt': 'replaced in the next\n'}, 'replace')
        self.assertIn(f'{first[:7]} b.txt:1', [w for w, _ in self.read()['private']])

    def test_a_file_added_under_a_word_and_renamed_later(self):
        self.first_push()
        self.commit(self.r, {'project-x.md': 'a\n'}, 'file')
        self.git(self.r, 'mv', 'project-x.md', 'plain.md')
        self.git(self.r, 'commit', '-q', '-m', 'rename')
        r = self.read()
        self.assertIn('[private].md', [x for _, x in r['private']])
        self.git(self.r, 'tag', 'handmade')
        self.assertEqual(self.read()['private'], r['private'], 'a tag at HEAD changed what was read')

    def test_what_the_diff_parser_must_not_skip(self):
        self.first_push()
        self.commit(self.r, {'résumé "q".txt': 'zephyr in a quoted name\n',
                             'p.txt': '++ a line that looks like a header\nzephyr after it\n'}, 'names')
        texts = [x for _, x in self.read()['private']]
        self.assertIn('[private] in a quoted name', texts)
        self.assertIn('[private] after it', texts)

    def test_a_line_written_in_a_merge(self):
        self.first_push()
        self.git(self.r, 'checkout', '-q', '-b', 'side', 'origin/main')
        self.commit(self.r, {'s.txt': 'one\n'}, 'side')
        self.git(self.r, 'checkout', '-q', 'main')
        self.git(self.r, 'merge', '-q', '--no-ff', '--no-commit', 'side')
        with open(os.path.join(self.r, 'merged.txt'), 'w') as f:
            f.write('zephyr written in the merge\n')
        self.git(self.r, 'add', '.')
        self.git(self.r, 'commit', '-q', '-m', 'merge')
        self.assertIn('[private] written in the merge', [x for _, x in self.read()['private']])

    def test_an_annotated_tag_on_a_new_commit(self):
        self.first_push()
        self.commit(self.r, {'t.txt': 'fine\n'}, 'fine')
        self.git(self.r, 'tag', '-a', 'v9', '-m', 'release for Pat')
        self.assertIn(('tag v9', 'release for [private]'), self.read()['private'])

    def test_author_and_committer(self):
        self.first_push()
        self.git(self.r, 'config', 'user.name', 'Pat Sample')
        self.commit(self.r, {'i.txt': 'fine\n'}, 'fine')
        wheres = [w for w, _ in self.read()['private']]
        self.assertTrue(any(w.endswith(' author') for w in wheres) and any(w.endswith(' committer') for w in wheres), wheres)

    def test_nothing_found_is_shown_in_full(self):
        self.first_push()
        self.commit(self.r, {'zephyr-plan.md': 'the zephyr plan, with Pat\n'}, 'zephyr notes')
        shown = ' '.join(f'{w} {x}' for w, x in self.read()['private']).lower()
        self.assertIn('[private]', shown)
        for word in ('zephyr', 'pat'):
            self.assertNotIn(word, shown)

    def test_a_line_that_is_not_a_pattern_is_plain_text(self):
        self.first_push()
        self.commit(self.r, {'z.txt': 'a [unclosed bracket here\n'})
        self.words('nothing-matches-this\n[unclosed\n')
        self.assertEqual([x for _, x in self.read()['private']], ['a [private] bracket here'])

    def test_a_failing_git_command_is_never_clean(self):
        os.makedirs(os.path.join(self.box, 'not-a-repo'))
        with self.assertRaises(GitError):
            read_push(os.path.join(self.box, 'not-a-repo'), ['HEAD'], [], Words.read(self.words_file))


class OwnList(Box):
    def test_a_repositorys_own_list_adds_words_and_allows_for_itself_alone(self):
        self.words('zephyr\n')
        a, b = self.repo('a'), self.repo('b')
        for r in (a, b):
            self.commit(r, {'n.txt': 'see zephyr-notes\na quokka here\nthe zephyr plan\n'})
        own = own_words_path(a)
        self.assertEqual(own, os.path.join(a, '.git', 'info', 'telonion-words'))
        with open(own, 'w') as f:
            f.write('allow: zephyr-notes\nquokka\n')
        hits = lambda r: sorted(x for _, x in read_push(r, ['HEAD'], [], read_words(r))['private'])
        self.assertEqual(hits(a), ['a [private] here', 'the [private] plan'])
        self.assertEqual(hits(b), ['see [private]-notes', 'the [private] plan'], 'the allow line reached another repository')
        wt = os.path.join(self.box, 'wt')
        self.git(a, 'worktree', 'add', '-q', wt, '-b', 'side')
        self.assertEqual(own_words_path(wt), own, 'a worktree has a list of its own')
        os.remove(self.words_file)
        del os.environ['TELONION_WORDS']            # no main list was selected
        self.assertEqual(read_words(a).paths, [own], 'with no main list, the repository list alone')
        self.assertIsNone(read_words(b))
        self.assertIsNone(own_words_path(os.path.join(self.box, 'no-such-folder')))


class Includes(Box):
    def setUp(self):
        super().setUp()
        self.lists = os.path.join(self.box, 'lists')
        os.makedirs(self.lists)

    def list_file(self, name, text):
        path = os.path.join(self.lists, name)
        with open(path, 'w') as f:
            f.write(text)
        return path

    def test_an_included_file_adds_its_patterns_and_allow_lines(self):
        self.list_file('names.txt', '# written by another tool\nquokka\nallow: quokka-free\n')
        self.words(f'zephyr\ninclude: {os.path.join(self.lists, "names.txt")}\n')
        r = self.repo()
        self.commit(r, {'n.txt': 'a quokka here\nthis is quokka-free\nthe zephyr plan\n'})
        words = read_words(r)
        self.assertEqual((len(words.words), len(words.allows), words.included), (2, 1, (1, 1, 1)))
        self.assertEqual(sorted(x for _, x in read_push(r, ['HEAD'], [], words)['private']),
                         ['a [private] here', 'the [private] plan'])

    def test_a_path_from_home_or_from_the_folder_of_the_list_that_names_it(self):
        self.list_file('a.txt', 'quokka\ninclude: b.txt\n')
        self.list_file('b.txt', 'wombat\n')
        self.words('include: ~/lists/a.txt\nINCLUDE: lists/b.txt\n')
        w = Words.read(self.words_file)
        self.assertEqual((len(w.words), w.included), (2, (2, 2, 0)), 'a file named twice is read once')

    def test_an_include_that_leads_back_to_the_list_ends_there(self):
        self.list_file('a.txt', f'quokka\ninclude: {self.words_file}\n')
        self.words('zephyr\ninclude: ~/lists/a.txt\n')
        w = Words.read(self.words_file)
        self.assertEqual((len(w.words), w.included), (2, (1, 1, 0)))

    def test_an_include_that_is_missing_or_cannot_be_read_stops_the_reading(self):
        hidden = os.path.join(self.box, 'quokka-folder', 'names.txt')
        for line, says in ((f'include: {hidden}', 'the file it includes is not there'),
                           (f'include: {self.lists}', 'the file it includes could not be read'),
                           ('include:', 'an include that names no file')):
            self.words(f'zephyr\n{line}\n')
            with self.assertRaises(OSError) as e:
                Words.read(self.words_file)
            self.assertEqual(str(e.exception).split(' (')[0], f'~/words.txt line 2: {says}')
        if os.geteuid():                           # root reads a file whatever its mode
            locked = self.list_file('locked.txt', 'quokka\n')
            os.chmod(locked, 0)
            self.words(f'include: {locked}\n')
            with self.assertRaises(OSError):
                Words.read(self.words_file)

    def test_an_include_inside_an_included_file_names_its_place(self):
        self.list_file('a.txt', 'quokka\n\ninclude: missing.txt\n')
        self.words('zephyr\ninclude: ~/lists/a.txt\n')
        with self.assertRaises(OSError) as e:
            Words.read(self.words_file)
        self.assertEqual(str(e.exception),
                         '~/words.txt line 2, line 3 of the file it includes: the file it includes is not there')

    def test_a_repositorys_own_list_includes_for_itself_alone(self):
        self.words('zephyr\n')
        names = self.list_file('names.txt', 'quokka\n')
        a, b = self.repo('a'), self.repo('b')
        for r in (a, b):
            self.commit(r, {'n.txt': 'a quokka here\n'})
        with open(own_words_path(a), 'w') as f:
            f.write(f'include: {names}\n')
        hits = lambda r: [x for _, x in read_push(r, ['HEAD'], [], read_words(r))['private']]
        self.assertEqual((hits(a), hits(b)), (['a [private] here'], []))
        self.assertEqual(read_words(a).included, (1, 1, 0))


class NextCommit(Box):
    def setUp(self):
        super().setUp()
        self.words('zephyr\nproject-x\n')
        self.r = self.repo()

    def read(self, **kw):
        return read_commit(self.r, Words.read(self.words_file), **kw)

    def test_before_the_first_commit_everything_staged_is_read(self):
        self.stage(self.r, {'a.txt': 'the zephyr notes\n', 'project-x.md': 'fine\n'})
        r = self.read()
        self.assertEqual(sorted(r['private']), [('a.txt:1', 'the [private] notes'), ('new file', '[private].md')])
        self.assertEqual((r['lines'], r['files']), (2, 2))

    def test_only_what_the_commit_adds(self):
        self.commit(self.r, {'a.txt': 'an old zephyr line\n'})
        with open(os.path.join(self.r, 'a.txt'), 'a') as f:
            f.write('a new line\n')
        self.git(self.r, 'add', 'a.txt')
        with open(os.path.join(self.r, 'a.txt'), 'a') as f:
            f.write('zephyr, changed but not staged\n')
        r = self.read()
        self.assertEqual((r['private'], r['lines'], r['files']), ([], 1, 0))

    def test_a_rename_to_a_name_that_holds_a_word(self):
        self.commit(self.r, {'plain.md': 'a\n'})
        self.git(self.r, 'mv', 'plain.md', 'project-x.md')
        self.assertEqual(self.read()['private'], [('new file', '[private].md')])

    def test_credentials_and_files_that_hold_keys(self):
        self.stage(self.r, {'conf.py': f'TOKEN = "{TOKEN}"\n', '.env': 'x\n'})
        hits = self.read()['credentials']
        self.assertEqual(sorted(what for _, what, _ in hits), ['a GitHub token', 'a file that holds keys by its name'])
        self.assertFalse(any(TOKEN in w + x for w, _, x in hits), 'a token was shown')

    def test_the_message_and_who_the_commit_is_by(self):
        self.stage(self.r, {'a.txt': 'fine\n'})
        self.assertEqual(self.read(staged=False, message='notes for zephyr\n\nmore\n')['private'],
                         [('commit message', 'notes for [private]')])
        self.git(self.r, 'config', 'user.name', 'Zephyr Sample')
        self.assertEqual(sorted(w for w, _ in self.read()['private']), ['author', 'committer'])

    def test_a_failing_git_command_is_never_clean(self):
        os.makedirs(os.path.join(self.box, 'not-a-repo'))
        with self.assertRaises(GitError):
            read_commit(os.path.join(self.box, 'not-a-repo'), Words.read(self.words_file))


class Credentials(Box):
    def setUp(self):
        super().setUp()
        self.r, self.origin = self.repo(), self.bare()
        self.commit(self.r, {'a.txt': 'plain text, a password field named in prose, sk-short\n', '.env.example': 'KEY=\n'})

    def read(self, **kw):
        return read_push(self.r, ['HEAD'], fetched(self.r, 'origin'), None, **kw)

    def again(self, files, message='c'):
        """`files` in a new commit on the remote's tip, as the only change the push would send."""
        self.git(self.r, 'reset', '-q', '--hard', 'origin/main')
        self.commit(self.r, files, message)
        return self.read()

    def test_plain_text_and_an_example_env_file(self):
        r = self.read()
        self.assertEqual((r['credentials'], r['code'], r['commits']), ([], [], 1))

    def test_what_is_caught(self):
        self.git(self.r, 'remote', 'add', 'origin', self.origin)
        self.git(self.r, 'push', '-q', 'origin', 'main')
        hits = self.again({'conf.py': f'TOKEN = "{TOKEN}"\n'})['credentials']
        self.assertTrue(any('conf.py:1' in w and what == 'a GitHub token' for w, what, _ in hits), hits)
        self.assertFalse(any(TOKEN in w + x for w, _, x in hits), 'a token was shown')
        hits = self.again({'notes.md': '-----BEGIN ' + 'OPENSSH PRIVATE KEY-----\nabc\n'})['credentials']
        self.assertTrue(any('notes.md' in w and what == 'a private key' for w, what, _ in hits), hits)
        hits = self.again({'keys/id_ed25519': 'x\n', '.env': 'x\n', 'cert.pem': 'x\n'})['credentials']
        names = [x for _, what, x in hits if what == 'a file that holds keys by its name']
        self.assertEqual(sorted(names), ['.env', 'cert.pem', 'keys/id_ed25519'])
        hits = self.again({'b.txt': 'nothing\n'}, f'key {TOKEN}')['credentials']
        self.assertTrue(any(w.startswith('commit ') for w, _, _ in hits), 'a token in a commit message')
        hits = self.again({'c.py': 'API_KEY' + ' = "abcdefghijklmnop"\n'})['credentials']   # joined here, so this file holds none
        self.assertEqual([what for _, what, _ in hits], ['a literal given to a secret name'])

    def test_common_secret_assignment_forms(self):
        value = 'made-up-value-1234'
        for text in (
                f'client_secret = "{value}"', f'DB_PASSWORD = "{value}"',
                f'AWS_SECRET_ACCESS_KEY = "{value}"', f'clientSecret = "{value}"',
                f'{{"password": "{value}"}}', f'token={value}', f'export API_KEY={value}'):
            with self.subTest(text=text):
                self.assertEqual(credential_spans(text)[0], 'a literal given to a secret name')
        for text in (f'secretive = "{value}"', f'tokenizer = "{value}"', f'monkey = "{value}"',
                     'password = "short"', 'token = ' + 'TOKEN.encode("ascii")',
                     'secret_at = ' + 'rng.choice(points)'):
            with self.subTest(text=text):
                self.assertIsNone(credential_spans(text)[0])

    def test_an_unquoted_secret_added_to_an_existing_key_file(self):
        self.git(self.r, 'remote', 'add', 'origin', self.origin)
        self.git(self.r, 'push', '-q', 'origin', 'main')
        self.commit(self.r, {'.env': 'PUBLIC=yes\n'})
        self.git(self.r, 'push', '-q', 'origin', 'main')
        value = 'made-up-' + 'value-1234'
        self.commit(self.r, {'.env': 'PUBLIC=yes\nCLIENT_SECRET=' + value + '\n'})
        self.assertIn('a literal given to a secret name', [what for _, what, _ in self.read()['credentials']])

    def test_new_files_that_run_code(self):
        self.git(self.r, 'remote', 'add', 'origin', self.origin)
        self.git(self.r, 'push', '-q', 'origin', 'main')
        self.assertEqual([x for _, x in self.again({'.github/workflows/ci.yml': 'on: push\n'})['code']],
                         ['.github/workflows/ci.yml'])
        self.assertEqual(self.read(allow_code=['.github/workflows/*'])['code'], [], 'a path the repository allows')
        self.assertEqual([x for _, x in self.again({'package.json': '{}\n'})['code']], ['package.json'])


if __name__ == '__main__':
    unittest.main()
