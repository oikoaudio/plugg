# Vendor recipes and retained installers

This page sets out the design direction for vendor support. It covers how vendor helpers, retained installers and environments fit together. Parts of it are implemented, as described in [the vendor Helper workflow](vendor-helper-workflow.md) and [the recipe guide](recipes/getting-started.md). The rest describes intended behaviour, not finished features. The design grew out of getting Klevgrand working. See [the Klevgrand notes](compatibility/klevgrand.md).

## User experience

A vendor page shows its installed plug-ins, an **Open Helper** button when the vendor has a manager, and the retained installers. The planned installer actions are **Run again**, **Add newer installer** and **Remove download**. Today the card offers **Saved installer**, which opens the retained installation set. Plug-ins stay visible in the main library and publish as ordinary Linux VST3s for compatible hosts, including Bitwig and REAPER. Plugg tracks host compatibility separately from successful installation and discovery.

In the basic flow, you add an installer, choose or confirm the vendor and install, and the plug-ins appear. Plugg treats an EXE and the BIN files next to it as one installation set. Folder and ZIP intake can come later, with a clear choice of executable when there is more than one installer. Vendor detection can suggest a name, but it should never guess the installation destination silently.

The vendor's installer or helper stays available through Plugg. Opening a retained helper uses the same managed environment and account state. A newer standalone installer should be attached to its vendor, not create another prefix by default. The UI never makes you choose a Wine prefix or run a bridge synchronization command.

## Separate vendor environments; supervised plug-in processes

The starting policy is one environment per vendor. A vendor's helper, installed plug-ins, authorizations and shared content belong together. Other vendors get separate environments, so their dependencies, helpers and updates do not interfere. Recipes can make exceptions. Products that share a licensing system such as iLok/PACE share one environment on purpose, and products that need incompatible runtimes can be split.

Process isolation is a separate question. Each hosted plug-in instance has its own supervised Windows host process, while it shares its vendor environment. A shared prefix and wineserver are not a security sandbox. Limiting desktop input access and installer permissions would need its own explicit sandbox design and validation.

## Reusable recipes

A recipe is versioned data plus narrowly scoped actions that someone can review. It records the following:

- Supported runtime and bridge revisions, source URLs, hashes, licences and component dependencies.
- Installer intake rules, and documented quiet-install arguments where they apply.
- How to find and launch the helper executable, including how its windows identify themselves.
- The installed VST3 roots to scan, the expected architecture and stable class identities.
- Known installation and authorization prerequisites, and platform limits.
- Validation results by helper version, plug-in version, host and desktop environment.

Recipes stay separate from user state. A recipe contains no credentials, activation tokens, licence files or copied authenticated download links. It downloads redistributable dependencies from verified sources. Commercial installers that you supply stay on your machine. The project never bundles them.

Recipes are added one vendor at a time, as they are tested and with evidence. The project does not build a broad download catalogue or scrape vendor accounts.

## Lessons from Klevgrand that shaped recipes

- Pin the runtime (UMU 1.4.4 and UMU-Proton 10.0-4) and record the component hashes. Helper login works under Proton without adding WebView2. Under plain Wine 11, the same Helper's login fields ignored the keyboard, with or without WebView2.
- A helper can depend on external Windows tools. Klevgrand Helper needs `tar.exe`. A private, hash-checked MSYS2 bsdtar/libarchive component on the helper's PATH provides it, with its licences.
- Remove the Unix `SteamAppId` at the Proton entry point when launching desktop helpers. This changes the X11 class from `steam_app_default` to `steam_proton`, so class-based game and fullscreen rules do not catch the helper. Never hard-code a user's workspace or window position in a recipe.
- Helpers can update themselves. Record the executable's hash and version after an update, because the original installer no longer reproduces it.
- Discover installed copies under Windows `Common Files/VST3` only. Helper download caches can hold extracted VST3 copies that must not be published.
- Keep IPC in a private RAM-backed directory that both the DAW and the runtime container can see, and run one persistent container per prefix. With one container per instance, instances stalled when several ran at once.

## Installer storage and updates

Store immutable installation sets, not a single installer.exe that gets replaced. Keep the original filenames, the pairing of EXE and BIN files, SHA-256 inventories and a local acquisition timestamp. Track installers you imported separately from helper download caches and installed binaries.

By default, keep the most recent installer and the previous installer that is known to work, under a storage policy the user can see. Large sample payloads need size estimates and an optional retention choice. Removing a retained download must never remove an installed product. An installer is an input, not a full rollback. A helper can download newer binaries and change the registry, shared content and authorization state.

For updates, offer **Open Helper** or **Add newer installer** first. A check at launch, or an explicit **Check for updates**, can be added for each supported vendor. General account polling is not needed. Watch the managed installer or helper session, wait until installation settles, then discover and probe the installed modules that changed. Self-updaters and their child processes may outlive the first executable, so its exit alone is not enough.

Before running an updater, check whether any host is using that vendor environment, and postpone the update while plug-ins are active. Bridge and runtime bundles are immutable. A rebuild must never overwrite binaries a DAW has loaded. Stage the changes and keep a rollback manifest before publishing validated native bundles.

Runtime and prefix updates need their own migration policy. Never silently clone or move an activated environment on the assumption that licensing survives or that no activation is used up. Keep the working environment, validate the vendor's behaviour and report any reauthorization it needs.

## Implementation status

Implemented:

- Durable managed environments with recorded products and licensing protection.
- Vendor cards with **Open Helper**, **Refresh library** and **Saved installer**.
- Discovery limited to installed VST3 roots, excluding helper caches, with factory probes run one at a time and publication by stable class identity.
- Automatic refresh when a supported helper closes, so users do not need **Check again**.
- Persistent Proton sessions per prefix, with multi-instance and lifecycle tests.

Not built yet:

- **Run again**, **Add newer installer** and **Remove download** for retained installers.
- Guarded updates, storage cleanup and rollback (see [the roadmap](../ROADMAP.md)).
- Project save and reopen and audio validation in REAPER.
- Support for sandboxed DAWs, which needs tests of their access to published bundles, the runtime and IPC paths.
