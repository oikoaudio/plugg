# Building and running from a checkout

[The README](../README.md#install) has the dependencies and the short version. This page has the details, the tests and the build options.

The test fixtures also need Clang, lld-link and Wine's PE import libraries.

## Build

```sh
scripts/build-bridge.sh
scripts/build-fixture.sh
python3 -m unittest discover -s tests -v
python3 scripts/test-integration.py
```

After rebuilding the bridge, published plug-ins keep loading the build they
were published against: the library owns a copy of each build, and moving a
working plug-in to different code is a decision rather than a repair. `plugg
doctor` reports how many are on an older build, and moving them is explicit:

```sh
plugg use-current-bridge            # what would move
plugg use-current-bridge --apply    # move it
```

Class identities and publication paths do not change, so saved projects still
find their plug-ins. Restart the DAW afterwards.

The build script fetches the pinned yabridge sources and applies the recorded patch series from [`patches/`](../patches). It ignores any `CFLAGS`, `CXXFLAGS` and `LDFLAGS` in the environment: the Windows host must be built with yabridge's own flags, because a host compiled with `-march=native` or another non-baseline target overflows its stack while plug-ins initialise ([the diagnosis](../diagnostics/host-stack/README.md)). The manifest records the arguments each build used. Its manifest records artifact hashes and the compiler and dependency versions it observed. System build dependencies are not fully pinned yet. See [the build tooling decision](decisions/0002-build-tooling.md). Git holds no binaries, runtime downloads or test environments.

To use separate build and output directories:

```sh
PLUGG_BUILD_DIR=/tmp/plugg-build \
PLUGG_BRIDGE_OUTPUT=/tmp/plugg-artifacts \
scripts/build-bridge.sh
```

## Run

To try an isolated evaluation library that touches nothing you already have:

```sh
bin/plugg --data .test-preview --publish-dir .test-preview-published gui
```

To use the normal local library, which publishes under `~/.vst3/plugg`:

```sh
bin/plugg gui
```

Drop an EXE, MSI, or Windows VST3 file or bundle onto the window. For installers, leave any BIN files beside the EXE in the source folder. Plugg copies them automatically. Keep your licence files for the vendor's normal authorization step, and set your DAW to scan the publication directory.

For a configured vendor environment, close its plug-in instances before opening the vendor's helper. Install products, then close the helper. Closing it triggers the refresh. Your DAW may need a rescan. Generic installers that keep working in the background may still need **Check again**.

## What your DAW sees

Each published plug-in is a VST3 bundle in the publication directory, named after the plug-in, for example `Skaka.vst3`. The name has a length limit. yabridge builds a Unix socket path from it, and the kernel caps that path at 108 bytes. A long name therefore keeps its start and adds a short piece of its identity to stay unique. A name with nothing usable in it falls back to `ph-<hash>`.

Libraries published under the old hashed scheme can be renamed. `plugg rename-bundles` prints the new names, and `--apply` renames them. Plugg builds the new bundles beside the old ones and moves the links, so it deletes nothing and you can undo the change. Close your DAW first. The paths move, so the DAW will rescan.

A bundle links its bridge files into a release that the library owns, in `bridge-releases/<hash>` in the data directory. It never links into the build directory, so moving, renaming or rebuilding a checkout cannot break a published plug-in. Older bundles may still link into a checkout. `plugg relink-bundles` finds them, and `--apply` moves their links into the library. Each bundle keeps the build it had, and no path the DAW scans changes.

If a host refuses a plug-in and shows you only a path, type that file name into the library's search. Clicking a plug-in in its vendor's row shows what your DAW sees.

## How environments are reused

A recognized standalone import reuses a same-vendor environment only when that environment's recorded dependencies already meet the requirement and the runtime matches. Unknown imports get their own prefix. Plugg never upgrades existing dependencies to fit a new import. Environments in a library share the Proton runtime files, but each prefix is an ordinary directory, not a thin container overlay. [Disk space](storage.md) has the measured cost. See the [standalone import notes](standalone-import.md) for supported inputs and validation limits.

## Development harnesses

To provision the experimental runtime and run the original comparison harness:

```sh
python3 scripts/test-proton.py --rounds 2
```

Then test the persistent session implementation:

```sh
python3 scripts/test-proton-lifecycle.py --managed-session --rounds 3 --survival
```

The original per-launch-container comparison still has known lifecycle failures. It is not the managed-session release test. Both harnesses use the project's own installer and gain plug-in in fresh environments, with no vendor accounts. Results go under ignored `.test-*` directories. The timings are not a latency benchmark.

## Testing in a real host

`scripts/test-carla.py` loads Plugg's own test plug-ins in Carla, the way a DAW would. It uses a disposable library in `.test-carla/`, which holds only the project's fixtures, and a private headless weston with Xwayland as the display. It needs Carla with its Python API (the Arch `carla` package has it), weston and xdotool.

```sh
scripts/build-fixture.sh
python3 scripts/test-carla.py
```

The first run installs the fixtures into the test library, and that downloads the Proton runtime into it once. The fixtures are:

- `Plugg Test Editor`, a gain with an edit controller and a 400x300 Win32 editor. A left click reports where it landed, in the editor's own coordinates, through the plug-in's three parameters.
- `Plugg Test Crash`, the same plug-in, which ends the host's main thread in `initialize`.

The test checks that two instances load, and that clicks at four known points arrive at those points in every one of several editor open and close cycles. An editor drawn off its frame, or input with an offset, fails this check. The test also checks that the crashing plug-in fails to load within seconds while the other instance keeps answering, that closing everything returns, and that no host process stays behind.

The older `Plugg Test Gain` fixture has no edit controller. Carla's JUCE-based VST3 host crashes on it, so this test does not use it. Real plug-ins always have a controller.

On weston, the first click after the editor's first open does not reach the plug-in. Every later click lands at the exact pixel. The cause is not known yet, so the editor check fails. `--outputs 2`, for two monitors side by side, is not implemented, because weston 15's headless backend creates only one output.

`--x-display` runs against an X display you already have. It must have a window manager. On a bare Xvfb, Carla's JUCE window code sets properties with atoms that only a window manager creates, and it either dies with `BadAtom` or waits forever.

## Checking whether a Wine patch is still needed

Each Wine patch in Plugg's runtimes exists because stock Wine fails in a specific way, and each has a probe in `diagnostics/` that shows that failure without vendor software. `scripts/test-runtime-patches.py` runs every probe in a fresh disposable prefix on each runtime in a library, and reports each patch:

| Result | Meaning |
| --- | --- |
| still needed | The runtime lacks the patch and has the bug. |
| can retire? | The runtime lacks the patch and the bug is gone. Upstream probably fixed it. Check that release, then drop the patch. |
| works | The runtime carries the patch and the bug is gone. |
| REGRESSION | The runtime carries the patch and still has the bug. |

```sh
for b in diagnostics/*/build.sh; do sh "$b"; done
python3 scripts/test-runtime-patches.py --library .test-carla/library
python3 scripts/test-runtime-patches.py --runtime /path/to/a/newer/Proton
```

On 2026-09-28, stock UMU-Proton 10.0-4 had all four bugs, and `plugg-1` fixed the three it carries patches for. A copy of `plugg-1` with a local build of the patched `ntdll.dll` (the `plugg-2` fix) passed the unwind probe. The script reports that copy as "can retire?" rather than "works", because `runtime-overlays.json` does not record the `plugg-2` module's hash yet. To learn when a patch can go, point `--runtime` at each new UMU-Proton release. The script exits with status 2 when a patch may be retired.

Never point either script at a library that holds activations.
