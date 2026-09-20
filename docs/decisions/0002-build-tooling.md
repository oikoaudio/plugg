# Keep Meson, record more build evidence, defer Nix

Decided in September 2026. Plugg keeps the existing Meson build path for this development phase. Nix remains a candidate for producing release artifacts. It is not a dependency for musicians and not the recipe engine.

By default, the Meson configuration picks up system Asio and Bitsery headers where they exist. The pinned yabridge source and wrap files therefore do not pin the whole build. The build manifest records the dependency versions Meson actually used, compiler information, selected options, relevant source hashes and tool versions. This is an audit record. It does not claim a hermetic or bit-reproducible build.

The [Nixpkgs yabridge derivation](https://github.com/NixOS/nixpkgs/blob/master/pkgs/by-name/ya/yabridge/package.nix) already fetches hashed dependency sources, supplies the Meson and Wine dependencies and installs the bridge. It also applies Nix-specific patches for Wine and dependency paths and for chainloader lookup. Reusing that derivation unchanged would change Plugg's managed launch behaviour. A dedicated derivation would have to keep Plugg's own loader patches and handle dependencies outside NixOS. That is a plausible build project, but not a proven shortcut.

The project provides no Nix flake and does not claim one works. A development shell does not meet the acceptance gates in [the recipe-engine decision](0001-recipe-engine.md). Those gates are to build twice from pinned inputs, compare the outputs, and load the artifact under the existing UMU runtime on a system that does not need Nix installed. Weigh the total setup and packaging cost before adopting it.

## What is implemented

You can use separate build and output directories:

~~~sh
PLUGG_BUILD_DIR=/tmp/plugg-build \
PLUGG_BRIDGE_OUTPUT=/tmp/plugg-artifacts \
scripts/build-bridge.sh
~~~

Each output records only the six expected artifacts. If one is missing, manifest generation fails. Stale unrelated files never become release inputs. The manifest lists the observed system dependencies, but not local include paths or a full environment dump. Compiler information comes from the selected Meson build directory. The scanner's compiler is recorded separately.

A clean build can force the pinned Asio and Bitsery wraps before running the normal build script:

~~~sh
meson setup /tmp/plugg-pinned-headers-build vendor/yabridge \
  --cross-file vendor/yabridge/cross-wine.conf --buildtype=release \
  -Dclap=false -Dbitbridge=false --force-fallback-for=asio,bitsery
PLUGG_BUILD_DIR=/tmp/plugg-pinned-headers-build \
PLUGG_BRIDGE_OUTPUT=/tmp/plugg-pinned-headers-bridge \
scripts/build-bridge.sh
~~~

The manifest includes the selected subproject Git revisions, tracked-diff hashes, the actual `meson.build` hashes and the `force_fallback_for` option. This matters because the pinned Asio source is revision `ed6aa8a13d51dfc6c00ae453fc9fb7df5d6ea963` (asio-1-34-2), while its Meson overlay declares 1.28.2. Neither a version label nor a clean tracked diff covers every untracked header or transitive system input.

## What has been verified

- A clean build with pinned Asio and Bitsery passed the synthetic helper installation, publication, audio and reopening check in a disposable, unactivated prefix.
- A second clean build in a different directory on the same host produced identical bytes for all six artifacts. The recorded build inputs, upstream revision and patch hashes were equal.

This shows repeatability on one host with pinned Asio and Bitsery. It is not a fully pinned toolchain, a cross-distribution result or a vendor or DAW regression test. It makes another build framework less urgent. Compiler and system-library provisioning are still open.

If pinning the remaining compiler and system libraries becomes the main burden, write the dedicated Nix derivation and test its artifacts with the same loading tests.
