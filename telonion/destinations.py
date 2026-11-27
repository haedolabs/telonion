"""A repository's approved push endpoints and exact file versions. Neither URLs nor file paths are saved."""
import os
import re

from . import fingerprint
from .scan import GitError, config, git, lfs_pointers, repository_root

_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
_HASH = re.compile(r'[0-9a-f]{64}')


def label(name):
    return name if _NAME.fullmatch(name) else 'the destination'


def endpoint(repo, url):
    # Keep distinct transports, users, ports, queries, and paths distinct. Never render this input.
    if not url or '\n' in url or '\r' in url:
        raise GitError('the push endpoint could not be identified')
    if ':' not in url.split('/')[0]:               # a local path, relative to Git's working directory
        if not os.path.isabs(url):
            url = os.path.join(repository_root(repo), url)
        url = os.path.realpath(url)
    return fingerprint(url)


def destinations(repo):
    result = {}
    for value in config(repo, 'telonion.destination', '--local'):
        fields = value.split()
        if (len(fields) != 3 or not _NAME.fullmatch(fields[0]) or fields[1] not in ('allow', 'release', 'removed')
                or not _HASH.fullmatch(fields[2]) or fields[0] in result):
            raise GitError('the destination rules could not be read')
        result[fields[0]] = tuple(fields[1:])
    return result


def named_endpoint(repo, name):
    if not _NAME.fullmatch(name):
        raise GitError('use a configured remote name')
    urls = git(repo, 'remote', 'get-url', '--push', '--all', '--', name).splitlines()
    if len(urls) != 1:
        raise GitError('use a remote with one push URL; give each endpoint its own remote name')
    return endpoint(repo, urls[0])


def set_destination(repo, name, mode):
    rules = destinations(repo)
    if mode == 'removed':
        if name not in rules:
            raise GitError('no destination rule for this remote')
        key = rules[name][1]
    else:
        key = named_endpoint(repo, name)
    # One locked Git config update. A removed final entry still holds unknown destinations.
    git(repo, 'config', '--local', '--replace-all', 'telonion.destination', f'{name} {mode} {key}',
        '^' + re.escape(name) + ' ')


def approve_file(repo, name, path, revision, remove=False):
    key = named_endpoint(repo, name)
    if destinations(repo).get(name) != ('release', key):
        raise GitError('approve the release destination first')
    if not path or path.startswith('/') or any(s in ('', '.', '..') for s in path.split('/')):
        raise GitError('use a file path relative to the repository root')
    commit = git(repo, 'rev-parse', '--verify', '--end-of-options', revision + '^{commit}').strip()
    oid = git(repo, 'rev-parse', '--verify', '--end-of-options', f'{commit}:{path}').strip()
    if git(repo, 'cat-file', '-t', oid).strip() != 'blob':
        raise GitError('approval requires a file in that commit')
    if lfs_pointers(repo, [oid]):
        raise GitError('an LFS pointer cannot approve a separate LFS transfer')
    identity = fingerprint(name, key, fingerprint(path, oid))
    if remove:
        git(repo, 'config', '--local', '--unset-all', 'telonion.approvedFile', '^' + identity + '$')
    else:
        git(repo, 'config', '--local', '--replace-all', 'telonion.approvedFile', identity, '^' + identity + '$')


def describe_destinations(repo):
    descriptions = []
    for name, (mode, key) in destinations(repo).items():
        if mode != 'removed':
            try:
                if named_endpoint(repo, name) != key:
                    mode = 'endpoint changed'
            except GitError:
                mode = 'endpoint unavailable'
        descriptions.append(f'{name} ({mode})')
    return ', '.join(descriptions)


# Direct-publish approvals live in separate local settings. The Git hook never consults them.
PUBLISH_DESTINATION = 'telonion.publishDestination'
PUBLISH_FILE = 'telonion.publishFile'


def publish_repository(repo):
    """Use the repository selected by -C, even if a caller inherited another worktree's Git environment."""
    if not repo:
        raise GitError('select the repository with -C')
    env = os.environ.copy()
    for key in ('GIT_DIR', 'GIT_COMMON_DIR', 'GIT_WORK_TREE'):
        env.pop(key, None)
    common = git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir', env=env, binary=True)
    return os.fsdecode(common.removesuffix(b'\n')), env


def publish_key(target):
    """Identity from actual upload settings. The branch may itself contain slashes."""
    fields = (target or '').split('/', 4)
    if len(fields) == 5:
        service, account, project, environment, branch = fields
        if (service == 'cloudflare-pages' and re.fullmatch('[0-9a-fA-F]{32}', account)
                and re.fullmatch('[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', project)
                and environment in ('production', 'preview') and branch.isprintable()
                and not any(c.isspace() for c in branch) and all(p not in ('', '.', '..') for p in branch.split('/'))):
            parts = ('publish-destination-v1', service, account.lower(), project, environment, branch)
            return fingerprint(*(part.encode('utf-8') for part in parts))
    raise GitError('use cloudflare-pages/ACCOUNT/PROJECT/production/BRANCH or its preview equivalent')


def publish_approvals(repo, setting_name, env):
    values = set(config(repo, setting_name, '--local', git_env=env))
    if not all(_HASH.fullmatch(v) for v in values):
        raise GitError('the publish approvals could not be read')
    return values


def set_publish_approval(repo, setting_name, identity, remove, env):
    current = publish_approvals(repo, setting_name, env)
    if remove:
        if identity in current:
            git(repo, 'config', '--local', '--fixed-value', '--unset-all', setting_name, identity, env=env)
    else:
        git(repo, 'config', '--local', '--fixed-value', '--replace-all', setting_name, identity, identity, env=env)


def set_publish_destination(repo, target, remove=False):
    key = publish_key(target)
    _, env = publish_repository(repo)
    set_publish_approval(repo, PUBLISH_DESTINATION, key, remove, env)
