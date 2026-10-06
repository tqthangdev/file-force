#!/usr/bin/env bash
# Launch FileForge (Linux/macOS).
#
# Creates the virtual environment and installs the runtime dependencies from
# pyproject.toml if they are missing, then runs run.py.
#
# Usage:
#   ./start.sh [args passed to run.py]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -x "$VENV_PY" ]; then
    echo "Creating virtual environment in $VENV_DIR ..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "$VENV_PY" -c "import PyQt6, PIL, platformdirs" >/dev/null 2>&1; then
    echo "Installing dependencies ..."
    "$VENV_PY" -m pip install --upgrade pip
    "$VENV_PY" -m pip install -e "."
fi

exec "$VENV_PY" run.py "$@"
