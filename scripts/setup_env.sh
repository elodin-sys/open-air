#!/usr/bin/env bash
# Userspace environment bootstrap for the open-air design suite.
# No sudo. OpenVSP is extracted from the Ubuntu .deb; libcminpack/libGLEW
# are extracted from Ubuntu .debs into tools/libs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.12}"
OPENVSP_DEB_URL="${OPENVSP_DEB_URL:-https://openvsp.org/zips/current/linux/OpenVSP-3.51.3-Ubuntu-24.04_amd64.deb}"

mkdir -p tools/libs results

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  uv venv --python "$PYTHON_BIN" .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

uv pip install -e ".$([ -z "${SKIP_DEV:-}" ] && echo '[dev]' || true)" \
  numpy scipy matplotlib openmdao openaerostruct gmsh meshio pydantic pytest pyyaml pandas

# --- OpenVSP prebuilt (Ubuntu 24.04, Python 3.12 ABI) ---
if [[ ! -x tools/openvsp/opt/OpenVSP/vsp ]]; then
  echo "Downloading OpenVSP..."
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/openvsp.deb" "$OPENVSP_DEB_URL"
  mkdir -p tools/openvsp
  dpkg-deb -x "$tmp/openvsp.deb" tools/openvsp
  rm -rf "$tmp"
fi

# Shared libraries the OpenVSP .so needs that are not on a stock PATH
if [[ ! -e tools/libs/usr/lib/x86_64-linux-gnu/libcminpack.so.1 ]]; then
  tmp="$(mktemp -d)"
  (cd "$tmp" && apt-get download libcminpack1 libglew2.2)
  dpkg-deb -x "$tmp"/libcminpack1_*.deb tools/libs
  dpkg-deb -x "$tmp"/libglew2.2_*.deb tools/libs || true
  rm -rf "$tmp"
fi

export LD_LIBRARY_PATH="$ROOT/tools/libs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
export PATH="$ROOT/tools/openvsp/opt/OpenVSP:${PATH:-}"

VSPPY="$ROOT/tools/openvsp/opt/OpenVSP/python"
if ! python -c "import openvsp" 2>/dev/null; then
  uv pip install "$VSPPY/openvsp_config" "$VSPPY/utilities" "$VSPPY/degen_geom" "$VSPPY/openvsp"
fi

python - <<'PY'
import numpy, scipy, matplotlib, openmdao, openaerostruct, gmsh, meshio, pydantic, yaml
print("numpy", numpy.__version__)
print("openmdao", openmdao.__version__)
print("openaerostruct", openaerostruct.__version__)
import openvsp as vsp
print("openvsp", vsp.GetVSPVersion())
print("ENV_OK")
PY

echo "setup_env.sh complete. Activate with: source .venv/bin/activate"
echo "Also export LD_LIBRARY_PATH=$ROOT/tools/libs/usr/lib/x86_64-linux-gnu"
