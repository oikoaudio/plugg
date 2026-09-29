# Deployment troubleshooting

This page lists problems seen while running Windows plug-ins and vendor helpers through Plugg. For each, it gives the cause where known and the fix. Keep a confirmed fix apart from a plausible cause.

The observations come from the pinned UMU-Proton 10.0-4 / UMU 1.4.4 runtime, Plugg's patched yabridge build, native Bitwig and Hyprland/XWayland. Other runtime versions, desktops and vendors may behave differently. Do not apply every workaround to every deployment.

## Quick symptom map

| Symptom | First checks | What is known |
|---|---|---|
| Parameters change, but knobs and images never update | Loaded graphics DLLs, effective DXVK overrides | The affected hosts had loaded WineD3D. Selecting DXVK fixed editor redraws. |
| Plug-in crashes while creating a graphics context | Host OpenGL, loaded versus installed GPU driver | An NVIDIA kernel/userspace driver mismatch after an update. A reboot fixed it. |
| Helper is stretched, partly visible or hard to click | Initial tiling, fullscreen rules, remembered size | Floating the window before it first appears fixes the geometry. It does not fix a frozen interface. |
| Helper stays on a loading screen that looks frozen | Compare managed `runinprefix` with a full Proton launch | The same installation and login work through a full launch. The lower-level cause is not isolated. |
| Helper reports an unzip or install failure | Is there an external extractor? Is the archive intact? | Windows `tar.exe` was missing. A private bsdtar fixed installation. |
| One instance stalls as another exits | Runtime-container ownership, shared Wine services | Reproduced with one container per launch. One persistent container per prefix fixes it in fixture tests. |
| DAW cannot talk to the Windows bridge | Socket path visibility, backing filesystem | Use a private tmpfs directory that both the native host and the runtime container can see. |
| Rescan finds duplicates | Installed roots versus installer download or cache roots | Helper caches can hold extracted VST3 copies. Scan only installed roots. |
| DAW lists a plug-in but says it failed to initialize it | Do the bundle's bridge links under `Contents/x86_64-linux` resolve? Does `doctor` report anything under `publications_outside_library`? | Bundles that link into a renamed or moved checkout break. `relink-bundles --apply` moves them into the library. |

## 1. Working controls, frozen editor images

**Symptom.** A plug-in accepts parameter changes, including changes from the DAW's device controls, but its own editor graphics stay static. Parameter transport and audio processing are still working. Seen with Klevgrand DAW Cassette, Skaka and Slammer.

