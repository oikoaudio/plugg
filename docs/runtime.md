# The plugg-1 runtime

Every new environment runs on `plugg-1`, whether it comes from a recipe, a vendor helper, the iLok setup, a direct VST3 import or an installer Plugg has no recipe for. It is a copy of UMU-Proton 10.0-4 with seven Wine modules replaced by patched builds. The patches fix things that stop plug-ins and their installers on stock Proton:

| Module | Patch | What it fixes |
| --- | --- | --- |
| `rundll32.exe` (x86, x64) | [0001](../patches/wine/0001-rundll32-Declare-supported-Windows-versions-in-a-man.patch) | PACE's installer sees Windows 6.2 and refuses to install |
| `services.exe`, `sechost.dll` (x86, x64) | [0002](../patches/wine/0002-services-Store-and-report-service-failure-actions.patch) | PACE's installer rolls back when it can't read a service's failure actions |
| `ole32.dll` (x64) | [0004](../patches/0004-ole32-revoke-foreign-drop-target.patch) | Closing a plug-in editor that supports drag and drop crashes the host (UADx LA-2A, for one) |

[iLok and PACE](recipes/pace.md) explains the first two. [The drag-and-drop diagnostics](../diagnostics/dragdrop/README.md) cover the third.

Everything else is the unchanged UMU-Proton build. Plugg hard-links the unchanged files, so the copy costs a few megabytes.

## Getting it

```sh
plugg runtime assemble plugg-1
plugg runtime select plugg-1
```

`assemble` downloads the modules from this project's GitHub release `runtime-plugg-1`, as one uncompressed tar pinned by SHA-256 in [runtime-overlays.json](../plugg/recipes/runtime-overlays.json). It checks every module against its own recorded hash and the base Proton build against its entry point. Then it creates the runtime as a new directory next to the existing ones. It changes nothing that exists.

`select` makes new environments use it. Existing environments keep the runtime they were created on. Moving one to another runtime is a `replace_runtime` operation, and a protected environment refuses that without an explicit acknowledgement. An iLok environment should stay on the runtime it was activated on.

## Building it yourself

You don't have to trust the downloaded modules. This builds them from source and compares each one with the recorded hash:

```sh
python3 scripts/build-runtime-overlay.py plugg-1 --container docker   # or podman
plugg runtime assemble plugg-1 --artifacts ~/.cache/plugg/runtime-build/plugg-1-modules
```

The script downloads Wine at revision `b8fdff8e1f85`, the revision UMU-Proton 10.0-4 ships, and checks the archive's hash. It applies the patches from this repository, each checked against its recorded hash. It generates the files the source archive leaves out, then builds only the modules it needs. It links with the recorded timestamp through `SOURCE_DATE_EPOCH`. Without that, the timestamp is the only difference between two builds.

With `--container`, the build runs in an Arch Linux container. Its packages come from the Arch Linux Archive snapshot of 19 September 2026, which has the toolchain the modules were first built with (clang and lld 22.1.8, autoconf 2.73). That build reproduces the published modules byte for byte and takes a few minutes. Without `--container` the script uses your own compiler. The modules then work, but their hashes probably differ, and `runtime assemble` refuses them. The script tells you which files differ.

`--package FILE` also writes the release archive. It is deterministic, so you can compare it with the published one too.

`scripts/publish-runtime-release.py` publishes that archive as the runtime's GitHub release. It attaches the notes and source pointer from `packaging/runtime/<name>/` and Wine's licence files at the pinned revision, and it checks the archive against the hash in `runtime-overlays.json`. It only reports what it would do until you pass `--publish`. A runtime release is a pre-release titled as support files, so it is never mistaken for the app. The script never moves an existing tag, and it never replaces a file already published with different bytes.

`ole32.dll` keeps its debug information, which names the directory it was first built in. The build maps its own directory to that path so the bytes match.

## plugg-2

`plugg-2` is `plugg-1` plus two fixes:

| Module | Patch | What it fixes |
| --- | --- | --- |
| `ntdll.dll` (x64) | [0003](../patches/wine/0003-ntdll-Do-not-crash-in-RtlVirtualUnwind2-on-NULL-outp.patch) | Wine cannot report some crashes |
| `msi.dll` (x86, x64) | [0004](../patches/wine/0004-msi-Rewrite-every-table-when-the-string-reference-wi.patch) | Kontakt 8's installer installs nothing |

The `ntdll.dll` patch is the upstream Wine fix for `RtlVirtualUnwind2()` writing through NULL output parameters ([a55cddce98](https://gitlab.winehq.org/wine/wine/-/commit/a55cddce9839a1516f882ad2e5a2ab689084da92), Wine 11.7). Without it, Wine cannot report a crash that takes this path. The report recurses until the process dies, and nothing is printed.

That fix is for crash reporting. It does not fix plug-ins. The plug-in failures of 2026-09-20 came from a Windows host built with the packager's `-march=native`, and the bridge build fixed them. See [the diagnosis](../diagnostics/host-stack/README.md). With `plugg-2`, Wine can report the next failure of this kind.

The `msi.dll` patch fixes a Wine bug in saving large MSI databases. An MSI stores references to its strings in 2 or 3 bytes, and every table must use the same width. Wine picks the width from the capacity of the string pool, which grows by half each time, so a database of about 43,700 strings crosses the limit when it gains one string. Wine then saves only the tables it has open, and nothing can read the file after that. Kontakt 8's installer edits its MSI before it installs, so it hits this. `MsiInstallProduct` returns without running an action, the installer exits normally and Native Access reports success with nothing installed. See [the Native Instruments notes](compatibility/native-instruments.md#kontakt-8) and [the diagnosis](../diagnostics/msi-string-width/README.md). The patch is not in upstream Wine yet.

`python3 scripts/build-runtime-overlay.py plugg-2 --container docker` rebuilds its modules byte for byte from source. To use it for new environments:

```sh
plugg runtime assemble plugg-2
plugg runtime select plugg-2
```

Kontakt 8 Player installs, activates and plays on it. Nobody has tested PACE or iLok on it, and `plugg ilok create` still requires `plugg-1`.

Moving an existing environment to it keeps the prefix, the installed software and the machine identity. Only Wine modules change. A protected environment still asks first. Deactivate the plug-ins in an iLok environment before you move it.

## Changing it

A runtime's name and identity are fixed once environments use it. The identity is part of the directory name (`proton-10.0-4-plugg-1-440a6d29c2e6`), and environments record that path. Plugg refuses a `runtime-overlays.json` where plugg-1's modules or base no longer match its recorded `content_sha256`. Notes and build instructions can change without renaming anything.

A fix that changes a module goes into a new runtime, `plugg-2`, with its own release. People move to it when they create new environments. For an iLok environment, that means deactivating first.
