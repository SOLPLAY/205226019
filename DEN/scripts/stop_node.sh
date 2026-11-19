#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
node="${1:-}"
case "$node" in
    node-a|node-b|node-c) ;;
    *) printf 'Usage: %s node-a|node-b|node-c\n' "$0" >&2; exit 2 ;;
esac

pid_file="runtime/${node}.pid"
if [[ ! -f "$pid_file" ]]; then
    printf '%s is not recorded as running\n' "$node"
    exit 0
fi
pid="$(<"$pid_file")"
command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
case "$command_line" in
    *"node.main --config config/${node}.yaml"*) ;;
    *)
        printf 'Refusing to signal pid %s: it is not the recorded %s node\n' "$pid" "$node" >&2
        exit 1
        ;;
esac

kill -TERM "$pid"
for _ in {1..50}; do
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        printf 'Stopped %s\n' "$node"
        exit 0
    fi
    sleep 0.1
done
kill -KILL "$pid"
rm -f "$pid_file"
printf 'Force-stopped %s after graceful shutdown timed out\n' "$node"
