# Arturia Software Center

ASC 2.12.0.3157 on UMU-Proton 10.0-4 (plugg-1) works in the tested environment with the workarounds below. The exact-installer recipe is `plugg.arturia@1`. On 2026-10-15 the user signed in and installed products, without WebView2. Plugg's refresh published Delay TAPE-201, Jun-6 V and Tape MELLO-FI with no scan failures. They loaded and worked in Bitwig, and after the editor fix below, closing TAPE-201's editor no longer crashed. This is a manual functional check, not an exhaustive audio or editor test. Fresh unattended recipe installation still needs validation.

## Text input crash

On 2026-10-15, ASC installed and opened, then exited during interaction with its login fields. A diagnostic launch captured `EXCEPTION_ACCESS_VIOLATION` (`c0000005`), reading address zero in `UIAutomationCore.dll + 0x736a`, through `UIAutomationCore.dll + 0x2730` and `Arturia Software Center.exe + 0xc8f609`. These offsets describe this build, not other Wine or ASC versions.

Plugg 0.2.1 tried to disable `uiautomationcore` with a `set "WINEDLLOVERRIDES=…"` line in the manager's Windows batch launcher. That did not work. Later on 2026-10-15, ASC crashed with the same backtrace while synchronizing licences after an automatic login, and the crash dump listed Wine's built-in `uiautomationcore` as loaded. Proton reads `WINEDLLOVERRIDES` before the prefix starts, so a `set` inside `cmd.exe` comes too late. The earlier sign-in that succeeded did not prove the workaround.

The Arturia recipe now writes `WINEDLLOVERRIDES=uiautomationcore=` into the environment's `launch-full-proton`, after it clears any inherited value. Proton adds its own overrides to it. With that, Wine logged that it could not load `uiautomationcore.dll`, and ASC synchronized its licences and ran without crashing. The setting applies to everything the full launcher starts in this environment: ASC, the installers it runs, and the ASC installer. It does not change the shared runtime or the prefix registry. Disabling UI Automation limits accessibility support in the manager.

## Editor close crash

On 2026-10-15, with the manager fixed, Delay TAPE-201 loaded and worked in Bitwig. Closing its editor window took down Bitwig's audio engine, which exited with code 1. Nothing recorded the plug-in host's own output, so this fault has no backtrace.

The plug-in module is built with JUCE. It loads `UIAutomationCore.dll` at run time and calls `UiaDisconnectProvider` and `UiaDisconnectAllProviders`, which JUCE does when an editor window is destroyed. That is the DLL the manager crashed in. JUCE runs without accessibility when the DLL does not load.

The Arturia recipe therefore also writes `"disabled_dlls": ["uiautomationcore"]` to the environment's `session.json`. The managed session adds `uiautomationcore=` to every plug-in host's `WINEDLLOVERRIDES`, after the graphics overrides. With that setting, closing TAPE-201's editor did not crash. Plug-in editors in this environment get no Windows accessibility support.

The GUI also logged missing `WebView2Loader.dll`, a missing `ProgramData/Arturia/Shared/x64/webview2` directory, and `glGetString returned nullptr`. Those warnings alone did not explain the crash: the captured fault is in UI Automation. WebView2 has not been added to the recipe. A later browser-dependent workflow may still need it.

## Existing installations

The recipe intake creates a fresh environment; it does not migrate or reinstall an existing manager. Preserve existing activation state. To fix an existing ASC environment by hand, close ASC and the environment's plug-ins, and keep copies of the files you change. For ASC, add `export WINEDLLOVERRIDES=uiautomationcore=` to `launch-full-proton` after its `unset` line. For the plug-in hosts, run `plugg environment update-launcher <id>` with Plugg 0.2.1 or later, then add `"disabled_dlls": ["uiautomationcore"]` to `session.json`. Account sign-in remains a user action. Raw vendor and Wine logs may contain account information and are not included here.
