"""Curated preview compatibility notes; update after actual validation.
SPDX-License-Identifier: GPL-3.0-or-later
"""

SECTIONS = (
    ("What is supported?",
     "This preview manages 64-bit Windows VST3 plug-ins. These results come from "
     "testing in Bitwig on Linux with Hyprland; they are not guarantees for every "
     "product from a vendor. REAPER has not yet been separately validated."),
    ("Klevgrand — tested",
     "Skaka, Slammer, Korvpressor, Richter, DAW Cassette and REAMP have worked in "
     "our testing. Klevgrand Helper is managed by the app: install products, then "
     "close Helper to refresh the library. The tested setup includes graphics and "
     "window handling fixes. Other Klevgrand products are not yet verified."),
    ("Variety of Sound — tested",
     "FerricTDS mkIII, epicVerb mkII, epicPLATE mkII and ThrillseekerXTC mkIII "
     "have worked in testing. Drop the Windows .vst3 file directly. Known versions "
     "receive their required Visual C++ components and can share a compatible "
     "vendor environment. Sibling VST2 .dll files are not imported."),
    ("Native Instruments — experimental",
     "Native Access 2 installation and login work in the current development setup. "
     "Raum loads; Massive and Massive X work and find their presets. Reaktor 6, "
     "Reaktor 6 FX and Super 8 pass discovery, but playback, browsing and project "
     "recall are still awaiting user testing. Monark, Prism, Razor and Rounds content "
     "is installed, not yet validated. Fresh modular Native Access installation now passes "
     "with PowerShell; its login and product workflow are still being validated. "
     "Existing NI environments are not migrated."),
    ("UAD and shared iLok — experimental",
     "LA-2A has worked in Bitwig with the tested PACE setup and a Wine window-close "
     "fix. UA Connect can install products and refresh the library after closing. "
     "Soundtoys SpaceBlender and soothe v1 also opened successfully in the same "
     "persistent iLok environment. Fresh PACE setup still requires developer "
     "assistance; do not recreate this environment to fix a plug-in issue."),
    ("Plugin Alliance — experimental",
     "HG-2, DSM V3, Metric AB and several bx/Shadow Hills plug-ins have worked "
     "with a bridge editor-close fix. Some require different graphics settings. "
     "DSM curve dragging remains uneven; Kirchhoff has shown background flicker. "
     "These are product-specific observations, not support for the whole catalogue."),
    ("Other vendors and the default setup",
     "You can try an unlisted 64-bit Windows VST3. Direct imports use a managed "
     "Proton environment; known file versions receive recorded dependency recipes. "
     "Unknown versions have no extra vendor-specific components added automatically. "
     "Unrecognized EXE/MSI installers get the same Proton environment, on the "
     "selected runtime, with no vendor-specific components added. Environments "
     "made before September 2026 may still run on plain Wine 11."),
    ("Adding files",
     "Download installers from your vendor and drop the .exe, .msi or Windows .vst3 "
     "into the app. Leave any .bin companions beside the .exe in its source folder. "
     "Complete installation and licensing in the vendor's own window. Product "
     "details show the current helper or saved source file. Open or rescan your "
     "DAW after publication; discovery is not necessarily immediate."),
    ("A manager that will not finish",
     "Closing a vendor window does not always end the program behind it. Several "
     "managers keep running with no window at all. When that happens the card lists "
     "what is still running and its Open button turns orange: pressing it focuses the "
     "window if there is one, or asks the program to show itself — which some cannot "
     "do once their window has been closed rather than minimized, and the app says so "
     "instead of pretending. Force close beside it ends every Windows program in that "
     "environment — a licence manager sharing the environment goes too, since they "
     "share one Wine server — and clears the status. It refuses while a DAW is open, "
     "because those plug-ins are running in the same place."),
    ("How environments work",
     "The app manages environments for you. Compatible products can share a vendor "
     "environment and runtime files are shared to save space. Separate environments "
     "keep dependencies apart, but are not security sandboxes. A default recipe "
     "is a starting point, not a promise that most plug-ins will work. Vendor "
     "recipes will grow from tested installation and compatibility notes."),
)
