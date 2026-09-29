# Third-party source and licensing

New Plugg code is GPL-3.0-or-later. The root LICENSE contains GPL version 3, and the SPDX declarations permit later versions.

The bridge is a patched build of [yabridge](https://github.com/robbert-vdh/yabridge) at commit `b580a9f7fc46509767ca156d4f92872552b9e571`, plus the recorded patch series in `patches/`. Keep its authorship and GPL-3.0-or-later notices. The build records the revision, patch checksum and binary checksums in `bundle/bridge/build.json`, and copies yabridge's license beside the binaries. This repository ignores the vendor checkout. The build script can reproduce it.

The yabridge build selects VST3 SDK 3.7.7 and other dependencies through upstream Meson configuration. A newer SDK's license does not necessarily apply to those pinned sources. Keep the actual SDK and dependency licence files when preparing a distribution. A binary release of the bridge must carry yabridge's licence and those of the VST3 SDK and the libraries it compiles in (Asio, Bitsery, function2, toml++, ghc::filesystem), and point at the tagged source. `scripts/build-release-bridge.py` builds that package. Its archive carries all of these licence files and a `NOTICE.md` pointing at the tagged source (see [packaging](packaging.md#release-bridge)).

Every new environment runs on Proton. Plugg downloads [UMU launcher 1.4.4](https://github.com/Open-Wine-Components/umu-launcher/releases/tag/1.4.4) and [UMU-Proton 10.0-4](https://github.com/Open-Wine-Components/umu-proton/releases/tag/UMU-Proton-10.0-4) from their own releases, checks fixed archive checksums, and UMU provisions the matching Steam Linux Runtime. Plugg does not redistribute these. Each person downloads them from upstream, with their own licence material.

The `plugg-1` runtime is UMU-Proton 10.0-4 with seven Wine modules replaced (see [the runtime page](runtime.md)), and those modules are the one Wine binary Plugg itself distributes. Wine is LGPL-2.1-or-later. The corresponding source is Wine at the revision recorded in `patches/wine/series.json`, plus the patches in `patches/wine/` and `patches/0004-ole32-revoke-foreign-drop-target.patch`. `scripts/build-runtime-overlay.py` builds it and reproduces the published modules byte for byte. A release that attaches the modules must also carry Wine's licence and point at that source.

Environments made before the move to Proton run on [Kron4ek Wine-Builds 11.0](https://github.com/Kron4ek/Wine-Builds/releases/tag/11.0), downloaded from upstream in the same way. Wine and its bundled components keep their own licences; Plugg's GPL declaration does not relicense them.

The recipe leads under `plugg/leads/cabinet/` come from the plug-in catalogue of [Cabinet](https://github.com/Mark12870/cabinet) by Mark12870 and contributors, GPL-3.0-or-later. Each file names the Cabinet commit and directory it came from, and keeps Cabinet's install scripts verbatim as reference text. Plugg executes nothing in them. `scripts/import-cabinet-catalogue.py` regenerates them. Do not edit them by hand. Cabinet's artwork is not included.

The project authored the fixture effect and installer itself. They contain no proprietary plug-in code, activation material or vendor installers. The project license does not override upstream licenses.
