# Telonion reference

The full rules, settings, and limits. The overview is the [README](../README.md).

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
- A new file that makes code run on a hosting service or on install, such as a GitHub workflow, `package.json`, `setup.py`, `pyproject.toml`, or a `Makefile`, unless the repository lists it: `git config --add telonion.allowCode pyproject.toml`.
- A push that rewrites or deletes a branch on the remote, or lands on a remote commit this checkout has never seen. `TELONION_ALLOW_REWRITE=1` lets one through on purpose, and `git config telonion.allowRewrite true` turns the rule off for a repository.

A commit is stopped by the first three: a private word, a credential, or a file that holds keys by its name. A new file that runs code waits for the push.

No hit is printed in full. Each names its commit and place, with the word or credential masked, so a terminal log or an AI assistant's transcript does not repeat it:

```
Telonion: the push to origin is stopped
  private word: 3441baa notes/plan.md:4: the [private] notes
  a GitHub token: 3441baa conf.py:1: [credential]
  A hit stays in the commit that added it, and a later commit does not remove it: amend, squash, or rebase that commit before it leaves.
  Text that may be public gets an `allow:` line in the word list (~/.config/telonion/words.txt), or, for this repository alone, in its own (~/code/app/.git/info/telonion-words).
  A credential that was ever pushed anywhere is revoked, not only removed.
```

## The word list

One pattern a line: a regular expression, in which capitals and small letters match alike. A line that is not a valid expression is read as plain text. `allow: <pattern>` marks text that may appear though it holds a word, and a line that starts with `#` is a note. The list lives outside every repository, at the first of these that is set:

1. `$TELONION_WORDS`;
2. `git config telonion.words` (the repository's setting, then the global one);
3. `~/.config/telonion/words.txt`.

`telonion words --init` makes the list, readable by you alone. `telonion words` counts its lines and never prints them.

A repository can also keep a list of its own, among git's own files, so it is never committed: `.git/info/telonion-words`, shared by the repository's worktrees. Its patterns add to the main list, and its `allow:` lines apply to that repository alone, so one project's ordinary words can pass there without passing everywhere. `telonion words --init --here` makes it.

`include: <path>` in either list reads another file as part of that list, under the same rules, so a list that a project writes for itself, such as names kept outside every repository, is read where it is, never copied in. The path starts from `~` or from the folder of the list that names it. An included file is read once, however many lines name it, and its own `include:` lines are read too. An included file that is missing or cannot be read stops every push and every commit, as a list that cannot be read does; the message names the list and the line, never the path, since the path is a line of a private list. `telonion words` and `telonion status` count the included lines with the rest, and print none of them.

## Every repository

`telonion install` writes three hooks: pre-push, pre-commit, and commit-msg. A hook of one of those names that the repository already has is kept and runs first: it moves beside Telonion's as `pre-push.chained`, `pre-commit.chained`, or `commit-msg.chained`, and gets the same arguments and the same input, so a push or a commit goes only when both pass. When the repository's own hook stops it, Telonion does not read it. A commit-msg hook of the repository's own that adds to the message runs before the message is read. `telonion install --update` puts the pre-push hook in place and brings the commit hooks up to date only where the repository already has them, so moving repositories over to a new version adds no commit check. `telonion uninstall` puts the repository's own hooks back in their places. `telonion install` writes nothing when `core.hooksPath` sends git to a hooks folder that other repositories share.

A repository that holds private words on purpose, and is never made public, can turn the commit check off: `git config telonion.checkCommits false`. Its pushes are still read.

`telonion template` puts the hooks in git's template, so every repository made with `git init` or `git clone` from then on has them. When git has no template folder set, Telonion makes its own from git's default template (`~/.config/telonion/template`) and sets `init.templateDir`. `telonion template --off` takes the hooks out again. `telonion template --update` brings the hooks there up to date and adds no commit check.

## The old name

Telonion was called Push Gate until version 0.4.0. Nothing it set up under that name stops working:

- `pushgate` still runs Telonion, so every hook Push Gate wrote still reads every push and commit.
- A hook Push Gate wrote counts as Telonion's, out of date, never as another tool's: `telonion install` replaces it, and keeps a repository's own hook chained beside it.
- The old settings (`pushgate.words`, `pushgate.allowCode`, `pushgate.allowRewrite`, `pushgate.checkCommits`), variables (`$PUSHGATE_WORDS`, `PUSHGATE_ALLOW_REWRITE`), and files (`~/.config/pushgate/words.txt`, `.git/info/pushgate-words`) are read wherever the new ones are not set.
- `telonion install` (or `telonion install --update`, which adds no commit check) moves a repository over: its hooks, its own word list (renamed, never read aloud), and its own `pushgate.*` settings, when it has no `telonion.*` ones yet. `telonion template` (or `telonion template --update`) moves the template folder Push Gate made to `~/.config/telonion/template`. `telonion status` names a repository that still keeps the old names.

## What it does not do

- It reads text. A word inside a binary file, such as an image, a PDF, or a Word file, is not seen. Only the file's name is read.
- A hook guards against accidents, not intent: `git push --no-verify` and `git commit --no-verify` skip it.
- The commit check runs when `git commit` makes a commit; when `git merge` makes one, only its message is read. A commit that another command makes, such as `git rebase`, `git cherry-pick`, or `git am`, may not be read until the push, which reads every commit.
- It finds a credential by its fixed format. A password with no format of its own is found only on a line that gives it to a name like `password`.
