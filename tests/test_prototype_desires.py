"""A stable feasible fixture must meet the representative mission gates."""

from conftest import FORWARD_SWEPT_DESIGN
from openair.cli import load_spec
from openair.mdo.problem import evaluate_design
from openair.reporting.report import _shape_fidelity


def test_prototype_yaml_revalidates():
    spec = load_spec(FORWARD_SWEPT_DESIGN)
    assert spec.mission.payload_kg == 22.7
    assert "K-450G5" in spec.engine.name
    assert spec.mission.endurance_s == 7200.0


def test_prototype_meets_gates_closed_form():
    spec = load_spec(FORWARD_SWEPT_DESIGN)
    r = evaluate_design(spec)
    lo, hi = spec.mission.static_margin_min, spec.mission.static_margin_max
    assert r["endurance_s"] >= 0.98 * spec.mission.endurance_s, r["endurance_s"]
    assert lo - 0.01 <= r["sm_full"] <= hi + 0.01, r["sm_full"]
    assert lo - 0.01 <= r["sm_reserve"] <= hi + 0.01, r["sm_reserve"]
    assert r["vstall_mps"] <= spec.mission.stall_speed_max_mps + 0.5, r["vstall_mps"]
    assert r["failure"] <= 0.05, r["failure"]
    assert r["packing_violation"] <= 0.001, r["packing_violation"]
    assert r["bay_clearance_m"] >= -0.005, r["bay_clearance_m"]
    assert (
        -0.5
        <= (spec.wing.twist_root_deg - spec.wing.twist_tip_deg)
        - r["washout_required_deg"]
        <= 2.0
    )
    assert r["thrust_margin_cruise"] >= 0.0
    assert r["dash_mach"] <= spec.mission.dash_mach_cap + 0.02


def test_prototype_shape_matches_sketches():
    spec = load_spec(FORWARD_SWEPT_DESIGN)
    rows = _shape_fidelity(spec)
    assert rows["ok"], rows  # audit F5: the shape requirement is a gate
