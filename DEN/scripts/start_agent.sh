#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec python3 -m node.agent --config "${1:-config/agent.yaml}"
