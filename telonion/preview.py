"""Let Git negotiate a dry run and give the inspection hook exactly the same input as on a push."""
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from .hook import LAUNCHER, PY, hook_kind, hook_path
from .receipts import inspection_record, save_receipt
from .scan import GitError


def live_preview(repo, remote, refs, follow_tags=False, receipt=False):
    original = hook_path(repo)
    if not original:
        raise GitError('the preview needs a Git repository')
    with tempfile.TemporaryDirectory(prefix='telonion-preview-') as folder:
        report = Path(folder, 'decisions')
        report.touch(mode=0o600)
        kind = hook_kind(original, 'pre-push')
        command = [PY, LAUNCHER, 'hook', '--preview-output', str(report)]
        if kind != 'none':
            command.extend(['--first', original if kind == "another tool's" else original + '.chained'])
        wrapper = Path(folder, 'pre-push')
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(command) + ' -- "$@"\n', encoding='utf-8')
        wrapper.chmod(0o700)
        args = ['git', '-C', repo, '-c', f'core.hooksPath={folder}', 'push', '--dry-run', '--porcelain',
                '--recurse-submodules=no']
        if follow_tags:
            args.append('--follow-tags')
        if remote or refs:
            args.extend(['--', remote or 'origin', *refs])
        failure = 'Git could not complete the proposed push; check the remote, upstream, and refspecs.'
        try:
            status = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    env=dict(os.environ, GIT_TERMINAL_PROMPT='0'), timeout=180).returncode
        except subprocess.TimeoutExpired:
            status, failure = 2, 'the push preview timed out'
        code, lines, receipts = 0, ['Telonion: live push preview'], []
        for entry in report.read_text(encoding='utf-8').splitlines():
            result, messages, record = json.loads(entry)
            code = max(code, result)
            lines.extend(messages)
            receipts.append(record)
        if (status and not code) or not receipts:
            # A dry run may fail before Git offers any updates. An empty hook input is not clearance for that push.
            code, lines = 2, [lines[0], failure]
            receipts = [inspection_record('preview', 'the destination', code, {'error'}, None, 'unread', False)]
        if receipt or os.environ.get('TELONION_RECEIPT') == '1':
            for record in receipts:
                save_receipt(repo, record)
        return code, lines
