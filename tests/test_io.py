import json
from pathlib import Path

import numpy as np

from conftest import BASELINE_DESIGN
from openair.io import dump_json, load_yaml


def test_dump_json_roundtrip_with_numpy(tmp_path: Path):
    payload = {
        "ok": True,
        "arr": np.array([1.0, 2.0]),
        "scalar": np.float64(3.5),
        "nested": {"n": np.int64(7)},
    }
    p = dump_json(tmp_path / "x.json", payload)
    back = json.loads(p.read_text())
    assert back["ok"] is True
    assert back["arr"] == [1.0, 2.0]
    assert back["scalar"] == 3.5
    assert back["nested"]["n"] == 7


def test_case_yaml_is_mapping():
    data = load_yaml(BASELINE_DESIGN)
    assert isinstance(data, dict)
    for key in ("engine", "wing", "fuselage", "mission", "structures", "solver"):
        assert key in data, key


def test_stage_contract_keys_documented():
    """The QA gates rely on these stage keys; keep them stable."""
    from openair.mdo.problem import evaluate_design
    from openair.cli import load_spec

    spec = load_spec(BASELINE_DESIGN)
    r = evaluate_design(spec)
    for key in (
        "mtow_kg",
        "dash_mps",
        "dash_mach",
        "endurance_s",
        "sm_full",
        "sm_reserve",
        "vstall_mps",
        "washout_required_deg",
        "packing_violation",
        "bay_clearance_m",
        "failure",
    ):
        assert key in r, key
