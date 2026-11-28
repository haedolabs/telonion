"""What a push makes public, read before it leaves (every commit the remote does not hold, each on its own), and what
the next commit adds, read before it is made.

The same text is read two ways. Private words: lists kept outside every repository, one pattern a line, with `allow:`
lines for text that may appear and `include:` lines that read other lists as part of them. Credentials: tokens and keys
by their fixed formats, files that hold them by name, and new files that make code run on a hosting service or on
install.

Nothing found is printed in full. Each hit names its place, and the word or credential in it is masked, so output that
lands in a terminal log or an assistant's transcript does not repeat what the check exists to keep private.
"""
import fnmatch
import io
import json
import os
import re
import subprocess

from . import fingerprint, short_path

ZERO = '0' * 40
EXCERPT = 160                                      # characters of a line shown with a hit, after masking


class GitError(RuntimeError):
    """A git command failed: what it was reading is unknown, so it is never a clean reading."""


def git(repo, *args, stdin=None, timeout=None, env=None, binary=False):
    """Git's output. Its diagnostics can contain URLs, ref names, and private paths; never relay them."""
    io = dict(input=stdin) if stdin is not None else dict(stdin=subprocess.DEVNULL)
    try:
        r = subprocess.run(['git', '--no-replace-objects', '-C', repo, '-c', 'core.quotePath=false', *args], capture_output=True,
                            encoding=None if binary else 'utf-8', errors=None if binary else 'replace',
                            timeout=timeout, env=env, **io)
    except subprocess.TimeoutExpired:
        raise GitError(f'git {args[0]}: no answer in {timeout} s')
    except OSError:
        raise GitError('git could not be started') from None
    if r.returncode:
        raise GitError(f'git {args[0]} failed (exit {r.returncode})')
    return r.stdout


def config(repo, key, *kind, git_env=None):
    """A git setting as the repository sees it (its own, then the global one): every value, [] when it is unset.
    For a folder that does not exist, the global setting alone."""
    where = ['-C', repo] if repo and (git_env is not None or os.path.isdir(repo)) else []
    r = subprocess.run(['git', *where, 'config', '-z', *kind, '--get-all', key], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, env=git_env)
    if r.returncode == 1:
        return []
    if r.returncode:
        raise GitError('git settings could not be read')
    return r.stdout.split('\0')[:-1]


# The name before Telonion was Push Gate: its settings (pushgate.*), variables ($PUSHGATE_*), and files
# (~/.config/pushgate/, info/pushgate-words) are still read wherever the new ones are not set, so nothing it set up
# stops being read. `telonion install` moves a repository's own over to the new names.
OLD = 'pushgate'


def setting(repo, name, *kind, both=False, git_env=None):
    """The setting telonion.<name>, else the old pushgate.<name>: every value, [] when neither is set. With `both`,
    the values of the two together (for a setting that adds up, such as allowCode)."""
    new = config(repo, f'telonion.{name}', *kind, git_env=git_env)
    if new and not both:
        return new
    return new + config(repo, f'{OLD}.{name}', *kind, git_env=git_env)


def env(name):
    """$TELONION_<name>, else the old $PUSHGATE_<name>, else None."""
    return os.environ.get(f'TELONION_{name}') or os.environ.get(f'PUSHGATE_{name}') or None


def _home_config(*parts):
    """~/.config/telonion/<parts>, or the old ~/.config/pushgate/<parts> when only that one exists."""
    new = os.path.join(os.path.expanduser('~'), '.config', 'telonion', *parts)
    old = os.path.join(os.path.expanduser('~'), '.config', OLD, *parts)
    return old if not os.path.lexists(new) and os.path.lexists(old) else new


# The private word list.

def repository_root(repo, git_env=None):
    bare = git(repo, 'rev-parse', '--is-bare-repository', env=git_env).strip() == 'true'
    root = git(repo, 'rev-parse', '--absolute-git-dir' if bare else '--show-toplevel', binary=True, env=git_env)
    return os.fsdecode(root.removesuffix(b'\n'))


def _selected_words(repo, git_env=None, *, from_root=False):
    if env('WORDS'):
        return os.path.expanduser(env('WORDS'))
    set_in_git = setting(repo, 'words', '--type=path', git_env=git_env)
    if set_in_git:
        path = os.path.expanduser(set_in_git[-1])
        if from_root and not os.path.isabs(path):
            return os.path.join(repository_root(repo, git_env), path)
        return path
    return None


