# Telonion reference

The full rules, settings, and limits. The overview is the [README](../README.md).

## What it reads

Every commit the remote does not hold yet, each on its own:

- the lines each commit adds, the names of the files it adds or renames, its message, and its author and committer;
- the actual tag objects sent, including nested or renamed tags, their messages and taggers, and the names given to refs on the remote. A local tag left behind does not stop the push.

A word that a later commit removed is still in the commit that added it, so it still stops the push. The hook asks the remote what it holds at push time (`git ls-remote`), so a remote that was deleted and made again empty is read as empty. If the remote cannot be asked, the hook reads the pushed history in full.

Before each commit, what that commit adds: the lines it adds, as staged (`git commit -a` and `git commit <file>` included), the names of the files it adds or renames, its author and committer, and its message as git will keep it. With an editor, git drops the message's comment lines and everything below its scissors line, and so does the check.

## Preview

`telonion check --live` previews `git push` using Git's dry run. Git selects the push URL, branches, and tags. The dry run gives Telonion the same proposed updates as a real push. It contacts the remote, runs no repository hook or uploader, and sends no ref updates. Its decision applies to those refs and that view of the remote. A repository's own check or the remote can still refuse a real push.

`check --live --remote release main:refs/heads/stable refs/tags/v1` previews that remote and those refspecs. `--follow-tags` includes the tags Git selects; Git's `push.followTags` setting also applies. With no arguments, Git chooses its usual push remote and refs. With refspecs and no `--remote`, the preview uses `origin`.

`telonion check [TIP]` is an offline estimate against the last fetch from `--remote` (default `origin`). `check --all [TIP]` reads all history reachable from that tip. Both include local tags that might follow the commits. Neither grants destination or file approval. `check --staged` reads the index; `-m MESSAGE` or `-F FILE` adds a message to that check.

## Destination and file approvals

| Command | Effect in this repository |
|---|---|
| `telonion destination origin` | Approve the named remote and its current push endpoint. The first rule holds every other destination until approved. |
| `telonion destination --release release` | Approve that endpoint and require approval for every file version checked by name only. |
| `telonion destination --remove release` | Withdraw the destination. Removing the last one leaves all destinations held. |
| `telonion approve release docs/guide.pdf` | Approve the committed file at `HEAD`. The working copy is not used. |
| `telonion approve --at REV release docs/guide.pdf` | Approve the version in a particular outgoing commit. `--remove` withdraws that file approval. |
| `telonion status` | Show the rules, including a remote whose endpoint has changed. |

Use `-C DIR` to select a repository. A destination needs a remote name made of letters, digits, dots, underscores, or hyphens, starting with a letter or digit, and one push URL. Give separate endpoints separate names. An address pushed directly is not a named approval. Telonion binds Git's effective push URL, including push URL rewrites. Local paths bind to their resolved location. Approval identifies a configured endpoint; it does not establish the server's ownership or visibility.

File approvals bind the remote name, endpoint, repository-relative path, and full Git blob ID. A rename, a new version, or a change of destination needs its own approval. Every outgoing version counts, even if a later commit deletes it. Approval covers only the name-only inspection; all other rules still apply. The bindings live in the repository's Git config (`telonion.destination` and `telonion.approvedFile`), shared by its worktrees. Endpoint and file identities are stored as hashes. Repositories without destination rules keep their existing push policy.

## Inspect a publish directory

`check -C REPO --directory STAGE --destination TARGET --json` reads the directory the publisher has prepared. `STAGE` is relative to the caller's working directory, independent of `-C`. It can be outside the source repository. Every regular file and directory under it counts, including dotfiles, ignored files, and empty directories. Git's index, history, hooks, and remotes are not involved.

`REPO` supplies the usual word lists, `allowCode` rules, and repository-local approvals. In directory mode a relative `telonion.words` Git setting starts at the worktree root (the Git directory for a bare repository). A relative `$TELONION_WORDS` starts at the caller's working directory.

