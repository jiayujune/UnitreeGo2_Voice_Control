#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "Error: local virtual environment Python was not found:"
    echo "  $PYTHON_BIN"
    echo ""
    echo "Create it first, then install dependencies:"
    echo "  cd $SCRIPT_DIR"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/python -m pip install -r requirements.txt"
    exit 1
fi

cd "$SCRIPT_DIR"
if [ "$#" -eq 0 ]; then
    exec "$PYTHON_BIN" voice_llm_talk_v4.py dry
fi

exec "$PYTHON_BIN" voice_llm_talk_v4.py "$@"
