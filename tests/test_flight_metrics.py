from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy import signal

from openair.flightdyn.aeroelastic import (
    aeroelastic_section_matrices,
    run_aeroelastic_model,
)
from openair.io import load_yaml
from openair.schemas import VehicleSpec
from openair.truth.flight_metrics import (
    FlightSeries,
    estimate_control_response,
    estimate_control_peak,
    estimate_damped_mode,
    estimate_h1_mode,
    estimate_protocol_metrics,
    estimate_roll_time_constant,
    evaluate_frozen_protocol,
    fit_signal_slope,
    fit_static_aero,
    fit_trim_elevon,
    h1_frequency_response,
    welch_psd,
)


def test_damped_mode_recovers_frequency_and_damping():
    time = np.arange(0.0, 12.0, 0.01)
    frequency_hz = 1.25
    damping_ratio = 0.12
    omega_n = 2.0 * np.pi * frequency_hz
    omega_d = omega_n * np.sqrt(1.0 - damping_ratio**2)
    response = np.exp(-damping_ratio * omega_n * time) * np.sin(omega_d * time)

    estimate = estimate_damped_mode(
        time,
        response,
        frequency_band_hz=(0.7, 2.0),
    )

    assert estimate["frequency_hz"] == pytest.approx(frequency_hz, rel=0.08)
    assert estimate["damping_ratio"] == pytest.approx(damping_ratio, abs=0.035)
    assert estimate["phase_r2"] > 0.98


def test_roll_decay_and_control_peak_estimators():
    time = np.arange(0.0, 3.0, 0.01)
    response = 0.8 * np.exp(-time / 0.42) + 0.01

    estimate = estimate_roll_time_constant(time, response)
    peak = estimate_control_peak(
        np.r_[np.zeros(5), [0.1, -0.4, 0.2]],
        baseline_samples=5,
    )

    assert estimate["time_constant_s"] == pytest.approx(0.42, rel=0.01)
    assert estimate["fit_r2"] > 0.999
    assert peak["peak_delta"] == pytest.approx(-0.4)


def test_robust_trim_and_static_aero_regressions():
    speed = np.array([12.0, 14.0, 16.0, 18.0, 20.0, 22.0])
    elevon = 0.08 - 0.0025 * speed
    alpha = np.deg2rad(np.array([-2.0, 0.0, 2.0, 4.0, 6.0, 8.0]))
    lift = 0.15 + 4.8 * alpha
    drag = 0.025 + 0.07 * lift**2

    trim = fit_trim_elevon(speed, elevon)
    aero = fit_static_aero(alpha, lift, drag)

    assert trim["slope_rad_per_mps"] == pytest.approx(-0.0025)
    assert aero["cl_alpha_per_rad"] == pytest.approx(4.8)
    assert aero["cd_zero"] == pytest.approx(0.025)
    assert aero["induced_drag_k"] == pytest.approx(0.07)


def test_protocol_is_symmetric_for_measured_and_simulated_series():
    time = np.arange(0.0, 8.0, 0.01)
    response = np.exp(-0.8 * time) * np.sin(2.0 * np.pi * time)
    measured = FlightSeries.from_columns(time, {"q_rad_s": response})
    simulated = FlightSeries.from_columns(time, {"q_rad_s": response.copy()})
    protocol = {
        "short_period": {
            "kind": "damped_mode",
            "maneuvers": ["pitch-1"],
            "start_s": 0.0,
            "end_s": 7.99,
            "signal": "q_rad_s",
            "frequency_band_hz": [0.5, 1.5],
            "outputs": ["frequency_hz", "damping_ratio"],
        }
    }

    measured_metrics = estimate_protocol_metrics(
        {"pitch-1": measured},
        protocol,
    )
    simulated_metrics = estimate_protocol_metrics(
        {"pitch-1": simulated},
        protocol,
    )

    assert simulated_metrics == measured_metrics


def test_pattern_protocol_recovers_control_gain_and_signal_slope():
    time = np.arange(0.0, 6.0, 0.025)
    control = np.where(time < 1.0, 0.1, 0.1 + 0.2 * np.sin(2.0 * time))
    response = -0.3 + 4.0 * (control - 0.1)
    alpha = np.linspace(-0.1, 0.2, len(time))
    lift = 0.2 + 4.7 * alpha
    series = FlightSeries.from_columns(
        time,
        {
            "collective_elevon_rad": control,
            "q_rad_s": response,
            "alpha_rad": alpha,
            "cl": lift,
        },
    )
    protocol = {
        "metrics": {
            "pitch_gain": {
                "kind": "control_response",
                "maneuver_glob": "longitudinal_doublet_*.csv",
                "signal": "q_rad_s",
                "control": "collective_elevon_rad",
                "output": "peak_gain",
                "baseline_duration_s": 0.9,
            },
            "lift_slope": {
                "kind": "signal_slope",
                "maneuver_glob": "longitudinal_*.csv",
                "signal": "cl",
                "abscissa": "alpha_rad",
                "output": "slope",
            },
        }
    }

    response_fit = estimate_control_response(
        time,
        response,
        control,
        baseline_duration_s=0.9,
    )
    slope_fit = fit_signal_slope(alpha, lift)
    values, details = evaluate_frozen_protocol(
        {"longitudinal_doublet_1": series},
        protocol,
    )

    assert response_fit["peak_gain"] == pytest.approx(4.0)
    assert slope_fit["slope"] == pytest.approx(4.7)
    assert values == pytest.approx({"pitch_gain": 4.0, "lift_slope": 4.7})
    assert details["pitch_gain"]["maneuvers"] == ["longitudinal_doublet_1"]


