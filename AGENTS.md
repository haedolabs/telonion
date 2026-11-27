# Telonion

[By Haedo Labs™.](https://haedolabs.com/) Use that spelling for the maker in all public text. Telonion checks Git pushes, staged changes, commit messages, and prepared publish directories. It checks private words, credentials, and destination and file approvals. The overview is `README.md`; the full reference, `docs/reference.md`.

## Layout

- `telonion/scan.py`: the word lists (the main one, and a repository's own among git's files, `info/telonion-words`, read as one by `read_words`; an `include:` line in either reads another file into it, and one whose file is missing or cannot be read raises `ListError`, which names the list and the line, never the path), the credential formats, masking (`cleaner`: everything printed passes through it), the reading of a push (`read_push`): the lines each commit adds, the names of the files it adds or renames, its message, its author and committer, the annotated tags that go with it, and the ref names the push creates; and the reading of the next commit (`read_commit`): the lines the index adds to HEAD, the names of the files it adds or renames, who the commit is by, and its message.
- `telonion/hook.py`: the shared push decision (`prepush`), staged and message checks (`commit_hook`), hook installation, health, and templates. Preserve existing hooks and their input. Ordinary checks run first; a destination policy or a transfer hook requires inspection first. Git endpoint approval does not authorize an LFS upload. A release push that adds or updates a submodule pointer is held regardless of file approvals. `telonion.checkCommits false` turns off the commit checks only. Changing `hook_body` makes installed wrappers out of date.
- `telonion/preview.py`: `check --live` runs Git's dry run with a temporary inspection hook. The repository's own hooks never run in a preview. Offline checks remain estimates.
- `telonion/destinations.py`: repository-local approvals (`destination`, `approve`). Bind the remote name and effective push URL; bind a file approval to its path and full committed object ID as well. Removing the last destination still holds unknown endpoints.
- `telonion/directory.py`: `check -C REPO --directory STAGE --destination TARGET [--json] [--receipt]`. Inspect every entry, including dotfiles and empty directories. Bind `destination --publish` to the actual Pages account, project, environment, and branch; `approve --directory` to the stage-relative path and raw bytes at that destination. Keep publish approvals separate from Git's. The tree-v1 digest and version 1 JSON contract are specified in `docs/reference.md`. Incomplete reads have no digest. The publisher keeps the stage immutable and handles human approval, upload, and verification.
- `telonion/scan.py` also inventories changed path/object pairs with NUL-delimited Git output. Every outgoing version checked by name only counts. Inspect only actual tag objects in a negotiated push.
- `telonion/receipts.py`: `--receipt` saves a live preview or directory result. `TELONION_RECEIPT=1` saves receipts for pushes and live previews. Keep receipts private in the common Git directory. Save counts and the decision; never persist excerpts, URLs, or paths in a receipt.
- `telonion/cli.py`, `bin/telonion`: the command. `bin/pushgate` is its old name, kept so the hooks written under it still run.
- The old name, Push Gate: `OLD`, `setting`, `env`, and the fallbacks in `telonion/scan.py` read its settings (`pushgate.*`), variables (`$PUSHGATE_*`), and files (`~/.config/pushgate/`, `info/pushgate-words`) where the new ones are not set; `old_mark`, `old_names`, and `move_old_names` in `telonion/hook.py` count its hooks as Telonion's (out of date) and move a repository's names over on `telonion install`; `template_on` moves its template folder. Keep them while any repository may still hold the old names.
- `brand/`: the logo, the battlements: a keep with three merlons, the sapphire dot centred inside it. `python3 brand/logo.py` draws every file there and `docs/icon.png`, the README's icon.
- `tests/`: unittest. `tests/_helpers.py` gives each test a temporary folder and replaces git's global and system settings and the word list for its run.

## Rules of the code

- Standard library only. Python 3.9 or later, git 2.31 or later. No dependencies.
- Fail closed. A Git command that fails is never a clean reading. A selected main list or included file that is missing or unreadable stops the check; an unconfigured default is optional. A hook whose command is missing stops the push or the commit; status also verifies that Git can execute the wrapper. Raw Git errors and endpoint URLs never enter Telonion's diagnostics.
- Read more rather than less. When the remote cannot be asked what it holds, the hook reads the pushed history in full.
- Never print a word from the list or a credential, or the path an `include:` line names (it is a line of a private list). Every hit names its place, with the match masked (`[private]`, `[credential]`); an include is named by its list and line. Output lands in terminals, logs, and AI assistants' transcripts.
- Every rule gets a test first, on made-up words in made-up repositories. Tests build credentials at run time, so no file here holds one.
- Commit only this repository's files. Nothing personal, no other project's name, no machine's paths, and no narration in anything committed. Notes for one machine go in a `*.local.md` file beside this one, which git ignores; read it when it is there.
- Output is plain words with precise terms (commit, ref, remote, hook): one short summary for each run.
- When a command, default, or rule changes, update every document that states it: `README.md`, `docs/reference.md`, this file, and the command's help.

## Run the tests

    python3 -m unittest discover -s tests

Run them with Python 3.9 as well, the oldest supported version.
