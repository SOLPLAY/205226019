#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
node="${1:-}"
case "$node" in
    node-a|node-b|node-c) ;;
    *) printf 'Usage: %s node-a|node-b|node-c\n' "$0" >&2; exit 2 ;;
esac

mkdir -p runtime
pid_file="runtime/${node}.pid"
if [[ -f "$pid_file" ]]; then
    old_pid="$(<"$pid_file")"
    if kill -0 "$old_pid" 2>/dev/null; then
        printf '%s is already running (pid %s)\n' "$node" "$old_pid" >&2
        exit 1
    fi
    rm -f "$pid_file"
fi

nohup python3 -m node.main --config "config/${node}.yaml" \
    >"runtime/${node}.log" 2>&1 </dev/null &
pid=$!
printf '%s\n' "$pid" >"$pid_file"
sleep 0.2
if ! kill -0 "$pid" 2>/dev/null; then
    printf '%s failed to start; inspect runtime/%s.log\n' "$node" "$node" >&2
    rm -f "$pid_file"
    exit 1
fi
printf 'Started %s (pid %s)\n' "$node" "$pid"
