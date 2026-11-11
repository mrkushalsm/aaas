#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
cd "$root"
render_node=${AAAS_DRM_RENDER_NODE:-${AAAS_RENDER_NODE:-}}
if [ -z "$render_node" ]; then
    render_node=$(PYTHONPATH="$root/scripts" python3 -c 'import aaas_graphics; print(aaas_graphics.discover_render_node())')
fi
export AAAS_DRM_RENDER_NODE="$render_node"
log=results/m1a/producer-killed.log
experiments/m1a/build/aaas-m1a "$render_node" > "$log" 2>&1 &
parent=$!
trap 'kill "$parent" 2>/dev/null || :; wait "$parent" 2>/dev/null || :' EXIT
sleep 1
child=$(pgrep -P "$parent" | head -1)
test -n "$child"
kill -KILL "$child"
set +e
wait "$parent"
status=$?
set -e
trap - EXIT
rg -q '"event":"producer_disconnect"' "$log"
test "$status" -ne 139
echo "producer kill handled, presenter exit=$status"
