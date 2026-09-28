# One library list instead of four tabs (sketch)

Decided in September 2026. The four tabs are gone; the library is this list, and the recipe catalogue is a page behind **Recipes & fixes**.

## Problem

The window showed the library through four tabs, one for each kind of record the code keeps: plug-ins, helpers, recipes and environments. People think in vendors. One vendor's plug-ins, its helper app, and its size and licence handling sat on three different tabs. Leftover environments were visible only on the Environments tab, which someone had to think of opening.

## The sketch

`plugg/library_view.py` draws the library as one list, ordered by how often each thing is used:

1. **Needs you.** Only what blocks you or puts an activation at risk: a protected environment whose machine identity has drifted. Usually this section is absent.
2. **Vendors.** One row per vendor, by name, with a status dot (green: in your DAW; amber: something waiting for you, with the button that does it on the row; blue: its app is running), with its plug-in count, its size, and its own app as the button (Open Kilohearts Installer, Open Native Access). A shared iLok environment becomes an iLok row, which owns the size and settings, and one row per vendor in it, each with its own app. A helper's status, such as plug-ins waiting for activation, is a quiet line on its row. Opening a row lists its plug-ins.
3. **Cleanup.** A folded line under the vendors: orphaned, archived or dangling environments, unused runtimes, nested libraries, and space in the library folder that none of its parts explains, with what deleting them would free.
4. **The whole folder**, added up by part in the footer.

Every environment is a vendor row or a cleanup line, so nothing takes room unseen.

Rare actions sit behind a settings (cogwheel) button on each environment's row: show folder, rename, troubleshoot, licence handling, force close, and delete last, with the licence note right above Delete, the one place it is a warning and not a call to action. Runtime, ID and path are the menu's header, not the row's.

The view calls the manager's existing actions, so deletion still needs the typed confirmation and passes the licensing guard. Recipes open from "Recipes & fixes" in the top bar and from "Troubleshoot…" in the settings menu. Everything the old tabs did has a place here: each plug-in's details (what the DAW sees, where it came from, its version and status) open from its name in the row, and a helper's less frequent actions (refresh library, Native Access sign-in, installer files, choosing a helper) are in the row's settings.

## Keyboard and accessibility

The list works without a mouse. Up and Down move between rows, and Enter or Space shows a row's plug-ins. Tab moves into a row's buttons, and Enter runs one. The Menu key or Shift+F10 opens a row's settings, where Up and Down move and Escape closes. Typing anywhere starts a search. Ctrl+F goes to the search box, Down goes from there to the results, and Escape clears it. Ctrl+O adds a file. A solid ring marks the row the keyboard is on.

GTK exposes the interface to screen readers such as Orca through AT-SPI. Each row has a spoken summary ("Klevgrand, 4 plug-ins, 921.6 MB") and says whether it is expanded. Icon buttons are named ("Settings for Klevgrand"), and app buttons say whose they are ("Open manager for Klevgrand"). The size bars are hidden from screen readers as decoration. Text sizes are relative, so the desktop's text-size setting scales the window, and a `prefers-contrast: more` block turns muted text full strength and thickens the focus ring.

`PLUGG_TEXT_SCALE=1.5` and `PLUGG_HIGH_CONTRAST=1` set those desktop settings for the preview. `scripts/test-ui.py` checks row activation, the spoken labels and the expanded state.

## Looking at it without a screen

```sh
python3 -m plugg.library_view --demo                       # sample data, no library
python3 -m plugg.library_view --demo --library ~/.local/share/plugg   # a real library, read-only
python3 -m plugg.library_view --demo --snapshot out.png --light --search tape
PLUGG_UI_SMOKE=1 PLUGG_UI_SNAPSHOT=app.png bin/plugg --data <test library> gui
```

Run either on a headless weston (`weston --backend=headless --socket=x`, then `WAYLAND_DISPLAY=x`) to keep it off your desktop.

## Still open

- **Guided troubleshooting.** "Troubleshoot…" opens the fix catalogue. The useful version starts from a symptom ("the editor is black", "it crashes on load", "the installer stops"). It suggests the fixes whose recipe says they solve it, tries one on a copy of the environment, and keeps it only if the plug-in then works. It must refuse to experiment on a protected environment, following `docs/licensing-safety.md`.
- **What happened after a check.** A row cannot yet say "still not loading after activation", because Plugg does not record when it last checked each plug-in.
- **Survey cost.** The view runs `environments.survey`, which reads a licensing record and a registry hive per environment, whenever the library changes. That is fine for tens of environments. Measure it on a large library.
- **Vendor icons.** Each helper app carries its vendor's icon in its own resources, next to the version information Plugg already reads.
