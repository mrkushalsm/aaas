#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
cd "$root"
log=results/m1a/producer-killed.log
experiments/m1a/build/aaas-m1a "${AAAS_RENDER_NODE:-/dev/dri/renderD129}" > "$log" 2>&1 &
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
