#!/usr/bin/env bash
# Install the hash-pinned Elodin SDK and headless tools outside open-air's venv.

set -euo pipefail

VERSION="0.18.0"
RELEASE_BASE="https://github.com/elodin-sys/elodin/releases/download/v${VERSION}"
WHEEL="elodin-${VERSION}-cp310-abi3-manylinux_2_35_x86_64.whl"
CLI_ARCHIVE="elodin-x86_64-unknown-linux-gnu.tar.gz"
DB_ARCHIVE="elodin-db-x86_64-unknown-linux-musl.tar.gz"
WHEEL_SHA256="ec628f09b9f587fc870cdf81078fb85270a6410ac855f28a228d35154eab57ef"
CLI_SHA256="7491ff872a74348ded8b25f69d7a876ffc7184b5db06394cf4b6c54376e8ce95"
DB_SHA256="fe656aad70edb55538ea30541006df0494205339f507f7d42951136fc2307a9d"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="${REPO_ROOT}/tools/elodin"
TEMP="$(mktemp -d)"
trap 'rm -rf "${TEMP}"' EXIT

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "The pinned Elodin bundle supports Linux x86_64 only." >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/" >&2
  exit 1
fi

download() {
  local name="$1"
  local expected="$2"
  curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
    "${RELEASE_BASE}/${name}" -o "${TEMP}/${name}"
  echo "${expected}  ${TEMP}/${name}" | sha256sum --check --status
}

download "${WHEEL}" "${WHEEL_SHA256}"
download "${CLI_ARCHIVE}" "${CLI_SHA256}"
download "${DB_ARCHIVE}" "${DB_SHA256}"

rm -rf "${INSTALL_ROOT}"
mkdir -p "${INSTALL_ROOT}/bin" "${TEMP}/cli" "${TEMP}/db"
tar -xzf "${TEMP}/${CLI_ARCHIVE}" -C "${TEMP}/cli"
tar -xzf "${TEMP}/${DB_ARCHIVE}" -C "${TEMP}/db"

install_binary() {
  local source_root="$1"
  local binary="$2"
  local candidate
  for candidate in \
    "${source_root}/${binary}" \
    "${source_root}"/*/"${binary}" \
    "${source_root}"/*/bin/"${binary}"
  do
    if [[ -f "${candidate}" ]]; then
      install -m 0755 "${candidate}" "${INSTALL_ROOT}/bin/${binary}"
      return
    fi
  done
  echo "${binary} was not found in the release archive" >&2
  exit 1
}

install_binary "${TEMP}/cli" "elodin"
install_binary "${TEMP}/db" "elodin-db"
uv venv --python 3.13 "${INSTALL_ROOT}/.venv"
uv pip install --python "${INSTALL_ROOT}/.venv/bin/python" \
  "${TEMP}/${WHEEL}"

CLI_VERSION="$("${INSTALL_ROOT}/bin/elodin" --version)"
DB_VERSION="$("${INSTALL_ROOT}/bin/elodin-db" --version)"
CLI_INSTALLED_SHA256="$(sha256sum "${INSTALL_ROOT}/bin/elodin" | cut -d' ' -f1)"
DB_INSTALLED_SHA256="$(sha256sum "${INSTALL_ROOT}/bin/elodin-db" | cut -d' ' -f1)"

cat >"${INSTALL_ROOT}/provenance.json" <<EOF
{
  "version": "${VERSION}",
  "release": "https://github.com/elodin-sys/elodin/releases/tag/v${VERSION}",
  "wheel": {
    "name": "${WHEEL}",
    "sha256": "${WHEEL_SHA256}"
  },
  "cli_archive": {
    "name": "${CLI_ARCHIVE}",
    "sha256": "${CLI_SHA256}",
    "reported_version": "${CLI_VERSION}",
    "installed_sha256": "${CLI_INSTALLED_SHA256}"
  },
  "db_archive": {
    "name": "${DB_ARCHIVE}",
    "sha256": "${DB_SHA256}",
    "reported_version": "${DB_VERSION}",
    "installed_sha256": "${DB_INSTALLED_SHA256}"
  },
  "python": "$("${INSTALL_ROOT}/.venv/bin/python" --version 2>&1)"
}
EOF

"${INSTALL_ROOT}/.venv/bin/python" -c \
  'import elodin; print("Elodin SDK import: ok")'
echo "${CLI_VERSION}"
echo "${DB_VERSION}"
echo "Installed the pinned Elodin runtime under ${INSTALL_ROOT}"
