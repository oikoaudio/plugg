#!/bin/sh
set -eu
cd "$(dirname "$(readlink -f "$0")")/.."
revision=b580a9f7fc46509767ca156d4f92872552b9e571
if [ ! -d vendor/yabridge/.git ]; then
    git clone --no-checkout https://github.com/robbert-vdh/yabridge.git vendor/yabridge
    git -C vendor/yabridge checkout --detach "$revision"
fi
test "$(git -C vendor/yabridge rev-parse HEAD)" = "$revision"
python3 scripts/prepare-bridge-source.py
output="${PLUGG_BRIDGE_OUTPUT:-bundle/bridge}"
mkdir -p "$output"
output="$(readlink -f "$output")"
export PLUGG_BRIDGE_OUTPUT="$output"

build_dir="${PLUGG_BUILD_DIR:-build}"
mkdir -p "$build_dir"
build_dir="$(readlink -f "$build_dir")"
if [ ! -f "$build_dir/build.ninja" ]; then
    meson setup "$build_dir" vendor/yabridge --cross-file vendor/yabridge/cross-wine.conf --buildtype=release -Dclap=false -Dbitbridge=false
fi
ninja -C "$build_dir" -j "${PLUGG_BUILD_JOBS:-4}" libyabridge-vst3.so libyabridge-chainloader-vst3.so yabridge-host
mkdir -p "$output"
cp "$build_dir/libyabridge-vst3.so" "$build_dir/libyabridge-chainloader-vst3.so" "$build_dir/yabridge-host.exe" "$build_dir/yabridge-host.exe.so" "$output/"
c++ -std=c++20 -O2 -DRELEASE=1 -Ivendor/yabridge/subprojects/vst3 native/scan.cpp \
    -Wl,--start-group "$build_dir/src/common/vst3/libpluginterfaces_native.a" \
    "$build_dir/src/common/vst3/libsdk_native.a" "$build_dir/src/common/vst3/libbase_native.a" \
    -Wl,--end-group -ldl -lpthread -o "$output/plugg-scan"
cp vendor/yabridge/COPYING "$output/COPYING.yabridge"
python3 scripts/bridge-manifest.py --build "$build_dir" --output "$output"
