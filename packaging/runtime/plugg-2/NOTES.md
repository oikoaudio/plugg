**This is not the Plugg app.** These are support files that Plugg downloads for itself. To install Plugg, see the latest release or the README.

This archive holds the patched Wine modules for Plugg's `plugg-2` runtime, which is UMU-Proton 10.0-4 with ten modules replaced. Plugg downloads this archive itself with `plugg runtime assemble plugg-2` and checks every hash. You don't need to download it by hand.

It has everything in `plugg-1`, and two more fixes:

- `msi.dll` no longer damages a large MSI when it saves one. Without this, Kontakt 8's installer installs nothing and Native Access reports success.
- `ntdll.dll` carries the upstream Wine fix for `RtlVirtualUnwind2()`, so Wine can report crashes that used to end the process with no message.

Wine is LGPL-2.1-or-later. Wine's licence files and a pointer to the corresponding source are attached (`SOURCE.md`). The tag points at the commit that holds the patches and the build script that reproduces the archive byte for byte.

SHA-256 of `plugg-2-wine-modules.tar`: `685fbea918e9555b5a6e8ccf226d9e0ab94726c501c53c5d8f57df0040334aa9`
