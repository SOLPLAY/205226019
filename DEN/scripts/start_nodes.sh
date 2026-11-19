#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
for node in node-a node-b node-c; do
    ./scripts/start_node.sh "$node"
done
printf 'Started all DEN nodes. Logs: runtime/node-*.log\n'