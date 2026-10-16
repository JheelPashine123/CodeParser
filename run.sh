#!/usr/bin/env bash
# ==============================================================================
# GraphAgent Standalone 1-Command Runner
# Can be run on any computer with Python 3.9+ to parse any repository.
# Usage:
#   ./run.sh .
#   ./run.sh /path/to/repository
# ==============================================================================
set -e

TARGET_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="${HOME}/.cache/graphagent"
VENV_DIR="${CACHE_DIR}/venv"

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed or not in PATH."
    exit 1
fi

# 2. Bootstrap cached virtual environment if not already present
if [ ! -f "${VENV_DIR}/bin/graphagent" ]; then
    echo "⚡ First-time setup: Initializing portable parser environment in ${CACHE_DIR}..."
    mkdir -p "${CACHE_DIR}"
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --upgrade --quiet pip
    "${VENV_DIR}/bin/pip" install --quiet "${SCRIPT_DIR}"
    echo "✅ Setup complete!"
fi

# 3. Execute graphagent directly
"${VENV_DIR}/bin/graphagent" parse "${TARGET_DIR}" "${@:2}"
