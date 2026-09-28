# Contributing

The aim is for one person's compatibility fix to be useful to the next person. Plugg is a developer preview, and one person maintains it. A small, well-explained contribution with evidence helps more than a broad claim of vendor support.

## What helps most right now

- **Compatibility reports.** Use the issue template. Say what worked and what didn't, stage by stage.
- **Bug fixes and code**, by pull request.
- **Shared components**, such as a Microsoft runtime or a graphics setting that many vendors need, by pull request. These are small, pinned by hash, and everyone's recipes build on them, so they belong here and get reviewed.
- **Vendor recipes** belong in your own config directory for now. Plugg runs them there without a pull request. If one works, say so in a compatibility report and attach it. Once `recipe add <repository>@<commit>` exists, vendor recipes will live in their authors' own repositories, and a user will confirm before an unreviewed recipe runs an installer. The maintainer may adopt a proven one into `recipes/reviewed/`. Until then this repository doesn't take vendor recipe pull requests.

## Start here

- [Recipe trust](docs/recipe-trust.md) explains what a recipe may declare depending on where it lives. `python3 scripts/review-recipe.py <your recipe>` prints the report CI would post for it.
- To add a direct VST3 or graphics recipe, follow the [recipe guide](docs/recipes/getting-started.md). Local recipes work without a fork.
- For a new installer or licensing requirement, read the [extension boundaries](docs/recipe-authoring.md) and existing compatibility notes. Propose a typed core operation only when the current ones cannot express it.
- For the GUI and loader, follow the [design principles](docs/design-principles.md).
- For Wine fixes, read [the runtime page](docs/runtime.md). A runtime that environments already use never changes. A fix goes into a new runtime.
- Build decisions and current limits are in [the recipe ADR](docs/decisions/0001-recipe-engine.md) and [the build ADR](docs/decisions/0002-build-tooling.md).

Do not introduce a shell-command field into recipes. A downloaded recipe must not silently replace a working runtime or create a new licensing machine. Separate vendors from shared dependencies such as PACE.

Operations that write inside a prefix must be classified in `plugg/licensing.py` and must call `licensing.guard` before their first write. An unclassified operation is refused on a protected environment, which is the intended default. Read [licensing safety](docs/licensing-safety.md) before adding one: some users' activations cannot be recovered at any price.

## Checks

The unit tests and recipe catalogue checks need Python 3.12 or newer and nothing else. They use disposable fixtures, so you don't need Wine, vendor accounts or a running DAW. From the checkout:

~~~sh
python3 scripts/check-contribution.py
python3 scripts/review-recipe.py recipes/community/your-recipe.toml
~~~

For your local recipe, add its directory:

~~~sh
python3 scripts/check-contribution.py --recipe-dir /path/to/my-recipes
~~~

The check isolates application configuration so it does not load unrelated recipes from your home directory. It does not build the bridge or prove that a Windows plug-in works. [Building](docs/building.md) has the native build and the integration tests. Check the tools they need before running them.

A compatibility report should include exact product and installer versions, runtime and bridge identities, Linux desktop/graphics setup, DAW version, and the smallest reproduction. State separately what was observed for installation, activation, audio, editor close/reopen, multiple instances and project recall. A factory scan is not a playback test.

Keep installers, account data, callback URLs, licenses, downloaded runtimes and prefixes out of contributions. Trim logs to the relevant failure and check for private information. Never copy an activated prefix into a test fixture.

## Packaging

The Arch package (`packaging/aur/plugg-git/PKGBUILD`, and `packaging/aur/plugg/PKGBUILD` for a release) is the complete installation. It builds the bridge, the scanner and the PowerShell forwarder from pinned sources. The Python wheel on its own holds the manager, the recipe engine, the built-in recipes and the font. It has no bridge, so don't describe a wheel install as a working setup. See [packaging](docs/packaging.md).

When changing package data, build a wheel and check recipe commands from an isolated installation outside the checkout. With uv installed:

