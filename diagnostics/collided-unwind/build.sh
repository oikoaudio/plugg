#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/diagnostics
clang --target=x86_64-pc-windows-msvc -isystem /usr/include/wine/windows -isystem /usr/include/wine/msvcrt -D_WIN64 -O1 -ffreestanding -fno-stack-protector -c diagnostics/collided-unwind/null-outputs.c -o build/diagnostics/unwind-probe.obj
lld-link /nodefaultlib /entry:mainCRTStartup /subsystem:console /out:build/diagnostics/unwind-probe.exe build/diagnostics/unwind-probe.obj /usr/lib/wine/x86_64-windows/libkernel32.a /usr/lib/wine/x86_64-windows/libntdll.a
