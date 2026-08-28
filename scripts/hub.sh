#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/knowledgehub ]]; then
  echo "Installing Knowledge Hub into .venv …"
  python3 -m venv .venv
  .venv/bin/pip install -e ".[dev]"
fi

if [[ ! -f .env && -f .env.example ]]; then
  echo "No .env yet. Copy .env.example → .env if you need publish/translate keys."
fi

exec .venv/bin/knowledgehub serve "$@"
