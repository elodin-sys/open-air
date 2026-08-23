import hashlib
import json
import warnings

import pytest

from conftest import BASELINE_DESIGN, INSPIRATION_DESIGN, TRIM_INFEASIBLE_DESIGN
from openair.cli import load_spec
from openair.mdo.problem import (
    DV_BOUNDS,
    ENDURANCE_CONSTRAINT_MARGIN_S,
    STALL_CONSTRAINT_MARGIN_MPS,
    VV_CONSTRAINT_MARGIN,
    _add_dvs_and_cons,
    _apply_dvs,
    _calibrated_np_shift_mac,
    _clip_start,
    _enable_htail_fallback,
    _is_feasible,
    _recalibrated_tail_incidence_offset,
    _spec_dvs,
    _tighten_sm_bounds,
    _with_serialized_hybrid_calibration,
    dv_bounds_for,
    evaluate_design,
    run_mdo_stage,
)


def test_hybrid_calibration_requires_current_serialized_geometry(tmp_path):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.solver.stability_method = "hybrid_component"
    vsp3 = tmp_path / "aircraft.vsp3"
    vsp3.write_bytes(b"current geometry")
    hybrid = {
        "ok": True,
        "neutral_point_mac": 0.12,
        "cl_alpha_per_deg": 0.08,
        "source": str(vsp3),
        "vsp3_sha256": "0" * 64,
    }
    (tmp_path / "aero.json").write_text(
        json.dumps({"stability": {"hybrid_component": hybrid}}),
        encoding="utf-8",
    )

    _, stale = _with_serialized_hybrid_calibration(spec, tmp_path)
    assert stale is not None
    assert not stale["ok"]
    assert stale["reason"] == "stale_or_untraceable_hybrid_vsp3_evidence"

    hybrid["vsp3_sha256"] = hashlib.sha256(b"current geometry").hexdigest()
    (tmp_path / "aero.json").write_text(
        json.dumps({"stability": {"hybrid_component": hybrid}}),
        encoding="utf-8",
    )
    calibrated, fresh = _with_serialized_hybrid_calibration(spec, tmp_path)
    assert fresh is not None
    assert fresh["freshness"]["ok"]
    assert calibrated.solver.wing_body_np_mac == pytest.approx(0.12)


@pytest.mark.slow
def test_mdo_smoke(tmp_path):
    spec = load_spec(BASELINE_DESIGN)
    spec.mass.fuel_mass_kg = 46.0  # a sizing closure just above the MDO cap
    spec.solver.optimize_maxiter = 3
    spec.solver.optimize_tol = 1e-3
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = run_mdo_stage(spec, tmp_path, None)
    assert not any(
        "initial conditions are out of their specified bounds" in str(item.message)
        for item in caught
    )
    assert "best" in result
    assert result["best"]["dash_mps"] > 30.0
    yaml_path = tmp_path / "design.yaml"
    assert yaml_path.exists()
    # The published YAML must re-validate and stay inside the sketch envelope
    opt = load_spec(yaml_path)
    lo, hi = DV_BOUNDS["span"]
    assert lo - 1e-6 <= opt.wing.span_m <= hi + 1e-6
    lo, hi = DV_BOUNDS["sweep"]
    assert lo - 1e-6 <= opt.wing.le_sweep_deg <= hi + 1e-6
    # and re-evaluate through the same physics without error
    r = evaluate_design(opt)
    assert r["endurance_s"] > 1000.0


def test_dv_bounds_encode_sketch_envelope():
    """Audit F5: the bounds ARE the desires.md shape requirement."""
    length = 2.45
    assert DV_BOUNDS["span"][0] / length >= 1.30
    assert DV_BOUNDS["span"][1] / length <= 1.80
    assert DV_BOUNDS["root_chord"][0] / length >= 0.40
    assert 28.0 <= DV_BOUNDS["sweep"][0] and DV_BOUNDS["sweep"][1] <= 36.0


def test_dv_bounds_follow_concept_sketch():
    from openair.schemas import SketchEnvelopeSpec

    spec = load_spec(BASELINE_DESIGN)
    assert dv_bounds_for(spec)["sweep"] == DV_BOUNDS["sweep"]
    spec = spec.model_copy(deep=True)
    spec.sketch = SketchEnvelopeSpec(
        span_over_length=1.51,
        span_over_length_tol=0.16,
        root_over_length=0.49,
        root_over_length_tol=0.08,
        le_sweep_deg=-24.0,
        le_sweep_tol_deg=5.0,
        taper=0.50,
        taper_tol=0.12,
        x_le_root_over_length=0.53,
        x_le_root_over_length_tol=0.07,
    )
    bounds = dv_bounds_for(spec)
    assert bounds["sweep"][1] < 0
    assert bounds["sweep"][0] == pytest.approx(-29.0)
    assert bounds["taper"][0] == pytest.approx(0.38)


