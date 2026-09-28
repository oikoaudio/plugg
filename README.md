# Plugg

**Windows audio plug-ins in your Linux DAW.**

Install a plug-in with the vendor's own Windows installer, and it shows up in your DAW as a native VST3. Each vendor gets its own Windows environment, so one vendor's setup can't break another's. Licensing works the way the vendor intended, iLok included.

> **Developer preview.** It works on the maintainer's machine (CachyOS, Hyprland, Bitwig) with a small set of tested vendors. Plugg is not affiliated with Valve, Bitwig or any plug-in vendor.

## What it does

- **Takes an installer or a VST3.** Drop in an EXE, an MSI, or a Windows VST3 file or bundle. Plugg installs it in the background into a private Windows environment and keeps the installer next to it.
- **Runs the vendor's own manager.** Plugg installs, opens and watches Native Access, UA Connect, Softube Central or a vendor's helper app, and refreshes the library when you close it.
- **Publishes native VST3s.** Plugg publishes what it finds where your DAW looks, with the plug-ins' original class IDs, so saved projects find them again.
- **Uses recipes that are data, not scripts.** You can read off a shared recipe what it can do, and where it lives caps what it may declare.
- **Protects what holds licences.** An environment with activations refuses operations that could cost you a seat, unless you acknowledge them explicitly.
- **Shows the disk cost.** You see each environment's size and what takes the space. Deleting one needs a typed confirmation.

## Install

You need:

- Python 3.12 or newer, GTK 4.10 or newer, and PyGObject
- Wine (for `winegcc`), Meson, Ninja, a C++20 compiler and Git, to build the bridge
- libxcb, D-Bus, zstd, libarchive (`bsdtar`), bubblewrap and xdg-utils
- Go, only if you want Native Access (it builds a small PowerShell forwarder)

Then build the bridge and start the app from the checkout:

```sh
git clone https://github.com/oikoaudio/plugg.git
cd plugg
scripts/build-bridge.sh
python3 scripts/build-powershell-forwarder.py    # optional, needs Go
bin/plugg gui
```

The bridge build fetches the pinned yabridge source, applies Plugg's patches and takes a few minutes. Plugg downloads the Proton runtime the first time it needs it and checks it by hash.

On Arch-based systems (Arch, CachyOS, EndeavourOS and others), the package does all of that and puts `plugg` on your path:

```sh
cd plugg/packaging/aur/plugg-git
makepkg -si
```

Drop in an EXE, MSI or Windows VST3. Leave any BIN files next to an EXE, and Plugg copies them too. Then point your DAW at `~/.vst3/plugg`, where each plug-in appears as a bundle named after itself.

[The compatibility notes](docs/compatibility/) say, vendor by vendor, what has been tested. "The DAW found it" and "it actually worked" are different claims, and the notes say which one they make.

## iLok plug-ins

iLok-licensed plug-ins share one Windows environment with PACE License Support, and iLok sees it as one computer. PACE needs two Wine fixes, which the `plugg-1` runtime carries:

```sh
plugg runtime assemble plugg-1
plugg runtime select plugg-1
plugg ilok create PACE.msi
```

[iLok and PACE](docs/recipes/pace.md) covers adding vendors and activating. [The runtime page](docs/runtime.md) explains what `plugg-1` changes and how to rebuild it from source yourself.

## Recipes

A recipe is a TOML file that describes how a vendor gets installed: the runtime, the graphics settings, the Microsoft components, the installer arguments. It is data, never a script, so you can work out what it does instead of trusting it. Before you use one you didn't write:

```sh
plugg recipe explain ./downloaded-recipe.toml
```

That prints what the recipe can do in plain language, every download URL and hash, the exact arguments any installer would get, and anything worth a second look. Where a recipe lives caps what it may declare. An unreviewed recipe can't ask to run a vendor installer at all, and CI refuses anything over the ceiling. If you'd rather not trust anyone's finished recipe, `recipe components` lists the reviewed parts, each with the problem it solves, and you can assemble your own.

The app shows the same report before you add a recipe, under **Recipes & fixes**. The person most likely to open a file someone posted is the one least likely to be at a terminal.

See [recipe trust](docs/recipe-trust.md) for the model, [getting started](docs/recipes/getting-started.md) to write a recipe, and [CONTRIBUTING](CONTRIBUTING.md) for how to share what works.

## Protecting activated environments

An environment that holds activations is not disposable. Record what it holds, and Plugg refuses the operations that could cost you a seat:

```sh
plugg licensing protect --environment <path> \
  --product "SpaceBlender:deactivate-first" --product "ExampleSynth:limited-activations:3"
```

A machine-bound licence such as iLok survives a change only if you deactivate first. Some serial-limited activations can't be recovered at all. After you protect an environment, an identity-changing operation needs an explicit acknowledgement that expires, and Plugg can take a small recovery point first. Plugg records no serial numbers or credentials, and stores identity values only as hashes. See [licensing safety](docs/licensing-safety.md).

Environments are not security sandboxes. They're not disposable either. Never run generic cleanup such as `git clean -fdx` in a checkout you've used, because ignored directories hold live vendor installations and authorisation data.

## Known issues

- On Wayland, some installers show a large black window on top of the install dialog.
- Preparing UA Connect's archive tools fails with "Network is unreachable" when the MSYS2 redirector sends Plugg to a mirror it can't reach.
- Plugg can't express winetricks, DLL overrides, registry tweaks or launch arguments in a recipe yet.

## More

- [Roadmap](ROADMAP.md): what works, what's next, what Plugg doesn't claim
- [Why a dedicated manager](docs/why.md), and how it differs from Bottles
- [Disk space](docs/storage.md): how much, and where it goes
- [Building](docs/building.md): build options, tests and what your DAW sees
- [Recipe trust](docs/recipe-trust.md) and [licensing safety](docs/licensing-safety.md)
- [Troubleshooting](docs/deployment-troubleshooting.md) and [all documentation](docs/)

New code is GPL-3.0-or-later, see [LICENSE](LICENSE). Upstream sources keep their own licences, see [third-party notes](docs/third-party.md).

## About the name

*Plugg* is Swedish for a wall plug, the thing you put screws into.
