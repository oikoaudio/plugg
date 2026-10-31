# plugg-2 Wine modules: licence and source

`plugg-2-wine-modules.tar` holds ten Wine modules that Plugg's `plugg-2` runtime puts over UMU-Proton 10.0-4:

- `rundll32.exe`, `services.exe`, `sechost.dll` and `msi.dll`, for i386 and x86_64
- `ole32.dll` and `ntdll.dll`, for x86_64

The modules are Wine, which is free software under the GNU Lesser General Public License, version 2.1 or later. `wine-LICENSE`, `wine-COPYING.LIB` and `wine-AUTHORS` in this release are Wine's own licence files.

## Corresponding source

- Wine: https://github.com/ValveSoftware/wine at revision `b8fdff8e1f855b5276ec4ddca0f31b2792554322`, the Wine inside UMU-Proton 10.0-4.
- Patches: `patches/wine/` and `patches/0004-ole32-revoke-foreign-drop-target.patch` in https://github.com/oikoaudio/plugg at the commit this release's tag points to. `plugg/recipes/runtime-overlays.json` lists which patch each module carries, with its SHA-256.
- Build: `scripts/build-runtime-overlay.py` in the same commit rebuilds the modules byte for byte from that source. `plugg/recipes/runtime-overlays.json` records every module's SHA-256 and the archive's.

Archive SHA-256: `685fbea918e9555b5a6e8ccf226d9e0ab94726c501c53c5d8f57df0040334aa9`

Plugg never modifies PACE, iLok or any vendor's binaries. These modules fix Wine itself. See `docs/runtime.md` in the repository.
