"""What the Help window says: questions people ask, and what has been tested.

Answers describe what the app does now, in the words it uses on screen. The
vendor notes are also what an installer is matched against when it is added
(known_fixes), so update them after real testing, not before.

SPDX-License-Identifier: GPL-3.0-or-later
"""

FAQ = (
    ("Getting started", (
        ("What does Plugg do?",
         "It puts Windows audio plug-ins in your Linux DAW. You add a vendor's installer or a Windows "
         "VST3 file. Plugg installs it into a private Windows environment for that vendor, and puts a "
         "small adapter for each plug-in in ~/.vst3/plugg. Your DAW loads the adapter as an ordinary "
         "VST3, and the adapter starts the Windows plug-in and passes its audio and editor back and forth."),
        ("How do I add a plug-in?",
         "Drop the .exe, .msi or .vst3 file on the window, or press Choose file… (Ctrl+O). Keep any .bin "
         "files beside the .exe. If the vendor's own app opens, install your products there and close it: "
         "Plugg then checks for new plug-ins. Point your DAW at ~/.vst3/plugg and rescan."),
        ("What do the coloured dots mean?",
         "Green: that vendor's plug-ins are in your DAW. Amber: something is waiting for you, and the button "
         "on the same row does it, such as Activate in iLok or Check again. Blue: the vendor's app is "
         "running. No dot: nothing of its own to show, like the iLok licence manager when nothing waits."),
        ("Which DAWs work?",
         "Plugg is tested in Bitwig on Linux. A DAW that loads VST3 plug-ins from ~/.vst3 should see them, "
         "but REAPER and others have not been validated yet."),
        ("Can I use the keyboard?",
         "Yes. Up and Down move between vendors and Enter shows a vendor's plug-ins. Tab reaches a row's "
         "buttons, and the Menu key opens its settings. Start typing anywhere to search; Escape clears it."),
    )),
    ("When something does not work", (
        ("My plug-in is not in my DAW",
         "Rescan plug-ins in your DAW first. Then look at the vendor's row: an amber row has a button for "
         "what is missing. If the vendor is not listed at all, the installation did not finish; the strip "
         "at the top of the window says why. Plugg only adds plug-ins that load, so one that fails to load "
         "stays out of your DAW rather than crashing it."),
        ("An iLok plug-in is waiting for activation",
         "Press Activate in iLok (or Open iLok on the iLok row), sign in and activate your licence, then "
         "close iLok License Manager. Closing it is the signal: Plugg checks the waiting plug-ins again and "
         "adds the ones that now load."),
        ("A plug-in's editor is blank, black or flickers",
         "That is usually graphics. Open the vendor's settings (the cogwheel) and choose Troubleshoot…: "
         "Recipes & fixes lists reusable fixes, such as switching the environment between DXVK and "
         "WineD3D graphics, each with the problem it solves."),
        ("A vendor's app will not close, or its row stays busy",
         "Some managers keep running with no window. Choose Force close its apps in the vendor's settings. "
         "It ends every Windows program in that environment, a licence manager sharing it included, and "
         "refuses while your DAW is open, because the plug-ins run in the same place."),
        ("A plug-in crashes, or my DAW waits for it",
         "When a plug-in takes its Windows host down, Plugg ends the load within seconds, so your DAW sees a "
         "plug-in that failed rather than waiting forever. Try Troubleshoot…; if nothing there helps, "
         "report it."),
        ("How do I report a problem?",
         "Choose Report a bug in Plugg… below. Plugg prepares a summary of your setup, without licences, serials "
         "or account details, which you can read and edit. It then opens the issue form on GitHub for you "
         "to paste it into. Nothing is sent from the app. Check Recipes & fixes first: someone may already "
         "have solved it."),
    )),
    ("Your files and licences", (
        ("Where are my files?",
         "Everything Plugg keeps is in ~/.local/share/plugg; the bottom of the library adds it up. Your DAW "
         "scans ~/.vst3/plugg, which holds only links to the adapters."),
        ("Is it safe to delete something?",
         "Cleanup lists what nothing uses. Deleting a vendor's environment removes the Windows software in "
         "it and cannot be undone, so Plugg asks you to type a phrase first. For licensed products, "
         "deactivate them in the vendor's app or iLok before you delete: the phrase is how you confirm "
         "you did."),
        ("Where are my licences, and what goes online?",
         "Your licences stay where the vendor's own app puts them, inside that vendor's environment in "
         "~/.local/share/plugg/environments. iLok licences are managed by iLok License Manager in the iLok "
         "environment. Plugg itself keeps no serial numbers, licence files, passwords or account details. "
         "For a protected environment it records only the product names. Plugg goes online only to "
         "download its own parts (Proton, the plug-in bridge, Microsoft components), each checked by hash, "
         "and sends nothing about you or your plug-ins. The vendor's app signs in and activates on its "
         "own, as on Windows."),
        ("How do I keep my licences safe?",
         "Back up ~/.local/share/plugg with the rest of your home folder. Don't post environment folders, "
         "licensing recovery points or vendor app logs online: they can contain your machine's identifiers "
         "or account details. A bug report from Help leaves them out, and shows you everything before "
         "you send it."),
        ("Will Plugg use up my licence activations?",
         "Every environment on this computer presents the same machine identity, so vendors see one "
         "computer, not one per environment. An environment holding activations refuses anything that "
         "could cost you a seat unless you confirm it."),
        ("Is an environment a sandbox?",
         "No. Environments keep vendors' Windows setups apart so one cannot break another, but a Windows "
         "program in one can still reach your files like any other program you run."),
    )),
    ("Recipes", (
        ("What is a recipe?",
         "A recipe is a small file that says how a vendor gets installed: the runtime, graphics settings, "
         "Microsoft components and installer arguments. It is data, never a script. Recipes & fixes shows "
         "every recipe you have, says what each is allowed to do, and shows you that before adding one "
         "you did not write."),
    )),
)

