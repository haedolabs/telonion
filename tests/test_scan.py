"""The reading of a push: private words and credentials in every commit the remote does not hold, each on its own."""
import os
import unittest

from _helpers import TOKEN, Box
from pushgate.scan import GitError, Words, fetched, read_push

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

    def test_new_files_that_run_code(self):
        self.git(self.r, 'remote', 'add', 'origin', self.origin)
        self.git(self.r, 'push', '-q', 'origin', 'main')
        self.assertEqual([x for _, x in self.again({'.github/workflows/ci.yml': 'on: push\n'})['code']],
                         ['.github/workflows/ci.yml'])
        self.assertEqual(self.read(allow_code=['.github/workflows/*'])['code'], [], 'a path the repository allows')
        self.assertEqual([x for _, x in self.again({'package.json': '{}\n'})['code']], ['package.json'])


if __name__ == '__main__':
    unittest.main()
