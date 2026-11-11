#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"
render_node=${AAAS_DRM_RENDER_NODE:-${AAAS_RENDER_NODE:-}}
if [ -z "$render_node" ]; then
    render_node=$(PYTHONPATH="$root/scripts" python3 -c 'import aaas_graphics; print(aaas_graphics.discover_render_node())')
fi
export AAAS_DRM_RENDER_NODE="$render_node"
make -C experiments/m1a all test > results/m1a/build.log 2>&1
set +e
timeout --signal=INT --preserve-status "${AAAS_DURATION:-5}s" experiments/m1a/build/aaas-m1a "$render_node" > results/m1a/runtime.log 2>&1
status=$?
set -e
python3 experiments/m1a/tests/check_trace.py results/m1a/runtime.log
exit "$status"
