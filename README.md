# Push Gate

By [Haedo Labs](https://haedolabs.com).

Push Gate reads what a git push would make public, and stops the push when that holds a word from your private list or a credential. It runs as git's pre-push hook on your own computer, and it sends nothing anywhere.

**Status:** version 0.1.0. Not released.

## What it reads

Every commit the remote does not hold yet, each on its own:

- the lines each commit adds, the names of the files it adds or renames, its message, and its author and committer;
- the annotated tags that go with the push, their messages and taggers, and the names of the branches and tags it creates on the remote.

A word that a later commit removed is still in the commit that added it, so it still stops the push. The hook asks the remote what it holds at push time (`git ls-remote`), so a remote that was deleted and made again empty is read as empty. If the remote cannot be asked, the hook reads the pushed history in full.

## What stops a push

- A word or pattern from your private list: names, places, account numbers, or anything else that must stay private.
- A credential in one of these fixed formats: GitHub, AWS, Slack, Anthropic, OpenAI, Google, Stripe, npm, and Hugging Face tokens and keys, private key blocks, and a long literal given to a name like `password` or `token`.
- A file that holds keys by its name: `.env`, `id_ed25519`, `*.pem`, `credentials.json`, and others.
- A new file that makes code run on a hosting service or on install, such as a GitHub workflow, `package.json`, `setup.py`, `pyproject.toml`, or a `Makefile`, unless the repository lists it: `git config --add pushgate.allowCode pyproject.toml`.
- A push that rewrites or deletes a branch on the remote, or lands on a remote commit this checkout has never seen. `PUSHGATE_ALLOW_REWRITE=1` lets one through on purpose, and `git config pushgate.allowRewrite true` turns the rule off for a repository.

No hit is printed in full. Each names its commit and place, with the word or credential masked, so a terminal log or an AI assistant's transcript does not repeat it:

```
Push Gate: the push to origin is stopped
  private word: 3441baa notes/plan.md:4: the [private] notes
  a GitHub token: 3441baa conf.py:1: [credential]
  A hit stays in the commit that added it, and a later commit does not remove it: amend, squash, or rebase that commit before it leaves.
  Text that may be public gets an `allow:` line in the word list (~/.config/pushgate/words.txt).
  A credential that was ever pushed anywhere is revoked, not only removed.
```

## The word list

One pattern a line: a regular expression, in which capitals and small letters match alike. A line that is not a valid expression is read as plain text. `allow: <pattern>` marks text that may appear though it holds a word, and a line that starts with `#` is a note. The list lives outside every repository, at the first of these that is set:

1. `$PUSHGATE_WORDS`;
2. `git config pushgate.words` (the repository's setting, then the global one);
3. `~/.config/pushgate/words.txt`.

`pushgate words --init` makes the list, readable by you alone. `pushgate words` counts its lines and never prints them.

## Run it

Needs Python 3.9 or later and git 2.31 or later. No other software.

```bash
bin/pushgate words --init            # make the word list, then add your words
bin/pushgate install -C ~/code/app   # the hook in one repository (its worktrees share it)
bin/pushgate check -C ~/code/app     # what the next push would make public
bin/pushgate check --all -C ~/code/app   # every commit, as before a first push
bin/pushgate status ~/code/*         # which repositories have the hook
```

`pushgate install` leaves another tool's pre-push hook in place, and it writes nothing when `core.hooksPath` sends git to a hooks folder that other repositories share.

## What it does not do

- It reads text. A word inside a binary file, such as an image, a PDF, or a Word file, is not seen. Only the file's name is read.
- A hook guards against accidents, not intent: `git push --no-verify` skips it.
- It finds a credential by its fixed format. A password with no format of its own is found only on a line that gives it to a name like `password`.

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests use made-up words and made-up repositories. They replace git's global and system settings for their run, so they never read your word list or your git settings.
