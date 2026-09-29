# No Plugg Flatpak: Cabinet covers Flatpak

Decided in September 2026. Plugg does not ship a Flatpak. People who want one, and people on image-based distributions such as Fedora Silverblue, are well served by [Cabinet](https://github.com/Mark12870/cabinet). Plugg stays a native install.

## Two projects that fit together

Cabinet and Plugg share a design: one Wine prefix per vendor, a patched yabridge, and one long-lived session per prefix. They are built for different people.

**Cabinet** is a Flatpak. It installs with one command on any distribution, including image-based ones, and updates from a remote. It keeps a curated library of plug-ins that it installs for you, many of them free, and tests them in a real host on every release. It also works through what running a DAW's plug-ins across a sandbox boundary takes: DAWs inside and outside Flatpak, a shim that keeps one session per prefix, and supervision that works across PID namespaces. Its README states the permissions a sandboxed DAW needs plainly, so people can decide for themselves.

**Plugg** installs whatever Windows plug-in you bring it, free or paid: an installer, an MSI or a VST3 file. It is also built for the harder cases, where plug-ins come through their vendors' own managers (Native Access, UA Connect, Softube Central and others) or need iLok and PACE. It records which environments hold activations and refuses the operations that could cost a seat. It gives every environment on a computer one machine identity. It runs Proton, with Wine fixes of its own that the PACE installer needs. Much of that work sits close to the host, and a sandbox would make it harder, not easier.

Building a Plugg Flatpak would mean solving, a second time, the problems Cabinet has already solved well. Plugg's time is better spent on what sets it apart, and where the two projects can help each other. Cabinet's catalogue already informs Plugg's recipe leads (`plugg/leads/cabinet/`). In the other direction, `docs/upstream/cabinet.md` holds notes from Plugg's iLok and machine-identity work, drafted for Cabinet.

## How Plugg reaches more people

Plugg reaches more people through native packages. First comes a published release with prebuilt artifacts (the bridge and the `plugg-1` modules), so the README's steps work without building anything. Then come packages for more distribution families, or a relocatable tarball. The Arch package stays the supported install until then.

## If this is ever revisited

A Flatpak could still be added later without disturbing anyone's library, as long as user data never belongs to the app's install location. The library lives in `~/.local/share/plugg`, and a Flatpak would be granted that directory and use the existing environments in place. Moving an environment changes its path and in practice its runtime copy, which for iLok and other deactivate-first licences means deactivating first ([licensing safety](../licensing-safety.md)). The machine identity is derived from the host's `/etc/machine-id`, which a Flatpak app can read. `plugg environment update-launcher` rewrites the scripts that start sessions.

Two questions would need answers first, both about Proton rather than about packaging. Can Plugg's persistent session run inside a Flatpak, in the kind of sub-sandbox the Steam Flatpak uses for pressure-vessel? And can a DAW outside the sandbox reach it without being granted `org.freedesktop.Flatpak`?
