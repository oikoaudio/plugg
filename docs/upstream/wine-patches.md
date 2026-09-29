# Sending Plugg's Wine patches upstream

Plugg's runtimes carry three Wine fixes of its own. Upstream Wine is the right home for all three. Every Wine build would then install PACE and survive the drag-and-drop crash, including [Cabinet](https://github.com/Mark12870/cabinet)'s. Cabinet carries a yabridge patch for the same drag-and-drop bug and runs a probe that tells it when a Wine release fixes it. None of these patches has been submitted.

Wine takes merge requests at https://gitlab.winehq.org/wine/wine. A merge request needs a real-name author, commits against current `master`, a conformance test under the module's `tests/` directory where the behaviour can be tested, and behaviour that matches Windows. The patches in `patches/` are against Valve's Wine at `b8fdff8e1f85` (Wine 10.0), and their author line is `Plugg <noreply@local>`, so each needs work before it can be submitted.

## ole32: refuse to revoke another process's drop target

`patches/0004-ole32-revoke-foreign-drop-target.patch`, WineHQ bug [60225](https://bugs.winehq.org/show_bug.cgi?id=60225).

`RevokeDragDrop` reads the target pointer that `RegisterDragDrop` stored in a window property, and releases it, even when the window belongs to another process. There the pointer means nothing, and the call faults. WebView2 editors hit this every time an editor closes. `diagnostics/dragdrop` has the probe. Unpatched, the child process dies with `0xc0000005`. Patched, it gets `DRAGDROP_E_INVALIDHWND` and the owner's registration survives.

Before sending:

- Check on Windows what `RevokeDragDrop` returns for another process's window. The patch copies `RegisterDragDrop`'s answer to the same case, and no one has confirmed Windows does the same.
- Rebase onto `master`. Upstream had not fixed it as of 2026-09.
- Turn the probe into a test in `dlls/ole32/tests/dragdrop.c`. That needs a child process, which the ole32 tests already use elsewhere.

## rundll32: declare supported Windows versions in a manifest

`patches/wine/0001-rundll32-Declare-supported-Windows-versions-in-a-man.patch`.

Without a manifest, `GetVersionEx` inside `rundll32.exe` reports Windows 6.2, and PACE's installer stops at its launch conditions. On Windows, `rundll32.exe` has a manifest that declares support up to Windows 10, so DLLs it loads see 10.0. `diagnostics/service-config/version-probe.c` shows the difference.

Before sending, confirm the current `master` still lacks the manifest, and compare its contents with the one Windows ships.

## services: store and report service failure actions

`patches/wine/0002-services-Store-and-report-service-failure-actions.patch`.

`QueryServiceConfig2W(SERVICE_CONFIG_FAILURE_ACTIONS)` fails with `ERROR_INVALID_LEVEL`, and `ChangeServiceConfig2W` accepts failure actions and throws them away. PACE's installer reads them back and rolls back when it cannot. The patch stores them in the registry where Windows keeps them. `diagnostics/service-config/service-config.c` checks every information level on x64 and x86.

This is the largest of the three and touches the service RPC interface. Before sending, add tests to `dlls/advapi32/tests/service.c`, and split the IDL and RPC change from the client side if reviewers ask for it.

## Checking whether upstream has them

`scripts/test-runtime-patches.py --runtime <Proton>` runs all the probes against any Proton build. When it reports "can retire?" for a patch on a new UMU-Proton release, upstream has the fix, and Plugg can drop its patch.
