# Current loader contract

This page describes what happens between a DAW loading a published plug-in and the Windows module running, and where the guarantees stop. It covers the code in `core.py` and `proton_session.py` and the recorded bridge patch series.

## From a DAW to the Windows module

1. A stable publication link points at a completed native VST3 bundle in the managed library. Its publication manifest records the module hash, environment, class identities and metadata. Publication checks for duplicate class identities and refuses unsupported in-place replacement.
2. The native chainloader sees `.plugg-managed` and loads the bridge beside it. If that local library fails, it does not fall back to a system bridge.
3. The bridge resolves the Windows module symlink and walks up its parent directories looking for `.plugg-runtime`. That marker names the absolute path of the launcher and overrides the DAW-wide Wine selection. Bridges built with patch 0003 also reject a managed publication with no marker, instead of falling back to system Wine.
4. For a managed Proton environment, `launch-plugin` runs the environment's copy of the session manager with `session.json`. The launch checks the initialized prefix, the executable runtime entry points and the idle timeout. When a manager SHA-256 is recorded, it checks that too. Invalid configuration fails before Plugg creates an IPC endpoint or starts Wine.
5. A startup lock per prefix makes runtime starts wait for each other. The session address comes from the same configuration snapshot that was checked. A conflicting process in the prefix prevents a second runtime. An existing matching session can serve another request.
6. The session runs Proton's `runinprefix` for the requested Windows host and supplies the selected graphics overrides. From here, yabridge owns the plug-in protocol and the audio transport. A session ping means the control service is ready. The plug-in is ready only after yabridge's factory and plug-in handshake.

The management GUI plays no part in this path. The Python socket carries launch, output and exit control, never audio buffers or processing requests. The bridge requires private tmpfs IPC, and the session uses a private per-user Unix socket.

## Lifetime and isolation

Each ordinary launch request owns its child process group. When that client disconnects, the session cancels the group. The session stays up while other requests are active and exits after an idle timeout. Bitwig's sandbox grouping is independent of this. Per-module graphics overrides reject grouped yabridge hosts, because one process cannot use several DLL-selection policies.

An environment's Wine services, prefix files and licensing state stay shared. This is not a security sandbox, and it does not guarantee that every crash is contained. The gain-fixture lifecycle tests cover specific cases of concurrent processing and instance exit. They say nothing about arbitrary vendor plug-ins or REAPER. The GUI does not recover projects transparently.

## Checks

Unit tests cover missing or malformed paths, non-executable entry points, invalid timeouts, manager fingerprint mismatches and snapshot-based validation. All of these fail before any process starts. Plugg accepts legacy configurations without `manager_sha256`. That is a compatibility rule, not an integrity guarantee.

Environments that hold activations keep their own versioned copy of the session manager. A newer manager reaches them only through an explicit configuration operation while the environment is idle. Updating Plugg never replaces it.

## Known limitations

- Publication hashes describe the state at publication time. The native loader does not hash the whole module, bridge and runtime on every load.
- Deployed bridges keep their recorded versions. Older bridges do not gain the missing-marker check from patch 0003 on their own. A newer bridge has to be rolled out explicitly while the environment is idle.
- Startup checks and configuration-edit locks do not form one transaction with an external DAW launch. Keep the DAW closed during environment maintenance.
- After a half-finished session or launcher update, you have to inspect the recorded graphics application and configuration history by hand. There is no automatic prefix rollback.
- Real editor interaction, project recall and host-specific crash containment need separate DAW tests. Automated metadata scans cannot replace them.

These are open items. The recipe format does not promise any of them.

## Missing-marker regression test

Patch `0003-require-managed-runtime` adds the missing-marker check only for native publications that carry `.plugg-managed`. Ordinary unmarked yabridge behaviour does not change. The constructor fails before it asks Wine for a version or starts a Windows host.

Run it against a separately built bridge:

~~~sh
python3 scripts/test-loader-mapping.py --bridge /path/to/bridge --fixture build/fixtures/Gain.vst3
~~~

The test builds a temporary publication around the synthetic Windows gain module. It supplies an executable trap as the DAW's Wine loader, which records any unexpected call. Missing, empty and invalid markers must each produce the expected native error without calling the trap. The test needs no Wine process and no licensed environment. It does not show that normal audio works. The lifecycle test below covers that separately.

## Lifecycle test for a candidate bridge

The managed Proton lifecycle test accepts `--bridge` for a candidate build. Before it creates a prefix, it checks the candidate's files against the build manifest. It records the bridge manifest and the session-manager fingerprint in its results, with the manager fingerprint check enabled.

~~~sh
python3 scripts/test-proton-lifecycle.py --bridge /path/to/bridge --managed-session --rounds 2 --survival
~~~

In a new unactivated prefix, the test does the following:

1. Runs concurrent gain scans in each round.
2. Checks that gain processing continues when another instance closes normally, when its Windows host is forced to exit, and when its native host is forced to exit.
3. Lets the idle session stop, then has two racing clients restart it.

A bridge built from the full patch series, 0001 to 0003, has passed it. The test checks that gain is applied correctly and covers specific process-lifetime cases. It is not a latency benchmark, a vendor editor regression test, or a Bitwig or REAPER test.
