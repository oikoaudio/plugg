# Universal Audio

Universal Audio support is **experimental** and works for one product. On the maintainer's system (Bitwig, Hyprland/XWayland), UADx LA-2A Tube Compressor 1.0.8 works in Bitwig. Its editor closes and reopens repeatedly during playback. UA Connect 1.9.6.3797 opens from the app, installs products and triggers automatic discovery when you close it. Everything runs in the shared iLok/PACE environment described in [the PACE notes](../recipes/pace.md). [Universal Audio reusable setup](../recipes/universal-audio.md) describes the setup as a recipe.

Other UAD products, project recall, persistence across reboots, longer sessions and desktops other than Hyprland are not covered yet.

## What the setup needs

| Need | Why | Scope |
| --- | --- | --- |
| PACE / iLok License Support | Without it, UA Connect reports an `auth.pace` / iLok error | Shared iLok environment, see [PACE notes](../recipes/pace.md) |
| Windows archive tools (`tar.exe`) | Without them, downloads fail at extraction with `CreateProcess failed: File not found` and `auth.download_extraction_tar_error` | Helper PATH only |
| `--disable-gpu --no-sandbox` for UA Connect | Without them, UA Connect shows a blank window | UA Connect only, after explicit consent |
| OLE32 foreign-window guard | Without it, LA-2A's editor crashes the host on close | Runtime used by the environment |

## PACE installation

UA Connect downloads PACE 6.0.1 itself, but the installer fails under Wine with 0x80070643. There are two separate problems.

1. **OS version check.** The MSI's .NET custom action (`SetCompatibleOSVersion`) sees Windows version 6 and stops at LaunchConditions (`OSVersion=6 >= 10 == False`). `cmd /c ver` reports Windows 10.0.19045 in the same prefix. Wine reports the version according to the manifest of the calling image. The actual custom-action host is `rundll32.exe`, and its manifest has no Windows 10 `supportedOS` entry. Setting Windows 10 in `winecfg`, adding per-application AppDefaults or installing .NET 4.8 does not change this. The WiX DTF reproducer in `diagnostics/msi-version` shows the mechanism.
2. **Service configuration.** Once past the version check, installation fails at `Wix4ExecServiceConfig_X86` with `0x8007007c: Failed to get current service config info`. Wine lacks the service-configuration API the installer calls.

Both problems have fixes built from source. [The PACE notes](../recipes/pace.md) track their status and what must not ship as a fix. Plugg never modifies PACE binaries or licence checks. Automatic PACE provisioning stays disabled.

## UA Connect interface

UA Connect 1.9.6.3797 is an Electron 37.10.3 application. Launched normally, it shows a blank window because its GPU process fails to start (error 39). With `--disable-gpu --in-process-gpu`, the renderer process still fails. Disabling only the GPU sandbox is not enough. With `--disable-gpu --no-sandbox`, the main window loads, shows the signed-in product list and recognizes PACE.

