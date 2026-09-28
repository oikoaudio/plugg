# No Flatpak yet: prove two things first

Decided in September 2026. Plugg does not ship a Flatpak for now. The [ROADMAP](../ROADMAP.md) names one as a way to reach more distributions "if the bridge and runtimes can work inside one". This record says what that condition means in practice, what [Cabinet](https://github.com/Mark12870/cabinet) shows about it, and what would change the decision.

## What a Flatpak would give

One build that installs with one command on any distribution, including image-based ones such as Fedora Silverblue, with updates from a remote. Flatpak packages the app. It does not change how a plug-in gets bridged, so it gives no architectural advantage. It is a distribution channel.

## What Cabinet shows

Cabinet is a Flatpak with the same design underneath: one Wine prefix per vendor, a patched yabridge, and one long-lived session per prefix. Almost all of its hard problems come from the sandbox boundary between the DAW and Wine:

- A DAW that is itself a Flatpak needs `--talk-name=org.freedesktop.Flatpak` to start Cabinet's Wine. That permission lets the DAW run any command on the host, so the DAW's sandbox is gone.
- yabridge's watchdog tracks the host by PID, and PIDs differ across the boundary, so Cabinet turns it off and supervises the host another way.
- Two sandboxes over one prefix reached the same wineserver socket from different PID namespaces and froze REAPER. Cabinet now routes every launch through one session per prefix to avoid this.
- Cabinet patches yabridge so a DAW outside Flatpak finds Cabinet's yabridge inside the Flatpak installation directory.
- `flatpak uninstall --delete-data` deletes every prefix.

Cabinet also runs plain Wine, not Proton, so it never has to start pressure-vessel inside a Flatpak.

## What is unproven for Plugg

Plugg runs every environment through UMU and pressure-vessel, which starts its container with bubblewrap. Inside a Flatpak sandbox, an app cannot create the user namespaces bubblewrap needs. The Steam Flatpak gets around this by asking the Flatpak portal for a sub-sandbox, and pressure-vessel supports that mode. Whether Plugg's persistent session works that way has not been tested. The session needs `PRESSURE_VESSEL_SHARE_PID=1`, the private socket directory in `/dev/shm`, and a DAW outside the sandbox connecting to it.

The launch path is the second open question. Today a native DAW runs `launch-plugin`, which runs the session manager with the host's Python. From a Flatpak, that manager and its Python live inside the app, so a DAW outside it cannot run them without the same host-command permission Cabinet needs. Alternatives are a small static launcher outside the sandbox, or requiring host Python. Neither has been tried.

## What a Flatpak must not do to activations

Moving an existing environment into a Flatpak changes its path and, in practice, its runtime copy. For an environment with iLok or other deactivate-first licences, that is a move that needs deactivation first ([licensing safety](../licensing-safety.md)). A Flatpak must also keep environments out of reach of `flatpak uninstall --delete-data`, for example under `~/.local/share/plugg` with a filesystem grant, rather than in the app's own data directory.

## What would change the decision

A spike that answers both questions with the gain and editor fixtures (`scripts/test-carla.py`) and no vendor software:

1. From inside a Flatpak, start a persistent Proton session in a sub-sandbox and load a fixture from a native Carla outside it, with the session's host watchdog working.
2. Do that without granting the DAW, or anything the DAW runs, `org.freedesktop.Flatpak`.

If both hold, a Flatpak is worth building. If only the first holds, Plugg's own sandbox claims would be no stronger than Cabinet's, and more distribution packages or a relocatable tarball are the better next step. Until then, the Arch package stays the supported install, and other distributions build from a checkout.
