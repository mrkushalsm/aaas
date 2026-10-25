FROM debian@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8

# Timestamp matches the base image's recorded Debian snapshot. No host package changes.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates && \
  printf '%s\n' \
  'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261020T213255Z/ bookworm main' \
  'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20261020T213255Z/ bookworm-updates main' \
  'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20261020T213255Z/ bookworm-security main' \
  > /etc/apt/sources.list && rm /etc/apt/sources.list.d/debian.sources && \
  apt-get -o Acquire::Check-Valid-Until=false update && \
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential pkg-config git python3 \
    qtbase5-dev qtbase5-private-dev qtdeclarative5-dev qtdeclarative5-private-dev \
    libqt5waylandcompositor5-dev qtwayland5-private-dev qtwayland5-dev-tools \
    libqt5sensors5-dev qttools5-dev-tools \
    libwayland-dev wayland-protocols libegl1-mesa-dev libdbus-1-dev \
    libglib2.0-dev libsystemd-dev && \
  rm -rf /var/lib/apt/lists/*

USER 1000:1000
WORKDIR /work
