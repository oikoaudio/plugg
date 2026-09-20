# Packaging and clean-container checks

## Arch package

`packaging/arch/PKGBUILD` builds everything from pinned sources:

- the yabridge revision and patch series, which the bridge build script already verifies,
- the bridge and scanner,
- the manager wheel.

It runs the full unit suite in `check()` and installs the bridge to `/usr/lib/plugg/bridge`. A library created without `--bridge-dir` selects that bridge when there is no checkout build. The package does not strip binaries, because the bridge's `build.json` records their hashes. It does not include the Proton runtime either. Plugg downloads that on first use and checks its hash.

A test build from a checkout uses the local branch instead of GitHub:

```sh
cd packaging/arch
PLUGG_SOURCE="git+file://$(git rev-parse --show-toplevel)#branch=$(git branch --show-current)" makepkg -si
```

The package has been built and installed in a clean `archlinux:latest` container with Wine 11.17 and Python 3.14. The unit suite passed inside `check()`. The installed command ran `runtime plan` and `doctor`, the installed bridge passed `bridge_bundle.inspect`, and the GTK front end imported under Xvfb. Nothing in that container ran Proton or a plug-in. The package is `-git` because there is no tagged release yet. An AUR submission needs the repository to be public.

## Build the manager as a wheel

You can also build the manager as a Python wheel. The native bridge is a separate, versioned artifact. This is a developer packaging path, not a turnkey Linux installer. The sections below say what the container checks cover and what they do not.

It requires Python 3.12+ and uv:

```sh
python3 scripts/build-python-package.py --output dist
python3 scripts/test-python-package.py dist/plugg-0.1.0.dev0-py3-none-any.whl
```

Use the isolated build script. Native builds also use the checkout's `build/`, which may hold stale Python build output. The script copies the current package files into a fresh temporary source directory and leaves that shared directory alone. The verification step rejects extra namespaces, missing files and bytes that differ from the checkout, and it tests the installed recipe commands.

## Run the Ubuntu packaging gate

This needs Docker and outbound downloads. From the checkout:

```sh
python3 packaging/test-container.py \
  dist/plugg-0.1.0.dev0-py3-none-any.whl \
  --output .scratch/package-check-001
```

The output directory must be new, on a disk with several GB free. The test uses a digest-pinned Ubuntu 24.04 image, two CPUs, 3 GB RAM and a private Xvfb display. It installs system dependencies and builds the pinned bridge source with the explicit `patches/yabridge-series.json`. It then installs the wheel and, as an ordinary user, checks native library loading, scanner startup, recipe resolution and GTK window creation. The dependency list is in `packaging/test-container.py`. GTK comes from Ubuntu's PyGObject packages, which a virtual environment created with `--system-site-packages` can see.

The test copies in only selected build files and the wheel. It uses no host mounts, host desktop connections, Docker socket mounts or vendor credentials. It does not modify existing Docker containers, services, networks or volumes. At the end it exports the bridge, its build manifest and any results and logs. It then checks the ownership label and removes only the container it created. It keeps images. If the runner is killed, the output directory holds its container ID, so you can clean up that one container.

The base image and source revision are pinned. Apt packages and build tools come from the image's configured repositories at run time. This is a repeatable compatibility check, not a bit-for-bit reproducible build.

## Synthetic runtime and audio test

The optional `--runtime-smoke` phase downloads the recipe's pinned runtime assets into the empty container and verifies them. It then tries a synthetic helper installer, VST3 publication, deterministic audio and helper reopening. It uses no vendor software or activation. A failure gives a failing exit status, not a skipped pass.

Under ordinary Docker isolation, as tested so far, UMU/pressure-vessel cannot create its nested namespace. Downloads and hash checks succeed, but Windows startup fails before the fixture installer runs. The runner does not relax isolation or change the Docker daemon to get past this. Full clean-system audio validation needs a disposable VM or a separately reviewed runner that meets the runtime's namespace requirements. Xvfb checks say nothing about real GPU, Wayland/Hyprland, DAW or real-time performance compatibility.

## Distribution work still required

- Validate the Ubuntu-built Windows host and full audio path in a suitable runner.
- Test on another supported distribution and establish the oldest supported ABI.
- Turn the wheel and validated bridge into an installable release with desktop integration and clear dependency handling.
- Publish the corresponding source, patch series and license notices with native artifacts.
- Decide artifact signing and update policy before public distribution.

Keep candidate bridges in a stable location. A new library can select one with `--bridge-dir`, and its published plug-ins keep depending on it. Do not replace a live library's recorded bridge or runtime as part of a packaging test.
