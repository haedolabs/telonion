"""Inspect the bytes of a prepared directory for a direct publisher. No index, remote, or uploader is involved."""
import codecs
import errno
import hashlib
import io
import os
import re
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from . import fingerprint
from .destinations import (PUBLISH_DESTINATION, PUBLISH_FILE, publish_approvals, publish_key, publish_repository,
                           set_publish_approval)
from .receipts import receipt_folder, save_receipt
from .scan import OPAQUE_NAME, GitError, cleaner, credential_spans, key_file, read_words, setting, unapproved_code


class DirectoryError(OSError):
    """A fixed reason code, safe to return even when the word lists are unavailable."""


def _stamp(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _check_stamp(expected, actual):
    if _stamp(actual) != _stamp(expected):
        raise DirectoryError('directory_changed')


@contextmanager
def _opened(parent, name, info, *, directory):
    """Open the entry we enumerated. Never follow a replacement link or wait on a replacement FIFO."""
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(info.st_mode):
        raise DirectoryError('unsupported_entry')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if directory:
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(name, flags, dir_fd=parent)
    except OSError as e:
        if e.errno in (errno.ENOENT, errno.ELOOP, errno.ENOTDIR):
            raise DirectoryError('directory_changed') from None
        raise
    try:
        _check_stamp(info, os.fstat(fd))
        yield fd
        _check_stamp(info, os.fstat(fd))
        _check_stamp(info, os.stat(name, dir_fd=parent, follow_symlinks=False))
    finally:
        os.close(fd)


def _root(directory):
    if (not all(hasattr(os, flag) for flag in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'))
            or os.open not in os.supports_dir_fd or os.listdir not in os.supports_fd
            or os.stat not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks):
        raise DirectoryError('unsupported_filesystem')
    if not directory:
        raise DirectoryError('directory_unreadable')
    # A trailing slash or /. would make stat follow a link at the root. Preserve the meaning of interior '..'.
    path = os.fsdecode(directory).rstrip('/') or '/'
    while path.endswith('/.'):
        path = path[:-2].rstrip('/') or '/'
    return _opened(None, path, os.stat(path, follow_symlinks=False), directory=True)


def _entries(parent, prefix=''):
    for name in sorted(os.listdir(parent)):
        path = prefix + name
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            with _opened(parent, name, info, directory=True) as child:
                yield parent, name, path, info
                yield from _entries(child, path + '/')
        elif stat.S_ISREG(info.st_mode):
            yield parent, name, path, info
        else:
            raise DirectoryError('unsupported_entry')


def _text_reasons(text, words, exact=True):
    if words and (not exact or text not in words.publish_exact) and words.spans(text):
        yield 'private_word'
    if credential_spans(text)[0]:
        yield 'credential'


_NON_TEXT = re.compile(rb'[\x00-\x08\x0e-\x1f\x7f]')


def read_file(parent, name, info, *, inspect=False, words=None):
    """Hash every byte and scan complete lines from those reads, including readable parts of a mixed binary file."""
    digest = hashlib.sha256()
    decoder = io.IncrementalNewlineDecoder(codecs.getincrementaldecoder('utf-8-sig')(), True)
    readable = (io.IncrementalNewlineDecoder(codecs.getincrementaldecoder('utf-8-sig')('ignore'), True, 'ignore')
                if inspect else None)
    text, pending, pending_exact, line_number, first = True, [], True, 0, {}

    def check_line(line, exact):
        nonlocal line_number
        line_number += 1
        for reason in _text_reasons(line, words, exact):
            first.setdefault(reason, line_number)

    with _opened(parent, name, info, directory=False) as fd, open(fd, 'rb', closefd=False) as stream:
        while True:
            block = stream.read(128 * 1024)
            digest.update(block)
            if text:
                text = not _NON_TEXT.search(block)
                if text:
                    try:
                        decoder.decode(block, final=not block)
                    except UnicodeDecodeError:
                        text = False
            if inspect:
                decoded = readable.decode(block, final=not block)
                lines = decoded.split('\n')
                pending.append(lines[0])
                if len(lines) > 1:
                    check_line(''.join(pending), pending_exact and text)
                    for line in lines[1:-1]:
                        check_line(line, text)
                    pending = [lines[-1]]
                    pending_exact = text
                else:
                    pending_exact = pending_exact and text
            if not block:
                break
        if stream.tell() != info.st_size:
            raise DirectoryError('directory_changed')
    if any(pending):
        check_line(''.join(pending), pending_exact)
    return digest.digest(), bool(not text or OPAQUE_NAME.search(name)), first


def _file_key(destination, path, digest):
    return fingerprint('publish-file-v1', destination, path, digest.hex())


def _exact_entry(parent, name):
    # Some filesystems accept other spellings. Only a path listed in the stage can receive approval.
    if name not in os.listdir(parent):
        raise GitError('use the exact path in the prepared directory')
    return os.stat(name, dir_fd=parent, follow_symlinks=False)


def approve_directory_file(repo, directory, target, path, remove=False):
    key = publish_key(target)
    _, env = publish_repository(repo)
    if key not in publish_approvals(repo, PUBLISH_DESTINATION, env):
        raise GitError('approve this publish destination first')
    parts = path.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise GitError('use a file path relative to the prepared directory')
    with ExitStack() as stack:
        parent = stack.enter_context(_root(directory))
        for part in parts[:-1]:
            parent = stack.enter_context(_opened(parent, part, _exact_entry(parent, part), directory=True))
        name = parts[-1]
        digest, opaque, _ = read_file(parent, name, _exact_entry(parent, name))
    if not opaque:
        raise GitError('this file is read as text; it needs no binary approval')
    set_publish_approval(repo, PUBLISH_FILE, _file_key(key, path, digest), remove, env)


def _tree_digest(entries):
    tree = hashlib.sha256(b'telonion-tree-v1\0')
    for path, (_, digest) in sorted(entries.items()):
        tree.update(b'D' if digest is None else b'F')
        tree.update(len(path).to_bytes(8, 'big'))
        tree.update(path)
        if digest is not None:
            tree.update(digest)
    return 'tree-v1:sha256:' + tree.hexdigest()


def _inspect_tree(directory, key, enrolled, approvals, words, allow_code, details):
    entries, reasons, messages = {}, set(), []
    files = binary = approved = 0
    clean = cleaner(words)

    def hold(reason, path, line=None):
        reasons.add(reason)
        if details:
            where = clean(path) + (f':{line}' if line else '')
            messages.append(f'  {where}: {reason.replace("_", " ")}')

    if not enrolled:
        reasons.add('destination_unapproved')
    with _root(directory) as root:
        for parent, name, path, info in _entries(root):
            for reason in _text_reasons(path, words):
                hold(reason, path)
            digest = None
            if stat.S_ISREG(info.st_mode):
                files += 1
                if key_file(path):
                    hold('credential', path)
                if unapproved_code(path, allow_code):
                    hold('code_file', path)
                digest, opaque, found = read_file(parent, name, info, inspect=True, words=words)
                for reason, line in found.items():
                    hold(reason, path, line)
                if opaque:
                    binary += 1
                    if enrolled and _file_key(key, path, digest) in approvals:
                        approved += 1
                    else:
                        hold('binary_unapproved', path)
            entries[os.fsencode(path)] = _stamp(info), digest

        # A file can change after we close it while we read a later file. Recheck membership and identities too.
        seen = 0
        for _, _, path, info in _entries(root):
            entry = entries.get(os.fsencode(path))
            if entry is None or entry[0] != _stamp(info):
                raise DirectoryError('directory_changed')
            seen += 1
        if seen != len(entries):
            raise DirectoryError('directory_changed')

    record = dict(version=1, source='directory', decision='held' if reasons else 'passed',
                  destination_id='sha256:' + key, tree_digest=_tree_digest(entries), files=files, binary=binary,
                  binary_approved=approved, reasons=sorted(reasons))
    return record, messages


def incomplete(reason, destination_id=None):
    return dict(version=1, source='directory', decision='incomplete', destination_id=destination_id,
                tree_digest=None, files=0, binary=0, binary_approved=0, reasons=[reason])


def _receipt_inside_stage(directory, common):
    root = Path(os.path.realpath(directory))
    folder = Path(os.path.realpath(receipt_folder(common)))
    if root == folder or root in folder.parents:
        return True
    try:
        info = root.stat()
    except FileNotFoundError:
        return False
    # On some filesystems two different path spellings identify the same directory.
    for parent in (folder, *folder.parents):
        try:
            if os.path.samestat(info, parent.stat()):
                return True
        except FileNotFoundError:
            continue
    return False


def inspect_directory(repo, directory, target, *, save=False, details=False):
    """A path-free public result and optional masked findings for a person. Discard partial reads on error."""
    common = destination_id = None
    failure = 'repository_unavailable'
    try:
        common, env = publish_repository(repo)
        failure = 'invalid_destination'
        key = publish_key(target)
        destination_id = 'sha256:' + key
        failure = 'policy_unavailable'
        words = read_words(repo, common=common, git_env=env)
        enrolled = key in publish_approvals(repo, PUBLISH_DESTINATION, env)
        approvals = publish_approvals(repo, PUBLISH_FILE, env)
        allow_code = setting(repo, 'allowCode', both=True, git_env=env)
        failure = 'directory_unreadable'
        record, messages = _inspect_tree(directory, key, enrolled, approvals, words, allow_code, details)
    except (GitError, OSError, UnicodeError, RecursionError) as e:
        record = incomplete(str(e) if isinstance(e, DirectoryError) else failure, destination_id)
        messages = []
    if save and common is not None:
        try:
            # Writing the receipt inside the stage would change the very tree it identifies.
            if _receipt_inside_stage(directory, common):
                raise DirectoryError('receipt_unavailable')
            save_receipt(repo, record, common=common)
        except (OSError, UnicodeError):
            return incomplete('receipt_unavailable', destination_id), []
    return record, messages
