# Service configuration and rundll32 version fixtures

Own-code checks for the two Wine gaps that stop PACE's unmodified installer. Neither needs a vendor binary or a licence. Run them only in a disposable prefix: the service fixture creates and deletes a scratch service.

Build with `sh diagnostics/service-config/build.sh` (Clang/lld and the installed Wine headers, as for the drag-and-drop fixture). Output goes to the ignored `build/diagnostics`.

- `service-config{64,32}.exe` queries and changes every `QueryServiceConfig2W`/`ChangeServiceConfig2W` information level on a scratch service and writes `C:\service-config.txt`. `--keep` leaves the service in place, and `--reopen` reads its failure actions back after the service manager has restarted.
- `version-probe{64,32}.dll` is loaded by `rundll32.exe <dll>,Probe` and writes `C:\rundll32-version{64,32}.txt` with the version `GetVersionEx` and `RtlGetVersion` report inside rundll32.

## Results on UMU-Proton-10.0-4

Unpatched: reading failure actions fails with 124 (`ERROR_INVALID_LEVEL`), the value behind PACE's `0x8007007c` at `Wix4ExecServiceConfig_X86`. Writes are accepted and discarded. Inside rundll32, `GetVersionEx` reports 6.2, the value that stops PACE at LaunchConditions.

With [the Wine patch series](../../patches/wine/): failure actions and the non-crash flag round-trip exactly on x64 and x86 and reload from the registry, and rundll32 reports 10.0 through both APIs. The exact results and artifact hashes are in `patches/wine/series.json`.
