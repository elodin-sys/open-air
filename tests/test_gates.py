from conftest import BASELINE_DESIGN
from openair.atmosphere import isa
from openair.cli import _select_auto_retry, load_spec
from openair.reporting.gates import (
    _reproduction_changed_paths,
    evaluate_gates,
    feedback_from_gates,
    format_gate_table,
)


def _passing_context():
    spec = load_spec(BASELINE_DESIGN)
    washout = spec.wing.twist_root_deg - spec.wing.twist_tip_deg
    dash_mps = 100.0
    dash_mach = dash_mps / isa(spec.mission.dash_altitude_m).speed_of_sound_mps
    data = {
        "_schema": {"source_ok": True, "optimized_ok": True, "errors": []},
        "geometry": {
            "packing": {"ok": True, "margin_fuel_m3": 0.01},
            "openvsp": {
                "readback": {"matches_spec": True},
                "stl_bbox": {"ok": True},
                "mesh_checks": {"ok": True, "checks": [{"ok": True}]},
            },
        },
        "aero": {
            "mtow_kg": 100.0,
            "cruise": {
                "drag_n": 50.0,
                "buildup_lod": 10.0,
                "engine": {"thrust_available_n": 60.0},
            },
            "dash": {
                "tas_mps": dash_mps,
                "buildup": {"drag_n": 100.0, "tas_mps": dash_mps},
                "engine": {"thrust_available_n": 101.0},
            },
            "trim": {
                "converged": True,
                "washout_trim_deg": washout,
                "cm_residual": 0.0,
            },
            "stability": {"ok": True, "sm_full": 0.06, "sm_reserve": 0.07},
            "balance": {
                "stall_ok": True,
                "vstall_mps": 25.0,
                "vv_ok": True,
                "vv": 0.04,
                "vv_band": [0.02, 0.09],
            },
        },
        "structures": {
            "ok": True,
            "positive_g": {
                "failure": -0.1,
                "tip_disp_m": 0.01,
                "CL": 1.0,
                "required_CL": 1.0,
                "lift_closure_ok": True,
                "cl_domain_ok": True,
                "aerodynamic_domain_ok": True,
                "mass_closure_ok": True,
            },
            "negative_g": {
                "failure": -0.1,
                "lift_closure_ok": True,
                "cl_domain_ok": True,
                "aerodynamic_domain_ok": True,
                "mass_closure_ok": True,
            },
        },
        "validation": {
            "core_passed": 1,
            "core_total": 1,
            "checks": [
                {
                    "name": "vspaero_vs_oas_CL",
                    "ok": True,
                    "CL_ratio_vspaero_over_oas": 1.02,
                }
            ],
        },
        "report": {
            "desires": {
                "shape_ok": True,
                "dash_mps": dash_mps,
                "dash_mach": dash_mach,
                "endurance_hr_pred": spec.mission.endurance_s / 3600.0,
                "mtow_kg": 100.0,
                "fuel_kg": spec.mass.fuel_mass_kg,
                "cruise_lod": 10.0,
            }
        },
        "mdo": {
            "ok": True,
            "best": {
                "feasible": True,
                "driver_success": True,
                "dash_mps": dash_mps,
                "endurance_s": spec.mission.endurance_s,
                "mtow_kg": 100.0,
                "lod": 10.0,
                "dvs": {"fuel": spec.mass.fuel_mass_kg},
            },
            "oas_verify": {"ok": True},
            "starts": [{}, {}, {}],
        },
    }
    metrics = {
        "endurance_hr": spec.mission.endurance_s / 3600.0,
        "dash_kmh": dash_mps * 3.6,
        "mtow_kg": 100.0,
        "fuel_kg": spec.mass.fuel_mass_kg,
        "span_m": spec.wing.span_m,
        "lod": 10.0,
    }
    return spec, data, metrics


def test_unified_gate_contract_has_tiers_and_actions():
    spec, data, metrics = _passing_context()
    gates = evaluate_gates(spec, data, metrics)
    assert len(gates) == 12
    assert all(gate["ok"] for gate in gates)
    assert {gate["tier"] for gate in gates} == {"A", "B", "C"}
    assert all(gate["meaning"] and gate["upstream_knob"] for gate in gates)
    table = format_gate_table(
        feedback_from_gates(gates, data["validation"], concept="demo")
    )
    assert "12/12 gates pass" in table


