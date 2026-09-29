# Native Instruments modular setup

`plugg.native-instruments@2` recognizes the exact tested Native Access installer. It combines DXVK with the `plugg.powershell@1` and `plugg.ntk-daemon@1` components. New setups use the generic helper worker and the pinned UMU-Proton runtime. Plugg does not convert, repair or reprovision existing NI environments. Their vendor identity blocks a second installation in the same library.

The findings behind this recipe are in [the NI compatibility notes](../compatibility/native-instruments.md). A result from one environment does not automatically hold in a newly provisioned one.

## PowerShell component

The Native Access installer needs PowerShell in the prefix. The component installs Microsoft's pinned PowerShell 7.4.11 x64 MSI and a small forwarder, checked in at `components/powershell-forwarder/main.go`. The forwarder uses only the Go standard library. It passes arguments and standard streams to the installed `pwsh.exe`, turns off profile loading and returns the exit status. It does not stub queries, rewrite commands, install .NET 4.8 or download another project's wrapper binary.

Build both Windows entry points with `python3 scripts/build-powershell-forwarder.py`. The build runs with module downloads disabled. It records the compiler, the source hash and the output hashes, together with the project and Go licence notices. The installer checks that bundle before it changes the fresh environment. Shipping prebuilt components is still part of the release-packaging work.

PowerShell downloads can only come from the Microsoft PowerShell project's release path. Plugg accepts GitHub asset CDN hosts only as redirect targets, and the MSI must match the shipped SHA-256. Recipe authors choose the operation. They cannot choose its URL or command arguments.

Both forwarder entry points have run an arithmetic fixture through real PowerShell and returned its non-zero exit code. Fresh Native Access installations succeed with this component.

## Automated service component

Native Access expects its NTKDaemon service to be running. Without help, three things go wrong at first launch:

- Native Access asks for elevation to run its bundled NTKDaemon installer. The request fails with `UserDidNotGrantPermission`, and no prompt appears.
- Its fallback version check (`wmic datafile ... get Version /value`) fails under this runtime.
- Starting `NTKDaemon.exe` directly puts it in service mode, which does not give a usable standalone daemon.

Revision 2 therefore declares NTKDaemon as a separate component. `ntk_component.py` fixes the installer path, SHA-256 and silent argument, as well as the executable and service name. The installer is `NTKDaemon 1.32.0 Setup PC.exe`, SHA-256 `5f2199f4e1409d6eea5edaea9c4a8af31e8ee8ac3790851aa44d33e87a46b218`, run with `/S`. Recipe authors cannot substitute a URL or command. The helper worker installs the component after Native Access, checks the payload and the vendor's installation record, and records the hash of the installed binary. Before it stops this prefix's runtime, it waits until only known background processes remain. Unknown applications prevent that cleanup.

The generated helper batch starts `NTKDaemonService` with `sc.exe start`, then starts Native Access, all in one full Proton launch. In testing, separate full launches made Electron's GPU process fail. With both in one launch, Native Access finds the running daemon (version 1.32.0.0) and opens normally.

All Wine environments share NTKDaemon's local socket address. Setup and helper launch check for a daemon running outside their own prefix, and if they find one, ask you to close the other Native Access. This is not network namespace isolation. Plugg never stops another environment automatically.

Revision 1, with the installer but no service component, stays available as history. It does not produce a working first launch. Installer recognition picks the newest revision of the same recipe identity. Unrelated recipes that claim the same installer still conflict. Saved recipe snapshots keep their exact definitions.

## Helper profile and sign-in

`helper_profile = "native-access"` selects a fixed Python lifecycle adapter. Recipes cannot supply shell code or arbitrary process names. The adapter handles the Native Access window and the known background services, in this prefix only. Unknown applications, or a Wine server from a different runtime, block cleanup. The temporary Hyprland rule keeps normal floating placement. Closing the helper triggers VST3 discovery into this library.

The setup creates `C:\Native Instruments Downloads`, because the download location picker cannot create a new folder. Native Access still controls content locations and preset libraries. Plugg copies no library or preset data from another environment.

Browser callbacks go through a desktop handler that belongs to the running helper session. The router records only its process identity and configuration path. It refuses stale sessions and never stores the callback URL. Closing the managed helper releases it. Existing NI helper launch actions also register their session, without changing their Windows environment. The router becomes the default handler for `native-access://` links.

The browser may ask permission to open the link in Native Access. If the automatic handoff fails, use the Helper card's **Complete sign-in…** action. It takes the browser's `native-access://` return link in a hidden field and sends it only to this setup. Plugg does not log or store the link. Use a newly issued link straight away. Each link works once, and expired or used codes fail.

## Validation

On the maintainer's system, a fresh revision 2 setup installed Native Access and NTKDaemon. The normal helper action opened Native Access, which recognized the daemon. The browser handed the sign-in back to Native Access automatically. Closing the window triggered background cleanup and a library refresh, and left no processes in the prefix. Raum, installed through the fresh Native Access, worked in Bitwig.

The setup copied or changed no existing NI activation or account state. Keep any environment you have signed in to until you choose to clean it up, with licensing in mind. Never treat an activated environment as disposable.

If you test a second copy of a plug-in side by side, the published bundle's name must match the Linux binary inside it, for example `Raum.vst3` containing `Raum.so`. Bitwig did not scan a link renamed to `Raum-NI-Test.vst3`.

## Untested alternatives

The bundled recipe lead for Native Access (`recipe leads "native access"`) sets it up differently from this recipe. These differences are worth trying in a new environment, never in an existing one. Here is what the lead does:

- It installs the latest Native Access without a hash. This recipe pins one tested installer.
- Before installing, it sets Windows 10 and turns off UAC prompts (`EnableLUA=0`, `ConsentPromptBehaviorAdmin=0` under `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System`).
- It uses winetricks `powershell`, `corefonts` and `vcrun2022`. This recipe uses Microsoft PowerShell 7.4 through the checked-in launcher.
- It runs whichever bundled NTKDaemon installer is newest, with `/s IAgree=Yes`, a log file and a 180-second limit. This recipe runs exactly 1.32.0 with `/S`.
- It starts Native Access with Electron's `--no-sandbox --disable-gpu-sandbox --disable-gpu --disable-gpu-compositing --in-process-gpu`.
- It keeps the download folder under `users/Public/Documents/Native Instruments/Downloads` across reinstalls.
- It runs on a Wine build with better Direct2D support.

None of this counts as evidence for Plugg's runtime until someone tests it.
