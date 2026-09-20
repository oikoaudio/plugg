# Third-party source and licensing

New Plugg code is GPL-3.0-or-later. The root LICENSE contains GPL version 3, and the SPDX declarations permit later versions.

The bridge is a patched build of [yabridge](https://github.com/robbert-vdh/yabridge) at commit `b580a9f7fc46509767ca156d4f92872552b9e571`, plus the recorded patch series in `patches/`. Keep its authorship and GPL-3.0-or-later notices. The build records the revision, patch checksum and binary checksums in `bundle/bridge/build.json`, and copies yabridge's license beside the binaries. This repository ignores the vendor checkout. The build script can reproduce it.

The yabridge build selects VST3 SDK 3.7.7 and other dependencies through upstream Meson configuration. A newer SDK's license does not necessarily apply to those pinned sources. Keep the actual SDK and dependency license files when preparing a distribution. The current source build is not a finished binary distribution or compliance package.

Plugg downloads the managed Wine runtime from [Kron4ek Wine-Builds 11.0](https://github.com/Kron4ek/Wine-Builds/releases/tag/11.0) and keeps its package contents and license material. Wine and its bundled components keep their own licenses. Plugg's GPL declaration does not relicense them. A distributable release must provide the source and notices required for redistributed binaries.

The isolated Proton test downloads [UMU launcher 1.4.4](https://github.com/Open-Wine-Components/umu-launcher/releases/tag/1.4.4) and [UMU-Proton 10.0-4](https://github.com/Open-Wine-Components/umu-proton/releases/tag/UMU-Proton-10.0-4) and checks fixed archive checksums. UMU provisions the matching Steam Linux Runtime. The current application package does not embed these components. Anyone distributing them later must meet each component's license and source obligations.

The recipe leads under `plugg/leads/cabinet/` come from the plug-in catalogue of [Cabinet](https://github.com/Mark12870/cabinet) by Mark12870 and contributors, GPL-3.0-or-later. Each file names the Cabinet commit and directory it came from, and keeps Cabinet's install scripts verbatim as reference text. Plugg executes nothing in them. `scripts/import-cabinet-catalogue.py` regenerates them. Do not edit them by hand. Cabinet's artwork is not included.

The project authored the fixture effect and installer itself. They contain no proprietary plug-in code, activation material or vendor installers. The project license does not override upstream licenses.
