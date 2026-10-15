# Changelog

Each release's full notes are in [packaging/release-notes](packaging/release-notes/) and on the [releases page](https://github.com/oikoaudio/plugg/releases). The [ROADMAP](ROADMAP.md) lists what works, what comes next and what this project does not claim.

## 0.2.2

- Arturia Software Center no longer crashes while it synchronizes licences. 0.2.1's workaround for Wine's UI Automation did not take effect for the Software Center.

## 0.2.1

- Arturia Software Center installs from its exact installer, and Arturia's plug-ins open and close their editors without crashing the DAW.
- Deleting an environment works in cases where it was refused or failed: while its plug-in session was idle, when it held only unlicensed products, and when its licence record could not be read.
- A plain installer that fails before it runs no longer leaves its environment behind.
- The runtime selected for new environments is never offered for reclaim.
- The docs and the delete dialog say that a lost iLok machine can be recovered, slowly, and that recovery points go with a deleted environment.

## 0.2.0

- Plug-ins can be published as VST2 and CLAP as well as VST3, chosen under Settings. VST2 goes to `~/.vst/plugg` and CLAP to `~/.clap/plugg`.
- An installer that installs only its vendor's app, such as Plugin Alliance's Installation Manager, gets that app on the vendor's row. When Plugg is not sure which program is the app, it asks.
- **Change app…** replaces an app Plugg attached, such as a setup program's repair copy that 0.1.0 could attach.
- Dropping a file from Dolphin on Wayland works, and Help warns about Cytomic plug-ins that cannot be authorised yet.

## 0.1.0

The first release: one Windows environment per vendor, vendor apps opened from the library, a shared iLok environment, licence safety checks and help in the app. Packages for Ubuntu and Debian, Fedora and Arch.