def test_inspiration_bounds_expand_and_add_continuous_fin_design_vars():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    assert spec.sketch is not None
    requirement_bounds = dv_bounds_for(spec)
    spec.sketch.treatment = "inspiration"
    spec.sketch.hard_scale = 3.0
    spec.sketch.fin_span_m = spec.vtail.span_m
    spec.sketch.fin_span_tol_m = 0.05
    spec.sketch.fin_root_chord_m = spec.vtail.root_chord_m
    spec.sketch.fin_root_chord_tol_m = 0.04
    inspired_bounds = dv_bounds_for(spec)

    assert inspired_bounds["span"][0] < requirement_bounds["span"][0]
    assert inspired_bounds["span"][1] > requirement_bounds["span"][1]
    assert set(
        (
            "fin_span",
            "fin_root_chord",
            "fin_sweep",
            "fin_cant",
            "fin_x_le",
        )
    ).issubset(inspired_bounds)
    assert "dihedral" not in inspired_bounds

    dvs = _spec_dvs(spec)
    dvs.update(
        dihedral=4.0,
        fin_span=inspired_bounds["fin_span"][1],
        fin_root_chord=inspired_bounds["fin_root_chord"][1],
    )
    changed = _apply_dvs(spec, dvs)
    assert changed.wing.dihedral_deg == 4.0
    assert changed.vtail.span_m == inspired_bounds["fin_span"][1]

    tailed = spec.model_copy(deep=True)
    tailed.htail.span_m = 0.8
    tailed_bounds = dv_bounds_for(tailed)
    assert "htail_incidence" in tailed_bounds
    assert "twist_root" not in tailed_bounds
    assert "twist_tip" not in tailed_bounds


def test_requirement_bounds_keep_small_aircraft_inputs_and_tailed_controls():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    assert spec.sketch is not None
    spec.sketch.treatment = "requirement"
    spec.sketch.fin_span_m = spec.vtail.span_m
    spec.sketch.fin_span_tol_m = 0.03
    spec.sketch.fin_root_chord_m = spec.vtail.root_chord_m
    spec.sketch.fin_root_chord_tol_m = 0.04
    spec.sketch.fuel_tank_x_lo_m = None
    spec.sketch.fuel_tank_x_hi_m = None
    spec.mass.fuel_mass_kg = 5.0
    spec.fuselage.fuel_tank_x_m = 0.8
    spec.htail.span_m = 0.8

    bounds = dv_bounds_for(spec)

    assert bounds["fuel"][0] <= spec.mass.fuel_mass_kg <= bounds["fuel"][1]
    assert (
        bounds["fuel_tank_x"][0]
        <= spec.fuselage.fuel_tank_x_m
        <= bounds["fuel_tank_x"][1]
    )
    assert "fin_span" in bounds
    assert "fin_root_chord" in bounds
    assert "fin_cant" not in bounds
    assert "htail_incidence" in bounds
    assert "twist_root" not in bounds
    assert "twist_tip" not in bounds

    spec.mass.fuel_mass_mode = "fixed"
    fixed_bounds = dv_bounds_for(spec)
    assert "fuel" not in fixed_bounds
    fixed_inputs = {key: _spec_dvs(spec)[key] for key in fixed_bounds} | {"fuel": 99.0}
    assert _apply_dvs(spec, fixed_inputs).mass.fuel_mass_kg == 5.0


def test_reproduction_freezes_all_design_variables_and_defers_trim_to_verify():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    assert spec.sketch is not None
    spec.sketch.treatment = "reproduction"
    spec.htail.span_m = 0.8
    candidate = {
        "endurance_deficit_s": -1.0,
        "failure": -0.1,
        "packing_violation": -0.1,
        "bay_clearance_m": 0.1,
        "thrust_margin_cruise": 0.1,
        "sm_full": 0.05,
        "sm_reserve": 0.06,
        "vstall_margin_mps": -1.0,
        # The deterministic branch publishes independently verified OAS trim.
        "washout_gap_deg": 9.0,
    }

    assert dv_bounds_for(spec) == {}
    assert _is_feasible(candidate, spec)


