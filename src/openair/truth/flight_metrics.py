"""Symmetric estimators for measured and simulated flight responses."""

from __future__ import annotations

import csv
import fnmatch
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy import optimize, signal, stats


@dataclass(frozen=True)
class FlightSeries:
    time_s: np.ndarray
    columns: dict[str, np.ndarray]

    @classmethod
    def from_columns(
        cls,
        time_s: Sequence[float],
        columns: Mapping[str, Sequence[float]],
    ) -> FlightSeries:
        time = np.asarray(time_s, dtype=float)
        values = {
            name: np.asarray(column, dtype=float) for name, column in columns.items()
        }
        if time.ndim != 1 or len(time) < 10:
            raise ValueError("flight series needs at least ten time samples")
        if not np.all(np.isfinite(time)) or np.any(np.diff(time) <= 0.0):
            raise ValueError("flight time must be finite and strictly increasing")
        for name, column in values.items():
            if column.shape != time.shape or not np.all(np.isfinite(column)):
                raise ValueError(f"{name} must be finite and match flight time")
        return cls(time_s=time, columns=values)

    @classmethod
    def from_csv(cls, path: Path) -> FlightSeries:
        with open(path, newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if not rows or "time_s" not in rows[0]:
            raise ValueError(f"{path} must contain time_s")
        names = [name for name in rows[0] if name != "time_s"]
        return cls.from_columns(
            [float(row["time_s"]) for row in rows],
            {
                name: [float(row[name]) for row in rows]
                for name in names
                if all(row.get(name, "") != "" for row in rows)
            },
        )

    def window(self, start_s: float, end_s: float) -> FlightSeries:
        mask = (self.time_s >= start_s) & (self.time_s <= end_s)
        if np.count_nonzero(mask) < 10:
            raise ValueError(f"window {start_s:g}-{end_s:g}s has too few samples")
        return FlightSeries.from_columns(
            self.time_s[mask],
            {name: values[mask] for name, values in self.columns.items()},
        )


def _uniform_signal(
    time_s: np.ndarray,
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    dt = float(np.median(np.diff(time_s)))
    if np.max(np.abs(np.diff(time_s) - dt)) > 0.05 * dt:
        uniform_time = np.arange(time_s[0], time_s[-1] + 0.25 * dt, dt)
        uniform_values = np.interp(uniform_time, time_s, values)
    else:
        uniform_time = time_s
        uniform_values = values
    return uniform_time, uniform_values, dt


def estimate_damped_mode(
    time_s: Sequence[float],
    values: Sequence[float],
    *,
    frequency_band_hz: tuple[float, float],
) -> dict[str, float]:
    """Estimate one decaying mode from filtered half-cycle peaks."""
    time = np.asarray(time_s, dtype=float)
    raw = np.asarray(values, dtype=float)
    if time.shape != raw.shape or len(time) < 40:
        raise ValueError("mode estimator needs at least 40 paired samples")
    uniform_time, uniform, dt = _uniform_signal(time, raw)
    nyquist = 0.5 / dt
    low, high = frequency_band_hz
    if not (0.0 < low < high < nyquist):
        raise ValueError("mode frequency band must be inside (0, Nyquist)")
    detrended = signal.detrend(uniform, type="linear")
    sos = signal.butter(3, [low, high], btype="bandpass", fs=1.0 / dt, output="sos")
    filtered = signal.sosfiltfilt(sos, detrended)
    edge = max(3, round(0.05 * len(uniform_time)))
    magnitude = np.abs(filtered)
    peak_indices, _ = signal.find_peaks(
        magnitude,
        distance=max(1, round(0.35 / (high * dt))),
        prominence=max(float(np.max(magnitude)) * 1e-5, 1e-15),
    )
    peak_indices = peak_indices[
        (peak_indices >= edge) & (peak_indices < len(uniform_time) - edge)
    ]
    if len(peak_indices):
        peak_indices = peak_indices[
            magnitude[peak_indices] >= float(np.max(magnitude[peak_indices])) * 0.01
        ]
    if len(peak_indices) < 6:
        raise ValueError("mode estimator has insufficient decaying peaks")
    peak_time = uniform_time[peak_indices]
    peak_magnitude = magnitude[peak_indices]
    phase_fit = stats.linregress(
        peak_time,
        np.arange(len(peak_time), dtype=float) * math.pi,
    )
    decay_fit = stats.linregress(
        peak_time,
        np.log(np.maximum(peak_magnitude, 1e-15)),
    )
    omega_d = abs(float(phase_fit.slope))
    decay_rate = -float(decay_fit.slope)
    if omega_d <= 0.0 or decay_rate <= 0.0:
        raise ValueError("selected response is not a decaying oscillatory mode")
    omega_n = math.hypot(omega_d, decay_rate)
    return {
        "frequency_hz": omega_n / (2.0 * math.pi),
        "damped_frequency_hz": omega_d / (2.0 * math.pi),
        "damping_ratio": decay_rate / omega_n,
        "decay_rate_per_s": decay_rate,
        "phase_r2": float(phase_fit.rvalue**2),
        "envelope_r2": float(decay_fit.rvalue**2),
        "samples_used": float(len(peak_indices)),
    }


def welch_psd(
    time_s: Sequence[float],
    values: Sequence[float],
    *,
    nperseg: int = 1024,
    overlap_fraction: float = 0.5,
) -> dict[str, Any]:
    """Estimate a one-sided Welch PSD after symmetric time-grid handling."""
    time = np.asarray(time_s, dtype=float)
    raw = np.asarray(values, dtype=float)
    if time.shape != raw.shape or len(time) < 64:
        raise ValueError("Welch PSD needs at least 64 paired samples")
    _uniform_time, uniform, dt = _uniform_signal(time, raw)
    segment = min(int(nperseg), len(uniform))
    if segment < 32 or not 0.0 <= overlap_fraction < 1.0:
        raise ValueError("invalid Welch segment or overlap")
    overlap = int(round(overlap_fraction * segment))
    frequency, density = signal.welch(
        uniform,
        fs=1.0 / dt,
        window="hann",
        nperseg=segment,
        noverlap=overlap,
        detrend="linear",
        scaling="density",
    )
    return {
        "frequency_hz": frequency,
        "psd": density,
        "sample_rate_hz": 1.0 / dt,
        "nperseg": segment,
        "noverlap": overlap,
        "frequency_resolution_hz": float(frequency[1] - frequency[0]),
    }


def h1_frequency_response(
    time_s: Sequence[float],
    input_signal: Sequence[float],
    output_signal: Sequence[float],
    *,
    nperseg: int = 1024,
    overlap_fraction: float = 0.5,
    coherence_minimum: float = 0.60,
) -> dict[str, Any]:
    """Estimate H1 = S_yx/S_xx and retain only coherent frequency bins."""
    time = np.asarray(time_s, dtype=float)
    input_values = np.asarray(input_signal, dtype=float)
    output_values = np.asarray(output_signal, dtype=float)
    if (
        time.shape != input_values.shape
        or time.shape != output_values.shape
        or len(time) < 64
    ):
        raise ValueError("H1 estimator needs at least 64 aligned samples")
    uniform_time, uniform_input, dt = _uniform_signal(time, input_values)
    _, uniform_output, output_dt = _uniform_signal(time, output_values)
    if len(uniform_output) != len(uniform_input) or abs(output_dt - dt) > 1e-12:
        uniform_output = np.interp(uniform_time, time, output_values)
    segment = min(int(nperseg), len(uniform_input))
    if segment < 32 or not 0.0 <= overlap_fraction < 1.0:
        raise ValueError("invalid H1 segment or overlap")
    if not 0.0 <= coherence_minimum <= 1.0:
        raise ValueError("coherence minimum must be between zero and one")
    overlap = int(round(overlap_fraction * segment))
    kwargs = {
        "fs": 1.0 / dt,
        "window": "hann",
        "nperseg": segment,
        "noverlap": overlap,
        "detrend": "linear",
        "scaling": "density",
    }
    frequency, input_psd = signal.welch(uniform_input, **kwargs)
    _, cross_psd = signal.csd(uniform_input, uniform_output, **kwargs)
    _, coherence = signal.coherence(
        uniform_input,
        uniform_output,
        fs=1.0 / dt,
        window="hann",
        nperseg=segment,
        noverlap=overlap,
        detrend="linear",
    )
    h1 = cross_psd / np.maximum(input_psd, np.finfo(float).tiny)
    mask = coherence >= coherence_minimum
    return {
        "frequency_hz": frequency,
        "h1": h1,
        "magnitude": np.abs(h1),
        "phase_deg": np.degrees(np.angle(h1)),
        "coherence": coherence,
        "coherence_mask": mask,
        "coherence_minimum": coherence_minimum,
        "sample_rate_hz": 1.0 / dt,
        "nperseg": segment,
        "noverlap": overlap,
        "frequency_resolution_hz": float(frequency[1] - frequency[0]),
    }


def half_power_damping(
    frequency_hz: Sequence[float],
    magnitude: Sequence[float],
    *,
    frequency_band_hz: tuple[float, float],
    valid_mask: Sequence[bool] | None = None,
) -> dict[str, float]:
    """Estimate resonance and damping from interpolated -3 dB crossings."""
    frequency = np.asarray(frequency_hz, dtype=float)
    response = np.asarray(magnitude, dtype=float)
    if frequency.shape != response.shape or len(frequency) < 8:
        raise ValueError("half-power estimator needs at least eight frequency bins")
    mask = np.isfinite(frequency) & np.isfinite(response)
    if valid_mask is not None:
        supplied = np.asarray(valid_mask, dtype=bool)
        if supplied.shape != frequency.shape:
            raise ValueError("half-power validity mask shape mismatch")
        mask &= supplied
    low, high = frequency_band_hz
    mask &= (frequency >= low) & (frequency <= high)
    indices = np.flatnonzero(mask)
    if len(indices) < 5:
        raise ValueError("half-power band has too few valid bins")
    local_peak = int(indices[np.argmax(response[indices])])
    peak = float(response[local_peak])
    if peak <= 0.0:
        raise ValueError("half-power peak is not positive")
    threshold = peak / math.sqrt(2.0)

    def crossing(left: int, right: int) -> float:
        x0, x1 = frequency[left], frequency[right]
        y0, y1 = response[left], response[right]
        if abs(y1 - y0) < 1e-15:
            return float(0.5 * (x0 + x1))
        return float(x0 + (threshold - y0) * (x1 - x0) / (y1 - y0))

    lower = next(
        (
            crossing(index, index + 1)
            for index in range(local_peak - 1, indices[0] - 1, -1)
            if mask[index]
            and mask[index + 1]
            and (response[index] - threshold)
            * (response[index + 1] - threshold)
            <= 0.0
        ),
        None,
    )
    upper = next(
        (
            crossing(index, index + 1)
            for index in range(local_peak, indices[-1])
            if mask[index]
            and mask[index + 1]
            and (response[index] - threshold)
            * (response[index + 1] - threshold)
            <= 0.0
        ),
        None,
    )
    if lower is None or upper is None or upper <= lower:
        raise ValueError("half-power crossings are not resolved in the selected band")
    resonance = float(frequency[local_peak])
    damping = (upper - lower) / (2.0 * resonance)
    return {
        "frequency_hz": resonance,
        "peak_magnitude": peak,
        "half_power_magnitude": threshold,
        "lower_half_power_hz": lower,
        "upper_half_power_hz": upper,
        "damping_ratio": float(damping),
        "frequency_resolution_hz": float(np.median(np.diff(frequency))),
    }


def estimate_h1_mode(
    time_s: Sequence[float],
    input_signal: Sequence[float],
    output_signal: Sequence[float],
    *,
    frequency_band_hz: tuple[float, float],
    nperseg: int = 1024,
    coherence_minimum: float = 0.60,
    response_derivative_order: int = 0,
) -> dict[str, Any]:
    """Run the frozen H1/coherence/half-power estimator chain."""
    if response_derivative_order not in {0, 1, 2}:
        raise ValueError("H1 response derivative order must be 0, 1, or 2")
    estimate = h1_frequency_response(
        time_s,
        input_signal,
        output_signal,
        nperseg=nperseg,
        coherence_minimum=coherence_minimum,
    )
    corrected_magnitude = np.asarray(estimate["magnitude"], dtype=float)
    if response_derivative_order:
        omega = 2.0 * np.pi * np.asarray(estimate["frequency_hz"], dtype=float)
        denominator = np.where(
            omega > 0.0,
            omega**response_derivative_order,
            np.inf,
        )
        corrected_magnitude = corrected_magnitude / denominator
    mode = half_power_damping(
        estimate["frequency_hz"],
        corrected_magnitude,
        frequency_band_hz=frequency_band_hz,
        valid_mask=estimate["coherence_mask"],
    )
    band = (
        (estimate["frequency_hz"] >= frequency_band_hz[0])
        & (estimate["frequency_hz"] <= frequency_band_hz[1])
        & estimate["coherence_mask"]
    )
    mode_index = int(
        np.argmin(
            np.abs(
                np.asarray(estimate["frequency_hz"], dtype=float)
                - float(mode["frequency_hz"])
            )
        )
    )
    return {
        **mode,
        "raw_magnitude_at_mode": float(estimate["magnitude"][mode_index]),
        "response_derivative_order": response_derivative_order,
        "median_coherence": float(np.median(estimate["coherence"][band])),
        "valid_bin_count": int(np.count_nonzero(band)),
        "nperseg": int(estimate["nperseg"]),
    }


def estimate_roll_time_constant(
    time_s: Sequence[float],
    roll_rate_rad_s: Sequence[float],
) -> dict[str, float]:
    """Fit p(t)=offset+amplitude*exp(-t/tau) after control release."""
    time = np.asarray(time_s, dtype=float)
    rate = np.asarray(roll_rate_rad_s, dtype=float)
    if time.shape != rate.shape or len(time) < 20:
        raise ValueError("roll estimator needs at least 20 paired samples")
    relative_time = time - time[0]
    offset_guess = float(np.median(rate[-max(3, len(rate) // 10) :]))
    amplitude_guess = float(rate[0] - offset_guess)
    if abs(amplitude_guess) < 1e-8:
        raise ValueError("roll response has no resolvable initial amplitude")

    def response(
        t: np.ndarray, amplitude: float, tau: float, offset: float
    ) -> np.ndarray:
        return offset + amplitude * np.exp(-t / tau)

    parameters, _ = optimize.curve_fit(
        response,
        relative_time,
        rate,
        p0=(amplitude_guess, max(relative_time[-1] / 4.0, 0.01), offset_guess),
        bounds=(
            (-np.inf, max(np.median(np.diff(time)), 1e-6), -np.inf),
            (np.inf, max(relative_time[-1] * 5.0, 0.02), np.inf),
        ),
        maxfev=20_000,
    )
    predicted = response(relative_time, *parameters)
    residual = rate - predicted
    total = rate - np.mean(rate)
    r2 = 1.0 - float(np.sum(residual**2)) / max(float(np.sum(total**2)), 1e-15)
    return {
        "time_constant_s": float(parameters[1]),
        "amplitude_rad_s": float(parameters[0]),
        "offset_rad_s": float(parameters[2]),
        "fit_r2": r2,
    }


def estimate_control_peak(
    response: Sequence[float],
    *,
    baseline_samples: int = 5,
) -> dict[str, float]:
    values = np.asarray(response, dtype=float)
    if len(values) <= baseline_samples or baseline_samples < 1:
        raise ValueError("control peak needs response and baseline samples")
    baseline = float(np.median(values[:baseline_samples]))
    delta = values - baseline
    index = int(np.argmax(np.abs(delta)))
    return {
        "peak_delta": float(delta[index]),
        "peak_absolute_delta": float(abs(delta[index])),
        "baseline": baseline,
        "sample_index": float(index),
    }


def estimate_control_response(
    time_s: Sequence[float],
    response: Sequence[float],
    control: Sequence[float],
    *,
    baseline_duration_s: float = 1.0,
) -> dict[str, float]:
    """Estimate amplitude-normalized response without assuming pulse timing."""
    time = np.asarray(time_s, dtype=float)
    output = np.asarray(response, dtype=float)
    input_signal = np.asarray(control, dtype=float)
    if time.shape != output.shape or time.shape != input_signal.shape or len(time) < 20:
        raise ValueError("control response needs at least 20 aligned samples")
    baseline = time <= time[0] + baseline_duration_s
    if np.count_nonzero(baseline) < 5:
        raise ValueError("control response baseline has fewer than five samples")
    output_delta = output - float(np.median(output[baseline]))
    input_delta = input_signal - float(np.median(input_signal[baseline]))
    active = ~baseline
    if np.count_nonzero(active) < 5:
        raise ValueError("control response has fewer than five excited samples")
    active_indices = np.flatnonzero(active)
    input_peak = float(np.max(np.abs(input_delta[active])))
    if input_peak < 1e-6:
        raise ValueError("control response has no resolvable excitation")
    output_peak = float(np.max(np.abs(output_delta[active])))
    input_rms = float(np.sqrt(np.mean(input_delta[active] ** 2)))
    output_rms = float(np.sqrt(np.mean(output_delta[active] ** 2)))
    if input_rms < 1e-7:
        raise ValueError("control response excitation RMS is unresolved")
    input_peak_index = int(active_indices[int(np.argmax(np.abs(input_delta[active])))])
    output_peak_index = int(
        active_indices[int(np.argmax(np.abs(output_delta[active])))]
    )
    return {
        "peak_gain": output_peak / input_peak,
        "rms_gain": output_rms / input_rms,
        "peak_lag_s": float(time[output_peak_index] - time[input_peak_index]),
        "input_peak": input_peak,
        "output_peak": output_peak,
    }


def fit_signal_slope(
    abscissa: Sequence[float],
    ordinate: Sequence[float],
) -> dict[str, float]:
    """Robust Theil-Sen slope with an ordinary-fit diagnostic."""
    x = np.asarray(abscissa, dtype=float)
    y = np.asarray(ordinate, dtype=float)
    if x.shape != y.shape or len(x) < 20:
        raise ValueError("signal slope needs at least 20 paired samples")
    if float(np.ptp(x)) < 1e-6:
        raise ValueError("signal slope abscissa has no usable range")
    slope, intercept, low, high = stats.theilslopes(y, x, alpha=0.95)
    diagnostic = stats.linregress(x, y)
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "slope_95_low": float(low),
        "slope_95_high": float(high),
        "linear_fit_r2": float(diagnostic.rvalue**2),
    }


def fit_trim_elevon(
    airspeed_mps: Sequence[float],
    elevon_rad: Sequence[float],
) -> dict[str, float]:
    speed = np.asarray(airspeed_mps, dtype=float)
    elevon = np.asarray(elevon_rad, dtype=float)
    if speed.shape != elevon.shape or len(speed) < 4:
        raise ValueError("trim fit needs at least four paired points")
    slope, intercept, lower, upper = stats.theilslopes(elevon, speed, alpha=0.95)
    return {
        "slope_rad_per_mps": float(slope),
        "intercept_rad": float(intercept),
        "slope_95_low": float(lower),
        "slope_95_high": float(upper),
    }


def fit_static_aero(
    alpha_rad: Sequence[float],
    cl: Sequence[float],
    cd: Sequence[float],
) -> dict[str, float]:
    alpha = np.asarray(alpha_rad, dtype=float)
    lift = np.asarray(cl, dtype=float)
    drag = np.asarray(cd, dtype=float)
    if alpha.shape != lift.shape or alpha.shape != drag.shape or len(alpha) < 5:
        raise ValueError("static aero fit needs at least five paired points")
    lift_fit = stats.linregress(alpha, lift)
    drag_fit = stats.linregress(lift**2, drag)
    return {
        "cl_alpha_per_rad": float(lift_fit.slope),
        "cl_zero": float(lift_fit.intercept),
        "lift_fit_r2": float(lift_fit.rvalue**2),
        "cd_zero": float(drag_fit.intercept),
        "induced_drag_k": float(drag_fit.slope),
        "drag_fit_r2": float(drag_fit.rvalue**2),
    }


def aggregate_estimates(
    estimates: Iterable[Mapping[str, float]],
    keys: Sequence[str],
) -> dict[str, float]:
    rows = list(estimates)
    if not rows:
        raise ValueError("cannot aggregate an empty estimate set")
    result: dict[str, float] = {}
    for key in keys:
        values = np.asarray([float(row[key]) for row in rows])
        result[key] = float(np.median(values))
        result[f"{key}_mad"] = float(np.median(np.abs(values - np.median(values))))
    result["maneuver_count"] = float(len(rows))
    return result


def estimate_protocol_metrics(
    series_by_maneuver: Mapping[str, FlightSeries],
    protocol: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    """Apply one frozen protocol identically to measured or simulated series."""
    output: dict[str, dict[str, float]] = {}
    for metric_name, definition in protocol.items():
        kind = str(definition["kind"])
        maneuvers = [series_by_maneuver[name] for name in definition["maneuvers"]]
        estimates: list[dict[str, float]] = []
        for series in maneuvers:
            window = series.window(
                float(definition["start_s"]),
                float(definition["end_s"]),
            )
            if kind == "damped_mode":
                estimates.append(
                    estimate_damped_mode(
                        window.time_s,
                        window.columns[str(definition["signal"])],
                        frequency_band_hz=tuple(definition["frequency_band_hz"]),
                    )
                )
            elif kind == "roll_time_constant":
                estimates.append(
                    estimate_roll_time_constant(
                        window.time_s,
                        window.columns[str(definition["signal"])],
                    )
                )
            elif kind == "control_peak":
                estimates.append(
                    estimate_control_peak(
                        window.columns[str(definition["signal"])],
                        baseline_samples=int(definition.get("baseline_samples", 5)),
                    )
                )
            else:
                raise ValueError(f"unsupported flight metric kind: {kind}")
        output[metric_name] = aggregate_estimates(estimates, definition["outputs"])
    return output


def evaluate_frozen_protocol(
    series_by_maneuver: Mapping[str, FlightSeries],
    protocol: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    """Evaluate pattern-based metrics identically on flight and replay data."""
    definitions = protocol.get("metrics")
    if not isinstance(definitions, Mapping) or not definitions:
        raise ValueError("flight protocol requires a non-empty metrics mapping")
    values: dict[str, float] = {}
    details: dict[str, Any] = {}
    for metric_name, raw_definition in definitions.items():
        if not isinstance(raw_definition, Mapping):
            raise ValueError(f"{metric_name}: metric definition must be a mapping")
        definition = dict(raw_definition)
        pattern = str(definition["maneuver_glob"])
        names = sorted(
            name
            for name in series_by_maneuver
            if fnmatch.fnmatch(f"{name}.csv", pattern) or fnmatch.fnmatch(name, pattern)
        )
        if not names:
            raise ValueError(f"{metric_name}: no maneuvers match {pattern!r}")
        kind = str(definition["kind"])
        output_key = str(definition["output"])
        per_maneuver: list[dict[str, float | str]] = []
        if kind == "control_response":
            for name in names:
                series = series_by_maneuver[name]
                estimate = estimate_control_response(
                    series.time_s,
                    series.columns[str(definition["signal"])],
                    series.columns[str(definition["control"])],
                    baseline_duration_s=float(
                        definition.get("baseline_duration_s", 1.0)
                    ),
                )
                per_maneuver.append({"maneuver": name, **estimate})
            metric_values = np.asarray(
                [float(item[output_key]) for item in per_maneuver],
                dtype=float,
            )
            value = float(np.median(metric_values))
            dispersion = float(
                np.median(np.abs(metric_values - np.median(metric_values)))
            )
        elif kind == "signal_slope":
            x_values = np.concatenate(
                [
                    series_by_maneuver[name].columns[str(definition["abscissa"])]
                    for name in names
                ]
            )
            y_values = np.concatenate(
                [
                    series_by_maneuver[name].columns[str(definition["signal"])]
                    for name in names
                ]
            )
            estimate = fit_signal_slope(x_values, y_values)
            per_maneuver.append({"maneuver": "pooled", **estimate})
            value = float(estimate[output_key])
            dispersion = 0.5 * abs(
                float(estimate["slope_95_high"]) - float(estimate["slope_95_low"])
            )
        elif kind == "baseline_median":
            duration = float(definition.get("baseline_duration_s", 1.0))
            for name in names:
                series = series_by_maneuver[name]
                mask = series.time_s <= series.time_s[0] + duration
                if np.count_nonzero(mask) < 5:
                    raise ValueError(
                        f"{metric_name}/{name}: baseline has too few samples"
                    )
                per_maneuver.append(
                    {
                        "maneuver": name,
                        "median": float(
                            np.median(series.columns[str(definition["signal"])][mask])
                        ),
                    }
                )
            metric_values = np.asarray(
                [float(item[output_key]) for item in per_maneuver],
                dtype=float,
            )
            value = float(np.median(metric_values))
            dispersion = float(
                np.median(np.abs(metric_values - np.median(metric_values)))
            )
        else:
            raise ValueError(f"{metric_name}: unsupported frozen metric kind {kind}")
        values[str(metric_name)] = value
        details[str(metric_name)] = {
            "kind": kind,
            "maneuver_glob": pattern,
            "maneuvers": names,
            "output": output_key,
            "value": value,
            "median_absolute_deviation": dispersion,
            "per_maneuver": per_maneuver,
        }
    return values, details
