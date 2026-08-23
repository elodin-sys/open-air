"""Scorer-only conversion of evidence files into normalized truth rows."""

from __future__ import annotations

import csv
import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from openair.flightdyn.sixdof import replay_flightdyn
from openair.provenance import sha256_file
from openair.truth.corpus import load_truth_rows
from openair.truth.corpus import case_dir
from openair.truth.diana2 import evaluate_frf_protocol, load_diana2_directory
from openair.truth.models import TruthPrediction
from openair.truth.ntnu_x8 import (
    evaluate_series_protocol,
    load_ntnu_directory,
    load_replay_series,
    write_replay_controls,
)

TruthRows = list[dict[str, str]]


@dataclass(frozen=True)
class ScorerTruth:
    rows: TruthRows
    predictions: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


TruthLoader = Callable[[str, Path | None, TruthPrediction], ScorerTruth]

REQUIRED_COLUMNS = {
    "observable",
    "value",
    "units",
    "u_exp",
    "u_input",
    "u_num",
}


def _read_observations(path: Path) -> TruthRows:
    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or not REQUIRED_COLUMNS.issubset(rows[0]):
        raise ValueError(f"{path} must contain columns {sorted(REQUIRED_COLUMNS)}")
    return rows


def _observations_csv(
    case_id: str,
    holdout_dir: Path | None,
    _prediction: TruthPrediction,
) -> ScorerTruth:
    if holdout_dir is None:
        return ScorerTruth(rows=load_truth_rows(case_id))
    return ScorerTruth(rows=_read_observations(holdout_dir / "observations.csv"))


def _load_protocol(case_id: str) -> dict[str, Any]:
    path = case_dir(case_id) / "inputs" / "evaluation-protocol.yaml"
    with open(path, encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a protocol mapping")
    return payload


def _raw_maneuver_dir(case_id: str, holdout_dir: Path | None) -> Path:
    base = holdout_dir if holdout_dir is not None else case_dir(case_id) / "truth"
    for split in ("validation", "training"):
        candidate = base / split
        if candidate.is_dir():
            return candidate
    return base


def _ntnu_x8_flight(
    case_id: str,
    holdout_dir: Path | None,
    prediction: TruthPrediction,
) -> ScorerTruth:
    protocol = _load_protocol(case_id)
    metrics = protocol.get("metrics")
    uncertainties = protocol.get("uncertainties")
    if not isinstance(metrics, dict) or not isinstance(uncertainties, dict):
        raise ValueError(
            f"{case_id}: evaluation protocol is not frozen with uncertainties"
        )
    if set(metrics) != set(uncertainties):
        raise ValueError(f"{case_id}: metric and uncertainty coverage differ")
    artifacts = prediction.metadata.get("artifacts") or {}
    model_path = Path(str(artifacts.get("flightdyn", "")))
    if not model_path.is_file():
        raise FileNotFoundError(f"{case_id}: frozen flightdyn artifact is missing")
    with open(model_path, encoding="utf-8") as stream:
        model = json.load(stream)
    references = model["references"]
    mass_properties = model["mass_properties"]
    trim = model["trim_state"]
    measured = load_ntnu_directory(
        _raw_maneuver_dir(case_id, holdout_dir),
        mass_kg=float(mass_properties["mass_kg"]),
        area_m2=float(references["area_m2"]),
        density_kg_m3=float(trim["density_kg_m3"]),
    )
    simulated = {}
    replay_hashes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix=f"openair-{case_id}-scorer-") as raw:
        root = Path(raw)
        for name, measured_series in measured.items():
            maneuver_dir = root / name
            controls = write_replay_controls(
                measured_series,
                maneuver_dir / "controls.csv",
            )
            replay = replay_flightdyn(
                model_path,
                controls,
                maneuver_dir,
                dt_s=float(protocol.get("replay_timestep_s", 0.01)),
            )
            if not replay.get("ok"):
                raise RuntimeError(f"{case_id}/{name}: Elodin replay failed: {replay}")
            replay_path = Path(str(replay["artifacts"]["replay_csv"]))
            simulated[name] = load_replay_series(replay_path)
            replay_hashes[name] = sha256_file(replay_path)
    truth_values, measured_details = evaluate_series_protocol(measured, protocol)
    predicted_values, simulated_details = evaluate_series_protocol(simulated, protocol)
    rows: TruthRows = []
    for observable, value in truth_values.items():
        budget = uncertainties[observable]
        rows.append(
            {
                "observable": observable,
                "value": str(value),
                "units": str(metrics[observable]["units"]),
                "u_exp": str(float(budget["u_exp"])),
                "u_input": str(float(budget["u_input"])),
                "u_num": str(float(budget["u_num"])),
            }
        )
    protocol_path = case_dir(case_id) / "inputs" / "evaluation-protocol.yaml"
    return ScorerTruth(
        rows=rows,
        predictions=predicted_values,
        evidence={
            "evaluation_protocol_sha256": sha256_file(protocol_path),
            **{
                f"scorer_replay:{name}": digest
                for name, digest in replay_hashes.items()
            },
        },
        metadata={
            "measured_metric_details": measured_details,
            "simulated_metric_details": simulated_details,
            "temporary_replays_destroyed": True,
        },
    )