#: What has been tested, by vendor, as (status, note). The status is
#: "tested", "experimental" or "known problem"; anything else is untested.
VENDORS = {
    'Klevgrand': ('tested',
                  "Skaka, Slammer, Korvpressor, Richter, DAW Cassette and REAMP work in Bitwig. Klevgrand Helper is managed by the app: install "
                  "products, then close Helper. The tested setup includes graphics and window fixes. Other "
                  "Klevgrand products are not yet verified."),
    'Variety of Sound': ('tested',
                         "FerricTDS mkIII, epicVerb mkII, epicPLATE mkII and ThrillseekerXTC mkIII work in Bitwig. "
                         "Drop the Windows .vst3 "
                         "file directly; known versions get the Visual C++ components they need. Sibling VST2 "
                         ".dll files are not imported."),
    'Native Instruments': ('experimental',
                           "Native Access 2 installs and signs in. Raum works in Bitwig. Massive and Massive X "
                           "have played in Bitwig and found their presets; project recall is not yet checked. "
                           "Reaktor 6, Reaktor 6 FX and Super 8 are found, but playback, browsing and project "
                           "recall are still being tested."),
    'Universal Audio': ('experimental',
                        "The LA-2A has worked in Bitwig in the shared iLok environment, and UA Connect can "
                        "install products. Soundtoys SpaceBlender and soothe v1 have also opened there. "
                        "Creating the iLok environment is a command-line step for now (plugg ilok create); "
                        "do not recreate the iLok environment to fix a plug-in."),
    'Plugin Alliance': ('experimental',
                        "HG-2, DSM V3, Metric AB and several bx and Shadow Hills plug-ins have worked. Some "
                        "need different graphics settings. DSM curve dragging is uneven, and Kirchhoff has "
                        "shown background flicker."),
    'Cytomic': ('known problem',
                "The Glue 1.9.3 installs, and its editor opens in Bitwig, but it cannot be authorised. "
                "The authorisation window is black and crashes the plug-in host, in every host tried "
                "and without the bridge too. No fix is known yet."),
}

UNTESTED = ("You can try any 64-bit Windows VST3. Direct imports and installers Plugg has no recipe for get a "
            "standard environment with nothing vendor-specific added. That is a starting point, not a "
            "promise that a plug-in will work.")


def vendor_note(vendor):
    """The tested note for a vendor name, matched on whole words, or None."""
    wanted = ' ' + ' '.join((vendor or '').casefold().replace(',', ' ').split()) + ' '
    for name, note in VENDORS.items():
        if ' ' + name.casefold() + ' ' in wanted or wanted.strip() and wanted.strip() == name.casefold():
            return name, note
    return None
