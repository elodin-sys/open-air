"""Scorer-side NTNU Skywalker X8 flight-data conversion."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from openair.truth.flight_metrics import (
    FlightSeries,
    evaluate_frozen_protocol,
)

DATA_COLUMNS = (
    "t",
    "elevator",
    "aileron",
    "throttle",
    "IMU_acc_x",
    "IMU_acc_y",
    "IMU_acc_z",
    "IMU_angvel_p",
    "IMU_angvel_q",
    "IMU_angvel_r",
    "EstimatedState_phi",
    "EstimatedState_theta",
    "EstimatedState_psi",
    "EstimatedState_p",
    "EstimatedState_q",
    "EstimatedState_r",
    "EstimatedState_u",
    "EstimatedState_v",
    "EstimatedState_w",
    "EstimatedState_vx",
    "EstimatedState_vy",
    "EstimatedState_vz",
    "EstimatedStreamVelocity_x",
    "EstimatedStreamVelocity_y",
    "EstimatedStreamVelocity_z",
    "EstimatedState_alpha",
    "EstimatedState_beta",
    "TrueSpeed",
    "IndicatedSpeed",
    "GPS_lon",
    "GPS_lat",
    "GPS_height",
    "GPS_x",
    "GPS_y",
    "GPS_z",
    "GPS_cog",
    "GPS_sog",
    "Current",
    "Voltage",
    "Temperature",
    "Pressure",
)


def load_ntnu_maneuver(
    path: Path,
    *,
    mass_kg: float,
    area_m2: float,
    density_kg_m3: float,
) -> FlightSeries:
    """Map the publisher's headerless 41-column CSV into standard axes."""
    raw = np.loadtxt(path, delimiter=",", dtype=float)
    if raw.ndim != 2 or raw.shape[1] != len(DATA_COLUMNS):
        raise ValueError(
            f"{path} must contain {len(DATA_COLUMNS)} numeric columns; "
            f"got shape {raw.shape}"
        )
    if not np.all(np.isfinite(raw)):
        raise ValueError(f"{path} contains non-finite flight data")
    source = {name: raw[:, index] for index, name in enumerate(DATA_COLUMNS)}
    time = source["t"] - source["t"][0]
    dt = np.diff(time)
    if np.any(dt <= 0.0) or abs(float(np.median(dt)) - 0.025) > 0.002:
        raise ValueError(f"{path} is not a monotonic 40 Hz maneuver")
    airspeed = source["IndicatedSpeed"]
    dynamic_pressure = 0.5 * density_kg_m3 * np.maximum(airspeed, 1.0) ** 2
    # STIM300 body-z specific force is negative upward in the published body
    # convention. This normal-force lift estimate is intentionally simple;
    # wind, thrust-axis, and unsteady corrections remain in u_input.
    cl_normal_force = (
        -mass_kg * source["IMU_acc_z"] / np.maximum(dynamic_pressure * area_m2, 1e-9)
    )
    return FlightSeries.from_columns(
        time,
        {
            "collective_elevon_rad": source["elevator"],
            "differential_elevon_rad": source["aileron"],
            "throttle": source["throttle"],
            "airspeed_mps": airspeed,
            "alpha_rad": source["EstimatedState_alpha"],
            "beta_rad": source["EstimatedState_beta"],
            "p_rad_s": source["IMU_angvel_p"],
            "q_rad_s": source["IMU_angvel_q"],
            "r_rad_s": source["IMU_angvel_r"],
            "roll_rad": source["EstimatedState_phi"],
            "pitch_rad": source["EstimatedState_theta"],
            "yaw_rad": source["EstimatedState_psi"],
            "u_mps": source["EstimatedState_u"],
            "v_mps": source["EstimatedState_v"],
            "w_mps": source["EstimatedState_w"],
            "cl": cl_normal_force,
        },
    )


def load_ntnu_directory(
    directory: Path,
    *,
    mass_kg: float,
    area_m2: float,
    density_kg_m3: float,
) -> dict[str, FlightSeries]:
    files = sorted(directory.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no NTNU maneuver CSVs found under {directory}")
    return {
        path.stem: load_ntnu_maneuver(
            path,
            mass_kg=mass_kg,
            area_m2=area_m2,
            density_kg_m3=density_kg_m3,
        )
        for path in files
    }


def write_replay_controls(series: FlightSeries, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "time_s",
        "collective_elevon_rad",
        "differential_elevon_rad",
        "throttle",
        "airspeed_mps",
    )
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for index, time_s in enumerate(series.time_s):
            writer.writerow(
                {
                    "time_s": float(time_s),
                    **{
                        name: float(series.columns[name][index])
                        for name in fieldnames[1:]
                    },
                }
            )
    return path


def load_replay_series(path: Path) -> FlightSeries:
    series = FlightSeries.from_csv(path)
    required = {
        "collective_elevon_rad",
        "differential_elevon_rad",
        "p_rad_s",
        "q_rad_s",
        "r_rad_s",
        "roll_rad",
        "pitch_rad",
        "alpha_rad",
        "cl",
    }
    missing = required - series.columns.keys()
    if missing:
        raise ValueError(f"{path} lacks replay columns {sorted(missing)}")
    return series


def evaluate_series_protocol(
    series: Mapping[str, FlightSeries],
    protocol: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    return evaluate_frozen_protocol(series, protocol)