~~~sh
uv build --wheel --out-dir /tmp/plugg-wheel
python3 scripts/test-python-package.py /tmp/plugg-wheel/plugg-0.1.0.dev0-py3-none-any.whl
~~~

The check compares packaged modules and assets with the current checkout, then installs into a disposable environment without resolving dependencies. It checks built-in and local recipes and read-only status outside the source tree. It requires no Wine installation or vendor accounts. Retain third-party attribution. For changes to bridge or runtime behavior, keep patches small and record the upstream revision, reproduction, validation and conditions for removing the patch.

For GUI changes, an optional GTK smoke check is available:

~~~sh
python3 scripts/test-ui.py
~~~

It uses synthetic library data and temporary settings. A graphical GTK session is required. For headless development, run gtk4-broadwayd :8 separately and set GDK_BACKEND=broadway, GSK_RENDERER=broadway and BROADWAY_DISPLAY=:8 for the test. The harness covers widget behaviour. Check layout and desktop focus by eye when you change them.

For changes to archive-tool preparation, there is a separate integration check:

~~~sh
python3 scripts/test-archive-component.py
~~~

It downloads the pinned MSYS2 package set into a temporary cache, prepares a disposable Windows directory layout, checks license notices and repeats the operation to check unchanged output. It never starts Wine. Downloads and fixture files are removed when the check finishes. This does not test a vendor helper.

A real helper-recipe fixture check is available after building the test fixtures:

~~~sh
sh scripts/build-fixture.sh
python3 scripts/test-helper-recipe.py --runtime /path/to/runtime-artifacts --bridge /path/to/verified-bridge
~~~

The runtime argument is the artifact root containing UMU-Proton, umu-launcher and Steam Runtime, not a Windows prefix. This check creates a fresh library and prefix, runs a tiny Windows installer, publishes the deterministic gain plug-in, checks audio and reopens the installed fixture helper. It has no vendor login or licensing. Results go under `.test-helper-recipe` with a unique run ID. The check stops its idle session and keeps the prefix for inspection.

Pass `--vc-runtime` to test-helper-recipe.py to exercise the pinned VC2013 component before the helper installer. This variant checks installed VC DLL hashes as well as helper completion and audio.

To test an installed manager instead of source imports, run the same script with an installed environment's Python and `--installed`:

~~~sh
/path/to/venv/bin/python -I /path/to/checkout/scripts/test-helper-recipe.py --installed \
  --runtime /path/to/runtime-artifacts --bridge /path/to/verified-bridge
~~~

This mode rejects imports from the checkout. Both modes use the library's saved bridge selection. The check uses the supplied artifact root instead of downloading a runtime. Installation, launchers, scans, audio and reopening the helper run as normal. Keep the Python environment in place while inspecting the retained fixture, since its launcher uses that Python.

## Commit messages and releases

Write commit messages as Conventional Commits in the form `type(scope): description`. Use a short imperative description, and add a scope when it helps. Use `feat` for new behaviour, `fix` for corrections, `refactor` for restructuring, `docs` for documentation, `test` for tests, `ci` for workflows, `build` for build tooling, and `chore` for maintenance such as dependency upgrades (`chore(deps)`). Mark a breaking change with `!` before the colon, and explain its impact in a `BREAKING CHANGE:` footer. The body says what changed and why.

The version is written in one place, `plugg/__init__.py`. A release is a pushed `v<version>` tag on `main`, for example `v0.1.0`. Commit types do not trigger releases. The Arch package's version follows the latest tag.

## Documentation style

Markdown here is stored unwrapped, one line per paragraph. Your editor flows it for reading, and a diff shows the sentence that changed instead of a reflowed block. `scripts/unwrap-markdown.py FILE...` fixes a wrapped file in place, and refuses rather than touching anything it cannot join safely.

## Development notes

The maintainer keeps raw validation records, research notes and the project's early history in a separate, private repository, `plugg-lab`. A few evidence entries in `plugg/recipes/component-evidence.json` name a `plugg-lab:` path as their source, and the app shows it as plain text. Everything a user or contributor needs is in this repository.