Build `TARGET` from the **actual upload settings**: `cloudflare-pages/ACCOUNT/PROJECT/ENVIRONMENT/BRANCH`. Use the 32-hex-digit account ID, the lowercase project slug, `production` or `preview`, and the exact branch for either environment. Uppercase and lowercase hex identify the same account. Preserve the branch spelling, including capitals and slashes; use printable non-space characters and no empty, `.` or `..` path segments. The string is not a URL. Changing any field identifies a different destination. Telonion makes no request to Cloudflare.

```bash
target="cloudflare-pages/$account_id/$project/preview/$branch"
telonion destination -C "$repo" --publish "$target"
telonion approve -C "$repo" --directory "$stage" --destination "$target" -- assets/logo.png
telonion check -C "$repo" --directory "$stage" --destination "$target" --json
```

- **Destination approval is required**, even for a text-only or empty stage. Register each site separately. `destination --remove --publish TARGET` withdraws approval. These approvals have no effect on Git pushes.
- **File approval** binds the destination ID, full stage-relative path, and SHA-256 of the file bytes, without Git filters or line-ending conversion. Supply the path as it appears in the tree, with `/` separators and no empty, `.` or `..` segments. `approve --remove` with the same arguments withdraws that version. Removing a destination holds all its files; re-registering the same target retains its earlier file approvals. Only hashes are stored, in `telonion.publishDestination` and `telonion.publishFile` in the repository's local Git config.
- **Content checks** cover relative names, UTF-8 text line by line, key filenames, and the usual host/install code filenames. Invalid UTF-8, non-text control bytes, and common document, archive, and media filenames require binary approval. Text in one of those named formats is still checked if the bytes are readable as UTF-8 text. Approval does not excuse a private path, a credential, or a text finding. Telonion does not decode images or unpack documents.
- **Entry types:** regular files and directories only. A symbolic link (including at the stage root), FIFO, device, or socket makes the inspection incomplete. Directory mode needs filesystem support for descriptor-relative opens without following links.

### Result for the publisher

`--json` writes one JSON object and no findings to stdout. Without it, a person gets a summary and masked locations. `--receipt` also saves the JSON object, mode `0600`, under the source repository's common Git directory in `info/telonion-receipts/`. No record is saved by default. Keep receipt files and redirected stdout outside the stage.

| Exit | `decision` | `tree_digest` | Meaning |
|---|---|---|---|
| `0` | `passed` | digest | The whole tree was read and its required approvals were present. |
| `1` | `held` | digest | The whole tree was read; `reasons` gives every applicable policy category. |
| `2` | `incomplete` | `null` | The command, policy, read, or requested receipt could not be completed. Counts are zero. |

The version 1 object has `version`, `source` (`directory`), `decision`, `destination_id` (`sha256:` plus 64 hex digits, or `null` when unidentified), `tree_digest`, `files` (regular files), `binary` (files requiring approval), `binary_approved`, and `reasons` (sorted, unique codes). A pass has no reasons. Holds use `destination_unapproved`, `binary_unapproved`, `private_word`, `credential`, and `code_file`. Incomplete reasons include `invalid_arguments`, `invalid_destination`, `repository_unavailable`, `policy_unavailable`, `directory_unreadable`, `directory_changed`, `unsupported_entry`, `unsupported_filesystem`, and `receipt_unavailable`. No file path, target string, per-file hash, excerpt, or word-list value enters the object.

To compute `destination_id` independently, UTF-8 encode these six fields: `publish-destination-v1`, `cloudflare-pages`, lowercase account ID, project, environment, and branch. Join them with single NUL bytes (no trailing NUL), hash with SHA-256, and prefix the lowercase hex result with `sha256:`.

**Digest format (`tree-v1`).** Start SHA-256 with the ASCII bytes `telonion-tree-v1` and one NUL byte. Sort all entries by their raw root-relative pathname bytes, in unsigned byte order, using `/` as separator. For each entry, append ASCII `D` (directory) or `F` (regular file), an unsigned 8-byte big-endian path length, and the path bytes. For a file, also append the 32 raw bytes of SHA-256 of its exact contents. Return `tree-v1:sha256:` plus the lowercase hex digest. The root's own name, timestamps, permissions, and enumeration order do not enter the hash.

