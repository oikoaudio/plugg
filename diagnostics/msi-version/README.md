# MSI custom-action OS version probe

This source-only fixture installs nothing. Its .NET custom action logs `PLUGG_PROBE` with the managed and native OS versions, actual host image, and process bitness, then deliberately returns failure before LaunchConditions. An MSI failure exit is therefore expected; the log line is the result.

Build requirements: .NET Framework 4 compiler and WiX 3.14.1 binary tools/SDK. The investigated runtime is UMU-Proton-10.0-4 with Microsoft .NET 4.8 installed. WiX 3 DTF is a representative host, not a claim to duplicate PACE's exact DTF version or all its custom actions. Do not include any vendor binary or account state in an upstream reproduction.

In a disposable test prefix, copy these sources and the official WiX tools to one working directory. From that directory run under the selected Wine runtime:

```
csc.exe /target:library /out:Probe.dll /reference:wix\sdk\Microsoft.Deployment.WindowsInstaller.dll VersionAction.cs
wix\sdk\MakeSfxCA.exe Probe.CA.dll wix\sdk\x64\sfxca.dll Probe.dll CustomAction.config wix\sdk\Microsoft.Deployment.WindowsInstaller.dll
wix\candle.exe -arch x64 Probe.wxs -out Probe.wixobj
wix\light.exe -sval Probe.wixobj -out Probe.msi
msiexec.exe /i Probe.msi /qn /norestart /l*v baseline.log
```

Use the full paths to the .NET Framework 4 compiler and tools if not on PATH. `-sval` omits MSI validation tooling, not the custom action being tested.

## Observations on this deployment

- Baseline: managed=6.2.9200.0, native=10.0.19045, host=system32/rundll32.exe, bits=64. The WiX managed custom action is hosted by rundll32, even though MSI itself also uses msiexec processes.
- Adding a supportedOS Windows 10 manifest to prefix msiexec copies did not resolve PACE. Those copies were restored.
- Adding the declaration to prefix rundll32 copies alone did not affect the fixture; built-in Wine loading still selected the runtime component.
- Forcing `rundll32.exe=native` while retaining its DOS-stub `Wine builtin DLL` marker failed to create the custom-action process (126 / c0000135).
- A private prefix copy with that marker cleared, a Windows 10 manifest added, and native loading selected reports managed=10.0.19045.0 and native=10.0.19045 from inside the MSI custom action.

`AddManifest.cs` adds a manifest resource using Windows resource APIs. This is an experimental local workaround, not a supported runtime patch or distributable binary. Original x86/x64 rundll32 files must be preserved before applying it. Restore both originals and remove the DLL override to undo the experiment. A production fix should build the appropriate Wine component from source, include its license/source obligations, retain normal runtime loading, and test other rundll32 consumers. The fixture currently validates x64 only.

## Independent service query

Compile ServiceQuery.cs as a console executable with the same compiler and run it in the test prefix. It reads configuration from RpcSs using query-only access. On this Proton build, description and delayed-start buffer-size queries return 122 (expected), while failure-actions returns 124 (unsupported information level). This matches PACE's subsequent Wix4ExecServiceConfig failure.
