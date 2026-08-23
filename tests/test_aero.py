import numpy as np
import pytest

from conftest import BASELINE_DESIGN, FORWARD_SWEPT_DESIGN
from openair.aero.oas_backend import run_vlm
from openair.aero.oas_common import wing_surface_dict
from openair.cli import load_spec
from openair.validation.analytical import elliptical_induced_drag


def test_vlm_positive_lift():
    spec = load_spec(BASELINE_DESIGN)
    spec.solver.oas_with_wave = False
    r = run_vlm(spec, 0.0, 50.0, 4.0)
    assert r["CL"] > 0.15
    assert r["CD"] > 0.0
    assert r["S_ref"] > 1.0


def test_oas_transformed_mesh_preserves_declared_le_sweep():
    import openmdao.api as om
    from openaerostruct.geometry.geometry_group import Geometry

    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.wing.twist_root_deg = 0.0
    spec.wing.twist_tip_deg = 0.0
    spec.wing.dihedral_deg = 0.0
    surface = wing_surface_dict(spec, aero_only=True, cd0_extra=0.0)
    problem = om.Problem()
    problem.model.add_subsystem("wing", Geometry(surface=surface))
    problem.setup()
    problem.run_model()

    mesh = problem.get_val("wing.mesh")
    dx = float(mesh[0, 0, 0] - mesh[0, -1, 0])
    dy = abs(float(mesh[0, 0, 1] - mesh[0, -1, 1]))
    transformed_le_sweep = np.degrees(np.arctan2(dx, dy))
    assert transformed_le_sweep == pytest.approx(spec.wing.le_sweep_deg, abs=1e-8)


def test_vlm_applies_compressibility_at_wind_tunnel_mach():
    spec = load_spec(BASELINE_DESIGN)
    spec.solver.oas_with_viscous = False
    spec.solver.oas_with_wave = False

    incompressible = run_vlm(
        spec,
        0.0,
        50.0,
        4.0,
        mach_number=0.0,
        reynolds_per_m=1.0e7,
    )
    compressible = run_vlm(
        spec,
        0.0,
        50.0,
        4.0,
        mach_number=0.7,
        reynolds_per_m=1.0e7,
    )

    assert incompressible["compressibility_correction"] is False
    assert compressible["compressibility_correction"] is True
    assert compressible["CL"] > 1.1 * incompressible["CL"]
    assert compressible["reynolds_per_m"] == 1.0e7


def test_trim_pitch_closes_moment():
    from openair.aero.oas_backend import trim_pitch
    from openair.mission.balance import balance_report, thin_airfoil_props

    spec = load_spec(BASELINE_DESIGN)
    spec.solver.oas_with_wave = False
    bal = balance_report(spec, 100.0, 40.0)
    sect = thin_airfoil_props(spec.wing.airfoil)
    t = trim_pitch(
        spec, 1500.0, 62.0, 100.0 * 9.80665, bal.x_cg_full_m, cm_offset=sect["cm_ac"]
    )
    assert t["trim_converged"], t
    assert abs(t["cm_residual"]) < 5e-3
    assert abs(t["washout_trim_deg"]) <= 10.0


def test_trim_pitch_fwd_sweep_closes_with_bounded_twist():
    from openair.aero.oas_backend import trim_pitch
    from openair.mission.balance import balance_report, thin_airfoil_props
    from openair.mission.sizing import cruise_tas

    spec = load_spec(FORWARD_SWEPT_DESIGN)
    spec.solver.oas_with_wave = False
    mtow_kg = 110.0
    bal = balance_report(spec, mtow_kg, spec.mass.fuel_mass_kg)
    sect = thin_airfoil_props(spec.wing.airfoil)
    tas_mps, _ = cruise_tas(spec, mtow_kg)
    t = trim_pitch(
        spec,
        spec.mission.cruise_altitude_m,
        tas_mps,
        mtow_kg * 9.80665,
        bal.x_cg_full_m,
        cm_offset=sect["cm_ac"],
    )
    assert t["trim_converged"], t
    assert abs(t["cm_residual"]) < 5e-3
    assert abs(t["washout_trim_deg"]) <= 10.0


def test_twist_moment_effectiveness_reverses_with_sweep():
    from openair.aero.oas_backend import measure_neutral_point, trim_alpha

    def effect(design):
        spec = load_spec(design)
        spec.solver.oas_with_wave = False
        x_np = measure_neutral_point(
            spec,
            1500.0,
            62.0,
            x_ref_m=spec.wing.x_ac_m,
        )["x_np_m"]
        moments = []
        for washout_deg in (-0.5, 0.5):
            candidate = spec.model_copy(deep=True)
            candidate.wing.twist_tip_deg = candidate.wing.twist_root_deg - washout_deg
            result = trim_alpha(
                candidate,
                1500.0,
                62.0,
                100.0 * 9.80665,
                x_ref_m=x_np - 0.05 * spec.wing.mac_m,
            )
            moments.append(result["CM"][1])
        return moments[1] - moments[0]

    assert effect(BASELINE_DESIGN) > 0.0
    assert effect(FORWARD_SWEPT_DESIGN) < 0.0


def test_trim_pitch_with_horizontal_tail_uses_incidence():
    from openair.aero.oas_backend import trim_pitch
    from openair.mission.balance import balance_report, thin_airfoil_props
    from openair.mission.sizing import cruise_tas

    spec = load_spec(FORWARD_SWEPT_DESIGN)
    spec.solver.oas_with_wave = False
    spec.htail.span_m = 0.8
    spec.htail.root_chord_m = 0.25
    spec.htail.x_le_m = spec.fuselage.length_m - 0.34
    spec.htail.incidence_deg = 0.0
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
    assert result["trim_control"] == "tail_incidence"
    assert abs(result["cm_residual"]) < 5e-3
    assert abs(result["tail_incidence_trim_deg"]) <= 10.0
    assert set(result["surfaces"]) == {"wing", "htail"}
    assert result["S_ref"] == pytest.approx(spec.wing.area_m2)
    assert result["solver_S_ref_total"] > result["S_ref"]
    dimensional_cl_sum = sum(
        surface["CL"] * surface["S_ref"] for surface in result["surfaces"].values()
    )
    assert result["CL"] == pytest.approx(
        dimensional_cl_sum / spec.wing.area_m2,
        rel=1e-6,
    )
    native_total_cl = dimensional_cl_sum / result["solver_S_ref_total"]
    assert result["CL"] != pytest.approx(native_total_cl, rel=1e-3)


def test_induced_drag_high_ar_rect():
    spec = load_spec(BASELINE_DESIGN)
    spec.wing.span_m = 8.0
    spec.wing.root_chord_m = 0.5
    spec.wing.taper = 1.0
    spec.wing.le_sweep_deg = 0.0
    spec.wing.twist_root_deg = 0.0
    spec.wing.twist_tip_deg = 0.0
    spec.structures.n_spanwise = 11
    spec.solver.oas_with_viscous = False
    spec.solver.oas_with_wave = False
    r = run_vlm(spec, 0.0, 50.0, 4.0)
    theory = elliptical_induced_drag(r["CL"], spec.wing.aspect_ratio)
    assert r["CDi"] > 0
    assert abs(r["CDi"] - theory) / theory < 0.30
