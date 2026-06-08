#!/usr/bin/env bash
# Start the FastAPI backend. Real robot execution stays OFF unless GO2_EXECUTE=1.
set -euo pipefail
cd "$(dirname "$0")/backend"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

exec ./.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8001 --reload
