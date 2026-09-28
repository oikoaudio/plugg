**This is not the Plugg app.** These are support files that Plugg downloads for itself. To install Plugg, see the latest release or the README.

The patched Wine modules for Plugg's `plugg-1` runtime (UMU-Proton 10.0-4 plus seven replaced modules). Plugg downloads this archive itself with `plugg runtime assemble plugg-1` and checks every hash. You don't need to download it by hand.

- `rundll32.exe` declares Windows 10 support, so MSI custom actions such as PACE's see the right Windows version.
- `services.exe` and `sechost.dll` store and report service failure actions, which the PACE installer configures.
- `ole32.dll` stops a plug-in editor's close from crashing the host when it revokes a drop target another process owns.

Wine is LGPL-2.1-or-later. Wine's licence files and a pointer to the corresponding source are attached (`SOURCE.md`). The tag points at the commit that holds the patches and the build script that reproduces the archive byte for byte.

SHA-256 of `plugg-1-wine-modules.tar`: `2f2ebcfe16b7e8ca1538045e82f92962e300711ab282279d8b6a4417f02044ff`
