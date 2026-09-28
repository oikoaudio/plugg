# One library list instead of four tabs (sketch)

Proposed in September 2026, on the `gui-vendor-list` branch. Not decided.

## Problem

The window showed the library through four tabs, one for each kind of record the code keeps: plug-ins, helpers, recipes and environments. People think in vendors. One vendor's plug-ins, its helper app, and its size and licence handling sat on three different tabs. Leftover environments were visible only on the Environments tab, which someone had to think of opening.

## The sketch

`plugg/library_view.py` draws the library as one list, in three parts:

1. **Needs attention.** Environments that take room with nothing to show for it: orphaned, archived, dangling, or publishing nothing and with no helper. Also unused runtimes, nested libraries, and any entry of the library folder over 256 MB that none of its known parts explains. Each has its size and its action. An environment that is protected, or whose licensing note cannot be read, is never listed here.
2. **Vendors.** One row per environment, named after the vendor, largest first. Each row shows its plug-in count, runtime, short ID, size and licence chip, a thin bar with its share of the largest environment, and the vendor's own app as the main button. Opening a row shows its plug-ins and its actions: other helpers, licence handling, rename, troubleshoot, show folder, delete.
3. **The whole folder.** The footer adds up the library folder by part, so any space the rows do not explain shows up.

Every environment is a vendor row or an attention line. There is no third place for one to be. Search matches vendors and plug-in names, and opens the rows it matched.

The view calls the manager's existing actions, so deletion still needs the typed confirmation and passes the licensing guard. Nothing in the view deletes, stops or opens anything by itself.

Recipes are no longer a destination. "Recipes & fixes" in the top bar opens the catalogue, and "Troubleshoot…" on a row opens it filtered to reusable fixes. That is the moment someone needs them: a new plug-in that does not work at first.

The older tabs are still there, behind the grid button at the left of the title bar, so the two designs can be compared.

## Looking at it without a screen

```sh
python3 -m plugg.library_view --demo                       # sample data, no library
python3 -m plugg.library_view --demo --snapshot out.png --light --search tape
PLUGG_UI_SMOKE=1 PLUGG_UI_SNAPSHOT=app.png bin/plugg --data <test library> gui
```

Run either on a headless weston (`weston --backend=headless --socket=x`, then `WAYLAND_DISPLAY=x`) to keep it off your desktop.

## Open before this could replace the tabs

- **Guided troubleshooting.** "Troubleshoot…" only opens the fix catalogue. The useful version starts from a symptom ("the editor is black", "it crashes on load", "the installer stops"). It suggests the fixes whose recipe says they solve it, tries one on a copy of the environment, and keeps it only if the plug-in then works. It must refuse to experiment on a protected environment, following `docs/licensing-safety.md`.
- **Failed installs** still appear in the activity strip above the list. They should link to the same troubleshooting.
- **Survey cost.** The view runs `environments.survey`, which reads a licensing record and a registry hive per environment, whenever the library changes. That is fine for tens of environments. Measure it on a large library.
- **Retiring the old tabs.** They go once the list covers everything they do. The plug-in list's per-plug-in details (what the DAW sees, the saved installer) still exist only on the old Plug-ins tab.
