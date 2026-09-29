# Roadmap

Plugg is a developer preview. It works on the maintainer's machine with the vendors in the compatibility notes, and few other people have tried it yet.

## What works today

- A managed Windows environment per vendor, all on one runtime (`plugg-1`: UMU-Proton 10.0-4 with Plugg's Wine fixes) and a patched yabridge build, independent of the system's Wine and yabridge.
- Packages for Ubuntu, Debian, Fedora and Arch in each release, built and install-tested by the release workflow.
- Windows VST3 discovery and publication as native Linux VST3 bundles, with the original class identities.
- Drag-and-drop installer intake, background installation and cancellation. Plugg rescans automatically when a vendor helper closes.
- Direct import of exact Windows VST3 files and bundles, with the pinned Microsoft runtime each one needs.
- Automated setup of a fresh environment from a recipe for recognized helper installers, on a persistent Proton session per vendor.
- iLok plug-ins in one shared environment on the `plugg-1` runtime, created with the unmodified PACE installer. See [iLok and PACE](docs/recipes/pace.md).
- Data-only TOML recipes with exact revisions and reusable components. Plugg validates a recipe before use and records its provenance after.
- Capability reports and tier ceilings for shared recipes, enforced by CI.
- Protection for environments that hold activations. Plugg records the products and an identity baseline, refuses identity-changing operations without explicit acknowledgement, and takes small recovery points.

Vendor-specific evidence is in [the compatibility notes](docs/compatibility/). A factory scan is not a playback test, and the notes say which is which.

## Next

The items are listed roughly by how much each would help people use Plugg.

### 1. The AUR package

v0.1.0 is out, with a .deb for Ubuntu and Debian, an .rpm for Fedora and an Arch package. The release workflow builds and tests each one on every release by installing it in a clean container. The AUR package `plugg` is ready and pinned to the v0.1.0 source. It goes up when the AUR takes new accounts again, which it stopped doing in 2026 after a wave of malicious packages. Until then, Arch users install the package from the release, and updating means downloading the next one. Plugg does not plan a Flatpak. [Cabinet](https://github.com/Mark12870/cabinet) serves people who want one, and [the Flatpak decision](docs/decisions/0003-flatpak.md) explains how the two projects fit together.

### 2. DAW regression

Synthetic tests cover the loader's audio and lifecycle: concurrent processing, survival when either host process is killed, idle shutdown and restart. On the maintainer's system, every environment runs the current bridge, and plug-ins open, play and reopen their editors in Bitwig. A written pass through editor reopening during playback, multiple instances, idle restart, project recall and a reboot is still to come. REAPER and other DAWs are untested.

### 3. More vendors, by other people

The recipe path exists so that one person's compatibility fix helps the next person. The proof would be a vendor added entirely through TOML, by someone other than the maintainer, with evidence that holds up. `recipe init` and the component catalogue make that path shorter.

### 4. Say when a plug-in does not need bridging at all

Work on this has started. `recipe leads` marks the products in the bundled recipe leads that have a native Linux build, and `recipe init` warns when a vendor has one. The list only covers vendors the leads cover.

Some vendors ship a native Linux build. For those, the right answer is to use it rather than write a recipe. The manager does not know this. It will bridge a Windows plug-in whose Linux version is a download away, with worse latency, worse editor behaviour and a licensing environment to protect for no reason.

The smallest useful version is a note in the component catalogue and in `recipe explain` output, "this vendor ships a native Linux build". It should come from a curated list, not from anything automatic, because a wrong guess in either direction is worse than saying nothing. It matters most for contributors. A recipe for a product with a native build should be declined with an explanation, not merged.

### 4a. Recipes published by their authors

This follows the Minecraft Forge model. This project maintains the loader, the shared components and the runtimes. People publish recipes in their own repositories, and nobody has to merge them here. The parts that make this safe already exist. Recipes are data, their capabilities are computable, and `recipe add` validates and reports before saving.

Two things are missing. One is `recipe add <repository>@<commit>`, which would fetch exactly that commit and record it as the recipe's source. The other is a user confirmation each time an unreviewed remote recipe would run a vendor installer. That installer is ordinary Windows code, and an environment is not a sandbox.

Wine and yabridge patches don't block this, because they aren't per recipe. Every fix Plugg carries applies to everyone, so the fixes stay in the loader and the runtime, and a recipe can already require one by hash. The gap is runtime choice. Some products need a different Wine build, for example one with better Direct2D support. That calls for a small set of named, hash-pinned runtimes a recipe can select, never a runtime shipped inside a recipe.

### 5. Guarded updates and rollback

Updating plug-ins through the vendor's own app works today: the adapter in your DAW links to the plug-in file, so it loads the new version, and Plugg reports what was updated. Plugg doesn't yet load an updated plug-in to check that it still works. It also has no guarded path for the other kinds of change: reinstalling from an installer, or moving an environment to a new runtime, which today means a new environment. That path has to know what a change would affect, refuse it when licences are at stake, and roll back cleanly. The licensing recovery points are the first piece.

### 6. Storage accounting and shared runtimes

Environments in a library share runtime files, but each prefix is an ordinary directory, not a thin overlay. On the development machine the shared runtime is about 2.2 GiB and a vendor prefix a few hundred megabytes. The project considered layered filesystems and deferred them. They would change what a "machine" looks like to a licensing system, and making that safe is where this project has spent the most effort.

### 7. Other desktops

The app is used day to day on Hyprland, in tiled and floating layouts, with installers dropped in from the file manager. It hasn't been tried on GNOME or KDE, or with fractional scaling. The automated GTK test checks the widgets, keyboard control and screen-reader labels, not the desktop around them.

## Parked

### A shelf of free native plug-ins

A small curated set of good free Linux plug-ins with direct vendor downloads, installable in one step. This is a different job from bridging and stays separate from it. It needs no environment, runtime or licensing guard. Plugg would only download, check the hash and unpack into its own folders (`~/.vst3/plugg-native`, `~/.clap/plugg-native`, `~/.lv2`), so the plug-ins can be listed and removed cleanly. A commercial native product gets a pointer to its vendor, not an install.

The download data is already in the native entries of the bundled recipe leads. Updates need deciding first. Some vendors keep fixed versioned links and others serve a rolling "latest". The options are to re-pin hashes with each Plugg release, or to accept a vendor's HTTPS download for rolling links. This is parked until the Windows side is finished. It would make a good self-contained first contribution.

### 32-bit plug-ins

Plugg bridges 64-bit plug-ins only. It skips 32-bit VST2 and CLAP files an installer leaves behind, and refuses a dropped 32-bit DLL. Many old Windows freebies that older projects use were never released as 64-bit, so this matters most for VST2.

yabridge can host them through its bitbridge, a separate 32-bit Wine host that the bridge picks for a 32-bit DLL. The shipped UMU-Proton 10.0-4 still has a 32-bit `bin/wine` loader and 32-bit Unix libraries, `ntdll.so` and `winex11.so` among them. Two things are unknown: whether the 32-bit host builds without trouble (multilib GCC and 32-bit Wine and xcb libraries, locally, in the release container and for the AUR), and whether it runs under this Proton, with DXVK and the `plugg-1` overlay. Installers also often put a 32-bit and a 64-bit copy of one plug-in side by side, so Plugg would publish the 64-bit one and skip the other.

The next step is a short test: build the bridge with `-Dbitbridge=true`, build a 32-bit copy of the VST2 gain fixture, and play audio through it in a throwaway library. If the build or the runtime fights back, this stays parked.

## Known hard problems

**PACE and iLok.** `plugg ilok create` installs the unmodified PACE MSI on the `plugg-1` runtime, which carries source fixes for the two Wine gaps that stopped it. Activation works. Reboots, PACE updates and more vendors are still untested, and setup is command-line only. The app has no guided flow for it yet. Recipes can't provision PACE. See [iLok and PACE](docs/recipes/pace.md) and [the runtime](docs/runtime.md).

**Building Windows code with the packager's flags.** Every bridged plug-in died while initialising on 2026-09-20, and `makepkg` had built the Windows host with this machine's `CFLAGS`, `-march=native` among them. A host compiled for anything above the x86-64 baseline overflows its main thread's stack inside the plug-in's `initialize`. The same source built with yabridge's own flags loads. The bridge build now ignores the environment's compiler flags and records what it used ([the diagnosis](diagnostics/host-stack/README.md)). Wine 10.0 could not even report the overflow ([the unwinder note](diagnostics/collided-unwind/README.md)). Nobody else runs the bridge the way Plugg does, so faults there are found by measuring, one variable at a time.

**Claiming an installer by hash.** A recipe binds to an installer by SHA-256, which is an unauthenticated claim about someone else's binary. Validation cannot fix this. Tiering and disclosure handle it instead. See [recipe trust](docs/recipe-trust.md).

**Vendor managers with their own login and update logic.** Recipes can express only part of what Native Access and similar managers need. They still need adapters.

## Not goals

- **Security sandboxing.** A Windows environment is not a security boundary. A malicious plug-in inside one can read and change your files, as it could on Windows.
- **Defeating or working around licensing.** The project does not inspect, alter, emulate or bypass any licensing check, and will not accept a contribution that does.
- **Redistributing anything a vendor licenses.** Plugg ships no installers, no runtimes that aren't freely redistributable, and no activated prefixes.
- **Universal compatibility.** Plugg makes claims only per product and per version, with evidence.

## How to help

The most useful contributions, in order, are a compatibility report with real evidence, a recipe for a vendor you have working, a reproducible bug report, and tests for something currently unverified. See [CONTRIBUTING](CONTRIBUTING.md).
