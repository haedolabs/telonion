# <img src="docs/icon.png" alt="" width="32" height="32"> Telonion

By [Haedo Labs](https://haedolabs.com).

A git hook that stops a push, or a commit, holding a word from your private list or a credential. It runs on your own computer and sends nothing anywhere.

A telonion was the toll house at a city gate, where goods were checked before they passed.

## What it does

- **Reads every commit the remote lacks.** Added lines, new file names, messages, authors, committers, tags, and the ref names a push creates, each commit on its own. It asks the remote what it holds (`git ls-remote`), and reads the full history when it cannot.
- **Stops private words.** Regular expressions from a list kept outside every repository, with `allow:` lines for text that may pass, and a repository's own list in `.git/info/telonion-words`.
- **Stops credentials.** Tokens and keys in their fixed formats, private key blocks, key files by name (`.env`, `*.pem`), and long literals given to names like `password`.
- **Stops risky pushes.** New files that run code on a host or on install, and pushes that rewrite or delete a remote branch, each allowed per repository.
- **Masks every hit.** Each names its commit and place, with the match shown as `[private]` or `[credential]`, so logs and AI transcripts never repeat it.
- **Keeps your hooks.** A repository's own hook runs first, as `<name>.chained`.

## Install

Needs Python 3.9 or later and git 2.31 or later. No other software.

```bash
bin/telonion words --init            # make the word list, then add your words
bin/telonion install -C ~/code/app   # the hooks in one repository
bin/telonion template                # the hooks in every repository made from now on
```

## Use

```bash
bin/telonion check -C ~/code/app           # what the next push would make public
bin/telonion check --all -C ~/code/app     # every commit, as before a first push
bin/telonion check --staged -C ~/code/app  # what the next commit adds
bin/telonion status ~/code/*               # which repositories have the hooks
```

`git push --no-verify` skips the hook: it guards against accidents, not intent.

## Reference

What it reads, the word list, settings, the old name Push Gate, and its limits: [docs/reference.md](docs/reference.md).

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT, © 2026 [Haedo Labs](https://haedolabs.com); see [LICENSE](LICENSE).
