from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.flightdyn.anchors import strip_theory_roll_damping
from openair.flightdyn.calibration import apply_named_calibration
from openair.flightdyn.sixdof import (
    elodin_available,
    replay_flightdyn,
    verify_elodin_linear_model,
)
from openair.flightdyn.stability import (
    derivative_quality,
    parse_stab,
    parse_stability_history,
)


def test_parse_vspaero_stability_derivatives_and_control_group(tmp_path: Path):
    path = tmp_path / "fixture.stab"
    rows = "\n".join(
        f"{name} {base} " + " ".join(str(value) for value in derivatives)
        for name, base, derivatives in (
            ("CL", 0.3, (5.1, 0, 0, 3.0, 0, 0, 0, 0.8)),
            ("CD", 0.03, (0.2, 0, 0, 0.1, 0, 0, 0, 0.02)),
            ("CS", 0.0, (0, -0.4, 0, 0, 0.2, 0, 0, 0)),
            ("CMl", 0.0, (0, -0.1, -0.5, 0, 0.1, 0, 0, 0)),
            ("CMm", -0.01, (-0.4, 0, 0, -5.0, 0, 0, 0, -0.3)),
            ("CMn", 0.0, (0, 0.1, 0, 0, -0.2, 0, 0, 0)),
        )
    )
    path.write_text(
        """
Sref_ 0.75 Lunit^2
Cref_ 0.36 Lunit
Bref_ 2.10 Lunit
Xcg_ 0.43 Lunit
Mach_ 0.053 no_unit
AoA_ 8.0 deg
Beta_ 0.0 deg
Rho_ 1.225 Munit/Lunit^3
Vinf_ 18.0 Lunit/Tunit
Case Delta Units
#
Base_Aero +0.000 n/a
Alpha +0.010 deg
Beta +0.010 deg
elevator +0.100 deg
#
#             Base    Derivative:
Coef Total Alpha Beta p q r Mach U ConGrp_1
# - per per per per per per per per
"""
        + rows
        + """
# Result Value Units
SM 0.05 no_unit
X_np 0.448 Lunit
""",
        encoding="utf-8",
    )

    parsed = parse_stab(path)

    assert parsed["control_group_count"] == 1
    assert parsed["references"]["area_m2"] == pytest.approx(0.75)
    assert parsed["coefficients"]["CY"]["derivatives"]["beta"] == pytest.approx(-0.4)
    assert parsed["coefficients"]["Cm"]["derivatives"]["control_1"] == pytest.approx(
        -0.3
    )
    assert parsed["results"]["static_margin"] == pytest.approx(0.05)
    assert parsed["perturbations"]["alpha"] == {
        "delta": pytest.approx(0.01),
        "units": "deg",
    }
    assert parsed["perturbations"]["elevator"]["delta"] == pytest.approx(0.1)