def test_geometry_truth_gate_folds_in_reference_fidelity():
    spec, data, metrics = _passing_context()
    fidelity = {
        "available": True,
        "ok": False,
        "gates_stage_ok": False,
        "distance_model_to_reference": {"p95_m": 0.0177},
        "silhouettes": {"top": {"iou": 0.85}, "side": {"iou": 0.78}},
    }
    data["geometry"]["reference_fidelity"] = fidelity
    gates = evaluate_gates(spec, data, metrics)
    geometry = next(gate for gate in gates if gate["id"] == "geometry_truth")
    # Recorded only: an inspiration/requirement design still passes on
    # read-back, bbox, and mesh checks, but the evidence is disclosed.
    assert geometry["ok"]
    assert "whole aircraft 17.7 mm" in geometry["evidence"]
    assert "not gating" in geometry["evidence"]

    fidelity["gates_stage_ok"] = True
    gates = evaluate_gates(spec, data, metrics)
    geometry = next(gate for gate in gates if gate["id"] == "geometry_truth")
    assert not geometry["ok"]
    assert "outside band" in geometry["evidence"]
    assert len(gates) == 12


def test_mdo_gate_rejects_failed_driver_even_when_candidate_is_feasible():
    spec, data, metrics = _passing_context()
    data["mdo"]["best"]["driver_success"] = False

    gates = evaluate_gates(spec, data, metrics)
    mdo_gate = next(gate for gate in gates if gate["id"] == "mdo_honesty")

    assert not mdo_gate["ok"]
    assert "driver=no" in mdo_gate["evidence"]


def test_structures_gate_rejects_an_underloaded_maneuver_solution():
    spec, data, metrics = _passing_context()
    data["structures"]["positive_g"]["lift_closure_ok"] = False

    gates = evaluate_gates(spec, data, metrics)
    structures = next(gate for gate in gates if gate["id"] == "structures")

    assert not structures["ok"]
    assert "lift closed=no" in structures["evidence"]


def test_structures_gate_rejects_extrapolative_or_mass_open_solution():
    spec, data, metrics = _passing_context()
    data["structures"]["positive_g"]["aerodynamic_domain_ok"] = False
    gates = evaluate_gates(spec, data, metrics)
    assert not next(gate for gate in gates if gate["id"] == "structures")["ok"]

    data["structures"]["positive_g"]["aerodynamic_domain_ok"] = True
    data["structures"]["positive_g"]["mass_closure_ok"] = False
    gates = evaluate_gates(spec, data, metrics)
    assert not next(gate for gate in gates if gate["id"] == "structures")["ok"]


def test_reproduction_gates_do_not_claim_optimization_or_full_vv_band():
    spec, data, metrics = _passing_context()
    assert spec.sketch is not None
    spec.sketch.treatment = "reproduction"
    data["_schema"]["reproduction_frozen_ok"] = True
    data["aero"]["balance"]["vv"] = 0.12

    gates = evaluate_gates(spec, data, metrics)
    directional = next(gate for gate in gates if gate["id"] == "directional_stability")
    closure = next(gate for gate in gates if gate["id"] == "mdo_honesty")

    assert directional["name"] == "Directional authority"
    assert "no upper-band sizing claim" in directional["meaning"]
    assert closure["name"] == "Reproduction closure honesty"
    assert "remain frozen" in closure["meaning"]

    data["_schema"]["reproduction_frozen_ok"] = False
    gates = evaluate_gates(spec, data, metrics)
    assert not next(gate for gate in gates if gate["id"] == "schema")["ok"]
    assert not next(gate for gate in gates if gate["id"] == "mdo_honesty")["ok"]


def test_reproduction_diff_allows_only_trim_and_same_run_stability_constants():
    source = load_spec("designs/ceras-csr01/design.yaml")
    delivered = source.model_copy(deep=True)
    delivered.htail.incidence_deg = -3.2
    delivered.solver.np_shift_mac = -0.01
    delivered.solver.wing_body_np_mac = 0.22
    delivered.solver.wing_body_cl_alpha_per_deg = 0.1

    assert _reproduction_changed_paths(source, delivered) == []

    delivered.wing.span_m += 0.1
    assert _reproduction_changed_paths(source, delivered) == ["wing.span_m"]