def words_path(repo='.'):
    """The explicitly selected main list, or the optional default in the user's config folder."""
    selected = _selected_words(repo)
    return _home_config('words.txt') if selected is None else selected


def _pattern(text):
    """A line of the list as a pattern: a regular expression, capitals and small letters alike, or the plain text when
    it is not one."""
    try:
        return re.compile(text, re.I)
    except re.error:
        return re.compile(re.escape(text), re.I)


class ListError(OSError):
    """A word-list entry could not be read. Report its list and line number, never its contents."""


def _lines(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read().split('\n')


def _publish_exact(value, where):
    try:
        text = json.loads(value)
    except (ValueError, RecursionError):
        text = None
    if not isinstance(text, str) or not text or any(c in text for c in '\r\n\0'):
        raise ListError(f'{where}: publish-exact needs one nonempty line as a JSON string')
    return text


class Words:
    """A private word list: one pattern a line, `allow: <pattern>` for text that may appear though it holds a word,
    `include: <path>` for another list read as part of this one, and # for notes. `paths` are the lists it was read
    from; `included` counts what the files they include gave: (files, patterns, allow lines)."""

    def __init__(self, path, words, allows, paths=None, included=(0, 0, 0), publish_exact=()):
        self.path, self.words, self.allows, self.paths = path, words, allows, paths or [path]
        self.included = included
        self.publish_exact = frozenset(publish_exact)

    @classmethod
    def read(cls, path, label=None, *, repository=False):
        """The list at `path` with the files it includes, or None when no file is there. A list that is there and
        cannot be read raises OSError, and so does an include whose file is not there or cannot be read (ListError):
        no part of a list that exists is skipped.

        An include's path starts from ~ or from the folder of the list that names it. An included file is read under
        the same rules, its own includes too, and once however many lines name it."""
        try:
            lines = _lines(path)
        except FileNotFoundError:
            return None
        words, allows, seen, given = [], [], {os.path.realpath(path)}, [0, 0]    # given: by included files
        publish_exact = set()

        def take(lines, folder, at, depth):
            for n, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                prefix, colon, value = line.partition(':')
                directive = prefix.lower() if colon else ''
                if directive == 'allow':
                    if value.strip():
                        allows.append(_pattern(value.strip()))
                        if depth:
                            given[1] += 1
                elif directive == 'include':
                    include(value.strip(), folder, at(n), depth + 1)
                elif directive == 'publish-exact':
                    if not repository:
                        raise ListError(f'{at(n)}: publish-exact belongs in a repository word list')
                    text = _publish_exact(value, at(n))
                    if depth and text not in publish_exact:
                        given[1] += 1
                    publish_exact.add(text)
                else:
                    words.append(_pattern(line))
                    if depth:
                        given[0] += 1

        def include(name, folder, where, depth):
            if not name:
                raise ListError(f'{where}: an include that names no file')
            file = os.path.join(folder, os.path.expanduser(name))
            if os.path.realpath(file) in seen:     # read already: once is enough, and a loop ends here
                return
            try:
                lines = _lines(file)
            except FileNotFoundError:
                raise ListError(f'{where}: the file it includes is not there') from None
            except OSError as e:
                raise ListError(f'{where}: the file it includes could not be read '
                                f'({e.strerror or type(e).__name__})') from None
            seen.add(os.path.realpath(file))
            take(lines, os.path.dirname(file), lambda m: f'{where}, line {m} of the file it includes', depth)

        top = label or short_path(os.path.abspath(path))
        take(lines, os.path.dirname(os.path.abspath(path)), lambda n: f'{top} line {n}', 0)
        return cls(path, words, allows, included=(len(seen) - 1, given[0], given[1]), publish_exact=publish_exact)

    def joined(self, other):
        """This list and `other` read as one: the words of both, and the allow lines of both."""
        return Words(self.path, self.words + other.words, self.allows + other.allows, self.paths + other.paths,
                     tuple(a + b for a, b in zip(self.included, other.included)), self.publish_exact | other.publish_exact)

    def spans(self, text):
        """Where the list's words are in `text`, leaving out text an allow pattern covers: [(start, end)]."""
        filled = text
        for a in self.allows:                      # allowed text becomes spaces of its own length: places stay put
            filled = a.sub(lambda m: ' ' * len(m.group(0)), filled)
        return [(m.start(), m.end()) for w in self.words for m in w.finditer(filled) if m.end() > m.start()]


def own_words_path(repo='.'):
    """A repository's own list, among git's own files and so never committed: <git common dir>/info/telonion-words,
    shared by the repository's worktrees. Its patterns add to the main list, and its allow lines apply to this
    repository alone. The old name, info/pushgate-words, when only that one exists (`telonion install` moves it).
    None outside a repository."""
    if not repo or not os.path.isdir(repo):
        return None
    r = subprocess.run(['git', '-C', repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode or not r.stdout.strip():
        return None
    return _own_list(r.stdout.removesuffix('\n'))


def _own_list(common):
    info = os.path.join(common, 'info')
    new, old = os.path.join(info, 'telonion-words'), os.path.join(info, f'{OLD}-words')
    return old if not os.path.lexists(new) and os.path.lexists(old) else new


def read_words(repo='.', *, common=None, git_env=None):
    """The main list (words_path) and the repository's own (own_words_path), read as one, or None when neither
    exists. A list that exists and cannot be read raises OSError: a list that exists is never skipped."""
    selected = _selected_words(repo, git_env, from_root=common is not None)
    path = selected if selected is not None else _home_config('words.txt')
    main = Words.read(path, 'main word list')
    if main is None and (selected is not None or os.path.lexists(path)):
        raise ListError('the configured word list is missing')
    own_path = _own_list(common) if common is not None else own_words_path(repo)
    own = Words.read(own_path, 'repository word list', repository=True) if own_path else None
    if own is None and own_path and os.path.lexists(own_path):
        raise ListError("the repository's word list could not be read")
    if main is None or own is None:
        return main or own
    return main.joined(own)


# Credentials.

CREDENTIALS = [(what, re.compile(p, flags)) for what, p, flags in (   # fixed prefixes, so few false alarms
    ('a GitHub token', r'\bgh[pousr]_[A-Za-z0-9]{36,}', 0),
    ('a GitHub token', r'\bgithub_pat_[A-Za-z0-9_]{60,}', 0),
    ('an AWS access key id', r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b', 0),
    ('a private key', r'-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----', 0),
    ('a Slack token', r'\bxox[abposr]-[A-Za-z0-9-]{10,}', 0),
    ('a Slack webhook', r'https://hooks\.slack\.com/services/T[A-Za-z0-9/]+', 0),
    ('an Anthropic API key', r'\bsk-ant-[A-Za-z0-9_-]{20,}', 0),
    ('an OpenAI API key', r'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}', 0),
    ('a Google API key', r'\bAIza[0-9A-Za-z_-]{35}\b', 0),
    ('a Stripe live key', r'\b[rs]k_live_[0-9A-Za-z]{24,}', 0),
    ('an npm token', r'\bnpm_[A-Za-z0-9]{36}\b', 0),
    ('a Hugging Face token', r'\bhf_[A-Za-z0-9]{34,}\b', 0),
)]

# An assignment is a candidate only when its complete name has a secret component. Splitting snake, kebab, dotted,
# and capitalized compound names catches client_secret, DB_PASSWORD, AWS_SECRET_ACCESS_KEY, and clientSecret without
# treating ordinary words such as secretive or tokenizer as credentials. Quoted JSON keys and unquoted values count.
_ASSIGNMENT = re.compile(r'''
    (?<![A-Za-z0-9_.-])
    (?:export\s+)?
    (?P<quote>["\']?)(?P<name>[A-Za-z][A-Za-z0-9_.-]*)(?P=quote)
    \s*[:=]\s*
    (?: "[^"\s]{12,}" | \'[^\'\s]{12,}\' | [^"\'\s,;&}]{12,}(?=$|\s|[,;&}#]) )
''', re.I | re.X)


def _secret_name(name):
    name = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name)
    parts = [part for part in re.split(r'[^a-z0-9]+', name.lower()) if part]
    return (bool({'password', 'passwd', 'secret', 'token', 'apikey'}.intersection(parts))
            or any(parts[n:n + 2] == ['api', 'key'] for n in range(len(parts) - 1)))


KEY_FILES = re.compile(r'(?:^|/)(?:\.env(?:\.[^/]*)?|id_(?:rsa|dsa|ecdsa|ed25519)|credentials(?:\.json)?|\.netrc|\.pypirc|'
                       r'[^/]*\.(?:pem|p12|pfx|key|keystore|jks|mobileprovision))$', re.I)
KEY_FILES_OK = re.compile(r'\.env\.(?:example|sample|template)$')
RUNS_CODE = re.compile(r'(?:^|/)(?:\.github/(?:workflows|actions)/.*|action\.ya?ml|package\.json|\.npmrc|setup\.py|'
                       r'setup\.cfg|pyproject\.toml|Makefile|\.gitlab-ci\.yml|\.circleci/.*)$')


def key_file(path):
    return KEY_FILES.search(path) and not KEY_FILES_OK.search(path)


def unapproved_code(path, allowed):
    return allowed is not None and RUNS_CODE.search(path) and not any(fnmatch.fnmatchcase(path, a) for a in allowed)


def credential_spans(text):
    """The credentials in `text`: (what the first one is, [(start, end)]), or (None, [])."""
    what, spans = None, []
    for name, p in CREDENTIALS:
        for m in p.finditer(text):
            what = what or name
            spans.append(m.span())
    for m in _ASSIGNMENT.finditer(text):
        if _secret_name(m.group('name')):
            what = what or 'a literal given to a secret name'
            spans.append(m.span())
    return what, spans


# Masking: everything printed goes through cleaner().

def mask(text, spans):
    """`text` with each (start, end, label) span replaced by [label]; spans that overlap are taken as one."""
    merged = []
    for s, e, label in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e, label])
    out, at = [], 0
    for s, e, label in merged:
        out += [text[at:s], f'[{label}]']
        at = e
    return ''.join(out) + text[at:]


_ADDRESS = re.compile(r'(?:[a-zA-Z][a-zA-Z0-9+.-]*://|[^\s/@:]+@[^\s/:]+:)\S+')


def cleaner(words):
    """A function that masks every word of `words` (a Words, or None) and every credential in a text."""
    def clean(text):
        spans = [(s, e, 'private') for s, e in (words.spans(text) if words else [])]
        spans += [(s, e, 'credential') for s, e in credential_spans(text)[1]]
        spans += [(m.start(), m.end(), 'address') for m in _ADDRESS.finditer(text)]
        masked = mask(text, spans) if spans else text
        return ''.join(c if c.isprintable() else ascii(c)[1:-1] for c in masked)
    return clean


def _excerpt(text):
    text = text.strip()
    return text if len(text) <= EXCERPT else text[:EXCERPT - 3] + '...'


# What a push sends.

OBJECT_ID = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?$')
_HUNK = re.compile(r'@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def _unquote(path):
    """A file name as git prints it: in double quotes, with C escapes, when it holds a quote, a backslash, or a control
    character (core.quotePath=false leaves other characters as they are)."""
    if not (path.startswith('"') and path.endswith('"')):
        return path
    esc = dict(n='\n', t='\t', a='\a', b='\b', f='\f', r='\r', v='\v')
    return re.sub(r'\\([0-7]{3}|.)', lambda m: chr(int(m.group(1), 8)) if len(m.group(1)) == 3
                  else esc.get(m.group(1), m.group(1)), path[1:-1])


def present(repo, objects):
    """The commits and tags among `objects` that this repository holds: what rev-list can stop at."""
    objects = [o for o in dict.fromkeys(objects) if o and o != ZERO]
    if not objects:
        return []
    out = git(repo, 'cat-file', '--batch-check=%(objectname) %(objecttype)', stdin=''.join(o + '\n' for o in objects))
    return [line.split()[0] for line in out.split('\n') if line.endswith((' commit', ' tag'))]


def commits(repo, tips, stop=()):
    """The commits reachable from `tips` and from none of `stop`, oldest first."""
    tips = [t for t in tips if t and t != ZERO]
    if not tips:
        return []
    spec = ''.join(t + '\n' for t in tips) + ''.join('^' + s + '\n' for s in present(repo, stop))
    return git(repo, 'rev-list', '--reverse', '--stdin', stdin=spec).split()


def fetched(repo, remote):
    """What this checkout last fetched from `remote`: the object each of its remote-tracking refs names."""
    return git(repo, 'for-each-ref', '--format=%(objectname)', f'refs/remotes/{remote}/').split()


def advertised(repo, remote, timeout=60):
    """What `remote` holds now, by asking it (git ls-remote): the object each of its refs names, tags peeled too.
    GitError when it cannot be asked."""
    out = git(repo, 'ls-remote', '--', remote, timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
    return [line.split('\t')[0] for line in out.split('\n') if '\t' in line]


class _Reading:
    """What a reading finds, each hit once, with its place and its text masked. New files that run code on a host or
    on install are looked for only when `allow_code` is given (the paths a repository allows), as for a push."""

    def __init__(self, words, allow_code=None):
        self.words, self.clean, self.seen = words, cleaner(words), set()
        self.allow_code = None if allow_code is None else list(allow_code)
        self.private, self.credentials, self.code = [], [], []

    def look(self, where, text, key, credentials=True):
        if self.words is not None and ('p', key) not in self.seen and self.words.spans(text):
            self.seen.add(('p', key))
            self.private.append((self.clean(where), _excerpt(self.clean(text))))
        what = credential_spans(text)[0] if credentials else None
        if what and ('c', key) not in self.seen:
            self.seen.add(('c', key))
            self.credentials.append((self.clean(where), what, _excerpt(self.clean(text))))

    def look_name(self, where, name):
        """A file that is added or renamed: its name, and what the name says it holds or does."""
        self.look(where, name, ('name', name))
        if key_file(name) and ('k', name) not in self.seen:
            self.seen.add(('k', name))
            self.credentials.append((self.clean(where), 'a file that holds keys by its name', _excerpt(self.clean(name))))
        if unapproved_code(name, self.allow_code) and ('r', name) not in self.seen:
            self.seen.add(('r', name))
            self.code.append((self.clean(where), _excerpt(self.clean(name))))


def _walk(patch, on_line, on_name):
    """A patch with raw lines, walked: on_line(sha, path, n, text) for each line it adds (n: the line's number in the
    new file), and on_name(sha, name) for each file it adds or renames. `sha` is the commit whose diff follows, from
    git diff-tree --stdin; '' for a diff that is not a commit's."""
    sha, path, n, old, new = '', '', 0, 0, 0
    for line in patch.split('\n'):
        if old > 0 or new > 0:                     # inside a hunk, whose header counts its lines: none is a header
            if line.startswith('+'):
                new -= 1
                on_line(sha, path, n, line[1:])
                n += 1
            elif line.startswith('-'):
                old -= 1
            elif line.startswith(' '):
                old, new, n = old - 1, new - 1, n + 1
            continue
        if OBJECT_ID.fullmatch(line):              # the commit whose diff follows (a merge's comes once a parent)
            sha = line
        elif line.startswith(':') and '\t' in line:   # a raw line: the status, then the file names
            f = line.split('\t')
            if f[0].split()[-1][:1] in ('A', 'R'):
                on_name(sha, _unquote(f[-1]))
        elif line.startswith('+++ '):
            p = _unquote(line[4:].rstrip('\t'))
            path = p[2:] if p.startswith('b/') else p
        else:
            m = _HUNK.match(line)
            if m:
                old, n, new = int(m.group(1) or 1), int(m.group(2)), int(m.group(3) or 1)


_DIFF = ('--patch-with-raw', '-M', '--unified=0', '--no-color', '--no-ext-diff', '--no-textconv', '--src-prefix=a/',
         '--dst-prefix=b/')


OPAQUE_NAME = re.compile(r'\.(?:pdf|docx?|xlsx?|pptx?|od[pts]|zip|gz|7z|png|jpe?g|gif|webp|mp[34]|wav)$', re.I)
_LFS_VERSIONS = (b'version https://git-lfs.github.com/spec/v1', b'version https://hawser.github.com/spec/v1')


def lfs_pointers(repo, blobs):
    """Recognize the pointer in the committed blob, even on a rename or a change only to its object ID."""
    if not blobs:
        return set()
    sizes = git(repo, 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)',
                stdin=''.join(oid + '\n' for oid in blobs))
    small = []
    for line in sizes.splitlines():
        fields = line.split()
        if len(fields) != 3 or fields[1] != 'blob' or not fields[2].isdigit():
            raise GitError('a changed file could not be read')
        if len(_LFS_VERSIONS[0]) <= int(fields[2]) <= 1024:
            small.append(fields[0])
    if not small:
        return set()
    data = io.BytesIO(git(repo, 'cat-file', '--batch', binary=True, stdin=('\n'.join(small) + '\n').encode('ascii')))
    pointers = set()
    for oid in small:
        fields = data.readline().split()
        if len(fields) != 3 or fields[:2] != [oid.encode('ascii'), b'blob'] or not fields[2].isdigit():
            raise GitError('a changed file could not be read')
        body = data.read(int(fields[2]))
        if data.read(1) != b'\n':
            raise GitError('a changed file was not read in full')
        if body.partition(b'\n')[0].rstrip(b'\r') in _LFS_VERSIONS:
            pointers.add(oid)
    return pointers


def file_versions(repo, feed, clean):
    """Changed (path, object) pairs whose contents a line diff cannot inspect. Use Git's binary
    classification, including attributes. Turning off rename detection here gives a new path its own decision."""
    raw = git(repo, 'diff-tree', '--stdin', '--root', '-m', '-r', '--no-renames', '--raw', '--numstat',
              '--no-abbrev', '--no-ext-diff', '--no-textconv', '-z', binary=True, stdin=feed.encode('ascii'))
    records = iter(raw.split(b'\0'))
    versions, binary, submodules, changed = {}, set(), set(), {}
    commit = ''
    for entry in records:
        if entry.startswith(b':'):
            _, mode, _, object_id, status = entry.split()
            path = os.fsdecode(next(records))
            if status != b'D':
                key = path, object_id.decode('ascii')
                changed[path] = key
                versions.setdefault(key, commit)
                if mode == b'160000':
                    submodules.add(key)
        elif entry.startswith(b'-\t-\t'):
            key = changed.get(os.fsdecode(entry[4:]))
            if key:
                binary.add(key)
        elif re.fullmatch(rb'[a-f0-9]{40}(?:[a-f0-9]{24})?', entry):
            commit = entry.decode('ascii')
            changed = {}
    pointers = lfs_pointers(repo, {oid for path, oid in versions if (path, oid) not in submodules})
    opaque = []
    for key, sha in versions.items():
        path, oid = key
        if oid in pointers:
            kind = 'LFS'
        elif key in submodules:
            kind = 'submodule'
        elif key in binary or OPAQUE_NAME.search(path):
            kind = 'file'
        else:
            continue
        opaque.append((clean(path), fingerprint(path, oid), sha, kind))
    return opaque


def _outgoing_tags(repo, tips, found):
    """Read actual tag objects, including a tag sent under a different ref, or a tag of another tag."""
    seen = set()
    for tip in tips:
        oid = tip
        while oid not in seen:
            seen.add(oid)
            kind = git(repo, 'cat-file', '-t', oid).strip()
            if kind == 'commit':
                break
            if kind != 'tag':
                raise GitError('the push names an object other than a commit or a tag of a commit')
            headers, _, body = git(repo, 'cat-file', 'tag', oid).partition('\n\n')
            fields = dict(line.split(' ', 1) for line in headers.splitlines() if ' ' in line)
            if not OBJECT_ID.fullmatch(fields.get('object', '')) or 'tag' not in fields:
                raise GitError('a tag could not be read')
            name = fields['tag']
            found.look(f'tag {name}', name, ('tag name', oid))
            found.look(f'tag {name} tagger', fields.get('tagger', ''), ('tagger', oid))
            for line in body.split('\n'):
                found.look(f'tag {name}', line, ('tag', oid, line))
            oid = fields['object']


def read_push(repo, tips, stop=(), words=None, allow_code=(), tag_refs=None, ref_names=()):
    """What a push of `tips` makes public beyond the commits under `stop`, read against `words` (a Words, or None when
    there is no list) and the credential formats.

    Each commit is read on its own: the lines it adds (a merge's, against each parent), the names of the files it adds
    or renames, its message, its author and committer, and the tag objects actually proposed. In an offline estimate
    (`tag_refs=None`), include the annotated tags that might follow these commits. `ref_names` are destination refs.

    -> {commits, lines, files, private: [(where, excerpt)], credentials: [(where, what, excerpt)],
        code: [(where, name)], opaque: [(masked path, version fingerprint, commit, kind)]}. Git errors stop the read."""
    tips = list(tips)
    found, out, names = _Reading(words, allow_code), dict(commits=0, lines=0, files=0), set()

    def added(sha, path, n, text):
        out['lines'] += 1
        found.look(f'{sha[:7]} {path}:{n}', text, ('line', path, text))

    def named(sha, name):
        if name not in names:
            names.add(name)
            out['files'] += 1
        found.look_name(f'{sha[:7]} new file', name)

    shas = commits(repo, tips, stop)
    feed = ''.join(s + '\n' for s in shas)
    if shas:
        _walk(git(repo, 'diff-tree', '--stdin', '-m', '-r', '--root', *_DIFF, stdin=feed), added, named)
        log = git(repo, 'log', '--stdin', '--no-walk=unsorted', '--no-show-signature',
                  '--format=%h%x00%an <%ae>%x00%cn <%ce>%x00%B%x1e', stdin=feed)
        for rec in log.split('\x1e'):
            if '\x00' not in rec:
                continue
            short, author, committer, body = (rec.lstrip('\n').split('\x00', 3) + ['', '', ''])[:4]
            out['commits'] += 1
            found.look(f'commit {short} author', author, ('author', author), credentials=False)
            found.look(f'commit {short} committer', committer, ('committer', committer), credentials=False)
            for line in body.split('\n'):
                found.look(f'commit {short}', line, ('message', short, line))
    tag_tips = tips + list(tag_refs or ())
    if tag_refs is None and shas:                   # an offline estimate includes tags that might follow these commits
        sent = set(shas)
        fmt = '%(objectname)%09%(*objectname)'
        for line in git(repo, 'for-each-ref', f'--format={fmt}', 'refs/tags').splitlines():
            oid, _, target = line.partition('\t')
            if target in sent:
                tag_tips.append(oid)
    _outgoing_tags(repo, tag_tips, found)
    for ref in ref_names:
        found.look('ref on the remote', ref, ('ref', ref))
    return dict(out, private=found.private, credentials=found.credentials, code=found.code,
                opaque=file_versions(repo, feed, found.clean) if shas else [])


# What the next commit adds.

_IDENT_DATE = re.compile(r'\s+\d+\s+[-+]\d{4}$')


def read_commit(repo, words=None, staged=True, message=None):
    """What the next commit adds, read against `words` (a Words, or None when there is no list) and the credential
    formats. With `staged`: the lines the index adds to HEAD (to nothing, before the first commit), the names of the
    files it adds or renames, and the author and committer the commit would carry (git var). With `message`: the
    commit message, every line. A new file that runs code on a host or on install is left to the push.

    -> {lines, files, private: [(where, excerpt)], credentials: [(where, what, excerpt)]}, every text masked.
    GitError when a git command fails: never a clean reading."""
    found, out, names = _Reading(words), dict(lines=0, files=0), set()

    def added(sha, path, n, text):
        out['lines'] += 1
        found.look(f'{path}:{n}', text, ('line', path, text))

    def named(sha, name):
        if name not in names:
            names.add(name)
            out['files'] += 1
        found.look_name('new file', name)

    if staged:
        try:
            base = git(repo, 'rev-parse', '--verify', '-q', 'HEAD^{commit}').strip()
        except GitError:                           # no commit yet: what is staged is read against nothing
            base = git(repo, 'hash-object', '-t', 'tree', '--stdin', stdin='').strip()
        _walk(git(repo, 'diff-index', '--cached', *_DIFF, base), added, named)
        for who in ('author', 'committer'):
            ident = _IDENT_DATE.sub('', git(repo, 'var', f'GIT_{who.upper()}_IDENT').strip())
            found.look(who, ident, (who, ident), credentials=False)
    if message is not None:
        for line in message.split('\n'):
            found.look('commit message', line, ('message', line))
    return dict(out, private=found.private, credentials=found.credentials)
