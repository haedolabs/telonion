# Push Gate

By Haedo Labs. Push Gate reads what a git push would make public (every commit the remote does not hold, each on its own) and stops the push when that holds a word from a private list or a credential. Before each commit, it reads what the commit adds the same way. The overview is `README.md`.

## Layout

- `pushgate/scan.py`: the word lists (the main one, and a repository's own among git's files, `info/pushgate-words`, read as one by `read_words`; an `include:` line in either reads another file into it, and one whose file is missing or cannot be read raises `ListError`, which names the list and the line, never the path), the credential formats, masking (`cleaner`: everything printed passes through it), the reading of a push (`read_push`): the lines each commit adds, the names of the files it adds or renames, its message, its author and committer, the annotated tags that go with it, and the ref names the push creates; and the reading of the next commit (`read_commit`): the lines the index adds to HEAD, the names of the files it adds or renames, who the commit is by, and its message.
- `pushgate/hook.py`: git's hooks (`HOOKS`: pre-push, pre-commit, and commit-msg). `prepush`: the repository's own pre-push hook run first, kept beside Push Gate's as `pre-push.chained`; what the remote holds, asked with `git ls-remote`; the rewrite rule; the result as lines. `commit_hook`: the pre-commit and commit-msg hooks, each after the repository's own (`<name>.chained`); `kept_message`, the message as git keeps it; `pushgate.checkCommits false` turns them off for a repository. The hooks' place in a repository (`install`, which keeps each of a repository's own hooks and runs it first; `uninstall`, which puts them back; `state`), and in git's template for repositories made after it (`template_on`, `template_off`). A change to a hook's text (`hook_body`) makes every hook already written out of date, until `pushgate install` runs again in each repository.
- `pushgate/cli.py`, `bin/pushgate`: the command.
- `brand/`: the logo. `python3 brand/logo.py` draws every file there and `docs/icon.png`, the README's icon.
- `tests/`: unittest. `tests/_helpers.py` gives each test a temporary folder and replaces git's global and system settings and the word list for its run.

## Rules of the code

- Standard library only. Python 3.9 or later, git 2.31 or later. No dependencies.
- Fail closed. A git command that fails is never a clean reading. A word list that exists and cannot be read stops the push and the commit, and so does an `include:` line whose file is missing or cannot be read. A hook whose command is missing stops the push or the commit.
- Read more rather than less. When the remote cannot be asked what it holds, the hook reads the pushed history in full.
- Never print a word from the list or a credential, or the path an `include:` line names (it is a line of a private list). Every hit names its place, with the match masked (`[private]`, `[credential]`); an include is named by its list and line. Output lands in terminals, logs, and AI assistants' transcripts.
- Every rule gets a test first, on made-up words in made-up repositories. Tests build credentials at run time, so no file here holds one.
- Commit only this repository's files. Nothing personal, no other project's name, no machine's paths, and no narration in anything committed. Notes for one machine go in a `*.local.md` file beside this one, which git ignores; read it when it is there.
- Output is plain words with precise terms (commit, ref, remote, hook): one short summary for each run.
- When a command, default, or rule changes, update every document that states it: `README.md`, this file, and the command's help.

## Run the tests

    python3 -m unittest discover -s tests

Run them with Python 3.9 as well, the oldest supported version.
