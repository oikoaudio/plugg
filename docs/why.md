# Why a dedicated plug-in manager

The aim is a working Windows plug-in setup that musicians can repeat without managing Wine versions, prefixes, dependencies or bridge synchronization. A tested vendor recipe puts installation, the vendor's authorization helper, runtime settings and DAW discovery into one workflow. Proton supplies the Windows runtime. yabridge still handles the plug-in interface between Linux and Windows.

## Prior art

[Bottles](https://usebottles.com/) already provides separate Wine environments, and [yabridge-bottles-wineloader](https://github.com/microfortnight/yabridge-bottles-wineloader) connects yabridge to a bottle's selected runner. That is a good option for people who want to configure their own environments. Its documented workflow is to create a bottle, install the plug-ins, add the plug-in directory to yabridge and synchronize.

Plugg uses the same idea of separate environments and adds the audio-specific integration around it:

- A recognized installer selects a tested recipe and its verified runtime dependencies, so the person installing does not have to choose.
- A recipe carries the extraction tools, graphics settings and helper-window handling that a particular vendor turned out to need.
- Closing the vendor's helper triggers discovery and publication to the DAW's plug-in folder.
- One library holds the vendor controls, the saved installers and the installed plug-in metadata.
- Plugg records and protects environments that hold activations, because a rebuild can cost a licence seat.

## What this is not

Separate environments are not unique to this project, and they are **not security sandboxes**. Bottles is a broader general-purpose environment manager. Plugg is a small set of tested installation paths plus some local compatibility experiments.

The Bottles loader script runs the selected runner's Wine executable, and that can be the Wine inside a Proton distribution. Plugg's recipes also manage Proton startup and the graphics settings of a persistent plug-in session. That is a difference in integration. It is not evidence that Proton is faster or more compatible than a well-configured Bottles setup.

Packaging, guarded updates and recovery still need work. The goal is less setup and maintenance for Windows audio plug-ins in a Linux DAW. Plugg does not try to replace a general Wine manager.