def _diana2_flight(
    case_id: str,
    holdout_dir: Path | None,
    prediction: TruthPrediction,
) -> ScorerTruth:
    protocol = _load_protocol(case_id)
    metrics = protocol.get("metrics")
    uncertainties = protocol.get("uncertainties")
    if not isinstance(metrics, dict) or not isinstance(uncertainties, dict):
        raise ValueError(
            f"{case_id}: evaluation protocol is not frozen with uncertainties"
        )
    if set(metrics) != set(uncertainties):
        raise ValueError(f"{case_id}: metric and uncertainty coverage differ")
    artifacts = prediction.metadata.get("artifacts") or {}
    model_path = Path(str(artifacts.get("flightdyn", "")))
    if not model_path.is_file():
        raise FileNotFoundError(f"{case_id}: frozen flightdyn artifact is missing")
    with open(model_path, encoding="utf-8") as stream:
        flightdyn = json.load(stream)
    aeroelastic = flightdyn.get("aeroelastic")
    if not isinstance(aeroelastic, dict) or not aeroelastic.get("ok"):
        raise ValueError(f"{case_id}: frozen aeroelastic model is not scoreable")
    intake_path = case_dir(case_id) / "inputs" / "intake-record.yaml"
    with open(intake_path, encoding="utf-8") as stream:
        intake = yaml.safe_load(stream)
    if not isinstance(intake, dict) or intake.get("version") != 1:
        raise ValueError(f"{case_id}: Diana 2 intake record is invalid")
    partition_name = {
        "diana2-training": "training",
        "diana2-flight": "validation_holdout",
        "diana2-reserve": "reserve",
    }.get(case_id)
    if partition_name is None:
        raise ValueError(f"unsupported Diana 2 split case: {case_id}")
    expected_files = intake["partition"][partition_name]
    if not isinstance(expected_files, dict) or not expected_files:
        raise ValueError(f"{case_id}: intake partition is empty")
    maneuver_dir = _raw_maneuver_dir(case_id, holdout_dir)
    raw_hashes: dict[str, str] = {}
    for filename, record in expected_files.items():
        path = maneuver_dir / str(filename)
        expected = str(record["sha256"])
        if not path.is_file():
            raise FileNotFoundError(f"{case_id}: sealed split file is missing: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(
                f"{case_id}/{filename}: intake hash mismatch; "
                f"expected {expected}, got {actual}"
            )
        raw_hashes[f"raw_mat:{filename}"] = actual
    measured = load_diana2_directory(
        maneuver_dir,
        protocol,
    )
    truth_values, predicted_values, details = evaluate_frf_protocol(
        measured,
        aeroelastic,
        protocol,
    )
    rows: TruthRows = []
    for observable, value in truth_values.items():
        budget = uncertainties[observable]
        rows.append(
            {
                "observable": observable,
                "value": str(value),
                "units": str(metrics[observable]["units"]),
                "u_exp": str(float(budget["u_exp"])),
                "u_input": str(float(budget["u_input"])),
                "u_num": str(float(budget["u_num"])),
            }
        )
    protocol_path = case_dir(case_id) / "inputs" / "evaluation-protocol.yaml"
    return ScorerTruth(
        rows=rows,
        predictions=predicted_values,
        evidence={
            "evaluation_protocol_sha256": sha256_file(protocol_path),
            "intake_record_sha256": sha256_file(intake_path),
            **raw_hashes,
        },
        metadata={
            "metric_details": details,
            "mat_formats": {
                flight_id: flight.mat_format
                for flight_id, flight in measured.items()
            },
            "temperature_compensation": {
                flight_id: flight.temperature_compensation
                for flight_id, flight in measured.items()
            },
            "measured_encoder_forcing": True,
        },
    )


LOADERS: dict[str, TruthLoader] = {
    "diana2-flight": _diana2_flight,
    "ntnu-x8-flight": _ntnu_x8_flight,
    "observations-csv": _observations_csv,
}


def load_scorer_truth(
    loader_name: str,
    case_id: str,
    holdout_dir: Path | None,
    prediction: TruthPrediction,
) -> ScorerTruth:
    try:
        loader = LOADERS[loader_name]
    except KeyError as exc:
        raise ValueError(f"unsupported scorer truth loader: {loader_name}") from exc
    return loader(case_id, holdout_dir, prediction)
