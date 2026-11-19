#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
for node in node-a node-b node-c; do
    ./scripts/stop_node.sh "$node"
done