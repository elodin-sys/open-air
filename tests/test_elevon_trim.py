"""Elevon pitch-trim path: schema opt-in, mesh deflection, closed form, OAS, gates."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import BASELINE_DESIGN, FORWARD_SWEPT_DESIGN
from openair.cli import load_spec
from openair.controls import (
    pitch_control_surface,
    pitch_trim_control,
    set_pitch_trim_deflection,
    te_down_deg,
    trim_control_values,
)
from openair.geometry.mesh import deflect_trailing_edge, elevon_chord_fractions
from openair.mission.balance import (
    balance_report,
    elevon_pitch_derivative,
    plain_flap_theory,
)
from openair.schemas import VehicleSpec

ELEVON = {
    "id": "elevon",
    "host": "wing",
    "span_start_fraction": 0.35,
    "span_end_fraction": 0.95,
    "chord_fraction": 0.20,
    "max_up_deg": 30.0,
    "max_down_deg": 30.0,
    "trim_deflection_deg": 0.0,
    "source": "test fixture",
    "mixing": [
        {"id": "elevator", "mode": "collective", "axis": "pitch", "gain": 1.0},
        {"id": "aileron", "mode": "differential", "axis": "roll", "gain": 1.0},
    ],
}


def _elevon_spec(design=FORWARD_SWEPT_DESIGN, **overrides) -> VehicleSpec:
    data = load_spec(design).model_dump(mode="python")
    data["mission"]["pitch_trim_control"] = "elevon"
    data["flight_dynamics"]["control_surfaces"] = [{**ELEVON, **overrides}]
    data["solver"]["oas_with_wave"] = False
    return VehicleSpec.model_validate(data)


def test_plain_flap_theory_matches_textbook_values():
    # Glauert thin-airfoil plain flap: tau ~0.55 at 20 % chord, ~0.82 at 50 %.
    assert plain_flap_theory(0.20)["tau"] == pytest.approx(0.550, abs=0.005)
    assert plain_flap_theory(0.50)["tau"] == pytest.approx(0.818, abs=0.005)
    half = plain_flap_theory(0.50)
    assert half["dcl_ddelta_per_rad"] == pytest.approx(math.pi + 2.0, abs=1e-9)
    assert half["dcm_ac_ddelta_per_rad"] == pytest.approx(-0.5, abs=1e-9)
    # Trailing-edge down lifts and pitches nose-down for every hinge location.
    for chord_fraction in (0.05, 0.2, 0.4, 0.9):
        flap = plain_flap_theory(chord_fraction)
        assert flap["dcl_ddelta_per_rad"] > 0.0
        assert flap["dcm_ac_ddelta_per_rad"] < 0.0
    # Monotone: a bigger flap lifts more.
    taus = [plain_flap_theory(c)["tau"] for c in (0.1, 0.2, 0.3, 0.5, 0.8)]
    assert taus == sorted(taus)
    with pytest.raises(ValueError):
        plain_flap_theory(0.0)


def test_pitch_trim_control_is_opt_in_and_validated():
    legacy = load_spec(FORWARD_SWEPT_DESIGN)
    assert pitch_trim_control(legacy) == "wing_twist"
    # Declaring a control surface alone does not change the trim control.
    data = legacy.model_dump(mode="python")
    data["flight_dynamics"]["control_surfaces"] = [dict(ELEVON)]
    declared_only = VehicleSpec.model_validate(data)
    assert pitch_trim_control(declared_only) == "wing_twist"
    assert pitch_control_surface(declared_only) is not None

    spec = _elevon_spec()
    assert pitch_trim_control(spec) == "elevon"
    assert pitch_control_surface(spec).id == "elevon"

    # Opt-in without a collective-pitch wing surface is rejected.
    bad = legacy.model_dump(mode="python")
    bad["mission"]["pitch_trim_control"] = "elevon"
    with pytest.raises(ValueError, match="collective pitch"):
        VehicleSpec.model_validate(bad)

    # Elevon trim is for tailless aircraft.
    tailed = spec.model_dump(mode="python")
    tailed["htail"]["span_m"] = 0.8
    with pytest.raises(ValueError, match="tailless"):
        VehicleSpec.model_validate(tailed)

    # Deflections outside the declared travel are rejected (TE up positive).
    with pytest.raises(ValueError, match="outside the travel"):
        _elevon_spec(trim_deflection_deg=31.0)
    with pytest.raises(ValueError, match="outside the travel"):
        _elevon_spec(neutral_deg=-30.5)
    assert (
        _elevon_spec(neutral_deg=2.5).flight_dynamics.control_surfaces[0].neutral_deg
        == 2.5
    )

    # Tail-incidence opt-in needs a tail.
    tail_mode = legacy.model_dump(mode="python")
    tail_mode["mission"]["pitch_trim_control"] = "tail_incidence"
    with pytest.raises(ValueError, match="horizontal tail"):
        VehicleSpec.model_validate(tail_mode)

    # The effectiveness factor mirrors the tail-factor citation rule.
    cited = spec.model_dump(mode="python")
    cited["solver"]["elevon_effectiveness_factor"] = 0.8
    with pytest.raises(ValueError, match="source citation"):
        VehicleSpec.model_validate(cited)
    cited["solver"]["elevon_effectiveness_source"] = "wind tunnel run 12"
    VehicleSpec.model_validate(cited)


def test_sign_helpers_and_trim_control_values():
    assert te_down_deg(5.0) == -5.0
    spec = _elevon_spec(trim_deflection_deg=4.0)
    values = trim_control_values(
        spec, {"trim_control": "elevon", "elevon_trim_deg": 4.6}
    )
    assert values["control"] == "elevon"
    assert values["spec_deg"] == 4.0
    assert values["gap_deg"] == pytest.approx(0.6)
    # aero-stage key spelling and a missing solution both fail closed.
    assert trim_control_values(spec, {"control": "elevon"})["gap_deg"] == 99.0
    twist = load_spec(FORWARD_SWEPT_DESIGN)
    washout = twist.wing.twist_root_deg - twist.wing.twist_tip_deg
    values = trim_control_values(twist, {"washout_trim_deg": washout + 0.2})
    assert values["control"] == "wing_twist"
    assert values["gap_deg"] == pytest.approx(0.2)
    set_pitch_trim_deflection(spec, 12.5)
    assert spec.flight_dynamics.control_surfaces[0].trim_deflection_deg == 12.5
    with pytest.raises(ValueError, match="travel"):
        set_pitch_trim_deflection(spec, 31.0)


def test_deflect_trailing_edge_rotates_only_the_covered_flap():
    from openair.geometry.mesh import generate_oas_rect_mesh

    spec = _elevon_spec()
    hinge = 1.0 - ELEVON["chord_fraction"]
    mesh = generate_oas_rect_mesh(spec, chord_fractions=elevon_chord_fractions(hinge))
    le, te = mesh[0], mesh[-1]
    fractions = (mesh[:, 0, 0] - le[0, 0]) / (te[0, 0] - le[0, 0])
    assert hinge in [round(f, 6) for f in fractions]

    deflected = deflect_trailing_edge(
        mesh,
        hinge_fraction=hinge,
        span_start_fraction=0.35,
        span_end_fraction=0.95,
        deflection_te_down_deg=10.0,
        taper=spec.wing.taper,
    )
    # x and y are untouched; only z aft of the hinge moves.
    assert np.allclose(deflected[:, :, :2], mesh[:, :, :2])
    hinge_row = int(np.argmin(np.abs(fractions - hinge)))
    assert np.allclose(deflected[: hinge_row + 1, :, 2], mesh[: hinge_row + 1, :, 2])
    dz = deflected[-1, :, 2] - mesh[-1, :, 2]
    eta = np.abs(mesh[0, :, 1]) / np.max(np.abs(mesh[0, :, 1]))
    # Trailing edge down lowers the TE where the elevon is, and not at the root.
    assert np.all(dz[eta > 0.5] < 0.0)
    assert dz[np.argmin(eta)] == 0.0
    # Pre-scaled by OAS's taper-about-quarter-chord so the final slope is tan(delta):
    # after x is scaled by k(eta) the flap slope equals tan(10 deg) where fully covered.
    chord_root = te[0, 0] - le[0, 0]
    covered = (eta > 0.45) & (eta < 0.9)
    k = 1.0 - (1.0 - spec.wing.taper) * eta[covered]
    expected = -(1.0 - hinge) * chord_root * k * math.tan(math.radians(10.0))
    assert np.allclose(dz[covered], expected, rtol=0.05)
    # Opposite sign for trailing edge up.
    up = deflect_trailing_edge(
        mesh,
        hinge_fraction=hinge,
        span_start_fraction=0.35,
        span_end_fraction=0.95,
        deflection_te_down_deg=-10.0,
        taper=spec.wing.taper,
    )
    assert np.allclose(up[-1, :, 2] - mesh[-1, :, 2], -dz)
    with pytest.raises(ValueError, match="hinge line"):
        deflect_trailing_edge(
            generate_oas_rect_mesh(spec),
            hinge_fraction=0.777,
            span_start_fraction=0.3,
            span_end_fraction=0.9,
            deflection_te_down_deg=5.0,
            taper=spec.wing.taper,
        )


def test_closed_form_elevon_requirement_has_trim_sign_and_freezes_twist():
    from openair.mission.mass import closed_mass_breakdown

    spec = _elevon_spec()
    masses = closed_mass_breakdown(spec, spec.mass.fuel_mass_kg)
    bal = balance_report(spec, masses.mtow_kg, spec.mass.fuel_mass_kg)
    assert bal.trim_control == "elevon"
    assert bal.washout_required_deg == pytest.approx(bal.washout_available_deg)
    assert bal.elevon_travel_deg == (-30.0, 30.0)
    assert bal.elevon_model is not None
    derivative = elevon_pitch_derivative(
        spec, spec.flight_dynamics.control_surfaces[0], bal.x_cg_full_m
    )
    # TE down lifts and pitches nose-down about a CG ahead of the elevon strip.
    assert derivative["dcl_ddelta_per_rad"] > 0.0
    assert derivative["dcm_cg_ddelta_per_rad"] < 0.0
    assert 0.0 < derivative["strip_area_fraction"] < 1.0
    # A nose-down untrimmed moment needs trailing edge up (positive).
    untrimmed = bal.elevon_model["cm_cg_untrimmed"]
    assert (bal.elevon_required_deg > 0.0) == (untrimmed < 0.0)
    # The effectiveness factor scales the derivative, and only the derivative.
    cited = spec.model_copy(deep=True)
    cited.solver.elevon_effectiveness_source = "test"
    cited.solver.elevon_effectiveness_factor = 0.5
    halved = elevon_pitch_derivative(
        cited, cited.flight_dynamics.control_surfaces[0], bal.x_cg_full_m
    )
    assert halved["dcm_cg_ddelta_per_rad"] == pytest.approx(
        0.5 * derivative["dcm_cg_ddelta_per_rad"]
    )


def test_evaluate_design_reports_the_elevon_gap_instead_of_washout():
    from openair.mdo.problem import _is_feasible, evaluate_design

    spec = _elevon_spec()
    metrics = evaluate_design(spec)
    bal = balance_report(spec, metrics["mtow_kg"], spec.mass.fuel_mass_kg)
    assert metrics["elevon_required_deg"] == pytest.approx(bal.elevon_required_deg)
    assert metrics["washout_gap_deg"] == pytest.approx(0.0 - bal.elevon_required_deg)
    # Writing the closed-form requirement back closes the low-order gap.
    closed = spec.model_copy(deep=True)
    set_pitch_trim_deflection(closed, bal.elevon_required_deg)
    assert evaluate_design(closed)["washout_gap_deg"] == pytest.approx(0.0, abs=1e-9)
    # The post-verify feasibility band for a movable control is 1.5 degrees.
    candidate = {
        "endurance_deficit_s": -1.0,
        "failure": -0.1,
        "packing_violation": -0.1,
        "bay_clearance_m": 0.1,
        "thrust_margin_cruise": 0.1,
        "sm_full": 0.05,
        "sm_reserve": 0.06,
        "vstall_margin_mps": -1.0,
        "washout_gap_deg": 1.2,
    }
    assert _is_feasible(candidate, spec)
    candidate["washout_gap_deg"] = 1.8
    assert not _is_feasible(candidate, spec)


def test_oas_elevon_trim_closes_with_frozen_twist_and_positive_authority():
    from openair.aero.oas_backend import run_vlm, trim_pitch
    from openair.mission.balance import thin_airfoil_props
    from openair.mission.sizing import cruise_tas

    spec = _elevon_spec()
    mtow_kg = 110.0
    bal = balance_report(spec, mtow_kg, spec.mass.fuel_mass_kg)
    tas_mps, _ = cruise_tas(spec, mtow_kg)
    result = trim_pitch(
        spec,
        spec.mission.cruise_altitude_m,
        tas_mps,
        mtow_kg * 9.80665,
        bal.x_cg_full_m,
        cm_offset=thin_airfoil_props(spec.wing.airfoil)["cm_ac"],
    )
    assert result["trim_converged"], result
    assert result["trim_control"] == "elevon"
    assert result["twist_frozen"] is True
    assert result["twist_tip_trim_deg"] == spec.wing.twist_tip_deg
    assert result["elevon_within_travel"]
    assert -30.0 < result["elevon_trim_deg"] < 30.0
    assert abs(result["cm_residual"]) < 5e-3
    assert result["elevon_sign_convention"] == "trailing edge up positive"
    # Trailing edge up pitches nose-up (about the CG) and unloads the wing.
    assert result["dcm_ddelta_per_deg"] > 0.0
    assert result["dcm_ddelta_fixed_alpha_per_deg"] > 0.0
    assert result["dcl_ddelta_fixed_alpha_per_deg"] < 0.0
    # run_vlm without an override uses the serialized deflection.
    held = spec.model_copy(deep=True)
    set_pitch_trim_deflection(held, result["elevon_trim_deg"])
    implicit = run_vlm(
        held,
        spec.mission.cruise_altitude_m,
        tas_mps,
        result["alpha_deg"],
        x_ref_m=bal.x_cg_full_m,
    )
    explicit = run_vlm(
        spec,
        spec.mission.cruise_altitude_m,
        tas_mps,
        result["alpha_deg"],
        x_ref_m=bal.x_cg_full_m,
        elevon_deflection_deg=result["elevon_trim_deg"],
    )
    assert implicit["CM"][1] == pytest.approx(explicit["CM"][1], abs=1e-9)
    assert implicit["elevon_deflection_deg"] == pytest.approx(result["elevon_trim_deg"])
    # Legacy specs report no elevon deflection at all.
    plain = run_vlm(load_spec(FORWARD_SWEPT_DESIGN), 1500.0, 62.0, 3.0)
    assert plain["elevon_deflection_deg"] is None


def test_reproduction_branch_publishes_elevon_closure(monkeypatch):
    from openair.mdo import problem

    spec = _elevon_spec()
    assert spec.sketch is not None
    spec.sketch.treatment = "reproduction"
    calls: list[float] = []

    def fake_verify(opt_spec, best, source_spec):
        deflection = opt_spec.flight_dynamics.control_surfaces[0].trim_deflection_deg
        calls.append(deflection)
        return {
            "ok": True,
            "aero_trim": {
                "converged": True,
                "control": "elevon",
                "elevon_trim_deg": 7.3456,
                "control_gap_deg": abs(7.3456 - deflection),
            },
            "stability_measured": {},
            "structures": {"ok": True, "failure": -0.2},
        }

    monkeypatch.setattr(problem, "_verify_with_oas", fake_verify)
    result = problem._run_reproduction_branch(spec, spec, None)
    delivered = result["_optimized_spec"]
    assert delivered.flight_dynamics.control_surfaces[0].trim_deflection_deg == 7.3456
    assert delivered.wing.twist_tip_deg == spec.wing.twist_tip_deg
    assert delivered.wing.twist_root_deg == spec.wing.twist_root_deg
    closure = result["reference_closure"]
    assert closure["allowed_control"] == "elevon_deflection"
    assert closure["pitch_trim_control"] == "elevon"
    assert closure["twist_frozen"] is True
    assert "twist_tip" in closure["frozen_coordinates"]
    assert "htail_incidence" in closure["frozen_coordinates"]
    # First verify saw the closed-form start, the last one the published value.
    assert calls[-1] == 7.3456
    assert calls[0] != 7.3456


def test_reproduction_diff_allows_only_the_trim_deflection_of_a_control_surface():
    from openair.reporting.gates import _reproduction_changed_paths

    source = _elevon_spec()
    delivered = source.model_copy(deep=True)
    set_pitch_trim_deflection(delivered, 9.5)
    assert _reproduction_changed_paths(source, delivered) == []
    delivered.flight_dynamics.control_surfaces[0].chord_fraction = 0.25
    assert _reproduction_changed_paths(source, delivered) == [
        "flight_dynamics.control_surfaces.0.chord_fraction"
    ]


def test_pitch_trim_gate_accepts_elevon_within_travel_and_rejects_pinned_or_retwisted():
    from test_gates import _passing_context

    from openair.reporting.gates import evaluate_gates

    spec, data, metrics = _passing_context()
    data_spec = spec.model_dump(mode="python")
    data_spec["mission"]["pitch_trim_control"] = "elevon"
    data_spec["flight_dynamics"]["control_surfaces"] = [
        {**ELEVON, "trim_deflection_deg": 8.0}
    ]
    spec = VehicleSpec.model_validate(data_spec)
    data["aero"]["trim"] = {
        "converged": True,
        "control": "elevon",
        "elevon_trim_deg": 8.2,
        "elevon_travel_deg": [-30.0, 30.0],
        "elevon_within_travel": True,
        "twist_frozen": True,
        "dcm_ddelta_per_deg": 0.004,
        "cm_residual": 0.0004,
    }
    gates = evaluate_gates(spec, data, metrics)
    trim_gate = next(gate for gate in gates if gate["id"] == "pitch_trim")
    assert trim_gate["ok"], trim_gate
    assert "elevon deflection" in trim_gate["evidence"]
    assert "twist frozen" in trim_gate["evidence"]
    assert "not reported" in trim_gate["evidence"]

    data["aero"]["trim"]["elevon_within_travel"] = False
    assert not next(
        gate
        for gate in evaluate_gates(spec, data, metrics)
        if gate["id"] == "pitch_trim"
    )["ok"]
    data["aero"]["trim"]["elevon_within_travel"] = True
    data["aero"]["trim"]["twist_frozen"] = False
    assert not next(
        gate
        for gate in evaluate_gates(spec, data, metrics)
        if gate["id"] == "pitch_trim"
    )["ok"]
    data["aero"]["trim"]["twist_frozen"] = True
    data["aero"]["trim"]["elevon_trim_deg"] = 9.5
    assert not next(
        gate
        for gate in evaluate_gates(spec, data, metrics)
        if gate["id"] == "pitch_trim"
    )["ok"]


def test_elodin_package_trim_control_carries_the_elevon_setting():
    from openair.flightdyn.package import _trim_control

    assert _trim_control({"control": "elevon", "elevon_trim_deg": 16.3}) == (
        "elevon",
        16.3,
    )
    assert _trim_control(
        {"control": "tail_incidence", "tail_incidence_trim_deg": -1.5}
    ) == (
        "tail_incidence",
        -1.5,
    )
    assert _trim_control({"control": "wing_twist", "twist_tip_trim_deg": 2.0}) == (
        "wing_twist",
        2.0,
    )


def test_validation_elevon_cross_check_is_not_applicable_without_elevon_trim(tmp_path):
    from openair.validation.runner import _elevon_pitch_derivative_cross_check

    check = _elevon_pitch_derivative_cross_check(
        load_spec(BASELINE_DESIGN), tmp_path, None
    )
    assert check["ok"] is True
    assert check["status"] == "not-applicable"
    # With elevon trim selected but no aero artifact the check fails closed.
    failed = _elevon_pitch_derivative_cross_check(_elevon_spec(), tmp_path, None)
    assert failed["ok"] is False
    assert "dCm/ddelta" in failed["reason"]


def test_geometry_serializes_declared_control_groups_without_flight_dynamics(tmp_path):
    from openair.geometry.openvsp_model import run_geometry_stage

    spec = _elevon_spec()
    assert spec.flight_dynamics.enabled is False
    result = run_geometry_stage(spec, tmp_path)
    readback = (result.get("openvsp") or {}).get("readback") or {}
    assert readback.get("control_group_names") == ["elevator", "aileron"]
    assert readback.get("control_surfaces_match") is True
