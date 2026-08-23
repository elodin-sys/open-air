"""Independent code-verification anchors for the open-air physics kernels."""

from __future__ import annotations

import math

import pytest

from conftest import BASELINE_DESIGN
from openair.aero.oas_backend import run_vlm
from openair.atmosphere import isa
from openair.cli import load_spec
from openair.flightdyn.anchors import strip_theory_roll_damping
from openair.mdo.problem import evaluate_design
from openair.mission.balance import thin_airfoil_props
from openair.mission.engine import breguet_endurance_s
from openair.structures.oas_wingbox import run_aerostruct
from openair.validation.analytical import (
    cantilever_tip_deflection,
    elliptical_induced_drag,
)


def test_isa_against_us_standard_atmosphere_reference_points():
    """1976 standard-atmosphere values through the 20 km model ceiling."""
    references = {
        0.0: (288.15, 101325.0, 1.2250),
        11000.0: (216.65, 22632.1, 0.363918),
        20000.0: (216.65, 5474.89, 0.088035),
    }
    for altitude_m, (temperature_k, pressure_pa, density_kg_m3) in references.items():
        state = isa(altitude_m)
        assert state.temperature_k == pytest.approx(temperature_k, abs=0.02)
        assert state.pressure_pa == pytest.approx(pressure_pa, rel=3e-4)
        assert state.density_kg_m3 == pytest.approx(density_kg_m3, rel=4e-4)


def test_breguet_matches_independent_weight_ode_integration():
    """Integrate dW/dt = -cW/(L/D), then recover elapsed time analytically."""
    tsfc_weight_per_s = 4.5e-4
    lift_to_drag = 10.0
    target_s = 7200
    weight = 1000.0
    initial_weight = weight
    dt_s = 1.0
    for _ in range(target_s):
        weight += -(tsfc_weight_per_s / lift_to_drag) * weight * dt_s

    recovered_s = breguet_endurance_s(
        tsfc_weight_per_s,
        lift_to_drag,
        initial_weight / weight,
    )
    assert recovered_s == pytest.approx(target_s, abs=0.2)


def test_naca_four_digit_thin_airfoil_reference_values():
    """Theory-of-Wing-Sections values, independent of thickness distribution."""
    assert thin_airfoil_props("0012") == {"cm_ac": 0.0, "alpha_l0_deg": 0.0}

    naca2412 = thin_airfoil_props("2412")
    assert naca2412["alpha_l0_deg"] == pytest.approx(-2.08, abs=0.05)
    assert naca2412["cm_ac"] == pytest.approx(-0.053, abs=0.002)

    naca4412 = thin_airfoil_props("4412")
    assert naca4412["alpha_l0_deg"] == pytest.approx(-4.15, abs=0.08)
    assert naca4412["cm_ac"] == pytest.approx(-0.106, abs=0.003)


def test_tapered_strip_roll_damping_matches_spanwise_quadrature():
    """Independently integrate c(y)y² for the p*b/(2V) roll-rate convention."""
    spec = load_spec(BASELINE_DESIGN)
    semispan = 0.5 * spec.wing.span_m
    y = [semispan * index / 20_000 for index in range(20_001)]
    chord = [
        spec.wing.root_chord_m * (1.0 - (1.0 - spec.wing.taper) * station / semispan)
        for station in y
    ]
    integrand = [value * station**2 for value, station in zip(chord, y, strict=True)]
    half_integral = sum(
        0.5 * (left + right) * (y[index + 1] - y[index])
        for index, (left, right) in enumerate(
            zip(integrand[:-1], integrand[1:], strict=True)
        )
    )
    lift_slope = 2.0 * math.pi * spec.wing.aspect_ratio / (spec.wing.aspect_ratio + 2.0)
    quadrature = (
        -4.0 * lift_slope * half_integral / (spec.wing.area_m2 * spec.wing.span_m**2)
    )

    assert strip_theory_roll_damping(spec) == pytest.approx(quadrature, rel=1e-8)


def _rectangular_ar16_spec(n_spanwise: int):
    spec = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    spec.wing.span_m = 8.0
    spec.wing.root_chord_m = 0.5
    spec.wing.taper = 1.0
    spec.wing.le_sweep_deg = 0.0
    spec.wing.dihedral_deg = 0.0
    spec.wing.twist_root_deg = 0.0
    spec.wing.twist_tip_deg = 0.0
    spec.structures.n_spanwise = n_spanwise
    spec.solver.oas_with_viscous = False
    spec.solver.oas_with_wave = False
    return spec


