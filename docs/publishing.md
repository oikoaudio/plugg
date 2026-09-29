# Publishing this repository

## Branches

| Branch | Where | What it is |
| --- | --- | --- |
| `main` | GitHub | The shared history. It starts from a single commit that contains the project as it was when first shared. |
| feature branches | local, then GitHub if reviewed there | Work in progress, merged into `main` when done. |
| `archive/dev` | local only | The full development history from before `main` was squashed. It is never pushed to the shared repository. |

The squash was meant as a one-time step. Before the repository went public, `main` was rewritten twice more, both times with nothing lost: once to describe what the first commit holds, and once to give every commit a Conventional Commit title. Once the repository is public, `main` only moves forward with ordinary pushes.

The archive branch shares no ancestor with `main`, so it can't be merged. It is still useful. `git diff archive/dev main` compares trees, `git log archive/dev -- <path>` shows why a file became what it is, and `git cherry-pick` works across the two. The branch exists only on the machine that holds it, so keep a copy somewhere else:

~~~sh
git bundle create ../plugg-archive.bundle archive/dev --tags
~~~

Rolling back an installation does not use git history at all. The library keeps its own records. `migration-backups/` holds publication and bridge-link changes, protected environments have licensing recovery points, and every rewritten launcher has a `*-before-*` copy.

## Before you push

~~~sh
python3 scripts/check-contribution.py          # unit tests + recipe catalogue
xvfb-run -a python3 scripts/test-ui.py         # builds the window and uses it
python3 scripts/review-recipe.py recipes/community/*.toml
~~~

Then check what would be shared, not only what changed:

- `git status --short` is empty.
- `git ls-files` contains nothing you would not put in a public issue.
- `git grep -n -e /home/ -e '@'` finds no personal paths or addresses outside test fixtures.
- Commits carry the author identity you want public (`git log --format='%an <%ae>' origin/main..`).

## Repository settings

- Allow GitHub Actions. The workflow needs no secrets and only `contents: read`.
- Protect `main` and require the `Tests`, `Recipe review` and `Guardrail audit` checks. Without this, the recipe capability ceiling is only advisory.
- Enable "Require review from Code Owners". `CODEOWNERS` has no effect without it, and it is what gates `recipes/reviewed/` and `plugg/`. To route review to a team, name `@<organisation>/<team>` and give the team write access.

## When you make it public

Some things only matter once strangers can submit recipes:

1. Turn on branch protection and required reviews first, not after. `python3 scripts/github-settings.py --apply` applies `.github/repository.json` (rulesets for `main` and release tags, Code Owners review and the required checks) and reads it back. Without `--apply` it reports differences and changes nothing. Rulesets need a public repository, so run it right after the switch.
2. Check that CI refuses an over-ceiling recipe on a real pull request. A community recipe that declares `run-vendor-installer` should fail the `Recipe review` job. Prove this once with a throwaway pull request.
3. Decide whether `recipes/reviewed/` accepts anything yet. It is reasonable to start with community-tier contributions only, and open the reviewed tier once someone's evidence has held up.
4. The README describes a developer preview. Keep it that way until packaging exists. If the first install fails on a machine without a checkout, people stop trusting the project.

## At the first release

Once the v0.1.0 release is published, the README's Install section lists the packages first. Replace its opening paragraphs, down to the `makepkg` block, with this, and keep the "build from a checkout" link for other distributions:

````markdown
Download the package for your distribution from [the latest release](https://github.com/oikoaudio/plugg/releases/latest) and install it:

- Ubuntu 24.04 or newer, Debian 13 or newer: `sudo apt install ./plugg_<version>_amd64.deb`
- Fedora 42 or newer: `sudo dnf install ./plugg-<version>-1.x86_64.rpm`
- Arch and Arch-based systems: install `plugg` from the AUR, for example `yay -S plugg`

Then start Plugg from your applications menu, or run `plugg gui`.
````

Update the AUR package first (`scripts/update-aur.py`, see [packaging](packaging.md)), so the Arch line is true when the README says it.

At v0.1.0 the AUR package was not pushed yet, so the README lists the .deb and .rpm and keeps the Arch build-from-source commands. Once `yay -S plugg` works, replace those commands with the Arch line above.

## Keeping your working environments out of it

`.gitignore` already excludes `.test-*/`, `.scratch/`, downloaded runtimes, prefixes, installers, licensing records and recovery points. Live environments belong in the library (`~/.local/share/plugg`), not in the checkout. Published plug-ins and vendor launchers do not depend on where the checkout is, so you can move it or clone it again.

Never run `git clean -fdx` in a checkout that has been used for experiments. Ignored directories there may hold active vendor installations and authorization data.
