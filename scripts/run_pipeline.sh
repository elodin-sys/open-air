#!/usr/bin/env bash
# Thin environment wrapper around the Python concept orchestrator.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate
export LD_LIBRARY_PATH="$ROOT/tools/libs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PATH="$ROOT/tools/openvsp/opt/OpenVSP:$ROOT/tools/su2/bin:${PATH:-}"
export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"
export MAMBA_ROOT_PREFIX="$ROOT/tools/mamba"
export OPENMDAO_REPORTS=0

if [[ $# -ne 1 ]]; then
  echo "usage: $0 designs/<concept-or-design.yaml>" >&2
  exit 2
fi

DESIGN="$1"
exec python -m openair run "$DESIGN"