def _vlm_slope(spec) -> tuple[float, dict]:
    low = run_vlm(spec, 0.0, 50.0, 1.0)
    high = run_vlm(spec, 0.0, 50.0, 5.0)
    slope_per_rad = (high["CL"] - low["CL"]) / math.radians(4.0)
    return slope_per_rad, high


@pytest.mark.slow
def test_oas_rectangular_wing_matches_finite_wing_theory():
    spec = _rectangular_ar16_spec(15)
    slope, result = _vlm_slope(spec)
    ar = spec.wing.aspect_ratio
    finite_wing_slope = 2.0 * math.pi * ar / (2.0 + math.sqrt(4.0 + ar**2))
    ideal_cdi = elliptical_induced_drag(result["CL"], ar)

    assert slope == pytest.approx(finite_wing_slope, rel=0.06)
    assert result["CDi"] == pytest.approx(ideal_cdi, rel=0.08)


@pytest.mark.slow
def test_default_vlm_mesh_has_bounded_numerical_uncertainty():
    """Production n=9 compared with an n=21 Richardson-reference mesh."""
    production_slope, production = _vlm_slope(_rectangular_ar16_spec(9))
    reference_slope, reference = _vlm_slope(_rectangular_ar16_spec(21))

    relative = {
        "CL": abs(production["CL"] - reference["CL"]) / abs(reference["CL"]),
        "CDi": abs(production["CDi"] - reference["CDi"]) / abs(reference["CDi"]),
        "CL_alpha": abs(production_slope - reference_slope) / abs(reference_slope),
    }
    assert relative["CL"] < 0.025
    assert relative["CDi"] < 0.035
    assert relative["CL_alpha"] < 0.025


@pytest.mark.slow
def test_oas_tube_beam_matches_uniform_cantilever_scale():
    """OAS's elliptic distributed load should bracket the uniform-load beam."""
    spec = _rectangular_ar16_spec(11)
    spec.wing.span_m = 4.0
    spec.wing.root_chord_m = 0.6
    spec.structures.fem_model_type = "tube"
    spec.structures.tube_radius_m = 0.030
    spec.structures.tube_thickness_m = 0.003

    def solve(e_pa: float) -> tuple[float, float]:
        candidate = spec.model_copy(deep=True)
        candidate.structures.material.E_pa = e_pa
        result = run_aerostruct(candidate, 0.0, 40.0, 1.0, 3.0, 20.0, 2.0)
        assert result["ok"], result
        q_pa = 0.5 * isa(0.0).density_kg_m3 * 40.0**2
        half_wing_load_n = 0.5 * q_pa * candidate.wing.area_m2 * result["CL"]
        outer_radius = candidate.structures.tube_radius_m
        inner_radius = outer_radius - candidate.structures.tube_thickness_m
        inertia_m4 = math.pi * (outer_radius**4 - inner_radius**4) / 4.0
        beam_m = cantilever_tip_deflection(
            half_wing_load_n,
            0.5 * candidate.wing.span_m,
            e_pa,
            inertia_m4,
        )
        return result["tip_disp_m"], beam_m

    displacement_70, beam_70 = solve(70e9)
    displacement_140, _ = solve(140e9)
    assert displacement_70 / beam_70 == pytest.approx(0.78, abs=0.12)
    assert displacement_140 / displacement_70 == pytest.approx(0.5, abs=0.06)


def _central_derivative(
    spec, section: str, field: str, step: float, output: str
) -> float:
    low = spec.model_copy(deep=True)
    high = spec.model_copy(deep=True)
    baseline = float(getattr(getattr(spec, section), field))
    setattr(getattr(low, section), field, baseline - step)
    setattr(getattr(high, section), field, baseline + step)
    return (evaluate_design(high)[output] - evaluate_design(low)[output]) / (2.0 * step)


def test_closed_mda_gradient_directions_are_physical():
    """Guard optimizer-critical signs; a right baseline with a wrong gradient is unsafe."""
    spec = load_spec(BASELINE_DESIGN)
    assert _central_derivative(spec, "wing", "span_m", 0.01, "mtow_kg") > 0.0
    assert _central_derivative(spec, "wing", "x_le_root_m", 0.005, "sm_full") > 0.0
    assert (
        _central_derivative(
            spec,
            "structures",
            "skin_thickness_m",
            1e-5,
            "failure",
        )
        < 0.0
    )
    assert _central_derivative(spec, "mass", "fuel_mass_kg", 0.1, "endurance_s") > 0.0
