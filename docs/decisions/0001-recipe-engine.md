# Recipe engine and build reproducibility

Decided in September 2026:

- Keep application orchestration in Python.
- Expose small declarative TOML recipes.
- Evaluate Nix separately, for developer and CI artifact builds.
- No layered prefixes and no licensing-state migration.

The first concrete recipe operation was graphics configuration. It already had two real per-plug-in exceptions and a tested way to apply them. A larger, general installer language would have added abstractions nobody had tested. Dependency graphs use exact `id@revision` references. Components are reusable, and conflicting requirements fail explicitly. A resolved lock records the recipe content and hashes.

Nix could plausibly help pin the compiler, Wine headers, Meson and the other bridge build dependencies, and produce reusable CI artifacts. It cannot express the product lifecycle on its own. Vendor login, mutable licence services, DAW publication and interactive installers stay in the app.

Official references are [Nix flakes and lock files](https://nix.dev/manual/nix/2.24/command-ref/new-cli/nix3-flake.html), [Nix build isolation](https://releases.nixos.org/nix/nix-2.25.5/manual/command-ref/conf-file.html) and [NixOS reproducible builds](https://reproducible.nixos.org/). Nix gives a better basis for reproducibility. It does not prove bit-identical output or runtime compatibility. Build isolation is not a security sandbox for plug-ins at runtime.

Plugg adopts Nix only when all of these hold:

- One pinned build of the patched bridge.
- A clean second build.
- Documented loading of the artifact in the existing UMU session.
- A measurable reduction in contributor setup steps.

A dev shell alone is useful, but it is not a reproducible release build. Do not install a host daemon or change working runtime paths just to publish an untested flake.

## Consequences

Direct VST3 imports use the same TOML catalogue as graphics recipes. The Variety of Sound module identities and Microsoft asset hashes came from an earlier JSON catalogue and were checked against it. The typed Visual C++ operation reuses the existing importer and its fixed installer arguments.

A disposable end-to-end test adds a second vendor entirely through local TOML. It checks dependency selection, copies the vendor's synthetic module, reaches publication and refuses to replay a completed job. The test simulates runtime execution and probing, so it does not show compatibility for any real plug-in.
