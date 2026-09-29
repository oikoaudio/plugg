# Changelog

Each release's full notes are in [packaging/release-notes](packaging/release-notes/) and on the [releases page](https://github.com/oikoaudio/plugg/releases). The [ROADMAP](ROADMAP.md) lists what works, what comes next and what this project does not claim.

## 0.2.0

- Plug-ins can be published as VST2 and CLAP as well as VST3, chosen under Settings. VST2 goes to `~/.vst/plugg` and CLAP to `~/.clap/plugg`.
- An installer that installs only its vendor's app, such as Plugin Alliance's Installation Manager, gets that app on the vendor's row. When Plugg is not sure which program is the app, it asks.
- **Change app…** replaces an app Plugg attached, such as a setup program's repair copy that 0.1.0 could attach.
- Dropping a file from Dolphin on Wayland works, and Help warns about Cytomic plug-ins that cannot be authorised yet.

## 0.1.0

The first release: one Windows environment per vendor, vendor apps opened from the library, a shared iLok environment, licence safety checks and help in the app. Packages for Ubuntu and Debian, Fedora and Arch.