The publisher stages and freezes the directory, inspects it, gets human approval for the destination and tree digest, uploads those same bytes, and verifies the live result. A rebuild calls for another check. Telonion reads from open file descriptors and checks the entries again before returning; changes it detects invalidate the digest. This is a local decision about a supplied tree and target, not a filesystem lock or proof of an upload.

## Inspection receipts

The hook and live preview report what they read, which destination rule applied, the number of file versions checked by name only, and any missing approvals. For example:

```text
Telonion: the push to release is stopped
  2 commits, 34 added lines, and 1 new file name read
  28f49da docs/guide.pdf: this version has no approval for release
  approved destination (release)
  1 file version checked by name only
```

`telonion check --live --receipt` saves the decision for one preview. Setting `TELONION_RECEIPT=1` saves receipts for both `telonion check --live` and `git push`. Directory checks require the `--receipt` flag to save a receipt.

Each Git receipt is a separate JSON file (mode `0600`) in the common Git directory's `info/telonion-receipts/`. It records the time, source, masked remote label, policy, decision, reason categories, and counts. It contains no excerpts, file names, URLs, or list values. A receipt describes Telonion's local decision, not delivery. No receipt is kept by default.

## What stops a push

- A word or pattern from your private list: names, places, account numbers, or anything else that must stay private.
- A credential in one of these fixed formats: GitHub, AWS, Slack, Anthropic, OpenAI, Google, Stripe, npm, and Hugging Face tokens and keys, private key blocks, and a long literal given to a name like `password` or `token`.
- A file that holds keys by its name: `.env`, `id_ed25519`, `*.pem`, `credentials.json`, and others.
- A new file that makes code run on a hosting service or on install, such as a GitHub workflow, `package.json`, `setup.py`, `pyproject.toml`, or a `Makefile`, unless the repository lists it: `git config --add telonion.allowCode pyproject.toml`.
- A push that rewrites or deletes a branch on the remote, or lands on a remote commit this checkout has never seen. `TELONION_ALLOW_REWRITE=1` lets one through on purpose, and `git config telonion.allowRewrite true` turns the rule off for a repository.
- An unapproved destination or file version when the repository requires approval. A ref pointing directly or through a tag to an object other than a commit is held for lack of an inspection.

A commit is stopped by the first three: a private word, a credential, or a file that holds keys by its name. A new file that runs code waits for the push.

Telonion masks findings and private names in its diagnostics, omits addresses, and gives a short reason for Git failures. Its output is separate from Git's and from a repository's own hooks. A finding identifies its place:

```
private word: 3441baa notes/plan.md:4: the [private] notes
a GitHub token: 3441baa conf.py:1: [credential]
```

## The word list

One pattern a line: a regular expression, in which capitals and small letters match alike. A line that is not a valid expression is read as plain text. `allow: <pattern>` marks text that may appear though it holds a word, and a line that starts with `#` is a note. The list lives outside every repository, at the first of these that is set:

