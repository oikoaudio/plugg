# Wine cannot report a stack overflow on x64

While chasing [plug-ins dying during initialisation](../host-stack/README.md),
Wine's own crash report turned out to be broken: dispatching the overflow
recursed until the process died, with nothing printed. That is a separate
upstream bug, fixed in Wine 11.7 and backported in `plugg-2`.

It is not why plug-ins failed. It is why the failure was invisible.

## What happens

The bridge handshake completes, the factory answers, the instance is created,
and the plug-in stops responding inside `IPluginBase::initialize`. The Windows
host process is gone by then; `ps` shows it as a zombie while Wine's launcher
below it still waits in `NtWaitForMultipleObjects`. The DAW waits on that
launcher, so a crashed plug-in looks like a frozen DAW.

Wine, with its error output restored, says what happened:

```
err:virtual:virtual_setup_exception stack overflow 3392 bytes addr 0x6ffffffa9132 stack 0x202c0 (0x20000-0x21000-0x120000)
```

and with `WINEDEBUG=+seh`, the same four frames repeat until the megabyte of
stack is gone:

```
warn:seh:virtual_unwind backtrace: ntdll.dll + 0x36FA0   (RtlVirtualUnwind2)
warn:seh:virtual_unwind backtrace: ntdll.dll + 0x36356   (RtlVirtualUnwind)
warn:seh:virtual_unwind backtrace: ntdll.dll + 0x4379D
warn:seh:virtual_unwind backtrace: ntdll.dll + 0x45D47
warn:seh:virtual_unwind backtrace: ntdll.dll + 0xF8A6    (KiUserExceptionDispatcher)
...
trace:seh:call_seh_handlers handler at 0x7f0f6ecb91a0 returned 3   (ExceptionCollidedUnwind)
trace:seh:dispatch_exception code=c0000005 (EXCEPTION_ACCESS_VIOLATION) rip=00006ffffff76fa0
```

## Why

A C++ exception unwinds through a collided frame. Wine's dispatcher handles
that by calling `RtlVirtualUnwind()` with no handler data and no handler
(`dlls/ntdll/signal_x86_64.c`, all three `ExceptionCollidedUnwind` cases), and
`RtlVirtualUnwind2()` writes through those NULL pointers. The resulting fault
is dispatched, collides again, and recurses until the stack is gone.

Nothing of Plugg's is involved: the same code is in stock UMU-Proton 10.0-4,
whose `ntdll.dll` is byte for byte the one this project's runtime carries.

Upstream fixed it in [a55cddce98](https://gitlab.winehq.org/wine/wine/-/commit/a55cddce9839a1516f882ad2e5a2ab689084da92),
released in Wine 11.7. UMU-Proton 10.0-4 is Wine 10.0.

With the backport in place, the same load still failed, which is what ruled
this out as the cause and sent the search back to the stack itself.

## What made it hard to see

- The session container started Wine with `WINEDEBUG=-all`, which silences Wine's
  own error output along with everything else. The crash left no trace at all.
- When the Windows program dies, its launcher keeps waiting, so the launch never
  returns and the DAW has nothing to report but a timeout.

Both are fixed: the session keeps Wine's errors, and it ends a launch whose
Windows program has exited.

## Reproducing it

A load outside a DAW shows it, with Wine's error output left on:

```sh
plugg-scan "$HOME/.vst3/plugg/NAME.vst3/Contents/x86_64-linux/NAME.so" /tmp/out.json --audio
```

An exception thrown and caught in a plain winegcc-built Windows program does
*not* reproduce it: the collision is what matters, not the exception.

## Probe

`null-outputs.c` makes the dispatcher's call on its own frame: `RtlVirtualUnwind2()` with no handler data and no handler output. It writes `started` to `C:\unwind-probe.txt` first and `survived` once the call returns, so `started` alone means the bug. Build it with `sh diagnostics/collided-unwind/build.sh`. `scripts/test-runtime-patches.py` runs it with the other probes.

On 2026-09-28, stock UMU-Proton 10.0-4 crashed in the call. A copy of `plugg-1` with a local build of the patched `ntdll.dll` returned from it.
