from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import h5py
import numpy as np
import pytest
from scipy.io import savemat

from openair.truth.diana2 import (
    Diana2Flight,
    evaluate_frf_protocol,
    load_diana2_flight,
    load_mat_payload,
    numeric_channel_inventory,
    synthesize_frf_response,
    temperature_compensate_strain,
)
from openair.truth.flight_metrics import FlightSeries


def _intake_module():
    path = Path(__file__).parents[1] / "scripts" / "seal_diana2_intake.py"
    spec = importlib.util.spec_from_file_location("seal_diana2_intake", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classic_mat_maps_measured_controls_and_compensates_strain(tmp_path: Path):
    time = np.arange(0.0, 1.0, 0.005)
    temperature = 15.0 + 2.0 * time
    physical_strain = 30.0 * np.sin(2.0 * np.pi * 7.0 * time)
    path = tmp_path / "FT05.mat"
    savemat(
        path,
        {
            "Flight": {
                "time": time,
                "aileron_left": -0.1 * np.ones_like(time),
                "aileron_right": 0.1 * np.ones_like(time),
                "RO_ADS_z": physical_strain + 4.0 * (temperature - 15.0) + 3.0,
                "R_temp": temperature,
            }
        },
    )

    flight = load_diana2_flight(
        path,
        channel_map={
            "time_s": "Flight.time",
            "encoder.outer_left_rad": "Flight.aileron_left",
            "encoder.outer_right_rad": "Flight.aileron_right",
            "strain.RO_ADS_z": "Flight.RO_ADS_z",
            "temperature.right_c": "Flight.R_temp",
        },
        derived_channels={
            "control.outer_aileron_rad": [
                {"source": "encoder.outer_right_rad", "gain": 0.5},
                {"source": "encoder.outer_left_rad", "gain": -0.5},
            ]
        },
        temperature_compensation={
            "reference_temperature_c": 15.0,
            "channels": {
                "strain.RO_ADS_z": {
                    "temperature_channel": "temperature.right_c",
                    "slope_microstrain_per_c": 4.0,
                    "intercept_microstrain": 3.0,
                }
            },
        },
    )

    assert flight.mat_format == "matlab-pre-v7.3"
    assert flight.temperature_compensation == "openair-linear-correction"
    assert np.allclose(
        flight.series.columns["control.outer_aileron_rad"],
        0.1,
    )
    assert np.allclose(
        flight.series.columns["strain.RO_ADS_z"],
        physical_strain,
    )


def test_hdf5_mat_loader_and_inventory_do_not_return_samples(tmp_path: Path):
    path = tmp_path / "FT12.mat"
    with h5py.File(path, "w") as stream:
        time = stream.create_dataset("time", data=np.arange(200.0).reshape(1, -1))
        time.attrs["MATLAB_class"] = np.bytes_("double")
        title = stream.create_dataset(
            "title",
            data=np.array([[ord(character)] for character in "Diana"], dtype=np.uint16),
        )
        title.attrs["MATLAB_class"] = np.bytes_("char")

    payload, backend = load_mat_payload(path)
    inventory = numeric_channel_inventory(path)
    assert backend == "matlab-v7.3-hdf5"
    assert payload["title"] == "Diana"
    assert np.array(payload["time"]).shape == (200,)
    assert inventory == [
        {
            "path": "time",
            "shape": [200],
            "dtype": "float64",
            "mat_format": "matlab-v7.3-hdf5",
        }
    ]
    assert "values" not in inventory[0]


def test_temperature_compensation_requires_aligned_channels():
    with pytest.raises(ValueError, match="equal shapes"):
        temperature_compensate_strain(
            [1.0, 2.0],
            [15.0],
            slope_microstrain_per_c=1.0,
        )


def test_frf_protocol_forces_model_with_measured_encoder_signal():
    rng = np.random.default_rng(122)
    time = np.arange(0.0, 80.0, 0.005)
    control = rng.normal(0.0, 0.02, len(time))
    frequency = np.linspace(0.5, 20.0, 600)
    natural_hz = 7.4
    damping = 0.03
    frequency_ratio = frequency / natural_hz
    response = 2.5 / (
        1.0 - frequency_ratio**2 + 2j * damping * frequency_ratio
    )
    measured = synthesize_frf_response(time, control, frequency, response)
    measured += rng.normal(0.0, np.std(measured) * 0.002, len(measured))
    flight = Diana2Flight(
        series=FlightSeries.from_columns(
            time,
            {
                "control.outer_aileron_rad": control,
                "imu.RO.normal_accel_m_s2": measured,
            },
        ),
        source_channels={},
        mat_format="synthetic",
        temperature_compensation="publisher-applied",
    )
    aeroelastic = {
        "frfs": {
            "outer_aileron": {
                "supported": True,
                "frequency_hz": frequency.tolist(),
                "station_acceleration_m_s2_per_rad": {
                    "RO_normal_accel": {
                        "real": np.real(response).tolist(),
                        "imag": np.imag(response).tolist(),
                    }
                },
            }
        }
    }
    protocol = {
        "metrics": {
            "first_bending_frequency_hz": {
                "control": "control.outer_aileron_rad",
                "signal": "imu.RO.normal_accel_m_s2",
                "model_control": "outer_aileron",
                "model_response_group": "station_acceleration_m_s2_per_rad",
                "model_response": "RO_normal_accel",
                "frequency_band_hz": [5.0, 10.0],
                "nperseg": 4096,
                "coherence_minimum": 0.6,
                "minimum_successful_flights": 1,
                "output": "frequency_hz",
                "units": "Hz",
            }
        }
    }
    truth, prediction, details = evaluate_frf_protocol(
        {"synthetic": flight},
        aeroelastic,
        protocol,
    )
    assert truth["first_bending_frequency_hz"] == pytest.approx(
        prediction["first_bending_frequency_hz"],
        abs=0.05,
    )
    assert details["first_bending_frequency_hz"]["encoder_forcing"] == (
        "control.outer_aileron_rad"
    )


def test_intake_member_selection_uses_names_only_and_rejects_traversal(
    tmp_path: Path,
):
    module = _intake_module()
    archive_path = tmp_path / "flight.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("Flight testing/FT05.mat", b"secret samples")
        archive.writestr("Flight testing/FToverview.mat", b"metadata")
    with zipfile.ZipFile(archive_path) as archive:
        selected, names = module._flight_members(archive, ["FT05"])
    assert list(selected) == ["FT05"]
    assert names == [
        "Flight testing/FT05.mat",
        "Flight testing/FToverview.mat",
    ]

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../FT05.mat", b"secret samples")
    with zipfile.ZipFile(unsafe) as archive:
        with pytest.raises(ValueError, match="unsafe ZIP member"):
            module._flight_members(archive, ["FT05"])
