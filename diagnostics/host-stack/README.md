# Plug-ins take the Windows host down while initialising

On 2026-09-20, every bridged plug-in failed to load in Bitwig. Bitwig reported "Plug-in host is not responding", and the host was killed a minute later. The failures included Kilohearts, Native Instruments Massive, XLN Addictive Keys, and Klevgrand, which had all loaded the day before.

## What happens

The bridge handshake completes, the factory answers, the instance is created, and the plug-in stops responding inside `IPluginBase::initialize`. By then the Windows host process is a zombie, while Wine's launcher below it still waits in `NtWaitForMultipleObjects`. The DAW waits on the launcher, so a crashed plug-in looks like a frozen DAW.

Wine, with its error output restored, says what happened:

```
err:virtual:virtual_setup_exception stack overflow 3392 bytes addr 0x6ffffffa9132 stack 0x202c0 (0x20000-0x21000-0x120000)
```

`0x20000-0x120000` is a one megabyte stack, the first one the process allocated, and it is exhausted a few callbacks into `initialize`.

## Why

The host had been built by `makepkg`, and `makepkg` exports this machine's `CFLAGS`, `CXXFLAGS` and `LDFLAGS`. Meson passes them to the Wine cross build, so `yabridge-host.exe.so` was compiled with

```
-march=native -O3 -pipe -fno-plt -fexceptions -Wp,-D_FORTIFY_SOURCE=3 -Wformat
-Werror=format-security -fstack-clash-protection -fcf-protection -Wp,-D_GLIBCXX_ASSERTIONS
```

on a Zen 4 machine, where `-march=native` means AVX-512. A host built that way overflows its main thread's stack while the plug-in initialises. The same source built with yabridge's own flags, which add only `-msse2`, loads and activates, with upstream's default one megabyte thread stacks. Of the injected flags, `-march` alone reproduces the failure, and `-march=x86-64-v3` (AVX2, no AVX-512) fails the same way, so it is not specific to AVX-512.

The mechanism inside the host has not been identified. The compiled yabridge code has no stack frame above 64 KB in either build. The bridge log shows that the plug-in's `IHostApplication::getName` callback was answered normally just before the overflow. Whatever overflows the stack therefore runs between that answer and the next callback, in the plug-in or on the way back into it. The tests do establish the variable that matters, which is the host's target architecture.

The fix is in [`scripts/build-bridge.sh`](../../scripts/build-bridge.sh). The bridge build now clears the environment's compiler flags before configuring and refuses a build directory configured with `-march`. The manifest records the arguments each build used, so a build like this one can be recognised from its `build.json`.

## How it was narrowed down

Each of these was ruled out by measurement, not by argument:

| Suspect | Test | Result |
| --- | --- | --- |
| The rebuilt bridge binary | Load through the previous day's package build | Same failure |
| The `plugg-1` runtime's PACE modules | Stock `services.exe`, `sechost.dll`, `rundll32.exe` in runtime and prefix | Same failure |
| Wine's `RtlVirtualUnwind2` NULL write | Patched `ntdll.dll` in runtime and prefix | Same failure |
| Proton's accessibility agent | `PROTON_USE_XALIA=0` | Same failure |
| The prefix, the install, the plug-in | Load the same prefix under the system Wine and yabridge | **Loads and activates** |
| The one megabyte thread stack | 16 MB in `CreateThread`, built out of tree without `makepkg` | **Loads and activates** |
| The one megabyte thread stack, again | 16 MB in `CreateThread`, built through `makepkg` | Same failure |
| The packager's flags | Same source, 16 MB threads, `makepkg`'s flags exported by hand | Same failure |
| `-march=native` alone | Same source, only `-march=native` added | Same failure |
| `-fstack-clash-protection -fcf-protection` alone | Same source | Loads and activates |
| Fortify, `-fno-plt`, `-D_GLIBCXX_ASSERTIONS`, `makepkg`'s `LDFLAGS` | Same source | Loads and activates |
| `-march=x86-64-v3` alone | Same source | Same failure |
| Upstream's thread stack, yabridge's flags | No stack change, no injected flags | **Loads and activates** |

The first out-of-tree test changed two things at once: it raised the thread stack and, being run outside `makepkg`, dropped the packager's flags. The larger stack was taken to be the fix and went into a patch and then a package, and the package failed the same way. Building the same source with the flags exported by hand, then with one flag group at a time, found the real variable. The system Wine result had been consistent with this from the start, because the distribution's yabridge is built for the x86-64 baseline.

## What made it hard to see

- The session container started Wine with `WINEDEBUG=-all`, which silences Wine's own errors along with everything else. The overflow left no trace.
- Wine 10.0 cannot report this particular failure. Dispatching the overflow hits an unrelated bug where `RtlVirtualUnwind2()` writes through NULL output parameters on the collided-unwind path, so the report recurses until the process dies. [The unwinder note](../collided-unwind/README.md) covers it; upstream fixed it in Wine 11.7 and `plugg-2` carries the backport. It is not the cause of this failure, only the reason the cause stayed invisible.
- When the Windows program dies, its launcher keeps waiting, so the launch never returns and the DAW has nothing to report but a timeout.
- The first out-of-tree test changed two variables at once and passed, so it could not show which one mattered.

## Reproducing it

Build the host with `-march=native` exported, or take any `build.json` whose `build_inputs.arguments` show `-march` for the host machine, and load a plug-in that does real work while initialising:

```sh
plugg-scan "$HOME/.vst3/plugg/NAME.vst3/Contents/x86_64-linux/NAME.so" /tmp/out.json --audio
```

It stops after `SCAN_STAGE initialize` and the host disappears. With a baseline build it continues through `configure-audio` and `activate`.
