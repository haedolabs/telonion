"""A receipt records a local inspection decision, never its excerpts, paths, or endpoint."""
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone

from .scan import git


def inspection_record(source, remote, code, reasons, reading, policy, word_list_loaded):
    counts = reading or {}
    decision = 'passed' if code == 0 else 'held'
    if 'error' in reasons:
        decision = 'incomplete'
    opaque = counts.get('opaque', ())
    return dict(version=1, time=datetime.now(timezone.utc).isoformat(), source=source, destination=remote,
                decision=decision, reasons=sorted(reasons), policy=policy, word_list_loaded=word_list_loaded,
                approved_files=counts.get('approved_files', 0), ref_updates=counts.get('ref_updates', 0),
                inspected=reading is not None, commits=counts.get('commits', 0),
                added_lines=counts.get('lines', 0), new_names=counts.get('files', 0),
                name_only=len(opaque), lfs=sum(kind == 'LFS' for _, _, _, kind in opaque))


def receipt_folder(common):
    return os.path.join(common, 'info', 'telonion-receipts')


def save_receipt(repo, record, *, common=None):
    if common is None:
        common = git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir').removesuffix('\n')
    folder = receipt_folder(common)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix='.pending-', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2)
            f.write('\n')
        os.replace(path, os.path.join(folder, uuid.uuid4().hex + '.json'))
    finally:
        if os.path.exists(path):
            os.unlink(path)