1. `$TELONION_WORDS`;
2. `git config telonion.words` (the repository's setting, then the global one);
3. `~/.config/telonion/words.txt`.

`telonion words --init` makes the list, readable by you alone. `telonion words` counts its lines and never prints them.

A list selected by an environment variable or Git setting is required. If it disappears, pushes, commits with the checks enabled, and checks stop. On an installation with no selected or default list, the credential checks still run.

A repository can also keep a list of its own, among git's own files, so it is never committed: `.git/info/telonion-words`, shared by the repository's worktrees. Its patterns add to the main list, and its `allow:` lines apply to that repository alone, so one project's ordinary words can pass there without passing everywhere. `telonion words --init --here` makes it.

For a prepared directory, a repository's own list or a file it includes can contain `publish-exact: "  public label: sample."`. The value is a nonempty JSON string. It must match a complete original UTF-8 text line (without its line ending) or a complete stage-relative path, including capitalization and whitespace. This comparison precedes the regular-expression allowances. The string applies only to private-word findings in that repository's prepared directories. Git checks, diagnostic masking, credential checks, and destination and binary approvals keep their usual rules. A malformed entry or one in the main list makes the policy unreadable.

`include: <path>` in either list reads another file as part of that list, under the same rules, so a list that a project writes for itself, such as names kept outside every repository, is read where it is, never copied in. The path starts from `~` or from the folder of the list that names it. An included file is read once, however many lines name it, and its own `include:` lines are read too. An included file that is missing or cannot be read stops every push and every commit, as a list that cannot be read does; the message names the list and the line, never the path, since the path is a line of a private list. `telonion words` and `telonion status` count the included lines with the rest, and print none of them.

## Every repository

`telonion install` writes pre-push, pre-commit, and commit-msg. An existing hook moves beside Telonion's as `<name>.chained` and gets Git's arguments and input. Both must pass. Commit hooks and ordinary pre-push checks in repositories without destination rules run first. A pre-push hook in a repository with destination rules waits for inspection.

The standard Git LFS pre-push hook uploads objects to a separate service. Telonion recognizes its `git lfs pre-push` invocation as a transfer hook; identify other upload hooks with `git config --local telonion.transferHook true`. Without destination rules, a transfer hook runs only after the Git inspection passes. With destination rules, a recognized transfer hook or an outgoing LFS pointer holds the push: Git endpoint approval cannot authorize that separate transfer. Approving a pointer as a file cannot release it. Custom hooks are trusted local programs; Telonion does not sandbox them.

`telonion status` checks the wrapper text, execute permission, Python executable, and readable launcher. A 0.4 wrapper still calls the current inspector. `install --update` refreshes it and updates commit hooks only where installed. `uninstall` restores the repository's hooks. `install` leaves `core.hooksPath` alone.

A repository that holds private words on purpose, and is never made public, can turn the commit check off: `git config telonion.checkCommits false`. Its pushes are still read.

`telonion template` puts the hooks in git's template, so every repository made with `git init` or `git clone` from then on has them. When git has no template folder set, Telonion makes its own from git's default template (`~/.config/telonion/template`) and sets `init.templateDir`. `telonion template --off` takes the hooks out again. `telonion template --update` brings the hooks there up to date and adds no commit check.

## The old name

Telonion was called Push Gate until version 0.4.0. Nothing it set up under that name stops working:

- `pushgate` still runs Telonion, so every hook Push Gate wrote still reads every push and commit.
- A hook Push Gate wrote counts as Telonion's, out of date, never as another tool's: `telonion install` replaces it, and keeps a repository's own hook chained beside it.
- The old settings (`pushgate.words`, `pushgate.allowCode`, `pushgate.allowRewrite`, `pushgate.checkCommits`), variables (`$PUSHGATE_WORDS`, `PUSHGATE_ALLOW_REWRITE`), and files (`~/.config/pushgate/words.txt`, `.git/info/pushgate-words`) are read wherever the new ones are not set.
- `telonion install` (or `telonion install --update`, which adds no commit check) moves a repository over: its hooks, its own word list (renamed, never read aloud), and its own `pushgate.*` settings, when it has no `telonion.*` ones yet. `telonion template` (or `telonion template --update`) moves the template folder Push Gate made to `~/.config/telonion/template`. `telonion status` names a repository that still keeps the old names.

## What it does not do

- It reads added text, not text rendered inside documents or media. Git-classified binary changes and common document, archive, and media formats are reported as name-only. An LFS pointer is not its payload.
- A submodule pointer names a commit in another repository, which needs its own inspection. The live preview does not recurse into submodules. A release push that adds or updates a submodule pointer is held; `telonion approve` cannot clear it.
- A hook guards against accidents, not intent: `git push --no-verify` and `git commit --no-verify` skip it.
- The commit check runs when `git commit` makes a commit; when `git merge` makes one, only its message is read. A commit that another command makes, such as `git rebase`, `git cherry-pick`, or `git am`, may not be read until the push, which reads every commit.
- It finds a credential by its fixed format. A password with no format of its own is found only on a line that gives it to a name like `password`.
