#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
image=aaas-lipstick-m01:debian-bookworm-20261020
mkdir -p "$repo/results/m01/lipstick"
docker build -t "$image" -f "$repo/experiments/lipstick/Dockerfile" "$repo/experiments/lipstick" \
  > "$repo/results/m01/lipstick/image-build.log" 2>&1
docker image inspect "$image" --format '{{.Id}}' > "$repo/results/m01/lipstick/image-id.txt"
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$repo/sources/lipstick,dst=/src/lipstick,readonly" \
  --mount "type=bind,src=$repo/sources/sailfish-qtwayland,dst=/src/qtwayland,readonly" \
  --mount "type=bind,src=$repo/results/m01/lipstick,dst=/work" \
  "$image" sh -ec '
    qmake -v
    pkg-config --modversion Qt5Core Qt5Sensors Qt5WaylandCompositor
    run_dir=$(mktemp -d /work/upstream-run.XXXXXX)
    git clone -q /src/lipstick "$run_dir/lipstick"
    mkdir -p "$run_dir/build"
    cd "$run_dir/build"
    qmake VERSION=0.36.29 "$run_dir/lipstick/lipstick.pro"
    make -j2
  ' > "$repo/results/m01/lipstick/upstream-container.log" 2>&1 && upstream_rc=0 || upstream_rc=$?
printf 'EXIT=%s\n' "$upstream_rc" >> "$repo/results/m01/lipstick/upstream-container.log"
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$repo/sources/lipstick,dst=/src/lipstick,readonly" \
  --mount "type=bind,src=$repo/sources/sailfish-qtwayland,dst=/src/qtwayland,readonly" \
  --mount "type=bind,src=$repo/results/m01/lipstick,dst=/work" \
  "$image" sh -ec '
    cd /work/qtwayland
    qmake /src/qtwayland/qtwayland.pro
    make -j2
  ' > "$repo/results/m01/lipstick/qtwayland-fork.log" 2>&1 && fork_rc=0 || fork_rc=$?
printf 'EXIT=%s\n' "$fork_rc" >> "$repo/results/m01/lipstick/qtwayland-fork.log"
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$repo/sources/sailfish-qtwayland,dst=/src/qtwayland,readonly" \
  --mount "type=bind,src=$repo/results/m01/lipstick,dst=/work" \
  "$image" sh -ec '
    mkdir -p /work/qtw-target2/src
    cd /work/qtw-target2
    qmake /src/qtwayland/qtwayland.pro CONFIG+=wayland-compositor
    cd src
    qmake /src/qtwayland/src/src.pro CONFIG+=wayland-compositor
    make sub-compositor -j2
  ' > "$repo/results/m01/lipstick/qtwayland-compositor-only.log" 2>&1 && compositor_rc=0 || compositor_rc=$?
printf 'EXIT=%s\n' "$compositor_rc" >> "$repo/results/m01/lipstick/qtwayland-compositor-only.log"
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$repo/sources/lipstick,dst=/src/lipstick,readonly" \
  --mount "type=bind,src=$repo/results/m01/lipstick,dst=/work" \
  "$image" sh -ec '
    cd /work/simple
    qmake VERSION=0.36.29 /src/lipstick/tools/simple-compositor/simple-compositor.pro
    make -j2
  ' > "$repo/results/m01/lipstick/simplecompositor-container.log" 2>&1 && simple_rc=0 || simple_rc=$?
printf 'EXIT=%s\n' "$simple_rc" >> "$repo/results/m01/lipstick/simplecompositor-container.log"
printf 'upstream=%s fork=%s compositor-only=%s simplecompositor=%s\n' "$upstream_rc" "$fork_rc" "$compositor_rc" "$simple_rc" \
  > "$repo/results/m01/lipstick/probe-exits.txt"
printf 'logs: %s\n' "$repo/results/m01/lipstick"
