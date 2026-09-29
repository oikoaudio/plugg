# Klevgrand

Klevgrand plug-ins **work** on the maintainer's system (Bitwig, Hyprland/XWayland, NVIDIA). Products are installed and authorized through Klevgrand Helper under UMU-Proton 10.0-4. Klevgrand has an executable recipe that sets up Helper in a fresh environment.

Klevgrand's [licence policy](https://klevgrand.com/support/how-many-computers-may-i-use-my-plugin-on) allows installation on three computers you own, with one in use at a time.

## Tested products

| Product | Version | Result |
| --- | --- | --- |
| Skaka | 1.2.1 | Authorized and working in Bitwig, including editor open and close during playback |
| Slammer | 1.1.2 | Working in Bitwig, including editor open and close during playback |
| Richter | 1.0.2 | Working in Bitwig |
| Korvpressor | 2.1.2 | Working in Bitwig |
| DAW Cassette | not recorded | Working in Bitwig. The editor redraws correctly after the DXVK fix below. |
| REAMP | not recorded | Working in Bitwig |
| Klevgrand Helper | 1.0.12, self-updates after login | Login, product installation and authorization work |

Sustained stress tests, project save and reopen, and REAPER are not checked yet.

## What the setup needs

**UMU-Proton, not plain Wine.** Under managed Wine 11.0, Helper installs and shows its login window, but the login fields ignore the keyboard. The pointer turns into a text cursor and links work, but typing and Tab do nothing. A Wine virtual desktop did not help, and neither did installing Microsoft WebView2. Under UMU-Proton 10.0-4 in a fresh prefix, text entry works without WebView2.

**A Windows `tar.exe`.** Helper extracts downloads by running an external `tar -xf` with `--no-same-owner` and `--no-same-permissions`. Without it, installation fails with "Unzip/installation failed", and the log says "unzip/tar failed to start". The shared archive-tools component fixes this. It puts a hash-pinned MSYS2 bsdtar/libarchive build, its DLLs and their licences in `C:\Plugg\Tools\Archive` and adds that directory to Helper's PATH.

**A full Proton launch for Helper.** Through the managed `runinprefix` session that plug-ins use, Helper hangs on its loading screen. The environment stops its idle plug-in session and launches Helper through full Proton instead. See [the vendor Helper workflow](../vendor-helper-workflow.md#helper-uses-the-full-proton-launch).

**No `SteamAppId`, and floating before the window appears, on Hyprland.** With the Steam app ID set, the window class is `steam_app_default`. Class-based gaming rules may then move the window to another workspace or force it fullscreen. Plugg clears the variable, so the class becomes `steam_proton`, and floats Helper with a temporary rule set before launch. See [deployment troubleshooting](../deployment-troubleshooting.md#3-hyprland-initial-placement-and-remembered-geometry).

**DXVK for plug-in editors.** With WineD3D, the editors accept parameter changes but their graphics freeze. The plug-in session selects DXVK explicitly. See [deployment troubleshooting](../deployment-troubleshooting.md#1-working-controls-frozen-editor-images).

## Installation and discovery

Klevgrand's `.exe` installers come with `.bin` payload files. Keep them in the same folder with their original filenames. Plugg treats them as one installation set.

Helper keeps extracted copies of plug-ins in its download cache. Plugg scans only `Program Files/Common Files/VST3`, so it publishes each product once. Helper's own settings decide which formats it installs. Plugg publishes only VST3 and does not remove the other formats.

Helper updates itself after login, so the installed executable no longer matches the original installer. Record the Helper version and hash you tested with.

## Known issues

- Importing a `.kledi` licence file directly into Skaka failed with "Invalid license file", even with a freshly downloaded file. The cause is not known. It could be file handling, the activation count or something else. Authorize through Helper instead.
- After login, restoring Helper from fullscreen to a small window once left it unresponsive. Plugg now launches it floating from the start and does not resize it.
- Crashes on load with `X_GLXCreateContext` / `BadValue` came from a host NVIDIA driver/library mismatch after an update, not from Plugg. A reboot fixed them. See [deployment troubleshooting](../deployment-troubleshooting.md#2-graphics-driver-update-without-reboot).

## Validation limits

Helper is a PE64 JUCE application. It does not statically import .NET, WebView2 or a Visual C++ runtime, but it may still load them dynamically. Factory discovery through the managed session, fixture audio and the lifecycle tests are automated. Everything that involves the Klevgrand account, authorization, editors and audio was checked by hand. This project records no account credentials or licence contents anywhere.

The design based on this vendor's setup is in [vendor recipes](../vendor-recipes.md).
