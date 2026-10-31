#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/diagnostics
x86_64-w64-mingw32-gcc -O1 -static -o build/diagnostics/msi-width-probe64.exe diagnostics/msi-string-width/probe.c -lmsi
i686-w64-mingw32-gcc -O1 -static -o build/diagnostics/msi-width-probe32.exe diagnostics/msi-string-width/probe.c -lmsi