def test_stability_history_requires_each_perturbation_to_converge(tmp_path: Path):
    path = tmp_path / "fixture.history"

    def row(iteration: int, cl: float, cm: float, residual: float) -> str:
        values = [0.0] * 30
        values[0] = float(iteration)
        values[6] = cl
        values[22] = cm
        values[-3] = residual
        values[-2] = residual
        return " ".join(str(value) for value in values)

    path.write_text(
        "\n".join(
            [
                row(1, 0.30, -0.02, -0.5),
                row(2, 0.301, -0.0201, -1.5),
                row(3, 0.301, -0.0201, -2.2),
                row(1, 0.31, -0.021, -0.5),
                row(2, 0.311, -0.0211, -1.5),
                row(3, 0.311, -0.0211, -2.2),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    convergence = parse_stability_history(path, expected_iterations=8)

    assert convergence["case_count"] == 2
    assert convergence["converged"]


def test_derivative_quality_rejects_noise_dominated_small_step():
    coefficients = {
        "CL": {
            "base": 0.4,
            "derivatives": {"alpha": 4.5, "beta": 0.001},
        },
        "Cm": {
            "base": -0.01,
            "derivatives": {"alpha": -0.4, "beta": 0.001},
        },
        "CY": {"base": 0.0, "derivatives": {"alpha": 0.001}},
        "Cl": {"base": 0.0, "derivatives": {"alpha": 0.001}},
        "Cn": {"base": 0.0, "derivatives": {"alpha": 0.001}},
    }
    parsed = {"coefficients": coefficients, "perturbations": {}}
    wake = {
        "available": True,
        "converged": True,
        "cases": [{"final_l2_residual_log10": -2.5}],
    }

    clean = derivative_quality(
        parsed,
        4.48,
        wake_convergence=wake,
        fixed_wake=False,
    )
    assert clean["ok"]
    assert clean["CL_alpha_ratio_small_over_large"] == pytest.approx(4.5 / 4.48)

    coefficients["CL"]["derivatives"]["beta"] = 0.5
    noisy = derivative_quality(
        parsed,
        4.48,
        wake_convergence=wake,
        fixed_wake=False,
    )
    assert not noisy["ok"]
    assert not noisy["noise_ok"]

    coefficients["CL"]["derivatives"]["beta"] = 0.001
    stalled = derivative_quality(
        parsed,
        4.48,
        wake_convergence={
            **wake,
            "cases": [{"final_l2_residual_log10": -1.4}],
        },
        fixed_wake=False,
    )
    assert not stalled["ok"]
    assert not stalled["relaxed_wake_residual_ok"]


def test_aeroelastic_flap_effectiveness_uses_shared_glauert_theory():
    from openair.aero.thin_airfoil import flap_effectiveness as shared
    from openair.flightdyn.aeroelastic import flap_effectiveness

    assert flap_effectiveness(0.20) == pytest.approx(0.550, abs=0.005)
    assert flap_effectiveness(0.50) == pytest.approx(0.818, abs=0.005)
    assert flap_effectiveness(0.22) == shared(0.22)


def test_tapered_strip_theory_roll_damping_has_damping_sign():
    spec = load_spec(BASELINE_DESIGN)
    clp = strip_theory_roll_damping(spec)
    assert -2.0 < clp < -0.1


def test_named_low_re_calibration_is_explicit_and_bounded():
    spec = load_spec(Path("designs/ntnu-x8/design.yaml"))
    derivatives = {
        "controls": {
            "collective_elevon": {"Cm": -0.4, "Cl": 0.0},
            "differential_elevon": {"Cm": 0.0, "Cl": -0.25},
        },
        "state": {
            "Cm": {"q": -1.5},
            "Cl": {"p": -0.5},
        },
    }

    calibrated, provenance = apply_named_calibration(spec, derivatives)

    assert calibrated["controls"]["collective_elevon"]["Cm"] == pytest.approx(-0.3)
    assert calibrated["controls"]["differential_elevon"]["Cl"] == pytest.approx(-0.175)
    assert calibrated["state"]["Cm"]["q"] == pytest.approx(-1.8)
    assert calibrated["state"]["Cl"]["p"] == pytest.approx(-0.6)
    assert derivatives["state"]["Cm"]["q"] == -1.5
    assert provenance["source_case"] == "ntnu-x8-training"
    assert provenance["reference_reynolds"] < 750_000.0


@pytest.mark.stretch
def test_elodin_linear_mode_and_recorded_control_replay(tmp_path: Path):
    if not elodin_available():
        pytest.skip("run scripts/install_elodin.sh")
    verification = verify_elodin_linear_model(tmp_path / "linear")
    assert verification["ok"], verification

    coefficients = ("CL", "CD", "CY", "Cl", "Cm", "Cn")
    zero_derivatives = {
        name: {
            "alpha": 0.0,
            "beta": 0.0,
            "p": 0.0,
            "q": 0.0,
            "r": 0.0,
        }
        for name in coefficients
    }
    zero_derivatives["CL"]["alpha"] = 4.5
    zero_derivatives["Cm"]["alpha"] = -0.5
    zero_derivatives["Cm"]["q"] = -5.0
    zero_derivatives["Cl"]["p"] = -0.5
    zero_derivatives["Cn"]["beta"] = 0.1
    zero_derivatives["Cn"]["r"] = -0.2
    model = {
        "ok": True,
        "trim_state": {
            "airspeed_mps": 18.0,
            "altitude_m": 100.0,
            "mach": 0.05,
            "alpha_deg": 5.0,
            "density_kg_m3": 1.213,
        },
        "references": {
            "area_m2": 0.75,
            "span_m": 2.1,
            "chord_m": 0.36,
        },
        "mass_properties": {
            "mass_kg": 3.2,
            "elodin_diagonal_kg_m2": [0.8, 0.15, 0.9],
        },
        "propulsion": {
            "max_thrust_sl_n": 20.0,
            "deck": {
                "points": [
                    {
                        "altitude_m": 0.0,
                        "mach": 0.05,
                        "throttle": 0.2,
                        "thrust_n": 5.0,
                    },
                    {
                        "altitude_m": 0.0,
                        "mach": 0.05,
                        "throttle": 0.8,
                        "thrust_n": 17.0,
                    },
                ]
            },
        },
        "derivatives": {
            "base": {
                "CL": 0.4,
                "CD": 0.04,
                "CY": 0.0,
                "Cl": 0.0,
                "Cm": 0.0,
                "Cn": 0.0,
            },
            "state": zero_derivatives,
            "controls": {
                "collective_elevon": {
                    "CL": 0.1,
                    "CD": 0.0,
                    "CY": 0.0,
                    "Cl": 0.0,
                    "Cm": -0.3,
                    "Cn": 0.0,
                },
                "differential_elevon": {
                    "CL": 0.0,
                    "CD": 0.0,
                    "CY": 0.0,
                    "Cl": 0.2,
                    "Cm": 0.0,
                    "Cn": 0.01,
                },
            },
        },
    }
    model_path = tmp_path / "flightdyn.json"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    controls_path = tmp_path / "controls.csv"
    with open(controls_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "time_s",
                "collective_elevon_rad",
                "differential_elevon_rad",
                "throttle",
                "airspeed_mps",
            ]
        )
        writer.writerows(
            [
                (0.0, 0.0, 0.0, 0.5, 18.0),
                (0.5, 0.0, 0.0, 0.5, 18.0),
                (0.6, 0.03, 0.02, 0.5, 18.0),
                (1.0, 0.0, 0.0, 0.5, 18.0),
            ]
        )

    replay = replay_flightdyn(
        model_path,
        controls_path,
        tmp_path / "replay",
        dt_s=0.01,
    )

    assert replay["ok"], replay
    replay_csv = tmp_path / "replay" / "replay.csv"
    assert replay_csv.is_file()
    with open(replay_csv, newline="", encoding="utf-8") as stream:
        replay_rows = list(csv.DictReader(stream))
    assert float(replay_rows[0]["time_s"]) == pytest.approx(0.01)
    assert float(replay_rows[-1]["time_s"]) == pytest.approx(1.0)
    assert float(replay_rows[0]["deck_thrust_n"]) == pytest.approx(11.0)

    repeated = replay_flightdyn(
        model_path,
        controls_path,
        tmp_path / "replay-repeat",
        dt_s=0.01,
    )
    assert repeated["ok"], repeated
    assert (
        replay_csv.read_bytes()
        == (tmp_path / "replay-repeat" / "replay.csv").read_bytes()
    )
