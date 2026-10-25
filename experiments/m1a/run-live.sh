#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"
make -C experiments/m1a all test > results/m1a/build.log 2>&1
set +e
timeout --signal=INT --preserve-status "${AAAS_DURATION:-5}s" experiments/m1a/build/aaas-m1a "${AAAS_RENDER_NODE:-/dev/dri/renderD129}" > results/m1a/runtime.log 2>&1
status=$?
set -e
python3 experiments/m1a/tests/check_trace.py results/m1a/runtime.log
exit "$status"