def test_control_response_peak_excludes_pre_excitation_baseline_outlier():
    time = np.arange(0.0, 5.0, 0.05)
    control = np.zeros_like(time)
    control[time > 1.0] = 0.2 * np.sin(2.0 * time[time > 1.0])
    response = 3.0 * control
    response[np.argmin(np.abs(time - 0.5))] = 20.0

    estimate = estimate_control_response(
        time,
        response,
        control,
        baseline_duration_s=1.0,
    )

    assert estimate["peak_gain"] == pytest.approx(3.0)


def test_welch_h1_and_half_power_recover_first_mode_of_two_dof_response():
    sample_rate = 200.0
    time = np.arange(0.0, 120.0, 1.0 / sample_rate)
    excitation = np.random.default_rng(7).normal(size=len(time))

    def response(frequency_hz: float, damping: float, gain: float) -> np.ndarray:
        omega = 2.0 * np.pi * frequency_hz
        system = signal.TransferFunction(
            [gain],
            [1.0, 2.0 * damping * omega, omega**2],
        )
        _, output, _ = signal.lsim(system, U=excitation, T=time)
        return output

    output = response(5.0, 0.03, 1.0) + response(12.0, 0.05, 0.35)
    psd = welch_psd(time, output, nperseg=4096)
    h1 = h1_frequency_response(
        time,
        excitation,
        output,
        nperseg=4096,
        coherence_minimum=0.90,
    )
    estimate = estimate_h1_mode(
        time,
        excitation,
        output,
        frequency_band_hz=(4.0, 6.0),
        nperseg=4096,
        coherence_minimum=0.90,
    )

    assert len(psd["frequency_hz"]) == len(psd["psd"])
    assert np.count_nonzero(h1["coherence_mask"]) > 100
    assert estimate["frequency_hz"] == pytest.approx(5.0, abs=0.08)
    assert estimate["damping_ratio"] == pytest.approx(0.03, abs=0.015)
    assert estimate["median_coherence"] > 0.95


def test_h1_mode_removes_acceleration_order_before_half_power_fit():
    sample_rate = 200.0
    time = np.arange(0.0, 120.0, 1.0 / sample_rate)
    excitation = np.random.default_rng(9).normal(size=len(time))
    frequency_hz = 7.4
    damping = 0.025
    omega = 2.0 * np.pi * frequency_hz
    acceleration_system = signal.TransferFunction(
        [1.0, 0.0, 0.0],
        [1.0, 2.0 * damping * omega, omega**2],
    )
    _, acceleration, _ = signal.lsim(
        acceleration_system,
        U=excitation,
        T=time,
    )

    estimate = estimate_h1_mode(
        time,
        excitation,
        acceleration,
        frequency_band_hz=(6.5, 8.5),
        nperseg=4096,
        coherence_minimum=0.90,
        response_derivative_order=2,
    )

    assert estimate["frequency_hz"] == pytest.approx(frequency_hz, abs=0.08)
    assert estimate["damping_ratio"] == pytest.approx(damping, abs=0.015)
    assert estimate["raw_magnitude_at_mode"] > 1.0
    assert estimate["response_derivative_order"] == 2


def test_quasi_steady_section_anchor_softens_stiffness_and_adds_damping():
    omega = 2.0 * np.pi * 5.0
    mass = np.array([[2.0]])
    stiffness = np.array([[2.0 * omega**2]])
    damping = np.array([[2.0 * 0.02 * omega * 2.0]])
    aerodynamic_position = 0.20 * stiffness
    aerodynamic_velocity = -0.25 * damping

    zero = aeroelastic_section_matrices(
        mass=mass,
        stiffness=stiffness,
        damping=damping,
        aerodynamic_position=aerodynamic_position,
        aerodynamic_velocity=aerodynamic_velocity,
        dynamic_pressure_pa=0.0,
        reference_dynamic_pressure_pa=100.0,
    )
    reference = aeroelastic_section_matrices(
        mass=mass,
        stiffness=stiffness,
        damping=damping,
        aerodynamic_position=aerodynamic_position,
        aerodynamic_velocity=aerodynamic_velocity,
        dynamic_pressure_pa=100.0,
        reference_dynamic_pressure_pa=100.0,
    )

    assert zero["stiffness"] == pytest.approx(stiffness)
    assert zero["damping"] == pytest.approx(damping)
    assert reference["stiffness"][0, 0] == pytest.approx(0.8 * stiffness[0, 0])
    assert reference["damping"][0, 0] == pytest.approx(1.25 * damping[0, 0])


def test_diana_aeroelastic_model_reports_airspeed_modal_sweep():
    root = Path(__file__).parents[1]
    spec = VehicleSpec.model_validate(
        load_yaml(root / "designs" / "diana2" / "design.yaml")
    )

    model = run_aeroelastic_model(spec, {})

    speeds = [item["airspeed_mps"] for item in model["airspeed_sweep"]]
    first_modes = [item["modes"][0] for item in model["airspeed_sweep"]]
    assert model["ok"]
    assert len(speeds) == 8
    assert speeds == sorted(speeds)
    assert all(mode["stable"] for mode in first_modes)
    assert first_modes[-1]["reduced_frequency"] < first_modes[0]["reduced_frequency"]
    assert model["calibration"]["force_scale"] == {"aileron": 0.55}
    assert model["frfs"]["aileron"]["supported"]
