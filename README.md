# Plugg

**Windows audio plug-ins in your Linux DAW.**

Install a plug-in with the vendor's own Windows installer, and it shows up in your DAW as a native VST3. Each vendor gets its own Windows environment, so one vendor's setup can't break another's. Plug-ins keep their vendor's licensing, iLok included.

> **Developer preview.** It works on the maintainer's machine (CachyOS, Hyprland, Bitwig) with a small set of tested vendors. Plugg is not affiliated with Valve, Bitwig or any plug-in vendor.

## What it does

- **Takes an installer or a VST3.** Drop in an EXE, an MSI, or a Windows VST3 file or bundle. Plugg installs it in the background into a private Windows environment and keeps the installer next to it.
- **Runs the vendor's own manager.** Plugg installs, opens and watches Native Access, UA Connect, Softube Central or a vendor's helper app, and refreshes the library when you close it.
- **Publishes native VST3s.** Plugg publishes what it finds where your DAW looks, with the plug-ins' original class IDs, so saved projects find them again.
- **Uses recipes that are data, not scripts.** You can read what a shared recipe can do before you use it, and its location limits what it may declare.
- **Protects what holds licences.** An environment with activations refuses operations that could cost you a seat, unless you acknowledge them explicitly.
- **Shows the disk cost.** You see each environment's size and what takes the space. Deleting one needs a typed confirmation.

## Install

There is no packaged release yet. The first one, v0.1.0, will have packages for Ubuntu and Debian (.deb), Fedora (.rpm) and Arch (AUR). [Watch the releases](https://github.com/oikoaudio/plugg/releases) to hear when it's out.

Until then, on Arch and Arch-based systems (CachyOS, EndeavourOS and others), build the package from source:

```sh
git clone https://github.com/oikoaudio/plugg.git
cd plugg/packaging/aur/plugg-git
makepkg -si
plugg gui
```

The build takes a few minutes, because it compiles the plug-in bridge from pinned sources. On other distributions, [build from a checkout](docs/building.md#build-from-a-checkout). Plugg downloads its Proton runtime the first time it needs it and checks it by hash.

Drop in an EXE, MSI or Windows VST3. Leave any BIN files next to an EXE, and Plugg copies them too. Then point your DAW at `~/.vst3/plugg`, where each plug-in appears as a bundle named after itself.

[The compatibility notes](docs/compatibility/) say, vendor by vendor, what has been tested. For each plug-in they say whether the DAW only found it, or whether it was also played and reloaded.

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

That prints what the recipe can do in plain language, every download URL and hash, the exact arguments any installer would get, and anything worth a second look. A recipe's location limits what it may declare. An unreviewed recipe can't ask to run a vendor installer at all, and CI refuses anything over that limit. If you'd rather not trust anyone's finished recipe, `recipe components` lists the reviewed parts, each with the problem it solves, and you can assemble your own.

The app shows the same report before you add a recipe, under **Recipes & fixes**, for people who don't use a terminal.

See [recipe trust](docs/recipe-trust.md) for the model, [getting started](docs/recipes/getting-started.md) to write a recipe, and [CONTRIBUTING](CONTRIBUTING.md) for how to share what works.

## Protecting activated environments

An environment that holds activations is not disposable. Record what it holds, and Plugg refuses the operations that could cost you a seat:

```sh
plugg licensing protect --environment <path> \
  --product "SpaceBlender:deactivate-first" --product "ExampleSynth:limited-activations:3"
```

A machine-bound licence such as iLok survives a change only if you deactivate first. Some serial-limited activations can't be recovered at all. After you protect an environment, an identity-changing operation needs an explicit acknowledgement that expires, and Plugg can take a small recovery point first. Plugg records no serial numbers or credentials, and stores identity values only as hashes. See [licensing safety](docs/licensing-safety.md).

Environments are not security sandboxes, and they are not disposable. Never run generic cleanup such as `git clean -fdx` in a checkout you've used, because ignored directories hold live vendor installations and authorisation data.

## Your licences stay on your computer

Licences live where the vendor's own app puts them, inside that vendor's Windows environment under `~/.local/share/plugg/environments/`. iLok licences are managed by iLok License Manager in the shared iLok environment. Plugg itself keeps no serial numbers, licence files, passwords or account details. For a protected environment it records the product names and hashed identity values, nothing more ([licensing safety](docs/licensing-safety.md)).

Plugg goes online only to download its own parts: Proton, its Wine modules, the plug-in bridge and Microsoft components. It fetches them from a fixed list of sites and checks each one by hash. It sends nothing about you or your plug-ins anywhere. The vendor's app signs in and activates on its own, as it would on Windows. A bug report opens GitHub's form in your browser, filled with a summary you can read and edit first, and nothing leaves your computer unless you submit it.

To keep your licences safe:

- Back up `~/.local/share/plugg` along with the rest of your home folder.
- Don't post environment folders, licensing recovery points (`licensing-backups`) or vendor app logs online. They can contain your machine's identifiers or account details.

## Known issues

- On Wayland, some installers show a large black window on top of the install dialog.
- Preparing UA Connect's archive tools fails with "Network is unreachable" when the MSYS2 redirector sends Plugg to a mirror it can't reach.
- A recipe can choose the graphics backend and require Plugg's own pinned components, but can't yet set DLL overrides, registry values or launch arguments, or use winetricks verbs. [The plan](docs/decisions/0005-prefix-settings-in-recipes.md) adds them in typed form after v0.1.0.

## More

- [Roadmap](ROADMAP.md): what's done and what's planned
- [Why a dedicated manager](docs/why.md), and how it differs from Bottles
- [Disk space](docs/storage.md): how much, and where it goes
- [Building](docs/building.md): build options, tests and what your DAW sees
- [Recipe trust](docs/recipe-trust.md) and [licensing safety](docs/licensing-safety.md)
- [Troubleshooting](docs/deployment-troubleshooting.md) and [all documentation](docs/)

New code is GPL-3.0-or-later, see [LICENSE](LICENSE). Upstream sources keep their own licences, see [third-party notes](docs/third-party.md).

## About the name

*Plugg* is Swedish for a wall plug, the thing you put screws into.
