# Arturia Software Center

ASC 2.12.0.3157 on UMU-Proton 10.0-4 (plugg-1) works in the tested environment with the manager workaround below. The exact-installer recipe is `plugg.arturia@1`. On 2026-10-15 the user confirmed successful sign-in and product installation with UIAutomationCore disabled, without installing WebView2. Plugg's refresh published Delay TAPE-201, Jun-6 V and Tape MELLO-FI with no scan failures; the user then confirmed they work in Bitwig. This is a manual functional check, not an exhaustive audio or editor test. Fresh unattended recipe installation still needs validation.

## Text input crash

On 2026-10-15, ASC installed and opened, then exited during interaction with its login fields. A diagnostic launch captured `EXCEPTION_ACCESS_VIOLATION` (`c0000005`), reading address zero in `UIAutomationCore.dll + 0x736a`, through `UIAutomationCore.dll + 0x2730` and `Arturia Software Center.exe + 0xc8f609`. These offsets describe this build, not other Wine or ASC versions.

The Arturia helper profile sets `WINEDLLOVERRIDES` to disable `uiautomationcore` in the manager's Windows batch launcher. Existing overrides are retained. The setting applies to the manager and its children. It does not modify the shared runtime, prefix registry or DAW plugin launcher. Disabling UI Automation limits accessibility support in the manager.

The GUI also logged missing `WebView2Loader.dll`, a missing `ProgramData/Arturia/Shared/x64/webview2` directory, and `glGetString returned nullptr`. Those warnings alone did not explain the crash: the captured fault is in UI Automation. WebView2 has not been added to the recipe. A later browser-dependent workflow may still need it.

## Existing installations

The recipe intake creates a fresh environment; it does not migrate or reinstall an existing manager. Preserve existing activation state. The same launcher profile can be applied to an existing ASC environment after checking its helper operation lock and saving the previous launcher. Account sign-in remains a user action. Raw vendor and Wine logs may contain account information and are not included here.
