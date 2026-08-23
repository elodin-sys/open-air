"""MATLAB intake and canonical channel mapping for the Diana 2 dataset.

The public flight files were produced by MATLAB R2022b.  This module accepts
both classic MAT files (through :func:`scipy.io.loadmat`) and v7.3/HDF5 files
without exposing either representation to the scorer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import numpy as np
from scipy import signal
from scipy.io import loadmat

from openair.truth.flight_metrics import FlightSeries, estimate_h1_mode


_MATLAB_METADATA_KEYS = {"__header__", "__version__", "__globals__", "#refs#"}


@dataclass(frozen=True)
class Diana2Flight:
    """One flight represented on the dataset's common time base."""

    series: FlightSeries
    source_channels: dict[str, str]
    mat_format: str
    temperature_compensation: str


def _decode_matlab_chars(values: np.ndarray) -> str:
    flat = np.asarray(values).ravel(order="F")
    return "".join(chr(int(value)) for value in flat if int(value)).rstrip("\x00")


def _hdf5_value(node: h5py.Group | h5py.Dataset, root: h5py.File) -> Any:
    if isinstance(node, h5py.Group):
        return {
            name: _hdf5_value(child, root)
            for name, child in node.items()
            if name not in _MATLAB_METADATA_KEYS
        }

    values = node[()]
    matlab_class = node.attrs.get("MATLAB_class", b"")
    if isinstance(matlab_class, np.ndarray):
        matlab_class = matlab_class.tobytes()
    if isinstance(matlab_class, bytes):
        matlab_class = matlab_class.decode("ascii", errors="replace")
    if matlab_class == "char":
        return _decode_matlab_chars(values)

    if h5py.check_dtype(ref=node.dtype) is not None:
        resolved = np.empty(values.shape, dtype=object)
        for index, reference in np.ndenumerate(values):
            resolved[index] = (
                _hdf5_value(root[reference], root) if reference else None
            )
        squeezed = np.squeeze(resolved)
        if squeezed.ndim == 0:
            return squeezed.item()
        return squeezed

    array = np.asarray(values)
    if array.dtype.names == ("real", "imag"):
        array = array["real"] + 1j * array["imag"]
    if matlab_class == "logical":
        array = array.astype(bool)
    if array.ndim >= 2:
        array = np.transpose(array, axes=tuple(reversed(range(array.ndim))))
    return np.squeeze(array)


def load_mat_payload(path: Path) -> tuple[dict[str, Any], str]:
    """Load a classic or HDF5 MAT file and report the selected backend."""

    path = Path(path)
    try:
        payload = loadmat(path, simplify_cells=True)
    except (NotImplementedError, OSError, ValueError):
        with h5py.File(path, "r") as stream:
            payload = {
                name: _hdf5_value(node, stream)
                for name, node in stream.items()
                if name not in _MATLAB_METADATA_KEYS
            }
        backend = "matlab-v7.3-hdf5"
    else:
        backend = "matlab-pre-v7.3"
    return (
        {
            str(key): value
            for key, value in payload.items()
            if key not in _MATLAB_METADATA_KEYS
        },
        backend,
    )


