# Recipe trust

A shared recipe is someone else's decisions running against your licensed Windows environments. That is a fair reason to be nervous. "We will review them carefully" is not an honest answer, because review does not scale and it would all fall on one maintainer.

This project takes a different approach, in three parts:

1. **A recipe is data, so what it can do is computable.** Every recipe resolves to a fixed set of capabilities, derived from the file with no judgement involved. You can see them before you use it, and so can a machine.
2. **Where a recipe lives decides what it may declare.** An unreviewed recipe cannot ask to run a vendor installer at all. The check fails before anyone reads the diff.
3. **You do not have to trust anyone's finished recipe.** Each component says which problem it solves, so you can assemble your own recipe from parts that are already reviewed.

## What a recipe can do

There are eleven capabilities and nothing else. There is no shell field, command, script or dynamic import. That is not a convention. The schema has no place to put one.

| Capability | What it means for you |
| --- | --- |
| `configure-graphics` | Change which graphics driver an environment uses |
| `create-environment` | Create a new Windows environment |
| `join-environment` | Install into a Windows environment that already exists |
| `import-module` | Copy an exact Windows plug-in you already have into an environment |
| `claim-module` | Recognize a plug-in file by hash and decide how it is installed |
| `claim-installer` | Recognize an installer by hash and decide how it is run |
| `download-component` | Download a pinned Microsoft runtime and run it |
| `run-vendor-installer` | Run a Windows installer you supply, with arguments the recipe chooses |
| `prepare-archive-tools` | Install the pinned archive utilities into an environment |
| `require-bridge-patch` | Require a patched build of the audio bridge |
| `require-existing-files` | Require specific files to already be present in an environment |

Downloads have extra limits. The only host a recipe may name is a Microsoft download host, over HTTPS, on the default port, pinned to an exact SHA-256. Plugg checks this again on every redirect, not only for the URL as written. Installer arguments may not name another drive letter, a network path, a parent directory or a Windows variable. Wine maps `Z:` to your filesystem root, so an output-directory switch alone could otherwise make a genuine vendor installer write anywhere you can.

## Seeing what a recipe touches

~~~sh
plugg recipe explain local.some-vendor@1
plugg recipe explain ./downloaded-recipe.toml
~~~

The report lists the following:

- The capabilities, in plain language.
- Every download URL and hash.
- The exact arguments any installer would run with.
- Every artifact the recipe recognizes by hash.
- The components it is built from.
- A short list of the moves worth looking at, worst first.

Add `--json` for a machine, an agent or your own tooling.

The verdicts are deliberately boring:

- `routine` means the recipe changes settings only.
- `check-the-details` means it is ordinary for its kind, and the report lists the details.
- `needs-review` means a person should look at it.
- `refused` means it declares more than its tier allows. It will not be accepted.

## Tiers

Trust comes from where a file lives, not from what it says about itself.

| Tier | Where | Who can add one | May declare |
| --- | --- | --- | --- |
| `community` | `recipes/community/` | anyone, by pull request | graphics, module imports, pinned Microsoft components, new environments |
| `reviewed` | `recipes/reviewed/` | maintainer approval required | the above, plus running a vendor installer you supply, claiming an installer by hash, archive tools, joining an existing environment |
| `shipped` | inside the package | maintainers only | everything, including bridge patches |
| `local` | your own config directory | you | everything, with no ceiling, because it is your machine |

CI refuses a community recipe that declares a reviewed capability. Moving a recipe up a tier is a maintainer decision about the person and the evidence. It happens in a separate pull request, and a contributor cannot do it by editing a field. `CODEOWNERS` requires a maintainer for `recipes/reviewed/`.

A shared recipe must be a **direct child** of `recipes/community/` or `recipes/reviewed/`. Plugg refuses nested paths rather than guessing. Otherwise a file at `recipes/community/reviewed/x.toml` would claim the reviewed ceiling while the diff a reviewer reads says "community". A `needs-review` verdict does not pass CI either. A recipe that runs a vendor installer with arguments it chooses should never show up as a green check.

This is close to how the AUR works, with one difference. Here the ceiling is mechanical. In the AUR, a PKGBUILD can run anything, and you are expected to read it. Here, an unreviewed recipe *cannot express* the dangerous operations.

## The part that validation cannot solve

A recipe claims an installer by SHA-256, and that is an unauthenticated claim about someone else's binary. Nothing stops a recipe author from publishing the real hash of a genuine vendor installer and attaching their own arguments to it. If you then download that installer yourself, from the vendor, the attacker's recipe decides how it runs.

Schema validation cannot fix this. That is why `claim-installer` and `run-vendor-installer` are reviewed-tier capabilities. It is also why the report always names the claimed hash and the exact arguments, and why the manager shows you the recipe before it lets the recipe take over an installer you added.

## Assembling your own

If you would rather not trust anyone's finished recipe, list the components:

~~~sh
plugg recipe components
~~~

Every component says which problem it solves, which capabilities it carries and what it needs. Most compatibility work is a graphics setting plus a Visual C++ runtime. That is an eight-line recipe built from reviewed parts, and a `local` recipe never has to be published at all.

The same listing with `--json` is meant for tooling, and for an agent helping someone assemble a recipe. The purpose text is written for a person deciding what to try next, not as a label.

## For reviewers

On every pull request that touches `recipes/`, CI posts the report, refuses anything over its ceiling and runs the guardrail tests. That leaves three questions for a human:

1. Does the evidence in the pull request match what the recipe claims to do? A factory scan is not a playback test.
2. For a flagged `claim-installer`, is this installer really the vendor's, and are those arguments the vendor's documented silent-install switches?
3. For a tier promotion, has this person's earlier work held up?

If a recipe's report is clean and its tier is `community`, reading the TOML adds nothing the machine has not already checked. That is the point.

## Related

- [Licensing safety](licensing-safety.md) explains why an environment that holds activations is not a disposable target.
- [Extension boundaries](recipe-authoring.md) covers when a requirement needs a new core operation rather than a recipe.
- [Getting started with recipes](recipes/getting-started.md).
