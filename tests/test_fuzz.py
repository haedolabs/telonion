"""Deterministic generated inputs for assignment detection and mixed-binary directory reads."""
import hashlib
import os
import random
import unittest

from _helpers import TOKEN, Box
from telonion.directory import read_file
from telonion.scan import credential_spans, mask, read_commit, read_push, read_words


class GeneratedInputs(Box):
    def setUp(self):
        super().setUp()
        self.words('quokka\n')

    def test_generated_secret_assignment_spellings_and_masking(self):
        rng = random.Random(20261128)
        value = 'made-up-' + 'value-1234'
        secret_names = (
            ('client', 'secret'), ('db', 'password'), ('api', 'key'), ('auth', 'token'),
            ('aws', 'secret', 'access', 'key'),
        )
        harmless_names = (('secretive', 'notes'), ('tokenizer',), ('monkey', 'business'), ('public', 'value'))

        def make_name(parts):
            style = rng.randrange(5)
            if style < 3:
                name = ('_', '-', '.')[style].join(parts)
                return name.upper() if rng.choice((False, True)) else name
            name = parts[0].lower() + ''.join(part.capitalize() for part in parts[1:])
            return name.upper() if style == 4 else name

        for n in range(80):
            parts = secret_names[n % len(secret_names)]
            for expected in (True, False):
                chosen = parts if expected else harmless_names[n % len(harmless_names)]
                name = make_name(chosen)
                key_quote = rng.choice(('', '"', "'"))
                value_quote = rng.choice(('', '"', "'"))
                separator = rng.choice(('=', '=', ':'))
                spacing = rng.choice(('', ' ', '  '))
                exported = 'export ' if separator == '=' and not value_quote and rng.choice((False, True)) else ''
                text = (exported + key_quote + name + key_quote + spacing + separator + spacing
                        + value_quote + value + value_quote)
                with self.subTest(n=n, expected=expected, text=text):
                    what, spans = credential_spans(text)
                    if expected:
                        self.assertEqual(what, 'a literal given to a secret name')
                        self.assertNotIn(value, mask(text, [(s, e, 'credential') for s, e in spans]))
                    else:
                        self.assertIsNone(what)

    def test_generated_git_paths_and_patch_shaped_lines(self):
        rng = random.Random(20261128)
        symbols = (' ', '\t', '\n', '\r', '\x1b', '"', '\\', 'é', '中', ':', '#', ';', '[', ']', '@', '-')
        shapes = (
            '@@ -1,0 +2,1 @@ quokka', '+++ b/not-the-file quokka', '--- a/old-file quokka',
            ':100644 100644 1000000 2000000 A\tquokka', '\\ No newline at end of file quokka',
        )
        files = {}
        for n in range(24):
            folder = rng.choice(('nested ', 'dir"q', 'plain'))
            name = f'{folder}/quokka-{n}-{rng.choice(symbols)}-end'
            shape = rng.choice(shapes)
            files[name] = (shape + '\n' + 'a' * 40 + '\n'
                           + ':100644 100644 ' + 'a' * 40 + ' ' + 'b' * 40 + ' A\tfake\n'
                           + '+++ b/not-the-file\n')
        r = self.repo()
        self.stage(r, files)

        def check(result):
            self.assertEqual((result['lines'], result['files']), (4 * len(files), len(files)))
            self.assertEqual(len(result['private']), 2 * len(files))
            self.assertEqual(sum(where.endswith('new file') for where, _ in result['private']), len(files))
            self.assertNotIn('quokka', repr(result))
            for finding in result['private']:
                for text in finding:
                    self.assertTrue(all(c.isprintable() for c in text))

        check(read_commit(r, read_words(r)))
        self.git(r, 'commit', '-q', '-m', 'generated paths')
        pushed = read_push(r, ['HEAD'], [], read_words(r))
        self.assertEqual(pushed['commits'], 1)
        check(pushed)

    def test_generated_mixed_binary_offsets_keep_findings_and_hash(self):
        repo = self.repo()
        words = read_words(repo)
        file = os.path.join(self.box, 'data')
        rng = random.Random(20261128)
        points = (0, 1, 128 * 1024 - 1, 128 * 1024, 128 * 1024 + 1)
        secret = b'quokka ' + TOKEN.encode('ascii')
        for n in range(16):
            secret_at = rng.choice(points)
            invalid_at = rng.choice(points)
            while abs(secret_at - invalid_at) < len(secret):
                invalid_at = rng.choice(points)
            body = b''
            cursor = 0
            for position, payload in sorted(((secret_at, secret), (invalid_at, rng.choice((b'\xff', b'\x00'))))):
                body += b'x' * (position - cursor) + payload
                cursor = position + len(payload)
            body += rng.choice((b'', b'\n', b'\r\n'))
            with self.subTest(n=n, secret_at=secret_at, invalid_at=invalid_at, size=len(body)):
                with open(file, 'wb') as f:
                    f.write(body)
                digest, opaque, found = read_file(None, file, os.stat(file), inspect=True, words=words)
                self.assertTrue(opaque)
                self.assertEqual(found, {'private_word': 1, 'credential': 1})
                self.assertEqual(digest, hashlib.sha256(body).digest())


if __name__ == '__main__':
    unittest.main()
