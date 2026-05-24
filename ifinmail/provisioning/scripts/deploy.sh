#!/usr/bin/env bash
# Backward-compatible name for the production provisioning entry point.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/provision.sh" "$@"
