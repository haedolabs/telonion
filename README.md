# <img src="docs/icon.png" alt="" width="32" height="32"> Push Gate

By [Haedo Labs](https://haedolabs.com).

Push Gate reads what a git push would make public, and stops the push when that holds a word from your private list or a credential. It runs as git's pre-push hook on your own computer, and it sends nothing anywhere. Before each commit, as git's pre-commit and commit-msg hooks, it reads what the commit adds the same way, so a private word is stopped before it enters the history at all.

**Status:** version 0.3.0.

## What it reads

Every commit the remote does not hold yet, each on its own:

- the lines each commit adds, the names of the files it adds or renames, its message, and its author and committer;
- the annotated tags that go with the push, their messages and taggers, and the names of the branches and tags it creates on the remote.

A word that a later commit removed is still in the commit that added it, so it still stops the push. The hook asks the remote what it holds at push time (`git ls-remote`), so a remote that was deleted and made again empty is read as empty. If the remote cannot be asked, the hook reads the pushed history in full.

Before each commit, what that commit adds: the lines it adds, as staged (`git commit -a` and `git commit <file>` included), the names of the files it adds or renames, its author and committer, and its message as git will keep it. With an editor, git drops the message's comment lines and everything below its scissors line, and so does the check.

## What stops a push

- A word or pattern from your private list: names, places, account numbers, or anything else that must stay private.
- A credential in one of these fixed formats: GitHub, AWS, Slack, Anthropic, OpenAI, Google, Stripe, npm, and Hugging Face tokens and keys, private key blocks, and a long literal given to a name like `password` or `token`.
- A file that holds keys by its name: `.env`, `id_ed25519`, `*.pem`, `credentials.json`, and others.
- A new file that makes code run on a hosting service or on install, such as a GitHub workflow, `package.json`, `setup.py`, `pyproject.toml`, or a `Makefile`, unless the repository lists it: `git config --add pushgate.allowCode pyproject.toml`.
- A push that rewrites or deletes a branch on the remote, or lands on a remote commit this checkout has never seen. `PUSHGATE_ALLOW_REWRITE=1` lets one through on purpose, and `git config pushgate.allowRewrite true` turns the rule off for a repository.

A commit is stopped by the first three: a private word, a credential, or a file that holds keys by its name. A new file that runs code waits for the push.

No hit is printed in full. Each names its commit and place, with the word or credential masked, so a terminal log or an AI assistant's transcript does not repeat it:

```
Push Gate: the push to origin is stopped
  private word: 3441baa notes/plan.md:4: the [private] notes
  a GitHub token: 3441baa conf.py:1: [credential]
  A hit stays in the commit that added it, and a later commit does not remove it: amend, squash, or rebase that commit before it leaves.
  Text that may be public gets an `allow:` line in the word list (~/.config/pushgate/words.txt), or, for this repository alone, in its own (~/code/app/.git/info/pushgate-words).
  A credential that was ever pushed anywhere is revoked, not only removed.
```

## The word list

One pattern a line: a regular expression, in which capitals and small letters match alike. A line that is not a valid expression is read as plain text. `allow: <pattern>` marks text that may appear though it holds a word, and a line that starts with `#` is a note. The list lives outside every repository, at the first of these that is set:

1. `$PUSHGATE_WORDS`;
2. `git config pushgate.words` (the repository's setting, then the global one);
3. `~/.config/pushgate/words.txt`.

`pushgate words --init` makes the list, readable by you alone. `pushgate words` counts its lines and never prints them.

A repository can also keep a list of its own, among git's own files, so it is never committed: `.git/info/pushgate-words`, shared by the repository's worktrees. Its patterns add to the main list, and its `allow:` lines apply to that repository alone, so one project's ordinary words can pass there without passing everywhere. `pushgate words --init --here` makes it.

`include: <path>` in either list reads another file as part of that list, under the same rules, so a list that a project writes for itself, such as names kept outside every repository, is read where it is, never copied in. The path starts from `~` or from the folder of the list that names it. An included file is read once, however many lines name it, and its own `include:` lines are read too. An included file that is missing or cannot be read stops every push and every commit, as a list that cannot be read does; the message names the list and the line, never the path, since the path is a line of a private list. `pushgate words` and `pushgate status` count the included lines with the rest, and print none of them.

## Run it

Needs Python 3.9 or later and git 2.31 or later. No other software.

```bash
bin/pushgate words --init            # make the word list, then add your words
bin/pushgate install -C ~/code/app   # the hooks in one repository (its worktrees share them)
bin/pushgate template                # the hooks in every repository made or cloned from now on
bin/pushgate check -C ~/code/app     # what the next push would make public
bin/pushgate check --all -C ~/code/app   # every commit, as before a first push
bin/pushgate check --staged -C ~/code/app   # what the next commit adds (-m or -F reads its message too)
bin/pushgate status ~/code/*         # which repositories have the hooks
```

## Every repository

`pushgate install` writes three hooks: pre-push, pre-commit, and commit-msg. A hook of one of those names that the repository already has is kept and runs first: it moves beside Push Gate's as `pre-push.chained`, `pre-commit.chained`, or `commit-msg.chained`, and gets the same arguments and the same input, so a push or a commit goes only when both pass. When the repository's own hook stops it, Push Gate does not read it. A commit-msg hook of the repository's own that adds to the message runs before the message is read. `pushgate uninstall` puts the repository's own hooks back in their places. `pushgate install` writes nothing when `core.hooksPath` sends git to a hooks folder that other repositories share.

A repository that holds private words on purpose, and is never made public, can turn the commit check off: `git config pushgate.checkCommits false`. Its pushes are still read.

`pushgate template` puts the hooks in git's template, so every repository made with `git init` or `git clone` from then on has them. When git has no template folder set, Push Gate makes its own from git's default template (`~/.config/pushgate/template`) and sets `init.templateDir`. `pushgate template --off` takes the hooks out again.

## What it does not do

- It reads text. A word inside a binary file, such as an image, a PDF, or a Word file, is not seen. Only the file's name is read.
- A hook guards against accidents, not intent: `git push --no-verify` and `git commit --no-verify` skip it.
- The commit check runs when `git commit` makes a commit; when `git merge` makes one, only its message is read. A commit that another command makes, such as `git rebase`, `git cherry-pick`, or `git am`, may not be read until the push, which reads every commit.
- It finds a credential by its fixed format. A password with no format of its own is found only on a line that gives it to a name like `password`.

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests use made-up words and made-up repositories. They replace git's global and system settings for their run, so they never read your word list or your git settings.

## License

MIT, © 2026 [Haedo Labs](https://haedolabs.com); see [LICENSE](LICENSE).
