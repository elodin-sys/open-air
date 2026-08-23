# 11 — Environment: uv, userspace .deb extraction, micromamba

## What it is

Everything installs without sudo. Python deps live in a `uv` venv pinned to
the system Python 3.12 (OpenVSP's ABI); native solvers are vendored under
`tools/` (gitignored); TACS lives in its own micromamba env because it is
conda-only.

## Source and docs

- uv: [docs.astral.sh/uv](https://docs.astral.sh/uv/) ·
  [github.com/astral-sh/uv](https://github.com/astral-sh/uv)
- micromamba: [mamba.readthedocs.io](https://mamba.readthedocs.io/en/latest/user_guide/micromamba.html)
- OpenVSP downloads: [openvsp.org/download.php](https://openvsp.org/download.php)
- SU2 releases: [github.com/su2code/SU2/releases](https://github.com/su2code/SU2/releases)
- Extended notes: [`_research/openvsp.md`](_research/openvsp.md) §6,
  [`_research/tacs.md`](_research/tacs.md) §6

## The layout

```
.venv/                  uv venv on /usr/bin/python3.12 (OpenVSP ABI match)
tools/openvsp/          OpenVSP 3.51.3 Ubuntu-24.04 .deb, extracted (dpkg-deb -x)
tools/libs/             libcminpack1 + libglew2.2 extracted from Ubuntu .debs
tools/su2/bin/          SU2 8.5 linux64-omp binaries (nested zip in the release)
tools/micromamba/       micromamba binary
tools/mamba/            MAMBA_ROOT_PREFIX; env `tacs` (Python 3.10, tacs 3.12.3,
                        channels conda-forge + smdogroup)
tools/elodin/           Elodin 0.18.0 SDK + CLI/DB release, isolated Python
                        3.13 uv venv and hash-recorded provenance
```

Bootstrap: [`scripts/setup_env.sh`](../../scripts/setup_env.sh). Runtime
wiring: [`src/openair/paths.py`](../../src/openair/paths.py) (PATH for
OpenVSP/SU2 binaries, `OPENMDAO_REPORTS=0`) — **but `LD_LIBRARY_PATH` must be
exported by the parent shell** before Python starts; glibc reads it at
process start and `os.environ` edits do not affect the current process's
`dlopen`. This is why `import openvsp` can fail in a bare unit-test shell
while the pipeline works.

```bash
source .venv/bin/activate
export LD_LIBRARY_PATH="$PWD/tools/libs/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
```

## Gotchas that cost us time

- OpenVSP publishes Linux builds as `.deb` only — extract, don't install.
- The `.deb` bundles a CPython **3.12** extension; a venv on any other Python
  fails at `from . import _vsp`.
- SU2's GitHub asset is a zip containing another zip (`linux64-omp.zip`).
- SU2 8.5 prebuilt accepts `MESH_FORMAT= SU2|CGNS` — not GMSH.
- TACS is not on PyPI; `micromamba create -n tacs -c conda-forge -c smdogroup
  python=3.10 tacs` and invoke via
  `micromamba run -n tacs python …` with `MAMBA_ROOT_PREFIX` set.
- OpenMDAO writes `*_out/reports` directories anywhere it runs unless
  `OPENMDAO_REPORTS=0`.
- Elodin 0.18.0 requires Python ≥3.13, so
  [`scripts/install_elodin.sh`](../../scripts/install_elodin.sh) creates a
  separate venv and verifies the wheel, CLI archive, and DB archive hashes.
  Replays run headless with fixed-step RK4 and single-threaded CPU JAX; they do
  not import the RC-jet example's force model.

## Check your work

1. `pytest tests/test_env.py` — imports and versions.
2. `python -c "import openvsp; print(openvsp.GetVSPVersion())"` → 3.51.3.
3. `tools/su2/bin/SU2_CFD` prints the 8.5 banner.
4. `micromamba run -n tacs python -c "import tacs"` exits 0.
5. `tools/elodin/.venv/bin/python -c "import elodin"` and
   `tools/elodin/bin/elodin --version` both succeed; inspect
   `tools/elodin/provenance.json`.
6. Log tool versions into stage JSONs so results trace to binaries.