def test_reproduction_np_shift_calibration_inverts_same_geometry_oas_error():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    old_shift = spec.solver.np_shift_mac
    modeled_np_m = 1.2
    measured_np_m = 1.2 - 0.06 * spec.wing.mac_m

    calibrated = _calibrated_np_shift_mac(spec, measured_np_m, modeled_np_m)

    assert calibrated == pytest.approx(old_shift - 0.06)


def test_inspiration_and_trim_fallback_fixtures_exercise_repair_physics():
    inspired = load_spec(INSPIRATION_DESIGN)
    assert inspired.sketch is not None
    assert inspired.sketch.treatment == "inspiration"
    assert evaluate_design(inspired)["vv_lower_violation"] > 0.0
    assert "fin_span" in dv_bounds_for(inspired)

    blocked = load_spec(TRIM_INFEASIBLE_DESIGN)
    assert abs(evaluate_design(blocked)["washout_gap_deg"]) > 0.75
    repaired = _enable_htail_fallback(blocked)
    repaired_metrics = evaluate_design(repaired)
    assert repaired.htail.span_m > 0.05
    assert abs(repaired_metrics["washout_gap_deg"]) < 0.1


def test_mdo_mass_objective_feels_structure_gauges():
    spec = load_spec(BASELINE_DESIGN)
    base = evaluate_design(spec)
    thinner = spec.model_copy(deep=True)
    thinner.structures.skin_thickness_m *= 0.8
    thinner.structures.spar_thickness_m *= 0.8
    light = evaluate_design(thinner)
    assert light["mtow_kg"] < base["mtow_kg"]


def test_first_mdo_start_is_clipped_to_all_bounds():
    spec = load_spec(BASELINE_DESIGN)
    spec.mass.fuel_mass_kg = 99.0
    bounds = dv_bounds_for(spec)
    start = _clip_start(_spec_dvs(spec), bounds)
    assert set(start) == set(bounds)
    assert all(
        bounds[key][0] <= value <= bounds[key][1] for key, value in start.items()
    )


def test_mdo_design_variables_are_scaled_to_their_bounds():
    class RecordingModel:
        def __init__(self):
            self.design_vars = {}
            self.constraints = {}

        def add_design_var(self, name, **kwargs):
            self.design_vars[name] = kwargs

        def add_constraint(self, name, **kwargs):
            self.constraints[name] = kwargs

        def add_objective(self, *_args, **_kwargs):
            pass

    class RecordingProblem:
        model = RecordingModel()

    spec = load_spec(INSPIRATION_DESIGN)
    bounds = dv_bounds_for(spec)
    problem = RecordingProblem()
    _add_dvs_and_cons(problem, spec)

    assert set(problem.model.design_vars) == set(bounds)
    for name, (lo, hi) in bounds.items():
        assert problem.model.design_vars[name]["ref0"] == lo
        assert problem.model.design_vars[name]["ref"] == hi
    assert problem.model.constraints["vv_lower_violation"]["upper"] == (
        -VV_CONSTRAINT_MARGIN
    )
    assert problem.model.constraints["endurance_deficit_s"]["upper"] == (
        -ENDURANCE_CONSTRAINT_MARGIN_S
    )
    assert problem.model.constraints["vstall_margin_mps"]["upper"] == (
        -STALL_CONSTRAINT_MARGIN_MPS
    )


def test_sm_tightening_uses_only_post_recalibration_residual():
    bounds = (0.03, 0.10)
    measured = {"sm_full": 0.12, "sm_reserve": 0.14}
    modeled_after = {"sm_full": 0.12, "sm_reserve": 0.14}

    tightened = _tighten_sm_bounds(bounds, measured, bounds, modeled_after)

    assert tightened == pytest.approx((0.032, 0.098))


