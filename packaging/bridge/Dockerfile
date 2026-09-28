# The release bridge is built here, not on the packager's machine.
#
# Ubuntu 22.04 sets how old a system the bridge runs on: built here, it needs
# glibc 2.34 and GCC 11's libstdc++, so one build runs on Ubuntu 22.04,
# Debian 12, Fedora 35 and Arch, or anything newer.
# Wine comes from WineHQ at 10.0, the Wine that UMU-Proton 10.0-4 is based on;
# Ubuntu's own Wine 6.0 is older than yabridge supports well.
#
# Everything is pinned: the image by digest, Ubuntu's packages by a dated
# snapshot of the archive, Wine by version, Meson by hash. Changing the
# snapshot date is how the compiler and libraries move, on purpose. The one
# package fetched from the live archive is ca-certificates, which the
# snapshot's HTTPS needs before anything else can come from it.
FROM ubuntu@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02

ARG WINE_VERSION=10.0.0.0~jammy-1
# WineHQ's archive signing key, checked by fingerprint before it is trusted.
ARG WINEHQ_FINGERPRINT=D43F640145369C51D786DDEA76F1A20FF987672F

ARG UBUNTU_SNAPSHOT=20260928T000000Z

ENV DEBIAN_FRONTEND=noninteractive
# Mirrors fail now and then; retry a download before failing the build.
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && sed -i -E "s#http://(archive|security)\.ubuntu\.com/ubuntu/?#https://snapshot.ubuntu.com/ubuntu/$UBUNTU_SNAPSHOT/#" \
      /etc/apt/sources.list \
 && rm -rf /var/lib/apt/lists/*
RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg \
 && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key -o /tmp/winehq.key \
 && gpg --show-keys --with-colons /tmp/winehq.key | grep -q "^fpr:::::::::$WINEHQ_FINGERPRINT:" \
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
