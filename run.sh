#!/usr/bin/env bash
# Single-command runner: creates/reuses a venv, installs deps, runs the CLI.
# Usage:
#   ./run.sh rank --profile healthcare_services_default
#   ./run.sh rank --all-profiles
#   MOCK_LLM=1 ./run.sh rank --profile healthcare_services_default   # no API key needed
#   ./run.sh enrich
#   ./run.sh serve --port 8000

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python -m app "$@"