`--no-sandbox` turns off Electron/Chromium process sandboxing. That is a security trade-off. Electron [documents it as a testing option](https://www.electronjs.org/docs/latest/tutorial/sandbox#disabling-chromiums-sandbox-testing-only), and it is not a general Proton setting. Plugg applies it to UA Connect only, after explicit consent, and never to plug-in launchers. Wine is not a security boundary either way. Keep raw UA Connect logs private, because they can contain account information.

In an early test, UA Connect's login fields accepted pasted text but not typed input. Nobody has looked at keyboard focus in UA Connect again since.

## Downloads and discovery

UA Connect extracts downloads with an external `tar`. The shared archive-tools component fixes the extraction failure. It puts bsdtar/libarchive as `tar.exe`, with its DLLs and licence notices, on UA Connect's PATH. This is a helper dependency and has nothing to do with PACE.

To stop the environment's idle Wine services before discovery, run the selected runtime's own `files/bin/wineserver -k` with the exact `WINEPREFIX`. If you pass the bare name `wineserver` through the full Proton application launcher, Proton tries to open it as a Windows application and the session keeps running. First check that no audio host or installer is using the environment.

<a id="durable-helper-action-2026-09-11"></a>

## UA Connect helper action

The app action and the desktop shortcut both use `plugg.ua_connect`. Its local opt-in configuration applies `--disable-gpu --no-sandbox` and puts `C:\Plugg\Tools\Archive` on PATH for UA Connect only. Audio hosts never get these flags. The helper uses the same OLE32-guarded runtime as the audio session.

Maintenance refuses to run while Bitwig, REAPER or unknown Windows applications are running. Plugg stops known leftover PACE and UA services only through the matching runtime's Wine server for this prefix. On Hyprland, UA Connect opens floating. The launcher watches for its window to close, because Electron can otherwise stay alive after Close. It then releases the helper runtime for the next audio session. An error from a compositor query never counts as the window closing. This close detection only works on Hyprland. Other desktops need validation.

### Automatic discovery after helper closure

UA Connect and Klevgrand share `vendors.finish_installation()`. After UA Connect closes, Plugg releases its helper runtime and waits until the installed VST3 files have not changed for five seconds. It then probes new modules and publishes the ones it discovers. The runtime cleanup also runs after probing, including when a discovery check fails. Plugg keeps unchanged publications without probing them again or creating duplicate wrappers. It reports changed installed versions for your attention instead of republishing them. Because the PACE environment is shared, discovery covers all its installed VST3s from every vendor, and each plug-in keeps the vendor name it reports.

The helper action and the desktop shortcut both run this workflow. Plugg holds the helper and job locks from launch through discovery. The UI shows progress and results. The DAW may still need its normal plug-in rescan. Installation, activation, audio validation and automatic product updates are separate jobs. [The UA recipe](../recipes/universal-audio.md#updating-ua-connect) covers updating UA Connect itself.

## Editor-close crash and the OLE32 guard

**Symptom.** Closing LA-2A's editor in Bitwig hangs the plug-in host. The DAW then reports the host as unresponsive, fails to save the plug-in state and has to terminate it. Reloading brings the plug-in back.

**Cause.** When its editor closes, the plug-in calls `RevokeDragDrop` for a window that belongs to a different Windows process, the WebView2 process that hosts its interface. Wine's `ole32!RevokeDragDrop` reads the window's `OleDropTargetInterface` property and calls `IDropTarget::Release` on it. That pointer is only valid in the other process. The fault at `RevokeDragDrop+0x66` ends the host's main thread during exception handling. The other threads keep waiting for it, so the host hangs instead of exiting. A window inventory taken just before one reproduction matched the faulting window handle and target pointer to the WebView2-owned window. Current upstream Wine reads the property and calls Release in the same way, so a newer Wine alone does not fix it.

**Fix.** Patch `patches/0004-ole32-revoke-foreign-drop-target.patch` makes `RevokeDragDrop` return an error for a window owned by another process, before it reads any process-local registration data. Cleanup by the owning process is unchanged. Turning `RevokeDragDrop` into a no-op would leak registrations and break drag-and-drop, so the patch does not do that. The regression fixture in [diagnostics/dragdrop](../../diagnostics/dragdrop/README.md) runs against the exact Wine revision of the UMU-Proton release. It shows three things:

- the unpatched build faults on revoking another process's window,
- the patched build returns an error instead,
- 100 normal register/revoke cycles with reference-count checks pass.

The build provenance is in `patches/0004-ole32-revoke-foreign-drop-target.provenance.json`. Recipes can check for the patch with the `plugg.ole32-foreign-window-guard@1` component.

With the guarded runtime (`proton-10.0-4-ole32-guard-920c6467a441`), LA-2A's editor closes and reopens repeatedly during playback. The change is not upstream. Nobody has checked which error code real Windows returns in this case. Other editors that span several processes may hit the same path, but this has not been shown for any other product.

The guard was also tested with Plugin Alliance. Its editor-close failures turned out to need a separate bridge fix. See [Plugin Alliance](plugin-alliance.md#the-editor-close-detach-fix).

## Changing a licensed environment

Switch a runtime or launcher only while the environment is idle, and do it by changing the session configuration. Never restore, recreate or copy the licensed prefix. Before you do anything that could change the environment's machine identity, deactivate its iLok licences. See [licensing safety](../licensing-safety.md).
