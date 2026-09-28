# Managed Proton sessions

For the full launch path from DAW to Windows module and its known limits, see [the loader contract](loader-contract.md).

Plugg runs one persistent Steam runtime container per vendor Wine prefix, with a separate Windows bridge process for each plug-in instance. Bitwig's own plug-in hosting mode is independent of this choice.

## Why a persistent container

An earlier launcher started a fresh pressure-vessel container for every bridged instance. With two gain fixtures, both could initialize, and then one stalled waiting for its factory response while the other exited. Copying the runtime did not help. Keeping the faster instance alive made the reproduction pass, and so did sharing one persistent container. This points to a container lifetime problem. It does not identify the exact signal or Wine server failure.

## Implementation

`plugg/proton_session.py` provides the session server, the client and automatic startup. A prefix lock makes simultaneous starts wait for each other. Clients connect through a private Unix socket under `/dev/shm/plugg-<uid>`, and the server checks the peer's UID. For each request, the server runs the selected Proton's `runinprefix` command inside the prepared runtime. It relays output and exit status to the native bridge. When a client disconnects, the server cancels that child's process group. The container stays alive while other requests remain, and exits after five idle minutes by default.

Audio does not pass through the Python control socket. It uses yabridge's own native/Windows transport, in the private tmpfs directory that Plugg's bridge patch checks. The launcher clears the Steam application identity (`SteamAppId`), so compositor rules that match Steam games do not catch plug-in or helper windows.

The session manager requires an initialized prefix and a prepared runtime. If a previous launcher is still using the prefix, startup refuses to mix the two, so switching launchers needs an idle environment. This is process supervision, not a security sandbox for untrusted installers or plug-ins. Processes and plug-ins in one vendor environment still share Wine services and files.

## Selecting DXVK graphics

Proton's `runinprefix` skips `setup_prefix()`. That function also sets per-process native DLL overrides for DXVK, so prepared DLLs on disk are not enough. Without the overrides, plug-in hosts load WineD3D instead. With Klevgrand plug-ins (DAW Cassette, Skaka, Slammer) the controls kept working while the editor graphics froze. This matches the redraw issue described in [yabridge's known issues](https://github.com/robbert-vdh/yabridge#known-issues-and-fixes).

A session configured with `graphics_backend: dxvk` checks the prepared 64-bit `d3d11`, `dxgi`, `d3d10core` and `d3d9` DLLs against the selected Proton build. It then sets their native overrides before it starts its server. It never replaces DLLs during a live plug-in launch. If the prepared files do not match, it fails instead of falling back. This supports the current pinned Proton layout. It does not infer future Proton compatibility flags or graphics components. [Recipe authoring](recipe-authoring.md#implemented-graphics-policy-fragment) describes how to choose the renderer per plug-in.

With DXVK selected, fixture audio passed before and after an idle restart. On the maintainer's system, the affected Klevgrand editors redraw correctly with this setting.

## Vendor helpers

Some vendor manager applications do not work through `runinprefix`. Klevgrand Helper, for example, needs a full Proton launch, so its environment stops the idle managed session before opening Helper. See [the vendor Helper workflow](vendor-helper-workflow.md#helper-uses-the-full-proton-launch).

## When a plug-in takes its host down

A plug-in can kill the Windows host's main thread, for example with a stack overflow in `initialize`. The process stays alive in its other threads, and its leader shows as a zombie in `ps`. Wine's launcher (`start.exe`) keeps waiting for it, so the DAW waits too, and a crashed plug-in looks like a frozen DAW. [The host-stack diagnosis](../diagnostics/host-stack/README.md) describes one such case.

The session therefore watches the host itself. Every two seconds it looks for the host in the launch's own process group. Wine keeps new processes in that group, even after they are reparented. When the host has exited, or its leader is a zombie, the session ends the launch and reports exit status 127 to the bridge. The DAW then sees a failed load instead of a hang.

The session recognises the host by its program name, not by its path appearing in a command line. Proton's `runinprefix` and Wine's `start.exe` carry the host's Unix path as an argument, and they are the launcher. The host's own `argv[0]` is the same path in Windows form, such as `X:\...\yabridge-host.exe.so`. The first version of this check matched the path anywhere, found the launcher, and so never fired. Matching by process group also keeps one healthy instance from hiding another instance that has died, because every instance runs the same host program.

`scripts/test-carla.py` checks this with the `Plugg Test Crash` fixture, which ends the host's main thread in `initialize`. With the check in place, Carla's load fails after about five seconds. Without it, Carla was still waiting when a 45-second timeout ended the test.

Environments keep the session manager they were created with. To give existing environments the current one:

```sh
plugg environment update-launcher            # every environment in the library
plugg environment update-launcher <id>       # one environment
```

This replaces only the launcher script and its recorded fingerprint, and keeps a backup. It does not touch the prefix, the runtime or the machine identity, so the licensing guard allows it for protected environments. Stop the environment's plug-ins first.

## Validation

From the repository, run:

```sh
python3 scripts/test-proton-lifecycle.py --managed-session --rounds 3 --survival
```

The test installs only the project's gain fixture into a new disposable prefix. It then does the following:

1. Races two clients to start the session.
2. Repeats concurrent audio probes.
3. Checks that gain processing continues while another instance closes normally, has its Windows bridge killed, or has its native host killed.
4. Waits for idle shutdown and races clients again to check automatic restart.

The scanner's optional stage tracing and paced processing support these lifecycle checks. Their elapsed times are not latency or performance benchmarks. Vendor audio, editor focus, resize and reopen, project state recovery and REAPER need separate validation. Nothing here proves that Plugg contains arbitrary Windows plug-in crashes or a shared Wine server failure.