def test_recalibration_loop_converges_and_publishes_constants(tmp_path, monkeypatch):
    import math

    import openair.mdo.problem as problem
    from openair.mission.balance import balance_report

    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    assert spec.sketch is not None
    spec.sketch.treatment = "inspiration"
    spec.solver.np_shift_mac = 0.15

    def fake_optimize(current, _outdir, _sm_bounds, record):
        del record
        metrics = evaluate_design(current)
        dvs = {key: _spec_dvs(current)[key] for key in dv_bounds_for(current)}
        candidate = {
            "start": 0,
            "objective": -metrics["dash_mps"] / 100.0,
            **metrics,
            "dvs": dvs,
            "feasible": True,
            "driver_success": True,
            "driver_status": "success",
            "driver_iterations": 2,
        }
        return candidate, [candidate.copy()]

    def fake_verify(current, best, _source):
        bal = balance_report(current, best["mtow_kg"], best["dvs"]["fuel"])
        reference = math.tan(math.radians(current.sketch.le_sweep_deg))
        ratio = math.tan(math.radians(current.wing.le_sweep_deg)) / reference
        measured_np = (
            current.wing.x_le_mac_m + (0.25 + 0.08 * abs(ratio)) * current.wing.mac_m
        )
        return {
            "ok": True,
            "stability_measured": {
                "x_np_m": measured_np,
                "x_np_model_m": bal.x_np_m,
                "sm_full": 0.05,
                "sm_reserve": 0.06,
                "ok": True,
            },
            "aero_trim": {
                "washout_trim_deg": 5.0,
                "CL": current.mission.cruise_cl,
            },
        }

    monkeypatch.setattr(problem, "_optimize_starts", fake_optimize)
    monkeypatch.setattr(problem, "_verify_with_oas", fake_verify)

    result = problem.run_mdo_stage(spec, tmp_path)
    delivered = load_spec(tmp_path / "design.yaml")

    assert result["calibration_converged"]
    assert len(result["calibration_history"]) == 2
    assert result["calibration_history"][-1]["np_error_mac"] == pytest.approx(0.0)
    assert result["calibration_history"][-1]["final_published_verify_ok"]
    assert result["calibration_history"][-1][
        "final_published_np_error_mac"
    ] == pytest.approx(0.0)
    assert delivered.solver.np_shift_mac == pytest.approx(0.08)
    assert delivered.solver.cm_washout_per_deg != spec.solver.cm_washout_per_deg


def test_htail_fallback_runs_only_after_all_tailless_branches_fail(
    tmp_path,
    monkeypatch,
):
    import openair.mdo.problem as problem

    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    assert spec.sketch is not None
    spec.sketch.treatment = "inspiration"
    calls = []

    def fake_branch(branch_spec, _outdir, *, source_spec, record):
        del source_spec, record
        tail_enabled = branch_spec.htail.span_m > 0.05
        calls.append((branch_spec.wing.airfoil, tail_enabled))
        return {
            "ok": tail_enabled,
            "best": {
                "feasible": tail_enabled,
                "driver_success": True,
                "objective": -0.8 if tail_enabled else -0.7,
                "dash_mps": 80.0 if tail_enabled else 70.0,
            },
            "starts": [],
            "calibration_history": [],
            "calibration_converged": tail_enabled,
            "sm_calibration": [],
            "oas_verify": {"ok": tail_enabled},
            "dv_bounds": {},
            "_optimized_spec": branch_spec,
        }

    monkeypatch.setattr(problem, "_run_calibrated_branch", fake_branch)
    monkeypatch.setattr(problem, "_fidelity_sweep", lambda *_args: [])
    monkeypatch.setattr(problem, "_departure_audit", lambda *_args: [])

    result = problem.run_mdo_stage(spec, tmp_path)
    delivered = load_spec(tmp_path / "design.yaml")

    assert calls[:3] == [("0012", False), ("2412", False), ("4412", False)]
    assert len(calls) == 4
    assert calls[-1] == ("0012", True)
    assert result["branch_topology"] == "htail"
    assert delivered.htail.span_m > 0.05


def test_post_verify_htail_feasibility_uses_conceptual_tail_tolerance():
    candidate = {
        "endurance_deficit_s": 0.0,
        "failure": -0.1,
        "packing_violation": -0.1,
        "bay_clearance_m": 0.1,
        "thrust_margin_cruise": 0.2,
        "sm_full": 0.05,
        "sm_reserve": 0.07,
        "vstall_margin_mps": 0.0,
        "washout_gap_deg": 1.2,
        "vv_lower_violation": -0.01,
        "vv_upper_violation": -0.01,
        "fin_te_overhang_m": -0.01,
    }
    tailless = load_spec(BASELINE_DESIGN)
    assert not _is_feasible(candidate, tailless)

    tailed = tailless.model_copy(deep=True)
    tailed.htail.span_m = 0.8
    assert _is_feasible(candidate, tailed)

    endurance_short = {**candidate, "endurance_deficit_s": 0.001}
    assert not _is_feasible(endurance_short, tailed)
    stall_high = {**candidate, "vstall_margin_mps": 0.001}
    assert not _is_feasible(stall_high, tailed)


def test_htail_trim_calibration_learns_oas_incidence_residual():
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.htail.span_m = 0.8
    spec.solver.tail_incidence_offset_deg = 0.2
    verify = {"aero_trim": {"tail_incidence_trim_deg": -0.1}}

    calibrated = _recalibrated_tail_incidence_offset(spec, verify, -1.4)

    assert calibrated == pytest.approx(1.5)
