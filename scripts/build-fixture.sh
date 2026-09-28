#!/bin/sh
set -eu
cd "$(dirname "$(readlink -f "$0")")/.."
mkdir -p build/fixtures
kernel32="${WINE_KERNEL32_IMPORT_LIB:-/usr/lib/wine/x86_64-windows/libkernel32.a}"
test -f "$kernel32"
clang++ --target=x86_64-pc-windows-msvc -std=c++17 -O1 -ffreestanding -fno-exceptions -fno-rtti \
    -fno-threadsafe-statics -fno-stack-protector -c tests/fixtures/gain.cpp -o build/fixtures/gain.obj
lld-link /dll /nodefaultlib /entry:DllMain /out:build/fixtures/Gain.vst3 build/fixtures/gain.obj
python3 - <<'PY'
from pathlib import Path
b=Path('build/fixtures/Gain.vst3').read_bytes()
Path('build/fixtures/plugin-blob.h').write_text('static const unsigned char plugin_blob[]={'+','.join(str(x) for x in b)+'};\n')
PY
clang --target=x86_64-pc-windows-msvc -O1 -ffreestanding -fno-stack-protector \
    -Ibuild/fixtures -c tests/fixtures/installer.c -o build/fixtures/installer.obj
lld-link /nodefaultlib /entry:mainCRTStartup /subsystem:console /out:build/fixtures/Install-Test-Gain.exe \
    build/fixtures/installer.obj "$kernel32"

clang --target=x86_64-pc-windows-msvc -O1 -ffreestanding -fno-stack-protector \
    -Ibuild/fixtures -c tests/fixtures/helper-installer.c -o build/fixtures/helper-installer.obj
lld-link /nodefaultlib /entry:mainCRTStartup /subsystem:console /out:build/fixtures/Install-Test-Helper.exe \
    build/fixtures/helper-installer.obj "$kernel32"

# Editor fixture: the same gain, plus an edit controller and a Win32 editor that
# reports where clicks land (tests/fixtures/editor.cpp). Installed as a VST3 file.
windows_libs="$(dirname "$kernel32")"
clang++ --target=x86_64-pc-windows-msvc -std=c++17 -O1 -ffreestanding -fno-exceptions -fno-rtti \
    -fno-threadsafe-statics -fno-stack-protector -c tests/fixtures/editor.cpp -o build/fixtures/editor.obj
lld-link /dll /nodefaultlib /entry:DllMain /out:"build/fixtures/Plugg Test Editor.vst3" build/fixtures/editor.obj \
    "$kernel32" "$windows_libs/libuser32.a" "$windows_libs/libgdi32.a"

# The same plug-in, ending the host's main thread in initialize(): a crash the
# session supervisor must turn into a failed load rather than a frozen host.
clang++ --target=x86_64-pc-windows-msvc -std=c++17 -O1 -ffreestanding -fno-exceptions -fno-rtti \
    -fno-threadsafe-statics -fno-stack-protector -DPLUGG_FIXTURE_ENDS_MAIN_THREAD \
    -c tests/fixtures/editor.cpp -o build/fixtures/crash.obj
lld-link /dll /nodefaultlib /entry:DllMain /out:"build/fixtures/Plugg Test Crash.vst3" build/fixtures/crash.obj \
    "$kernel32" "$windows_libs/libuser32.a" "$windows_libs/libgdi32.a"
