# Typed prefix settings in recipes

Decided in September 2026, not built yet. It comes after v0.1.0.

## The gap

Many Windows plug-ins run under Wine only with a setting inside their environment: a native `d2d1`, the core fonts, a DPI value, a virtual desktop, or a flag for the vendor's app. Cabinet's catalogue records such settings per product, and Plugg shows them as hints ("ran in another project with ..., not tested here"). A Plugg recipe can't apply them yet. It can choose DXVK or WineD3D per plug-in and require typed components (Visual C++ runtimes, PowerShell, archive tools, the NTK service, a helper app entry point, bridge patches), and nothing more. So when someone finds the setting that makes a plug-in work, the next person can't get it from a recipe, and passing a fix on is what recipes are for.

Fixes to Wine's own code go into a new runtime (`plugg-1`, `plugg-2`), and that doesn't change. The settings here belong to one environment, and a runtime can't carry them.

## Why not free-form

Plugg keeps two rules that free-form settings would break:

- **Everything is pinned by hash.** winetricks downloads from many hosts without pinned hashes, and some of its verbs change the whole prefix.
- **Nothing may quietly change a licensed environment.** An arbitrary registry key or DLL override in an environment that holds iLok or vendor activations can break it, and some activations can't be recovered ([licensing safety](../licensing-safety.md)).

A free-form field also can't be reviewed. A reviewer can check "sets `d2d1` to native" in a second, but not an arbitrary `.reg` file.

## The decision

Each kind of setting gets its own typed shape, a line in the recipe report and a tier ceiling ([recipe trust](../recipe-trust.md)):

| Kind | Shape | Who may declare it |
| --- | --- | --- |
| winetricks verbs | No winetricks. A verb people need often becomes a Plugg component pinned by hash, as the Visual C++ runtimes already are: `corefonts`, `d3dcompiler_47` and so on. | Any tier, once the component exists |
| DLL overrides | `{dll = "d2d1", mode = "native" \| "builtin" \| "disabled"}`, for DLL names only, never paths. Recorded in the environment, so Plugg can show it and undo it. | Community and up |
| Registry settings | Named settings with typed values (DPI, virtual desktop, Direct2D), each written by core code that knows the key. No raw keys. | Community and up for named settings. Raw keys only in the reviewed tier, if ever. |
| Launch arguments | Per helper program, from a list the core knows, shown to the user and applied only with consent, the way UA Connect's `--disable-gpu --no-sandbox` works today. | Reviewed tier |

Two rules hold for all of them:

- **Licensed environments.** Applying a setting to a protected environment goes through `licensing.guard` like any other prefix write, and needs the user's explicit confirmation. A recipe can never apply one silently to an environment that holds activations.
- **Nothing silent.** Every setting appears in `recipe report` in plain words before anything runs, and in the environment's details afterwards.

## Order of work

1. Components for the most requested winetricks verbs, starting with those Cabinet's catalogue and Plugg's leads name most.
2. DLL overrides.
3. Named registry settings, starting with DPI and the virtual desktop.
4. Launch arguments, generalised from UA Connect's flags.

Each one becomes something a recipe can declare only when it has tests, a line in the report and an undo path.
