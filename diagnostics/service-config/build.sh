#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/diagnostics
# x64 and x86: PACE's failing custom action is 32-bit, and each architecture has its own client DLLs.
clang --target=x86_64-pc-windows-msvc -isystem /usr/include/wine/windows -isystem /usr/include/wine/msvcrt -D_WIN64 -O1 -ffreestanding -fno-stack-protector -c diagnostics/service-config/service-config.c -o build/diagnostics/service-config64.obj
lld-link /nodefaultlib /entry:mainCRTStartup /subsystem:console /out:build/diagnostics/service-config64.exe build/diagnostics/service-config64.obj /usr/lib/wine/x86_64-windows/libkernel32.a /usr/lib/wine/x86_64-windows/libuser32.a /usr/lib/wine/x86_64-windows/libadvapi32.a
clang --target=i686-pc-windows-msvc -isystem /usr/include/wine/windows -isystem /usr/include/wine/msvcrt -O1 -ffreestanding -fno-stack-protector -c diagnostics/service-config/service-config.c -o build/diagnostics/service-config32.obj
lld-link /nodefaultlib /safeseh:no /entry:mainCRTStartup /subsystem:console /out:build/diagnostics/service-config32.exe build/diagnostics/service-config32.obj /usr/lib/wine/i386-windows/libkernel32.a /usr/lib/wine/i386-windows/libuser32.a /usr/lib/wine/i386-windows/libadvapi32.a
# rundll32 version probe (a DLL rundll32 loads and calls).
clang --target=x86_64-pc-windows-msvc -isystem /usr/include/wine/windows -isystem /usr/include/wine/msvcrt -D_WIN64 -O1 -ffreestanding -fno-stack-protector -c diagnostics/service-config/version-probe.c -o build/diagnostics/version-probe64.obj
lld-link /nodefaultlib /dll /noentry /export:Probe /out:build/diagnostics/version-probe64.dll build/diagnostics/version-probe64.obj /usr/lib/wine/x86_64-windows/libkernel32.a /usr/lib/wine/x86_64-windows/libuser32.a /usr/lib/wine/x86_64-windows/libntdll.a
clang --target=i686-pc-windows-msvc -isystem /usr/include/wine/windows -isystem /usr/include/wine/msvcrt -O1 -ffreestanding -fno-stack-protector -c diagnostics/service-config/version-probe.c -o build/diagnostics/version-probe32.obj
lld-link /nodefaultlib /safeseh:no /dll /noentry /export:Probe=_Probe@16 /out:build/diagnostics/version-probe32.dll build/diagnostics/version-probe32.obj /usr/lib/wine/i386-windows/libkernel32.a /usr/lib/wine/i386-windows/libuser32.a /usr/lib/wine/i386-windows/libntdll.a
