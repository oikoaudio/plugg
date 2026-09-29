# Softube Central

Softube Central **works** in an existing shared PACE/iLok environment on the maintainer's system (Bitwig, Hyprland/XWayland). Central login, product sync, product installation and managed close work. `recipe setup-existing` reproduces the setup from the original Central installer. The iLok environment itself comes from `plugg ilok create` (see [iLok and PACE](pace.md)). The GUI has no chooser for this setup yet.

## Tested products

| Product | Version | Result |
| --- | --- | --- |
| Softube Central | 3.0.5 | Login, product sync, installs, managed close and automatic publication work. The top of the window is slightly clipped. |
| Saturation Knob | 2.6.41 | Activated. Audio, controls and repeated editor close and reopen work in Bitwig, with DXVK and the plug-in's own **Use OpenGL** option turned off. |
| Fix Phaser | not recorded | Installed through Central and published automatically. Audio and activation are untested. |

Other Softube products and other DAWs are untested.

## Inputs

- `Softube Central Setup 3.0.5.exe`, SHA-256 `8562f9ba43404cdd16eb36130c33d4afb0ca86dac6cef4374c477c9696046b46`. This is a Windows NSIS installer that contains an Electron app.
- Its bundled `resources/deps/Softube Installer Helper Installer.exe`, SHA-256 `f6542ed688a9bec3f0bd02bacf01708290aec909784c8018be6a2c8823a307cd`.

