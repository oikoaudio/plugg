# Native Instruments

Native Instruments **partly works** on the maintainer's system (Bitwig, Hyprland/XWayland). Native Access 2 runs under UMU-Proton 10.0-4, signs in through the Linux browser and installs products. Raum works in Bitwig. The [Native Instruments recipe](../recipes/native-instruments.md) automates the setup. This page records the findings the recipe is based on.

## Tested products

| Product | Version | Result |
| --- | --- | --- |
| Native Access | 2 | Installs, signs in and installs products. The UI is somewhat sluggish. |
| Raum | 1.3.7 (R34) | Working in Bitwig |
| Massive | 1.7.0 (R0) | Factory discovery and publication only |
| Massive X | 1.7.1 (R0) | Factory discovery and publication only. The factory library of 720 `.nksf` presets installs. The preset browser is untested. |

Massive X's preset browser did not work under an earlier plain Wine/yabridge setup. Nobody has checked it under Plugg yet.

## Native Access installer

The tested installer is `Native-Access_2.exe`, SHA-256 `82d7b7977d4fbc19db32aee8778c75906f6ddf935bcf2958f2d8d45141b2b2cc`. It is a 32-bit NSIS installer, which does not mean the installed application is 32-bit.

Without PowerShell, the installer fails. An unattended `/S` installation exits with code 2 and installs nothing. An interactive run shows the warning "Native Access is running" although no Native Access process exists. This happens on UMU-Proton 10.0-4 and on plain Wine 11.0, and renaming the installer does not help. With PowerShell in the prefix, `/S` exits 0 and installs Native Access on both runtimes. This step does not need .NET 4.8. Nobody knows exactly how the installer checks for running processes.

The recipe installs Microsoft's PowerShell 7.4.11 x64 MSI (SHA-256 `9579011c463a3ad6abf890736a97e2fbba9a7b4e09ce851576ccf263e15bdc97`) plus a small forwarder built from source. It does not use third-party wrapper scripts. See [the recipe](../recipes/native-instruments.md#powershell-component).

## Sign-in

Native Access signs in through the system browser, which returns a `native-access://` link. Windows inside the prefix already associates that scheme with Native Access. Linux has no desktop handler for it. Plugg registers a per-user handler that forwards only `native-access://` URLs to this environment's Native Access, unchanged and without a shell. Each callback URL works once. Do not paste it into chat or keep it in logs. As with any desktop protocol handler, the URL is briefly visible in process arguments to other processes of the same user.

## Installing products

- Native Access's download location picker cannot create a new folder. The recipe creates `C:\Native Instruments Downloads` in advance.
- Closing Native Access triggers discovery. Its NTKDaemon background service keeps running after the window closes. Plugg stops this prefix's Wine session, and only this one, before it discovers new VST3s through the managed plug-in session.
- NTKDaemon has to run as a Windows service, started in the same launch as Native Access. See [the recipe](../recipes/native-instruments.md#automated-service-component).

## Known issues

- Reopening Native Access has sometimes produced no window while NTKDaemon kept running. Restarting only this prefix's Wine session brought the window back. The cause is not known.
- The Linux browser handler can start a second full launch while Native Access is already open. Handing the link to the running instance has not been fully validated.
- On Hyprland, Plugg focuses the window with `hl.dsp.focus` and a window address. The tested version rejects the legacy `focuswindow` dispatcher.

## Validation limits

Discovery and publication are automated checks. Sign-in, product installation and Raum in Bitwig were checked by hand. Preset browsing, preset loading, authorization and project recall for Massive and Massive X are untested.
