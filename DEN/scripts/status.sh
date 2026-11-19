#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
for node in node-a node-b node-c; do
    printf '\n=== %s ===\n' "$node"
    python3 -m node.main --config "config/${node}.yaml" --status
done
