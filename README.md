# <img src="docs/icon.png" alt="" width="32" height="32"> Telonion™

[By Haedo Labs™.](https://haedolabs.com)

A local check for Git pushes and directories prepared for publishing. It reads what would be sent, checks for private words and credentials, and verifies the required destination and file approvals.

A telonion was a customs post where goods were checked before they passed.

## What it does

- **Reads the proposed push.** Git supplies the outgoing refs. Telonion checks the added lines, names, messages, authors, committers, and tags in the outgoing history. The live preview uses the same inspection.
- **Stops private words.** Regular expressions from a list kept outside every repository, with `allow:` lines for text that may pass. A repository's own `.git/info/telonion-words` can also use `publish-exact:` for one complete line or relative path in a prepared publish directory.
- **Stops credentials.** Tokens and keys in their fixed formats, private key blocks, key files by name (`.env`, `*.pem`), and long literals given to names like `password`.
- **Stops risky pushes.** New files that run code on a host or on install, and pushes that rewrite or delete a remote branch, each allowed per repository.
- **Masks findings.** Reported locations and excerpts mask private words and credentials as `[private]` or `[credential]`.
- **Checks destinations.** An approval binds a remote name to its push URL. A release destination also requires approval for each file version checked by name only.
- **Reports the decision.** The terminal shows counts and masked findings. Set `TELONION_RECEIPT=1` to save receipts for Git pushes and live previews. Existing repository hooks are kept.

## Install

Needs Python 3.9 or later and git 2.31 or later. No other software.

```bash
bin/telonion words --init            # make the word list, then add your words
bin/telonion install -C ~/code/app   # the hooks in one repository
bin/telonion template                # the hooks in every repository made from now on
```

## Use

```bash
bin/telonion check --live -C ~/code/app    # preview Git's proposed push
bin/telonion check -C ~/code/app           # offline estimate against the last fetch
bin/telonion check --staged -C ~/code/app  # what the next commit adds
bin/telonion status ~/code/*               # hook health and destination rules
```

With `bin/telonion` on your `PATH`, run these in a repository to limit its pushes to approved destinations:

```bash
telonion destination origin                # approve its current push URL
telonion destination --release release     # require approval for name-only files here
telonion approve release docs/guide.pdf    # this file at HEAD, for release alone
telonion check --live --remote release --receipt main
```

A selected word list must be readable. Content checks run locally. Git contacts the destination for the live preview. Repositories with destination rules hold separate Git LFS transfers. Release destinations also hold pushes that add or update a submodule pointer.

For a direct Cloudflare Pages upload, use the actual account ID, project, environment, and branch from the publisher. The source repository needs no remote:

```bash
target="cloudflare-pages/$account_id/$project/production/$branch"
telonion destination -C "$repo" --publish "$target"
telonion approve -C "$repo" --directory "$stage" --destination "$target" -- assets/logo.png
telonion check -C "$repo" --directory "$stage" --destination "$target" --json
```

Passed (exit `0`) and held (exit `1`) results include a tree digest. An incomplete check (exit `2`) returns `null` for `tree_digest`. The publisher keeps the stage immutable from inspection through upload.

## Reference

What it reads, the word list, settings, the old name Push Gate, and its limits: [docs/reference.md](docs/reference.md).

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT, © 2026 [Haedo Labs™](https://haedolabs.com); see [LICENSE](LICENSE).
