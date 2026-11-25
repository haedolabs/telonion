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
import os
import re
import subprocess

from . import short_path

ZERO = '0' * 40
EXCERPT = 160                                      # characters of a line shown with a hit, after masking


class GitError(RuntimeError):
    """A git command failed: what it was reading is unknown, so it is never a clean reading."""


def git(repo, *args, stdin=None, timeout=None, env=None):
    """git's output, run in `repo` with file names unquoted. GitError when git fails or does not answer in time."""
    io = dict(input=stdin) if stdin is not None else dict(stdin=subprocess.DEVNULL)
    try:
        r = subprocess.run(['git', '-C', repo, '-c', 'core.quotePath=false', *args], capture_output=True,
                           encoding='utf-8', errors='replace', timeout=timeout, env=env, **io)
    except subprocess.TimeoutExpired:
        raise GitError(f'git {args[0]}: no answer in {timeout} s')
    except OSError as e:
        raise GitError(f'git: {e}')
    if r.returncode:
        raise GitError(f'git {args[0]}: {(r.stderr or r.stdout).strip()[:300]}')
    return r.stdout


def config(repo, key, *kind):
    """A git setting as the repository sees it (its own, then the global one): every value, [] when it is unset.
    For a folder that does not exist, the global setting alone."""
    where = ['-C', repo] if repo and os.path.isdir(repo) else []
    r = subprocess.run(['git', *where, 'config', *kind, '--get-all', key], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    return [v for v in r.stdout.split('\n') if v] if r.returncode == 0 else []


# The private word list.

def words_path(repo='.'):
    """Where the private word list is: $PUSHGATE_WORDS, else `git config pushgate.words` (the repository's setting,
    then the global one), else ~/.config/pushgate/words.txt."""
    if os.environ.get('PUSHGATE_WORDS'):
        return os.path.expanduser(os.environ['PUSHGATE_WORDS'])
    set_in_git = config(repo, 'pushgate.words', '--type=path')
    if set_in_git:
        return os.path.expanduser(set_in_git[-1])
    return os.path.join(os.path.expanduser('~'), '.config', 'pushgate', 'words.txt')


def _pattern(text):
    """A line of the list as a pattern: a regular expression, capitals and small letters alike, or the plain text when
    it is not one."""
    try:
        return re.compile(text, re.I)
    except re.error:
        return re.compile(re.escape(text), re.I)


class ListError(OSError):
    """A list's `include:` line names a file that is not there or cannot be read. Its words name the list and the
    line, never the file the line names: an include's path is a line of a private list, and lines are never printed."""


def _lines(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read().split('\n')


class Words:
    """A private word list: one pattern a line, `allow: <pattern>` for text that may appear though it holds a word,
    `include: <path>` for another list read as part of this one, and # for notes. `paths` are the lists it was read
    from; `included` counts what the files they include gave: (files, patterns, allow lines)."""

    def __init__(self, path, words, allows, paths=None, included=(0, 0, 0)):
        self.path, self.words, self.allows, self.paths = path, words, allows, paths or [path]
        self.included = included

    @classmethod
    def read(cls, path):
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

        def take(lines, folder, at, depth):
            for n, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                key = line[:8].lower()
                if key.startswith('allow:'):
                    if line[6:].strip():
                        allows.append(_pattern(line[6:].strip()))
                        if depth:
                            given[1] += 1
                elif key == 'include:':
                    include(line[8:].strip(), folder, at(n), depth + 1)
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

        top = short_path(os.path.abspath(path))
        take(lines, os.path.dirname(os.path.abspath(path)), lambda n: f'{top} line {n}', 0)
        return cls(path, words, allows, included=(len(seen) - 1, given[0], given[1]))

    def joined(self, other):
        """This list and `other` read as one: the words of both, and the allow lines of both."""
        return Words(self.path, self.words + other.words, self.allows + other.allows, self.paths + other.paths,
                     tuple(a + b for a, b in zip(self.included, other.included)))

    def spans(self, text):
        """Where the list's words are in `text`, leaving out text an allow pattern covers: [(start, end)]."""
        filled = text
        for a in self.allows:                      # allowed text becomes spaces of its own length: places stay put
            filled = a.sub(lambda m: ' ' * len(m.group(0)), filled)
        return [(m.start(), m.end()) for w in self.words for m in w.finditer(filled) if m.end() > m.start()]


def own_words_path(repo='.'):
    """A repository's own list, among git's own files and so never committed: <git common dir>/info/pushgate-words,
    shared by the repository's worktrees. Its patterns add to the main list, and its allow lines apply to this
    repository alone. None outside a repository."""
    if not repo or not os.path.isdir(repo):
        return None
    r = subprocess.run(['git', '-C', repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode or not r.stdout.strip():
        return None
    return os.path.join(r.stdout.strip().split('\n')[-1], 'info', 'pushgate-words')


def read_words(repo='.'):
    """The main list (words_path) and the repository's own (own_words_path), read as one, or None when neither
    exists. A list that exists and cannot be read raises OSError: a list that exists is never skipped."""
    main = Words.read(words_path(repo))
    own_path = own_words_path(repo)
    own = Words.read(own_path) if own_path else None
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
    ('a literal given to a secret name', r'\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*["\'][^"\'\s]{12,}["\']', re.I),
)]
KEY_FILES = re.compile(r'(?:^|/)(?:\.env(?:\.[^/]*)?|id_(?:rsa|dsa|ecdsa|ed25519)|credentials(?:\.json)?|\.netrc|\.pypirc|'
                       r'[^/]*\.(?:pem|p12|pfx|key|keystore|jks|mobileprovision))$', re.I)
KEY_FILES_OK = re.compile(r'\.env\.(?:example|sample|template)$')
RUNS_CODE = re.compile(r'(?:^|/)(?:\.github/(?:workflows|actions)/.*|action\.ya?ml|package\.json|\.npmrc|setup\.py|'
                       r'setup\.cfg|pyproject\.toml|Makefile|\.gitlab-ci\.yml|\.circleci/.*)$')


def credential_spans(text):
    """The credentials in `text`: (what the first one is, [(start, end)]), or (None, [])."""
    what, spans = None, []
    for name, p in CREDENTIALS:
        for m in p.finditer(text):
            what = what or name
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


def cleaner(words):
    """A function that masks every word of `words` (a Words, or None) and every credential in a text."""
    def clean(text):
        spans = [(s, e, 'private') for s, e in (words.spans(text) if words else [])]
        spans += [(s, e, 'credential') for s, e in credential_spans(text)[1]]
        return mask(text, spans) if spans else text
    return clean


def _excerpt(text):
    text = text.strip()
    return text if len(text) <= EXCERPT else text[:EXCERPT - 3] + '...'


# What a push sends.

_SHA = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?$')
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
    out = git(repo, 'ls-remote', remote, timeout=timeout, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
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
        if KEY_FILES.search(name) and not KEY_FILES_OK.search(name) and ('k', name) not in self.seen:
            self.seen.add(('k', name))
            self.credentials.append((self.clean(where), 'a file that holds keys by its name', _excerpt(self.clean(name))))
        if (self.allow_code is not None and RUNS_CODE.search(name) and ('r', name) not in self.seen
                and not any(fnmatch.fnmatchcase(name, a) for a in self.allow_code)):
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
        if _SHA.match(line):                       # the commit whose diff follows (a merge's comes once a parent)
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


def read_push(repo, tips, stop=(), words=None, allow_code=(), tag_refs=(), ref_names=()):
    """What a push of `tips` makes public beyond the commits under `stop`, read against `words` (a Words, or None when
    there is no list) and the credential formats.

    Each commit is read on its own: the lines it adds (a merge's, against each parent), the names of the files it adds
    or renames, its message, its author and committer, and the annotated tags on it (`git push --follow-tags` sends
    those). A word that a later commit replaced is still in the commit that added it. `tag_refs` are tags read in full
    though their commit is already public; `ref_names` are the names the push gives refs on the remote.

    -> {commits, lines, files, private: [(where, excerpt)], credentials: [(where, what, excerpt)],
        code: [(where, name)]}, every text masked. GitError when a git command fails: never a clean reading."""
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
    if shas or tag_refs:
        sent, wanted = set(shas), set(tag_refs)
        fmt = '%(objecttype)%00%(*objectname)%00%(refname)%00%(taggername) %(taggeremail)%00%(contents)%1e'
        for rec in git(repo, 'for-each-ref', f'--format={fmt}', 'refs/tags').split('\x1e'):
            kind, target, ref, tagger, body = (rec.lstrip('\n').split('\x00', 4) + [''] * 5)[:5]
            if kind != 'tag' or (target not in sent and ref not in wanted):
                continue
            name = ref[len('refs/tags/'):]
            found.look(f'tag {name}', name, ('tag name', name))
            found.look(f'tag {name} tagger', tagger, ('tagger', tagger), credentials=False)
            for line in body.split('\n'):
                found.look(f'tag {name}', line, ('tag', name, line))
    for ref in ref_names:
        found.look('ref on the remote', ref, ('ref', ref))
    return dict(out, private=found.private, credentials=found.credentials, code=found.code)


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
