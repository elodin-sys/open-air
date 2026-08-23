from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from openair.cli import load_spec
from openair.structures.modal import run_modal_analysis, solve_beam_modes


def _uniform_solution(
    *,
    length_m: float,
    ei_n_m2: float,
    gj_n_m2: float,
    mass_kg_m: float,
    polar_mass_kg_m: float,
    elements: int,
):
    return solve_beam_modes(
        span_m=length_m,
        station_eta=np.array([0.0, 1.0]),
        station_ei_n_m2=np.array([ei_n_m2, ei_n_m2]),
        station_gj_n_m2=np.array([gj_n_m2, gj_n_m2]),
        station_mass_kg_m=np.array([mass_kg_m, mass_kg_m]),
        station_polar_mass_kg_m=np.array([polar_mass_kg_m, polar_mass_kg_m]),
        n_elements=elements,
    )


def test_uniform_cantilever_bending_matches_closed_form():
    length = 2.5
    ei = 5_000.0
    linear_mass = 0.8
    result = _uniform_solution(
        length_m=length,
        ei_n_m2=ei,
        gj_n_m2=300.0,
        mass_kg_m=linear_mass,
        polar_mass_kg_m=0.003,
        elements=80,
    )
    beta_1 = 1.875104068711961
    expected_hz = (
        beta_1**2
        / (2.0 * math.pi)
        * math.sqrt(ei / (linear_mass * length**4))
    )
    assert result["bending"][0]["frequency_hz"] == pytest.approx(
        expected_hz,
        rel=2e-4,
    )


def test_uniform_cantilever_torsion_matches_closed_form():
    length = 2.5
    gj = 300.0
    polar_mass = 0.003
    result = _uniform_solution(
        length_m=length,
        ei_n_m2=5_000.0,
        gj_n_m2=gj,
        mass_kg_m=0.8,
        polar_mass_kg_m=polar_mass,
        elements=80,
    )
    expected_hz = math.sqrt(gj / polar_mass) / (4.0 * length)
    assert result["torsion"][0]["frequency_hz"] == pytest.approx(
        expected_hz,
        rel=2e-4,
    )


def test_tapered_properties_converge_under_quadrature_refinement():
    kwargs = {
        "span_m": 2.5,
        "station_eta": np.array([0.0, 0.35, 0.7, 1.0]),
        "station_ei_n_m2": np.array([6_000.0, 4_500.0, 2_000.0, 500.0]),
        "station_gj_n_m2": np.array([400.0, 300.0, 140.0, 30.0]),
        "station_mass_kg_m": np.array([1.0, 0.85, 0.55, 0.3]),
        "station_polar_mass_kg_m": np.array([0.004, 0.003, 0.002, 0.001]),
    }
    coarse = solve_beam_modes(**kwargs, n_elements=20)
    fine = solve_beam_modes(**kwargs, n_elements=80)
    assert coarse["bending"][0]["frequency_hz"] == pytest.approx(
        fine["bending"][0]["frequency_hz"],
        rel=0.01,
    )
    assert coarse["torsion"][0]["frequency_hz"] == pytest.approx(
        fine["torsion"][0]["frequency_hz"],
        rel=0.01,
    )


def test_diana_overlay_closes_visible_l1_mode_and_maps_all_strain_channels():
    spec = load_spec(Path("designs/diana2/design.yaml"))
    result = run_modal_analysis(spec)
    assert result["ok"], result["calibration_comparisons"]
    comparison = result["calibration_comparisons"][0]
    assert comparison["id"] == "first_symmetric_wing_bending"
    assert comparison["absolute_relative_error"] <= 0.10
    mapping = result["strain_mapping"]
    assert mapping["total_channel_count"] == 21
    assert len({channel["id"] for channel in mapping["channels"]}) == 21
