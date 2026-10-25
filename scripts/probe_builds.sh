#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
mkdir -p results/m0/build-probes sources
probe() {
  local name=$1 url=$2 rev=$3 project=$4
  local log="results/m0/build-probes/$name.log"
  (
    printf 'source=%s\nrevision=%s\n' "$url" "$rev"
    if [ ! -d "sources/$name/.git" ]; then
      if ! git clone --filter=blob:none "$url" "sources/$name"; then echo 'RESULT=source-unavailable'; return; fi
    fi
    if ! git -C "sources/$name" checkout --detach "$rev"; then echo 'RESULT=revision-unavailable'; return; fi
    printf 'resolved=%s\n' "$(git -C "sources/$name" rev-parse HEAD)"
    mkdir -p "sources/$name/build"
    cd "sources/$name/build" || return
    if qmake "$project"; then
      if make -j2; then echo 'RESULT=compiled-only-runtime-untested'; else echo 'RESULT=build-failed'; fi
    else echo 'RESULT=configure-failed'; fi
  ) >"$log" 2>&1
  printf '%s: %s\n' "$name" "$(tail -1 "$log")"
}
probe lipstick https://github.com/sailfishos/lipstick.git b220a976699b30d69e00b5a6480ade809fca55ae ../lipstick.pro
probe qt-hwc https://github.com/mer-hybris/qt5-qpa-hwcomposer-plugin.git 31f4f6506702bd872ac47305fc8f8d75f2bb047b ../hwcomposer.pro
