# Standalone Windows VST3 import

Drop a `.vst3` file or bundle onto the app. The file chooser also accepts VST3 files, but bundles need drag-and-drop. The CLI `install` command accepts the same inputs. Plugg copies the plug-in into managed storage, prepares a private Proton prefix, probes its VST3 classes and publishes it to the normal DAW folder. You do not need an EXE installer.

## Recognized plug-ins

The catalogue recognizes these Variety of Sound plug-ins by the exact hash of their Windows module. For each one, Plugg installs the Microsoft Visual C++ runtime it needs.

| Plug-in | Runtime |
| --- | --- |
| FerricTDS mkIII | Visual C++ 2022 x64 |
| epicVerb mkII | Visual C++ 2022 x64 |
| epicPLATE mkII | Visual C++ 2013 x64 |
| ThrillseekerXTC mkIII | Visual C++ 2013 x64 |

These requirements match the DLLs the modules import and the vendor's [requirements by release date](https://varietyofsound.wordpress.com/downloads/). Plugg downloads the runtime from a pinned Microsoft URL and checks its checksum. This project distributes no vendor plug-in binaries. The TOML catalogue defines the recognized modules. To add others, see [the recipe guide](recipes/getting-started.md#adding-a-direct-vst3-import).

The FerricTDS mkIII download is typical. It holds a Windows x64 VST3, a sibling DLL and two text documents. Plugg imports the VST3 and both documents. It leaves the sibling DLL and the original download alone.

Unknown standalone VST3s get the base Proton setup. Plugg does not work out every plug-in's dependencies, and it does not promise compatibility.

## Input rules

- A bundle must contain one x64 Windows VST3 module under `Contents/x86_64-win`. Plugg keeps its resource tree.
- Plugg does not yet handle loose plug-ins that need sibling DLLs or separate content folders.
- Imports reject links and special files. The payload is capped at 2 GiB and 10,000 files. Plugg verifies the saved inventory before installation.
- Each adjacent text file is limited to 8 MiB.
- Publication still checks class IDs for duplicates.

## Environments

Direct imports appear under Added files, next to installer jobs. A recognized import reuses a vendor environment only if its recorded dependencies already meet the requirement, its Proton path matches and its graphics setup checks out. Extra installed dependencies do not prevent reuse. An unknown module, or a requirement the environment does not meet yet, gets a separate prefix. Plugg never upgrades an existing environment to fit a new import. When it reuses an environment, it runs no dependency installer and no prefix initialization.

Plugg selects and imports one plug-in at a time. Active vendor applications prevent reuse. This check only happens at the start. It does not stop you from launching a DAW afterwards.

Each import job keeps its own identity and saved payload. The publication records the environment the jobs share. A rescan probes only the selected import. Plugg stores accompanying documents in per-job directories, so one product's readme or licence never overwrites another's. Environments share runtime files, but not a writable Windows base layer. Keep a shared runtime while any environment uses it. There is no general runtime cleanup policy yet.

Visual C++ runtime generations can coexist. One environment can hold both 2013 and 2022 and serve all four plug-ins above, so different requirements do not by themselves mean incompatibility. Combining existing environments this way is a manual job for now, and you should take a snapshot first. The automatic import policy only reuses environments whose dependencies are already met. It never installs an extra runtime into an existing environment. A managed dependency-update workflow is future work.

## Validation

Synthetic tests cover file and bundle import, kept resources and text files, exclusion of sibling DLLs, changed payloads, external links and worker routing. On the maintainer's system, all four plug-ins above passed native factory discovery and were published from one shared environment. Factory discovery and publication do not replace audio, editor, preset and project-recall checks in a DAW.