def _flatten(
    value: Any,
    *,
    prefix: str = "",
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = output if output is not None else {}
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            _flatten(child, prefix=name, output=result)
    elif isinstance(value, np.ndarray) and value.dtype == object:
        if value.ndim == 0:
            _flatten(value.item(), prefix=prefix, output=result)
        elif value.size == 1:
            _flatten(value.ravel()[0], prefix=prefix, output=result)
        else:
            for index, child in np.ndenumerate(value):
                suffix = ",".join(str(part) for part in index)
                _flatten(child, prefix=f"{prefix}[{suffix}]", output=result)
    else:
        result[prefix] = value
    return result


def numeric_channel_inventory(path: Path) -> list[dict[str, Any]]:
    """Return names and shapes only; never serialize flight sample values."""

    path = Path(path)
    if h5py.is_hdf5(path):
        inventory: list[dict[str, Any]] = []
        with h5py.File(path, "r") as stream:

            def record(name: str, node: h5py.Group | h5py.Dataset) -> None:
                if not isinstance(node, h5py.Dataset):
                    return
                matlab_class = node.attrs.get("MATLAB_class", b"")
                if isinstance(matlab_class, bytes):
                    matlab_class = matlab_class.decode("ascii", errors="replace")
                if (
                    matlab_class == "char"
                    or h5py.check_dtype(ref=node.dtype) is not None
                    or node.dtype.kind not in "biufc"
                    or node.size < 2
                ):
                    return
                raw_shape = (
                    list(reversed(node.shape)) if node.ndim >= 2 else list(node.shape)
                )
                shape = [size for size in raw_shape if size != 1] or [1]
                inventory.append(
                    {
                        "path": name.replace("/", "."),
                        "shape": shape,
                        "dtype": str(node.dtype),
                        "mat_format": "matlab-v7.3-hdf5",
                    }
                )

            stream.visititems(record)
        return sorted(inventory, key=lambda item: str(item["path"]))

    payload, backend = load_mat_payload(path)
    inventory = []
    for name, value in sorted(_flatten(payload).items()):
        array = np.asarray(value)
        if array.dtype.kind not in "biufc" or array.size < 2:
            continue
        inventory.append(
            {
                "path": name,
                "shape": list(array.shape),
                "dtype": str(array.dtype),
                "mat_format": backend,
            }
        )
    return inventory


def _normalize_channel_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _resolve_channel(
    flattened: Mapping[str, Any],
    requested: str,
) -> tuple[np.ndarray, str]:
    if requested in flattened:
        return np.asarray(flattened[requested], dtype=float).reshape(-1), requested
    normalized = _normalize_channel_name(requested)
    matches = [
        name
        for name in flattened
        if _normalize_channel_name(name) == normalized
        or _normalize_channel_name(name).endswith(normalized)
    ]
    if len(matches) != 1:
        raise KeyError(
            f"MAT channel {requested!r} resolved to {len(matches)} paths: {matches}"
        )
    name = matches[0]
    return np.asarray(flattened[name], dtype=float).reshape(-1), name


def _auto_time_channel(flattened: Mapping[str, Any]) -> str:
    preferred = ("time", "times", "timestamp", "timestampsec")
    candidates = []
    for name, value in flattened.items():
        array = np.asarray(value)
        leaf = _normalize_channel_name(name.rsplit(".", maxsplit=1)[-1])
        if (
            leaf in preferred
            and array.dtype.kind in "biufc"
            and array.ndim <= 2
            and array.size >= 10
        ):
            candidates.append(name)
    if len(candidates) != 1:
        raise KeyError(
            "Diana 2 time channel must be explicit; "
            f"automatic discovery found {candidates}"
        )
    return candidates[0]


def temperature_compensate_strain(
    raw_microstrain: Sequence[float],
    temperature_c: Sequence[float],
    *,
    slope_microstrain_per_c: float,
    intercept_microstrain: float = 0.0,
    reference_temperature_c: float = 15.0,
) -> np.ndarray:
    """Remove the publisher's linear thermal bias model from a strain channel."""

    strain = np.asarray(raw_microstrain, dtype=float)
    temperature = np.asarray(temperature_c, dtype=float)
    if strain.shape != temperature.shape:
        raise ValueError("strain and temperature channels must have equal shapes")
    thermal_bias = (
        slope_microstrain_per_c * (temperature - reference_temperature_c)
        + intercept_microstrain
    )
    return strain - thermal_bias


def synthesize_frf_response(
    time_s: Sequence[float],
    measured_control: Sequence[float],
    model_frequency_hz: Sequence[float],
    model_response: Sequence[complex],
) -> np.ndarray:
    """Filter a measured encoder input through a frozen complex model FRF."""

    time = np.asarray(time_s, dtype=float)
    control = np.asarray(measured_control, dtype=float)
    frequency = np.asarray(model_frequency_hz, dtype=float)
    response = np.asarray(model_response, dtype=complex)
    if time.shape != control.shape or len(time) < 64:
        raise ValueError("FRF synthesis needs at least 64 paired time/control samples")
    if (
        frequency.shape != response.shape
        or len(frequency) < 8
        or np.any(np.diff(frequency) <= 0.0)
    ):
        raise ValueError("model FRF frequency grid is invalid")
    dt = float(np.median(np.diff(time)))
    if np.max(np.abs(np.diff(time) - dt)) > 0.05 * dt:
        uniform_time = np.arange(time[0], time[-1] + 0.25 * dt, dt)
        uniform_control = np.interp(uniform_time, time, control)
    else:
        uniform_time = time
        uniform_control = control
    fft_frequency = np.fft.rfftfreq(len(uniform_time), d=dt)
    interpolated = np.interp(
        fft_frequency,
        frequency,
        np.real(response),
        left=0.0,
        right=0.0,
    ) + 1j * np.interp(
        fft_frequency,
        frequency,
        np.imag(response),
        left=0.0,
        right=0.0,
    )
    control_fft = np.fft.rfft(
        uniform_control - float(np.mean(uniform_control))
    )
    output = np.fft.irfft(control_fft * interpolated, n=len(uniform_time))
    if uniform_time is not time:
        output = np.interp(time, uniform_time, output)
    return np.asarray(output, dtype=float)


def load_diana2_flight(
    path: Path,
    *,
    channel_map: Mapping[str, str],
    derived_channels: Mapping[str, Sequence[Mapping[str, float | str]]] | None = None,
    temperature_compensation: Mapping[str, Any] | None = None,
) -> Diana2Flight:
    """Map one publisher MAT file into canonical scorer channel names.

    ``channel_map`` is deliberately protocol-owned.  This prevents fuzzy
    channel guesses from changing silently between a training baseline and a
    sealed holdout score.  Values in ``derived_channels`` are linear
    combinations, used primarily to turn measured left/right encoder angles
    into collective or differential control inputs.
    """

    payload, backend = load_mat_payload(path)
    flattened = _flatten(payload)
    requested_time = channel_map.get("time_s") or _auto_time_channel(flattened)
    time_s, time_source = _resolve_channel(flattened, requested_time)
    columns: dict[str, np.ndarray] = {}
    sources = {"time_s": time_source}
    for canonical, requested in channel_map.items():
        if canonical == "time_s":
            continue
        values, source = _resolve_channel(flattened, requested)
        columns[str(canonical)] = values
        sources[str(canonical)] = source

    for canonical, terms in (derived_channels or {}).items():
        combined = np.zeros_like(time_s, dtype=float)
        source_terms = []
        for term in terms:
            source = str(term["source"])
            gain = float(term["gain"])
            if source not in columns:
                raise KeyError(
                    f"derived channel {canonical!r} references unmapped {source!r}"
                )
            combined += gain * columns[source]
            source_terms.append(f"{gain:g}*{source}")
        columns[str(canonical)] = combined
        sources[str(canonical)] = " + ".join(source_terms)

    correction = temperature_compensation or {}
    if correction.get("source_already_compensated", False):
        compensation_status = "publisher-applied"
    else:
        channels = correction.get("channels") or {}
        for canonical, parameters in channels.items():
            canonical = str(canonical)
            if canonical not in columns:
                raise KeyError(f"temperature correction channel missing: {canonical}")
            temperature_name = str(parameters["temperature_channel"])
            if temperature_name not in columns:
                raise KeyError(
                    f"temperature channel missing for {canonical}: {temperature_name}"
                )
            columns[canonical] = temperature_compensate_strain(
                columns[canonical],
                columns[temperature_name],
                slope_microstrain_per_c=float(
                    parameters["slope_microstrain_per_c"]
                ),
                intercept_microstrain=float(
                    parameters.get("intercept_microstrain", 0.0)
                ),
                reference_temperature_c=float(
                    correction.get("reference_temperature_c", 15.0)
                ),
            )
        compensation_status = (
            "openair-linear-correction" if channels else "not-requested"
        )

    lengths = {len(time_s), *(len(values) for values in columns.values())}
    if len(lengths) != 1:
        mismatches = {name: len(values) for name, values in columns.items()}
        raise ValueError(
            f"Diana 2 channel lengths differ from time ({len(time_s)}): {mismatches}"
        )
    finite = np.isfinite(time_s)
    for values in columns.values():
        finite &= np.isfinite(values)
    if np.count_nonzero(finite) < 64:
        raise ValueError(f"{path} has fewer than 64 jointly finite samples")
    time_s = time_s[finite]
    columns = {name: values[finite] for name, values in columns.items()}
    order = np.argsort(time_s, kind="stable")
    time_s = time_s[order]
    columns = {name: values[order] for name, values in columns.items()}
    unique = np.concatenate(([True], np.diff(time_s) > 0.0))
    return Diana2Flight(
        series=FlightSeries.from_columns(
            time_s[unique],
            {name: values[unique] for name, values in columns.items()},
        ),
        source_channels=sources,
        mat_format=backend,
        temperature_compensation=compensation_status,
    )


def load_diana2_directory(
    directory: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Diana2Flight]:
    """Load all sealed-split flight files with one protocol-owned channel map."""

    files = sorted(Path(directory).glob("*.mat"))
    if not files:
        raise FileNotFoundError(f"no Diana 2 MAT flights found in {directory}")
    channel_map = protocol.get("channel_map")
    if not isinstance(channel_map, Mapping) or not channel_map:
        raise ValueError("Diana 2 protocol requires a channel_map")
    return {
        path.stem: load_diana2_flight(
            path,
            channel_map={
                str(key): str(value) for key, value in channel_map.items()
            },
            derived_channels=protocol.get("derived_channels"),
            temperature_compensation=protocol.get("temperature_compensation"),
        )
        for path in files
    }


def _complex_response(payload: Mapping[str, Any]) -> np.ndarray:
    real = np.asarray(payload["real"], dtype=float)
    imaginary = np.asarray(payload["imag"], dtype=float)
    if real.shape != imaginary.shape:
        raise ValueError("model FRF real and imaginary arrays differ in shape")
    return real + 1j * imaginary


def _ranked_energy_flight_windows(
    series: FlightSeries,
    *,
    control_name: str,
    condition: Mapping[str, Any],
    duration_s: float,
    minimum_condition_fraction: float = 0.90,
    selection_frequency_band_hz: tuple[float, float] | None = None,
    candidate_count: int = 1,
    candidate_stride_s: float = 2.0,
) -> list[FlightSeries]:
    """Rank fixed-duration in-envelope windows by band-limited encoder energy."""

    if duration_s <= 0.0:
        raise ValueError("excitation-window duration must be positive")
    control = series.columns[control_name]
    condition_name = str(condition["signal"])
    condition_values = series.columns[condition_name]
    valid = (condition_values >= float(condition["minimum"])) & (
        condition_values <= float(condition["maximum"])
    )
    dt = float(np.median(np.diff(series.time_s)))
    samples = int(round(duration_s / dt))
    if samples < 64:
        raise ValueError("excitation window must contain at least 64 samples")
    if not 0.0 < minimum_condition_fraction <= 1.0:
        raise ValueError("minimum condition fraction must be in (0, 1]")
    if len(control) < samples:
        raise ValueError("flight is shorter than the requested excitation window")
    selection_signal = control
    if selection_frequency_band_hz is not None:
        low, high = selection_frequency_band_hz
        nyquist = 0.5 / dt
        if not 0.0 < low < high < nyquist:
            raise ValueError("window-selection frequency band is invalid")
        sos = signal.butter(
            3,
            [low, high],
            btype="bandpass",
            fs=1.0 / dt,
            output="sos",
        )
        selection_signal = signal.sosfiltfilt(sos, control)
    cumulative = np.concatenate(([0.0], np.cumsum(selection_signal)))
    cumulative_square = np.concatenate(([0.0], np.cumsum(selection_signal**2)))
    valid_cumulative = np.concatenate(([0], np.cumsum(valid.astype(np.int64))))
    sums = cumulative[samples:] - cumulative[:-samples]
    square_sums = cumulative_square[samples:] - cumulative_square[:-samples]
    variances = square_sums / samples - (sums / samples) ** 2
    fractions = (
        valid_cumulative[samples:] - valid_cumulative[:-samples]
    ) / samples
    eligible = fractions >= minimum_condition_fraction
    if not np.any(eligible):
        raise ValueError("no window satisfies the frozen flight-condition coverage")
    energies = np.where(eligible, variances, -np.inf)
    stride = max(1, int(round(candidate_stride_s / dt)))
    allowed_starts = np.arange(0, len(energies), stride, dtype=int)
    allowed_starts = allowed_starts[np.isfinite(energies[allowed_starts])]
    if not 1 <= candidate_count <= 100:
        raise ValueError("candidate window count must be between 1 and 100")
    if not len(allowed_starts):
        raise ValueError("no candidate starts satisfy the frozen window stride")
    ranked = allowed_starts[
        np.argsort(energies[allowed_starts], kind="stable")[::-1]
    ][:candidate_count]
    if not np.isfinite(energies[ranked[0]]) or energies[ranked[0]] <= 1e-12:
        raise ValueError("no in-envelope encoder excitation window was found")
    return [
        FlightSeries.from_columns(
            series.time_s[start : start + samples],
            {
                name: values[start : start + samples]
                for name, values in series.columns.items()
            },
        )
        for start in ranked
    ]


def _highest_energy_flight_window(
    series: FlightSeries,
    *,
    control_name: str,
    condition: Mapping[str, Any],
    duration_s: float,
    minimum_condition_fraction: float = 0.90,
    selection_frequency_band_hz: tuple[float, float] | None = None,
) -> FlightSeries:
    return _ranked_energy_flight_windows(
        series,
        control_name=control_name,
        condition=condition,
        duration_s=duration_s,
        minimum_condition_fraction=minimum_condition_fraction,
        selection_frequency_band_hz=selection_frequency_band_hz,
    )[0]


def evaluate_frf_protocol(
    flights: Mapping[str, Diana2Flight],
    aeroelastic: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    """Apply the frozen H1 chain to measured and model-filtered responses."""

    metric_definitions = protocol.get("metrics")
    if not isinstance(metric_definitions, Mapping) or not metric_definitions:
        raise ValueError("Diana 2 protocol requires non-empty metrics")
    measured_values: dict[str, float] = {}
    predicted_values: dict[str, float] = {}
    details: dict[str, Any] = {}
    frfs = aeroelastic.get("frfs")
    if not isinstance(frfs, Mapping):
        raise ValueError("flightdyn artifact has no aeroelastic FRFs")

    for observable, raw_definition in metric_definitions.items():
        if not isinstance(raw_definition, Mapping):
            raise ValueError(f"{observable}: metric definition must be a mapping")
        definition = dict(raw_definition)
        command = str(definition["model_control"])
        response_group = str(definition["model_response_group"])
        response_name = str(definition["model_response"])
        control_name = str(definition["control"])
        signal_name = str(definition["signal"])
        output_name = str(definition["output"])
        frf = frfs.get(command)
        if not isinstance(frf, Mapping) or not frf.get("supported"):
            raise ValueError(f"{observable}: model control {command!r} is unsupported")
        responses = frf.get(response_group)
        if not isinstance(responses, Mapping) or response_name not in responses:
            raise ValueError(
                f"{observable}: model response {response_group}/{response_name} missing"
            )
        frequency = np.asarray(frf["frequency_hz"], dtype=float)
        model_response = _complex_response(responses[response_name])
        measured_estimates = []
        predicted_estimates = []
        failures: dict[str, str] = {}
        for flight_id, flight in sorted(flights.items()):
            try:
                series = flight.series
                condition = definition.get("flight_condition")
                if isinstance(condition, Mapping):
                    candidates = _ranked_energy_flight_windows(
                        series,
                        control_name=control_name,
                        condition=condition,
                        duration_s=float(definition.get("window_duration_s", 60.0)),
                        minimum_condition_fraction=float(
                            definition.get("minimum_condition_fraction", 0.90)
                        ),
                        selection_frequency_band_hz=(
                            tuple(
                                float(value)
                                for value in definition[
                                    "selection_frequency_band_hz"
                                ]
                            )
                            if definition.get("selection_frequency_band_hz")
                            is not None
                            else None
                        ),
                        candidate_count=int(
                            definition.get("window_candidate_count", 1)
                        ),
                        candidate_stride_s=float(
                            definition.get("window_candidate_stride_s", 2.0)
                        ),
                    )
                else:
                    candidates = [series]
                estimator_kwargs = {
                    "frequency_band_hz": tuple(
                        float(value) for value in definition["frequency_band_hz"]
                    ),
                    "nperseg": int(definition.get("nperseg", 4096)),
                    "coherence_minimum": float(
                        definition.get("coherence_minimum", 0.60)
                    ),
                    "response_derivative_order": int(
                        definition.get("response_derivative_order", 0)
                    ),
                }
                successful_candidates = []
                for candidate in candidates:
                    try:
                        control = candidate.columns[control_name]
                        measured_signal = candidate.columns[signal_name]
                        simulated_signal = synthesize_frf_response(
                            candidate.time_s,
                            control,
                            frequency,
                            model_response,
                        )
                        measured = estimate_h1_mode(
                            candidate.time_s,
                            control,
                            measured_signal,
                            **estimator_kwargs,
                        )
                        predicted = estimate_h1_mode(
                            candidate.time_s,
                            control,
                            simulated_signal,
                            **estimator_kwargs,
                        )
                    except (KeyError, ValueError):
                        continue
                    successful_candidates.append(
                        (
                            float(measured["median_coherence"]),
                            int(measured["valid_bin_count"]),
                            candidate,
                            measured,
                            predicted,
                        )
                    )
                if not successful_candidates:
                    raise ValueError(
                        "no ranked excitation window passed the frozen H1 estimator"
                    )
                _, _, selected, measured, predicted = max(
                    successful_candidates,
                    key=lambda item: (item[0], item[1]),
                )
            except (KeyError, ValueError) as exc:
                failures[flight_id] = str(exc)
                continue
            window = {
                "window_start_s": float(selected.time_s[0]),
                "window_end_s": float(selected.time_s[-1]),
            }
            measured_estimates.append({"flight": flight_id, **window, **measured})
            predicted_estimates.append({"flight": flight_id, **window, **predicted})
        minimum = int(definition.get("minimum_successful_flights", 1))
        if len(measured_estimates) < minimum:
            raise ValueError(
                f"{observable}: only {len(measured_estimates)} flights passed the "
                f"frozen estimator; minimum={minimum}; failures={failures}"
            )
        measured_array = np.asarray(
            [float(item[output_name]) for item in measured_estimates],
            dtype=float,
        )
        predicted_array = np.asarray(
            [float(item[output_name]) for item in predicted_estimates],
            dtype=float,
        )
        measured_values[str(observable)] = float(np.median(measured_array))
        predicted_values[str(observable)] = float(np.median(predicted_array))
        details[str(observable)] = {
            "output": output_name,
            "successful_flights": [
                str(item["flight"]) for item in measured_estimates
            ],
            "failed_flights": failures,
            "measured_median_absolute_deviation": float(
                np.median(np.abs(measured_array - np.median(measured_array)))
            ),
            "predicted_median_absolute_deviation": float(
                np.median(np.abs(predicted_array - np.median(predicted_array)))
            ),
            "measured": measured_estimates,
            "predicted": predicted_estimates,
            "window_duration_s": definition.get("window_duration_s"),
            "encoder_forcing": control_name,
            "model_control": command,
            "model_response": f"{response_group}/{response_name}",
        }
    return measured_values, predicted_values, details
