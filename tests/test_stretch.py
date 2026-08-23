"""Stretch-solver honesty tests. Run with: pytest -m stretch"""

import shutil
from pathlib import Path

import pytest

from conftest import BASELINE_DESIGN
from openair.cli import load_spec

REPO = Path(__file__).resolve().parents[1]
SU2 = shutil.which("SU2_CFD") or (REPO / "tools" / "su2" / "bin" / "SU2_CFD")
MICROMAMBA = REPO / "tools" / "micromamba" / "bin" / "micromamba"

pytestmark = pytest.mark.stretch


@pytest.mark.skipif(not Path(SU2).exists(), reason="SU2_CFD not installed")
def test_su2_2d_euler_reports_convergence_separately(tmp_path: Path):
    from openair.validation.su2_backend import run_su2_stage

    spec = load_spec(BASELINE_DESIGN)
    spec.solver.su2_maxiter = 60  # short run: we test honesty, not convergence
    out = run_su2_stage(
        spec,
        tmp_path,
        {"mach": 0.13, "alpha_deg": 4.0, "CL": 0.35, "CD": 0.03},
        {"mach": 0.30, "alpha_deg": 1.0, "CL": 0.10, "CD": 0.02},
    )
    for label in ("cruise", "dash"):
        pt = out[label]
        assert "converged" in pt, "SU2 'ok' must not stand in for convergence"
        assert pt["mach_cfd"] >= 0.30  # documented low-Mach floor
        if pt["ok"]:
            assert pt["CL"] is not None


@pytest.mark.skipif(not MICROMAMBA.exists(), reason="micromamba tacs env not installed")
def test_tacs_static_runs_and_reports_backend(tmp_path: Path):
    from openair.structures.tacs_backend import run_tacs_stage

    spec = load_spec(BASELINE_DESIGN)
    out = run_tacs_stage(spec, tmp_path, lift_n=100.0 * 9.80665 * 4.0)
    assert out["mesh"]["ok"]
    ana = out["analysis"]
    assert "backend" in ana
    if ana.get("backend") == "tacs":
        assert "maneuver_ks_vm" in ana
        assert ana["maneuver_mass"] > 0.5
        assert ana["modal"]["ok"], ana["modal"]
        assert ana["modal"]["frequencies_hz"][0] > 0.0
