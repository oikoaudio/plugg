# The release bridge is built here, not on the packager's machine.
#
# Ubuntu 22.04 sets the oldest glibc (2.35) and libstdc++ the bridge needs, so
# one build runs on current Arch, Fedora, Debian 12 and Ubuntu 22.04 or newer.
# Wine comes from WineHQ at 10.0, the Wine that UMU-Proton 10.0-4 is based on;
# Ubuntu's own Wine 6.0 is older than yabridge supports well.
#
# The image and the Wine version are pinned. Other packages come from the
# archive at build time: this is a repeatable build, not a bit-for-bit one,
# and build.json records what it observed.
FROM ubuntu@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02

ARG WINE_VERSION=10.0.0.0~jammy-1
# WineHQ's archive signing key, checked by fingerprint before it is trusted.
ARG WINEHQ_KEY=D43F640145369C51D786DDEA76F1A20FF987672F

ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key -o /tmp/winehq.key \
 && gpg --show-keys --with-colons /tmp/winehq.key | grep -q "^fpr:::::::::$WINEHQ_KEY:" \
 && gpg --dearmor -o /usr/share/keyrings/winehq.gpg /tmp/winehq.key \
 && echo 'deb [signed-by=/usr/share/keyrings/winehq.gpg] https://dl.winehq.org/wine-builds/ubuntu/ jammy main' \
      > /etc/apt/sources.list.d/winehq.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      g++ git make patch ninja-build pkg-config cmake python3 python3-pip binutils \
      libxcb1-dev libdbus-1-dev \
      "wine-stable=$WINE_VERSION" "wine-stable-amd64=$WINE_VERSION" \
      "wine-stable-i386=$WINE_VERSION" "wine-stable-dev=$WINE_VERSION" \
 && rm -rf /var/lib/apt/lists/* /tmp/winehq.key
# Ubuntu's Meson 0.61 cannot find pkg-config for the Wine side of the cross
# build. yabridge's own release builds use Meson from PyPI too.
RUN echo 'meson==1.5.2 --hash=sha256:77706e2368a00d789c097632ccf4fc39251fba56d03e1e1b262559a3c7a08f5b' > /tmp/meson.txt \
 && python3 -m pip install --no-cache-dir --require-hashes -r /tmp/meson.txt \
 && rm /tmp/meson.txt

ENV PATH=/opt/wine-stable/bin:$PATH
RUN useradd --create-home builder
USER builder
WORKDIR /home/builder
