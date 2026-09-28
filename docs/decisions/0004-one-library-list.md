# One library list instead of four tabs (sketch)

Proposed in September 2026, on the `gui-vendor-list` branch. Not decided.

## Problem

The window showed the library through four tabs, one for each kind of record the code keeps: plug-ins, helpers, recipes and environments. People think in vendors. One vendor's plug-ins, its helper app, and its size and licence handling sat on three different tabs. Leftover environments were visible only on the Environments tab, which someone had to think of opening.

## The sketch

`plugg/library_view.py` draws the library as one list, ordered by how often each thing is used:

1. **Needs you.** Only what blocks you or puts an activation at risk: a protected environment whose machine identity has drifted. Usually this section is absent.
2. **Vendors.** One row per vendor, by name, with its plug-in count, its size, and its own app as the button (Open Kilohearts Installer, Open Native Access). A shared iLok environment becomes an iLok row, which owns the size and settings, and one row per vendor in it, each with its own app. A helper's status, such as plug-ins waiting for activation, is a quiet line on its row. Opening a row lists its plug-ins.
3. **Cleanup.** A folded line under the vendors: orphaned, archived or dangling environments, unused runtimes, nested libraries, and space in the library folder that none of its parts explains, with what deleting them would free.
4. **The whole folder**, added up by part in the footer.

Every environment is a vendor row or a cleanup line, so nothing takes room unseen.

Rare actions sit behind a settings (cogwheel) button on each environment's row: show folder, rename, troubleshoot, licence handling, force close, and delete last, with the licence note right above Delete, the one place it is a warning and not a call to action. Runtime, ID and path are the menu's header, not the row's.

The view calls the manager's existing actions, so deletion still needs the typed confirmation and passes the licensing guard. Recipes open from "Recipes & fixes" in the top bar and from "Troubleshoot…" in the settings menu. The older tabs are still there, behind the grid button at the left of the title bar, for comparison.

## Looking at it without a screen

```sh
python3 -m plugg.library_view --demo                       # sample data, no library
python3 -m plugg.library_view --demo --library ~/.local/share/plugg   # a real library, read-only
python3 -m plugg.library_view --demo --snapshot out.png --light --search tape
PLUGG_UI_SMOKE=1 PLUGG_UI_SNAPSHOT=app.png bin/plugg --data <test library> gui
```

Run either on a headless weston (`weston --backend=headless --socket=x`, then `WAYLAND_DISPLAY=x`) to keep it off your desktop.

## Open before this could replace the tabs

- **Guided troubleshooting.** "Troubleshoot…" only opens the fix catalogue. The useful version starts from a symptom ("the editor is black", "it crashes on load", "the installer stops"). It suggests the fixes whose recipe says they solve it, tries one on a copy of the environment, and keeps it only if the plug-in then works. It must refuse to experiment on a protected environment, following `docs/licensing-safety.md`.
- **Unidentified plug-ins.** A vendor comes from a published plug-in's own VST3 metadata, or, for a plug-in installed but not published (an iLok plug-in before activation, say), from the Windows version resource in its file (`plugg/pe_version.py`, read without running it). A file with neither is listed under "Not identified yet" rather than guessed; in one real library that was two of 58, a UA and a Softube plug-in whose modules carry no version resource.
- **Failed installs** still appear in the activity strip above the list. They should link to the same troubleshooting.
- **Survey cost.** The view runs `environments.survey`, which reads a licensing record and a registry hive per environment, whenever the library changes. That is fine for tens of environments. Measure it on a large library.
- **Retiring the old tabs.** They go once the list covers everything they do. The plug-in list's per-plug-in details (what the DAW sees, the saved installer) still exist only on the old Plug-ins tab.
