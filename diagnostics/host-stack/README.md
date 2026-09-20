# Plug-ins take the Windows host down while initialising

Every bridged plug-in failed to load in Bitwig on 2026-09-20: "Plug-in host is
not responding", then the host killed a minute later. Kilohearts, Native
Instruments Massive, XLN Addictive Keys, and Klevgrand, which had loaded the
day before.

## What happens

The bridge handshake completes, the factory answers, the instance is created,
and the plug-in stops responding inside `IPluginBase::initialize`. By then the
Windows host process is a zombie, while Wine's launcher below it still waits in
`NtWaitForMultipleObjects`. The DAW waits on the launcher, so a crashed plug-in
presents as a frozen DAW.

Wine, with its error output restored, says what happened:

```
err:virtual:virtual_setup_exception stack overflow 3392 bytes addr 0x6ffffffa9132 stack 0x202c0 (0x20000-0x21000-0x120000)
```

`0x20000-0x120000` is a one megabyte stack, and it is exhausted.

## Why

yabridge runs plug-in code on threads it creates with `CreateThread(nullptr, 0,
...)`. A size of zero means the executable's default, which is one megabyte.

Upstream never runs short of stack because it starts the Windows host directly
with the Wine loader, where the first thread gets the Unix stack, normally
eight megabytes. Plugg starts the host through Proton's `start.exe /exec`
inside the Steam runtime container, so a plug-in really does get one megabyte.
Plug-ins that do substantial work while initialising run off the end of it.

`patches/0005-wine-host-plugin-thread-stack.patch` reserves 16 MB for those
threads. The reservation is address space; pages are committed as they are
touched.

## How it was narrowed down

Each of these was ruled out by measurement, not by argument:

| Suspect | Test | Result |
| --- | --- | --- |
| The rebuilt bridge binary | Load through yesterday's build | Same failure |
| The `plugg-1` runtime's PACE modules | Stock `services.exe`, `sechost.dll`, `rundll32.exe` in runtime and prefix | Same failure |
| Wine's `RtlVirtualUnwind2` NULL write | Patched `ntdll.dll` in runtime and prefix | Same failure |
| Proton's accessibility agent | `PROTON_USE_XALIA=0` | Same failure |
| The prefix, the install, the plug-in | Load the same prefix under the system Wine and yabridge | **Loads and activates** |
| The stack size | 16 MB in `CreateThread` | **Loads and activates** |

The system Wine result is what turned it around: the same plug-in, the same
prefix, the same Windows module, working outside our launch path.

## What made it hard to see

- The session container started Wine with `WINEDEBUG=-all`, which silences
  Wine's own errors along with everything else. The overflow left no trace.
- Wine 10.0 cannot report this particular failure. Dispatching the overflow
  hits an unrelated bug where `RtlVirtualUnwind2()` writes through NULL output
  parameters on the collided-unwind path, so the report recurses until the
  process dies. [The unwinder note](../collided-unwind/README.md) covers it;
  upstream fixed it in Wine 11.7 and `plugg-2` carries the backport. It is not
  the cause of this failure, only the reason the cause stayed invisible.
- When the Windows program dies, its launcher keeps waiting, so the launch
  never returns and the DAW has nothing to report but a timeout.

## Reproducing it

Without the patch, any plug-in that works the stack while initialising will do:

```sh
plugg-scan "$HOME/.vst3/plugg/NAME.vst3/Contents/x86_64-linux/NAME.so" /tmp/out.json --audio
```

It stops after `SCAN_STAGE initialize` and the host disappears. With the patch
it continues through `configure-audio` and `activate`.