def test_traceability_gate_rejects_cross_phase_mtow_mismatch():
    spec, data, metrics = _passing_context()
    data["aero"]["mtow_kg"] = 98.0

    gates = evaluate_gates(spec, data, metrics)
    trace_gate = next(
        gate for gate in gates if gate["id"] == "cross_checks_traceability"
    )

    assert not trace_gate["ok"]
    assert "100.000/98.000/100.000" in trace_gate["evidence"]


def test_schema_gate_fails_closed_on_invalid_delivered_spec():
    spec, data, metrics = _passing_context()
    data["_schema"]["optimized_ok"] = False
    data["_schema"]["errors"] = ["optimized: validation failed"]

    gates = evaluate_gates(spec, data, metrics)
    schema_gate = next(gate for gate in gates if gate["id"] == "schema")

    assert not schema_gate["ok"]
    assert "validation failed" in schema_gate["evidence"]


def test_schema_gate_rejects_changed_source_requirements():
    spec, data, metrics = _passing_context()
    data["report"]["desires"]["engine_met"] = False
    data["report"]["desires"]["payload_met"] = True

    gates = evaluate_gates(spec, data, metrics)
    schema_gate = next(gate for gate in gates if gate["id"] == "schema")

    assert not schema_gate["ok"]
    assert "engine requirement=no" in schema_gate["evidence"]


def test_shape_gate_recomputes_fidelity_instead_of_trusting_report_flag():
    spec, data, metrics = _passing_context()
    assert data["report"]["desires"]["shape_ok"]
    spec.wing.span_m *= 2.0

    gates = evaluate_gates(spec, data, metrics)
    shape_gate = next(gate for gate in gates if gate["id"] == "shape_fidelity")

    assert not shape_gate["ok"]


def test_traceability_gate_rejects_cruise_lod_mismatch():
    spec, data, metrics = _passing_context()
    data["aero"]["cruise"]["buildup_lod"] = 9.5

    gates = evaluate_gates(spec, data, metrics)
    trace_gate = next(
        gate for gate in gates if gate["id"] == "cross_checks_traceability"
    )

    assert not trace_gate["ok"]
    assert "10.000/9.500/10.000" in trace_gate["evidence"]


def test_inspiration_mdo_gate_requires_converged_calibration_history():
    spec, data, metrics = _passing_context()
    assert spec.sketch is not None
    spec.sketch.treatment = "inspiration"
    data["mdo"]["calibration_converged"] = False
    data["mdo"]["calibration_history"] = [{"converged": False}]

    gates = evaluate_gates(spec, data, metrics)
    mdo_gate = next(gate for gate in gates if gate["id"] == "mdo_honesty")
    assert not mdo_gate["ok"]

    data["mdo"]["calibration_converged"] = True
    data["mdo"]["calibration_history"][-1]["converged"] = True
    gates = evaluate_gates(spec, data, metrics)
    assert next(gate for gate in gates if gate["id"] == "mdo_honesty")["ok"]


def test_pitch_trim_gate_accepts_verified_tail_incidence_control():
    spec, data, metrics = _passing_context()
    spec.htail.span_m = 0.8
    spec.htail.incidence_deg = 1.25
    data["aero"]["trim"] = {
        "converged": True,
        "control": "tail_incidence",
        "tail_incidence_trim_deg": 1.2,
        "cm_residual": 0.0005,
    }

    gates = evaluate_gates(spec, data, metrics)
    trim_gate = next(gate for gate in gates if gate["id"] == "pitch_trim")

    assert trim_gate["ok"]
    assert "tail incidence" in trim_gate["evidence"]


def test_wing_mass_failure_requests_one_tier_b_retry():
    spec, data, metrics = _passing_context()
    data["validation"]["checks"].append(
        {
            "name": "wing_mass_buildup_vs_oas",
            "ok": False,
            "got": 24.5,
            "want": 8.0,
            "ratio": 3.06,
        }
    )
    data["validation"]["core_total"] = 2
    gates = evaluate_gates(spec, data, metrics)
    feedback = feedback_from_gates(
        gates,
        data["validation"],
        concept="demo",
    )
    assert feedback["passed"] == 11
    candidate = feedback["retry_candidates"][0]
    assert candidate["key"] == "wing_mass_buildup_vs_oas"
    assert candidate["tier"] == "B"
    retry = _select_auto_retry(feedback)
    assert retry is not None
    assert retry["overlay"]["wing_mass_override_kg"] == 24.5

    candidate["tier"] = "C"
    assert _select_auto_retry(feedback) is None
