# plugg-1 Wine modules: licence and source

`plugg-1-wine-modules.tar` holds seven Wine modules that Plugg's `plugg-1` runtime puts over UMU-Proton 10.0-4:

- `rundll32.exe`, `services.exe` and `sechost.dll`, for i386 and x86_64
- `ole32.dll`, for x86_64

The modules are Wine, which is free software under the GNU Lesser General Public License, version 2.1 or later. `wine-LICENSE`, `wine-COPYING.LIB` and `wine-AUTHORS` in this release are Wine's own licence files at the revision below.

## Corresponding source

- Wine: https://github.com/ValveSoftware/wine at revision `b8fdff8e1f855b5276ec4ddca0f31b2792554322`, the Wine inside UMU-Proton 10.0-4.
- Patches: `patches/wine/` and `patches/0004-ole32-revoke-foreign-drop-target.patch` in https://github.com/oikoaudio/plugg at the commit this release's tag points to. `patches/wine/series.json` lists them with their SHA-256 hashes.
- Build: `scripts/build-runtime-overlay.py` in the same commit rebuilds the modules byte for byte from that source. `plugg/recipes/runtime-overlays.json` records every module's SHA-256 and the archive's.

Archive SHA-256: `2f2ebcfe16b7e8ca1538045e82f92962e300711ab282279d8b6a4417f02044ff`

Plugg never modifies PACE, iLok or any vendor's binaries. These modules fix Wine itself. See `docs/runtime.md` and `docs/recipes/pace.md` in the repository.