Softube [documents](https://www.softube.com/uk/support/support-getting-started/how-do-i-install-my-products) Central and direct product installers as alternatives. Both need a linked iLok account. Direct installers use iLok License Manager for activation.

## Why Softube joins the existing PACE environment

Central installs products through a separate Softube Installer Helper service and talks to it over IPC. The helper also handles PACE. This looks like Native Access's split between UI and service, but the service, protocol and licensing functions are different. None of the NTKDaemon handling applies.

Softube products are licensed through iLok. Instead of creating another activated machine, Softube joins the existing shared PACE environment. The generic helper recipe path always creates a new environment, so Softube does not use it. It has its own join operation, with identity checks, locking and checked service registration.

## Setting it up

Close the DAW and vendor managers first. Then drop `Softube Central Setup 3.0.5.exe` onto Plugg. Plugg recognises it and asks to add it to your iLok environment instead of making a new one. The command does the same:

```sh
python3 -m plugg recipe setup-existing plugg.softube@2 \
  --installer "$HOME/Downloads/Softube Central Setup 3.0.5.exe" \
  --environment "$HOME/.local/share/plugg/environments/EXISTING_ENVIRONMENT_ID"
```

The selected environment must already belong to this library. It needs a protected, matching licensing identity, PACE License Support and the full Proton launcher. Plugg first adds the recipe's requirements that the environment lacks, which are the pinned PowerShell 7.4 and the pinned Visual C++ 2015-2022 x64 runtime. It takes a recovery point before each. It never creates a Windows machine.

The command does the following:

1. Takes the shared helper and job locks.
2. Stages the pinned installer in a private directory.
3. Refuses to continue if an existing vendor file or service configuration differs.
4. Copies only missing files.
5. Registers the Softube service (`SoftubeInstallerDaemon`) if it is missing, with the fixed executable path, demand start and LocalSystem. It never runs the vendor's bundled PACE setup.
6. Configures the managed launcher.

It compares the PACE executable and library hashes, the licensing identity and the runtime configuration before and after. If registration fails, the new vendor files stay in place for inspection and a checked repeat, and no success record is written.

`existing_setup = "softube"` in the recipe names a fixed adapter implemented in `shared_setups.py`. It is not a Python import, an executable path or a shell command. The adapter accepts the reviewed component graph and checks the existing prerequisites. It does not provision a new licensing environment. It rejects extra operations and changed component definitions instead of silently ignoring them, and unreviewed community-tier recipes cannot call it. A new adapter needs an implementation, a capability declaration, and tests that show it preserves and integrates with existing environments.

The `documentation_only` marker still stops generic fresh provisioning of this graph, because PACE provisioning is unfinished. After the first setup, **Open Softube Central** and automatic product publication work from the app's Softube card. The card also shows the shared PACE dependency.

### Lower-level commands

`softube-stage` turns the reviewed installer into a verified payload directory of 909 Central files plus the installer service. It runs no Windows code and installs no licensing components. It refuses unknown installer hashes before unpacking. `--compare-environment` reads an environment and reports missing or different vendor files without replacing them.

```sh
python3 -m plugg softube-stage "$HOME/Downloads/Softube Central Setup 3.0.5.exe" \
  --output /tmp/softube-reviewed-payload \
  --compare-environment "$HOME/.local/share/plugg/environments/EXISTING_ENVIRONMENT_ID"
```

Choose an unused output directory. `softube-join` does the same checked join as `recipe setup-existing`, without going through the recipe interface:

```sh
python3 -m plugg softube-join "$HOME/Downloads/Softube Central Setup 3.0.5.exe" \
  --environment "$HOME/.local/share/plugg/environments/EXISTING_ENVIRONMENT_ID"
```

### Service extraction

The bundled helper wraps modified bzip2 streams in NSISBI chunk framing, which 7-Zip and libarchive cannot unpack. `softube_payload.extract_service()` extracts the service payload directly. It does not run the helper or its bundled PACE installer. It accepts only the reviewed helper bytes and checks the result, which has SHA-256 `2a19ede7f2f450e0d9e1fab717ccadd14b65768d5c7a8fb97681d57c24cfe634` and is 13,364,472 bytes long.

A different installer version needs a new verified payload record. Never apply these offsets to an unknown file. The bounded decoder is adapted from [NSISExtractor](https://github.com/KokerZhou/NSISExtractor/tree/8644b63d79a35bf002ba75f42375a9e4dafbbe74). Its licence and third-party notices are in `plugg/assets/nsis-extractor-license.txt`.

## The managed launcher

The managed launcher (`plugg.softube`) starts the Softube service and Central in one full Proton session, with `--disable-gpu` for Central. It uses the environment and job locks, waits for Central's window to close, and then refreshes the installed products. Its process allowlist refuses to stop an open iLok License Manager, UA Connect, installer or plug-in host. Central does not need Electron's sandbox disabled.

## Known issues

**Product installs from Central stall without the Visual C++ runtime.** Softube's product installers run their bundled `vcredist_x64.exe /quiet`. In an environment without the Visual C++ 2015-2022 runtime, that step installs the runtime and then never exits under Wine, so the product install never finishes and no window explains why. With the runtime already there, the same step returns at once. A Wine log of Fix Phaser's install shows this, and Fix Phaser and Dirty Tape then installed from Central. `plugg.softube@2` requires the runtime. Plugg installs the pinned Microsoft runtime before Central runs, and adds it the next time you open Central if an environment lacks it. Plugg's own install of the runtime has the same non-exiting installer, so Plugg stops waiting once the runtime is registered and ends the leftover processes.

**Saturation Knob flickers with OpenGL on.** With OpenGL enabled in the plug-in, its UI flickers heavily under DXVK, and a WineD3D override does not help. Untick **Use OpenGL** in the plug-in's own settings. Nobody knows where that setting is stored or whether it affects other Softube products, so Plugg does not change it automatically.

**Central's window is clipped.** Without `--disable-gpu`, Central is clipped at the top and bottom and the pointer is offset. With it, only a small strip at the top is clipped. The clipping is inside the app's own surface, not off-screen. A fixed-size Wine desktop did not help.

**Product installers bring other formats.** They also install VST2 and AAX. Plugg publishes only VST3.

**Activated environments are protected.** Once a product is activated, the environment is recorded as `deactivate-first`. Deactivate in iLok before any cleanup or rebuild that would remove the environment or change its identity.

## Validation

- Service registration from the extracted payload passes in a new disposable prefix with no PACE installation or account data. The first run registers the service, a repeat changes nothing, the registry configuration matches, and no Windows programs are left running. `scripts/test-softube-service.py` is the opt-in integration test. It does not cover product authorization in a new PACE installation.
- Run against a working shared installation, the full recipe command replaces nothing. PACE binaries, runtime configuration and the recorded machine identity stay unchanged.
- Staging from the original installer recovers all 910 files (909 Central files plus the service), identical to a working installation.
- PACE binary hashes and machine identity were checked before and after every installation and renderer change on this page. They never changed.
- Unit tests cover the first copy and a repeat, rejection of different files, failed registration, service configuration checks and refusal of unprotected environments.

This page does not claim automated fresh PACE provisioning, compatibility for other Softube products, a fix for every silent installer stall, or perfect window decoration on Hyprland.
