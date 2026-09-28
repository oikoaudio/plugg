# Vendor Helper workflow

This page describes how Plugg works with a vendor's own manager application, the "Helper". Klevgrand Helper is the reference case. For setting up a new vendor environment from an installer, see [the recipe guide](recipes/getting-started.md#exact-installer-helper-recipes).

## Helpers without a recipe

Some installers are their vendor's manager and install themselves into the environment, Kilohearts Installer for one. When an installer Plugg has no recipe for leaves a program with the installer's own name, Plugg gives it a helper card straight away. Otherwise, the vendor's row offers the program it found, or **Use as helper…** in the row's settings (the cogwheel) lists the programs the installer left and lets you pick one. From the command line, `plugg environment helpers <id>` lists them and `plugg environment use-helper <id> "Name" --program <path>` picks one. Environments made on the old plain Wine setup can't get a helper; install the product again first.

## Controls

The Vendors section has **Open Helper**, **Refresh library** and **Saved installer**. Saved installer opens the retained installation-set folder. It does not rerun the installer or download an update. Vendor status updates while the manager is open. A detached worker keeps running after you close the manager window. The vendor's saved installer appears only on its vendor card, not as a separate Installers entry.

## Installing products

Close this vendor's plug-in instances before opening Helper. The worker checks for active Windows applications in the same prefix and runs Helper and rescan operations one at a time. Keep plug-ins closed while Helper is installing. The check only happens at the start. It does not stop a DAW from starting another instance afterwards.

Install products in Helper, then close it. The worker waits for the remaining Windows applications to exit and for the installed files to stay unchanged for five seconds. It then scans the new modules one by one and publishes new VST3s. If installation has not settled after ten minutes, the worker gives up, shows a status that says what to do, and leaves a manual **Refresh library** action. Waiting for stable files is a heuristic. It is not a transaction, and it cannot catch vendor background work that starts much later. Plugg discards Helper's stdout and stderr, because vendor output can include authenticated URLs.

## What is scanned and published

Plugg scans only `drive_c/Program Files/Common Files/VST3`. It skips VST2, AAX and the copies in Helper's download cache. Discovery handles flat VST3 modules and modules inside VST3 bundles. It does not follow symlinked files or directories. It reports unsupported 32-bit modules.

Plugg matches existing publications by their resolved Windows module path and hash. An existing publication keeps its class ID and is not duplicated. Plugg does not reload unchanged modules. A new module must pass discovery and a post-probe hash check before Plugg publishes it. Plugg reports a changed installed version for your attention instead of republishing it. That does not undo changes a vendor updater has already made. Managed update rollback does not exist yet. Plugg does not unpublish removed products automatically.

For a configured vendor environment, **Check again** runs this refresh workflow instead of the generic installer rescan.

## Window placement on Hyprland

On Hyprland, the launch worker enables a named, temporary window rule **before** it starts Helper. The rule matches the exact Helper title and the `steam_proton` window class. It makes the window floating and non-fullscreen and turns off remembered size. The worker disables the rule when Helper exits and edits no persistent configuration. While the rule is enabled, it applies to any window with that title and class.

After launch, a fallback check looks for new Helper windows that belong to this vendor prefix, matching title, window class and PID. It floats each one once. It does not resize the window, move workspaces, change persistent rules or undo placement changes you make later. Plugg leaves other desktops alone. If a compositor command fails, Helper keeps running and Plugg shows a hint to float it by hand. If the compositor rejects the pre-launch rule, Plugg does not launch Helper.

Floating before the window first appears matters. Floating a window that was already tiled did not reliably make Helper usable. With the pre-launch rule, Klevgrand Helper opens floating at its natural size of 820 × 600. The rule syntax is in the [Hyprland window rules documentation](https://wiki.hypr.land/Configuring/Basics/Window-Rules/).

## Helper uses the full Proton launch

Started through the managed `runinprefix` session that plug-ins use, Klevgrand Helper stays on an unresponsive loading screen. With the same installation, account and prefix, it works through a full UMU/Proton launch. Nobody has isolated the lower-level difference, so do not call this a layout bug or a graphics bug.

Klevgrand's configuration therefore sets `helper_owns_runtime`. Before opening Helper, the worker makes sure no vendor applications are active. It then finds the idle managed session through its private socket and stops only that session, holding the startup lock. If the runtime is unknown or busy, the worker refuses. Helper runs through the full launcher, and DAW plug-ins keep the persistent session. After Helper exits, discovery waits for Helper's runtime processes to finish before it probes any plug-ins. Login, installation and authorization work as before.

## Validation

Automated tests cover:

- a fake Helper that installs a product, followed by automatic publication,
- Helper failure,
- cache exclusion,
- keeping existing publications,
- refusing to launch while vendor plug-ins are active,
- rejecting modules that change,
- window targeting and floating each window only once,
- setting up the pre-launch rule and cleaning it up after an exception,
- refusing maintenance when a session cannot be stopped safely.

On the maintainer's system (Bitwig, Hyprland/XWayland), a real Klevgrand refresh found the existing publications unchanged and created no duplicates. Helper interaction through the full launch was checked by hand. A complete new product installation through the automated handoff has not been checked separately yet.
