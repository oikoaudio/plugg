# Design principles

Plugg should be a small application that makes Windows plug-ins comfortable on Linux. Complexity goes where a real compatibility problem needs it and nowhere else. The user sees their plug-ins and the actions that matter. The code has clear ownership, explicit state and few moving parts.

## Engineering

- Each part has one job. The GUI presents operations. The core installs and publishes. Recipes describe a supported setup. The loader resolves and launches a plug-in. yabridge owns the bridge protocol and audio transport.
- One implementation per mechanism. Vendors share helper launch, discovery and component detection when they behave the same. Vendor exceptions stay visible and local.
- Every operation knows its environment, who depends on it and when it's finished. Closing an editor or the manager never stops a playing plug-in.
- Public identities don't move. Plug-in class IDs, publication paths, saved project state and licensing environments stay the same across refactors. A change that would create a new plug-in or a new licensing machine needs a migration.
- Setup work stays out of the audio callback: no recipe execution, downloads, logging, filesystem scans or manager round trips during processing. The bridge is cross-process and waits for processing results, so don't assume in-process guarantees carry over.
- Patches stay small. Each one has provenance, a test case and a condition for removing it. Write a shared framework only after real duplicated code shows what it needs to cover.
- Test the transitions that have broken before: helper focus and input, editor close, reopen and repaint, state recall, interrupted installs, runtime mismatches. Report what a person observed separately from what an automated check proved.

## The loader

"Loader" means the path from a published native plug-in through yabridge into its Windows environment. [The loader contract](loader-contract.md) has the details.

1. Resolve a published plug-in to an exact module, bridge, runtime and environment from a small recorded mapping. Check it at load time, outside audio processing. Never search every prefix.
2. Start the session through the same launch code the app uses. Keep helper window handling separate from the plug-in path.
3. Report ready only after the bridge handshake succeeds. A process that started is not proof of a usable plug-in.
4. Clean up only processes Plugg owns, keep the DAW's state, and give an error the user can act on when a runtime is missing or a worker dies. Don't promise crash recovery that hasn't been built and tested.
5. The manager is optional while the DAW runs. Don't add an always-running daemon unless something needs one, and document its lifetime if you do.

## Interface

The visual language follows OikoAudio. Components use named colour roles from one local theme, never colour literals.

| Role | Dark | Light |
| --- | --- | --- |
| Page | `#171817` | `#E8E8E5` |
| Panel | `#202220` | `#F6F6F2` |
| Text | `#EEEEE8` | `#161715` |
| Secondary text | `#A7AAA1` | `#4A4D46` |
| Border | `#3A3D38` | `#AEB3AA` |
| Field | `#171817` | `#D7D9D3` |
| Track and hover | `#30332F` | `#C5C9C0` |
| Orange accent | `#FFAD5C` | `#A63D05` |
| Blue accent | `#5BAACF` | `#123797` |
| Warning and error | `#EB5B46` | `#B02A20` |

- Ubuntu Regular, with its licence kept alongside. Four type sizes to start with: 11, 14, 18 and 20 points. Don't shrink text to make something fit.
- Orange for the main action, blue for selection and navigation. Errors get text and an icon, not colour alone. Check contrast on real controls in both themes.
- Aligned edges, restrained borders, consistent spacing, modest corner radii. Be generous with space in a desktop window.
- Design for a roomy desktop window first, and keep it usable when narrow.
- The toolbar has Add plug-in, search and vendor filter, and Help. Dropping a file is a first-class way in, with a clear result.
- The library groups plug-ins by vendor, collapsed at first, and keeps the user's expanded groups across refreshes.
- Vendor managers get their own section and are named by the application ("Native Access"), not the installer.
- iLok is a shared licensing capability with its own action. It is not a Universal Audio feature.
- Pending and failed attempts stay out of the library. Errors explain briefly and offer the relevant action. Technical detail is available on request.
- Progress shows only while something is running and names what it's doing. "Waiting for you in the vendor window" looks different from installing or scanning.

Check narrow and wide layouts, long names, keyboard focus, file drop, both themes and fractional scaling. On Hyprland, also check tiled and floating windows and helper focus. Prefer small visual passes over rewrites.