**Cause.** The running hosts had loaded Wine's builtin Direct3D libraries (WineD3D). Proton's full prefix setup installs the DXVK DLLs and adds native DLL overrides to the launch environment. `runinprefix` skips that setup, including the per-process overrides. A launcher that uses it has the DLLs installed but never selects them. Upstream yabridge describes a similar redraw problem with recent JUCE plug-ins on WineD3D in its [known issues](https://github.com/robbert-vdh/yabridge#known-issues-and-fixes).

**Fix.** The `graphics_backend: dxvk` session profile checks that the installed 64-bit `d3d11`, `dxgi`, `d3d10core` and `d3d9` DLLs match the selected Proton build. It then sets their native overrides before it starts the server. If the preparation is missing or inconsistent, it fails. Do not copy DLLs over an active environment, and do not silently switch to another renderer. Check the settings the child processes actually get and the libraries they load. The configuration files alone do not tell you.

**Scope.** The affected Klevgrand editors redraw correctly with this setting. It does not fix every repaint, input-offset, timer or embedding problem. Some plug-ins work better on WineD3D, which is why renderer selection is per plug-in (see [recipe authoring](recipe-authoring.md#implemented-graphics-policy-fragment)). Close all instances before you switch graphics profiles, because DLLs that are already loaded do not change.

## 2. Graphics driver update without reboot

**Symptom.** Plug-ins crash on load. The Windows host prints `X_GLXCreateContext` / `BadValue`. The DAW may also log a Vulkan swapchain failure and fall back to software presentation.

**Diagnosis.** Check host graphics before you touch a prefix. If `glxinfo -B` fails outside Proton too, the problem is the host. If `nvidia-smi` reports a driver/library version mismatch, the loaded kernel driver differs from the installed userspace libraries. This typically happens after a driver update, while the compositor still has the deleted old libraries mapped.

**Fix.** Reboot once a matching kernel module is installed. Afterwards both versions match, hardware OpenGL works and the plug-ins load again. A reboot does not replace diagnosing a broken installation. Plugg never restarts the compositor or the machine by itself.

The DAW's renderer and a Windows plug-in's renderer are separate. A DAW that uses Vulkan does not mean its hosted editors use Vulkan.

## 3. Hyprland initial placement and remembered geometry

**Symptom.** Tiled Helper windows are stretched or partly visible. Floating a window that is already tiled sometimes restores its normal size, but it may still not respond to input. Floating it shortly after it appears is not enough.

**Fix.** Enable a temporary named window rule before Helper's window is created. The rule matches the exact `steam_proton` class and Helper title, and sets floating, non-fullscreen and `persistent_size=false`. Disable the rule when Helper exits. No persistent user configuration changes. Let the app choose its natural size. Do not force a monitor-sized window or hard-code a workspace or coordinates. With this rule, Klevgrand Helper opens floating at 820 × 600. See [the vendor Helper workflow](vendor-helper-workflow.md#window-placement-on-hyprland).

The tested Hyprland version uses a Lua dispatcher API (`hl.dsp.window.float`). The legacy `togglefloating` syntax does not work there. The floating dispatcher needs `action="enable"`. `action="set"` falls back to toggling, so do not use it. Check the installed compositor's API instead of assuming the old command syntax. A title and class rule applies to every matching window while it is enabled. It is not a PID-specific security boundary. The later fallback check also verifies that the window's PID belongs to the prefix. The rule syntax is in the [Hyprland window rules documentation](https://wiki.hypr.land/Configuring/Basics/Window-Rules/).

Removing the Unix `SteamAppId` before starting Proton changes the window class from `steam_app_default` to `steam_proton`. Class-based rules for Steam games, such as sending them to a gaming workspace or forcing fullscreen, then do not catch vendor helpers. Clearing the variable only inside a Windows batch file does not work. Placement and renderer compatibility are separate problems. Correct geometry alone does not fix a frozen Helper.

## 4. Helper maintenance versus plug-in runtime launch

**Symptom.** A vendor Helper looks frozen through the managed `runinprefix` path. The same installation, account and prefix work through a full UMU/Proton launch. You do not need to reinstall, create a new account or add WebView2.

**Fix.** Close the vendor's plug-in instances and make sure the prefix is idle. Stop only that prefix's known managed session, then launch Helper through full Proton. When Helper closes, wait for its runtime processes to finish before probing plug-ins again. DAW instances keep the persistent runtime. If the runtime is unknown or busy, refuse. Never kill processes by name across the system.

The missing graphics overrides from section 1 might explain the difference. Nobody has retested Helper with the corrected managed graphics profile, so the full launch remains the supported path. The idle check only happens at the start and cannot stop a DAW instance from starting during installation. Keep vendor instances closed during maintenance.

## 5. External archive utility missing

**Symptom.** Helper login works, but installation fails with "Unzip/installation failed". Helper's log says unzip/tar could not start. The downloaded ZIP has valid CRCs, and there is no Windows `tar.exe` in the prefix.

**Fix.** Supply a private Windows bsdtar/libarchive build and the DLLs it needs, with verified package hashes and their licences, and put its directory on Helper's PATH. The shared `plugg.windows-archive-tools` component does this. Test the real `tar -xf` call with its flags, including `--no-same-owner` and `--no-same-permissions`, on compressed files and on paths that contain spaces. Klevgrand Helper and UA Connect both need it. Not every installation failure is a renderer problem, a damaged download or a missing web runtime.

## 6. Shared services outliving individual containers

**Symptom.** Two instances initialize. Then one stalls waiting for a factory response while the other exits. Keeping the faster instance alive makes the case pass. Copying the runtime does not help.

**Fix.** Run one persistent container per vendor prefix, a separate Windows bridge process per instance, and cancel only that client's processes when it disconnects. With this design, fixture tests pass for repeated concurrent processing, normal close, killed Windows and native hosts, and idle shutdown and restart. This points to a container or service lifetime problem. It does not identify the exact signal or Wine server failure. See [managed Proton sessions](proton-sessions.md).

DAW host grouping is not the same thing as Wine prefix or container ownership. Hosting each instance separately does not isolate it from shared Wine services or filesystem changes either. These are lifecycle checks, not low-latency audio benchmarks.

## 7. Native/container IPC visibility

Use a private per-user tmpfs directory that both sides can see. Plugg's bridge defaults to `/dev/shm/plugg-<uid>` and checks its ownership, permissions, directory type and tmpfs backing. The container may not see a DAW's inherited runtime directory. An explicit `YABRIDGE_TEMP_DIR` must pass the same checks.

A filesystem-backed transport for audio data can cause avoidable I/O stalls.

## 8. Discovery, authorization and validation boundaries

Scan the installed VST3 roots, not the whole prefix. Klevgrand Helper keeps extracted plug-ins in its download cache. Publish each installed module once, keep its class identity, and compare hashes before treating it as unchanged. Ignore VST2 and AAX when only VST3 is supported. Helper's format setting controls what it installs. Publication filtering does not uninstall other formats.

Importing a standalone Klevgrand licence file (`.kledi`) failed with "Invalid license file", even with a freshly downloaded copy. Neither file corruption nor an activation-count limit was established as the cause. Authorizing through Klevgrand Helper works. Investigate vendor authorization separately from graphics and loading, and keep the account state intact while you do.

Factory discovery does not test component initialization, renderer selection, editor repainting, audio, authorization or project-state recall. A fixture without a graphics path cannot catch frozen vendor editors. In each supported host, a deployment checklist should cover the following:

- editor interaction and animation,
- multiple instances,
- editor close and reopen,
- normal audio,
- project save and reload.

## Bridge links into a moved checkout

**Symptom.** The DAW lists plug-ins and then refuses each one with "failed to initialize VST plug-in", although nothing changed in their environment.

**Cause.** A bundle holds a copy of the yabridge chainloader and links to `libyabridge-vst3.so`, `yabridge-host.exe` and `yabridge-host.exe.so`. Early development versions linked those files into the bridge build directory inside the checkout, `<checkout>/bundle/bridge` or a `bundle/bridge-releases/<hash>` directory there. Renaming or moving the checkout breaks every such link. The chainloader loads, cannot find the bridge beside it, and the host reports only a failed initialization.

**Fix.** The library now keeps its own bridge releases in `bridge-releases/<hash>`. Each is named after its executable files and never changes once made. New bundles link only there. `plugg relink-bundles` lists bundles that still depend on something outside the library. `--apply` copies each bundle's current build into a release and moves its links. It does not upgrade a bundle to a newer build, so a bundle on a special build, such as the Plugin Alliance editor fix, stays on it. The paths the DAW scans do not change, so the DAW needs no rescan. The previous targets go into `migration-backups/bridge-links*.json`. If a bundle's build is already gone, the command reports it and leaves it. Recreate the old path temporarily and run the command again. Afterwards, `plugg doctor` should report nothing under `publications_outside_library`.

Vendor launchers written into an environment (`launch-ua-connect`, `launch-softube-central`) had the same flaw. They changed into the checkout directory before starting Python. They now call `bin/python-module` in the library. Plugg rewrites that file with the current package location every time it opens the library.

## Evidence and privacy

When you report a problem, record the following:

- runtime and bridge revisions,
- relevant DLL hashes,
- compositor API and version,
- GPU driver versions,
- exact error messages,
- what you tested and what you changed,
- where the rollback copies are.

Keep your own observations apart from automated results and from hypotheses.

Never commit licences, account state, authenticated URLs, raw Helper logs, private prefixes or crash dumps. Normalize personal paths in shareable records. A directory whose name looks like test data may hold an activated installation. Its name is not permission to delete it.

More detail is in [managed sessions](proton-sessions.md), the [Helper workflow](vendor-helper-workflow.md) and the [compatibility notes](compatibility/).
