"""Case runners: public inputs in, prediction values out, never truth data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import yaml

from openair.aero.oas_backend import run_vlm
from openair.atmosphere import isa
from openair.design_intent import shape_fidelity_report
from openair.io import load_yaml
from openair.mission.balance import thin_airfoil_props
from openair.mission.engine import breguet_endurance_s
from openair.mission.range_mission import BlockMissionSpec, simulate_block_mission
from openair.paths import RESULTS_DIR
from openair.provenance import model_source_sha256
from openair.schemas import EngineSpec, VehicleSpec
from openair.structures.modal import run_modal_analysis
from openair.truth.planforms import equivalent_trapezoid
from openair.truth.sections import (
    DEFAULT_CL_MAX_ASSUMPTION,
    SectionDomainError,
    evaluate_naca4_section,
)

Runner = Callable[[Path], tuple[dict[str, float], dict]]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _analytical_self(_directory: Path) -> tuple[dict[str, float], dict]:
    atmosphere = isa(0.0)
    naca = thin_airfoil_props("2412")
    endurance = breguet_endurance_s(4.5e-4, 10.0, 1.382858)
    return (
        {
            "isa_temperature_sl_k": atmosphere.temperature_k,
            "isa_density_sl_kg_m3": atmosphere.density_kg_m3,
            "naca2412_alpha_l0_deg": naca["alpha_l0_deg"],
            "naca2412_cm_ac": naca["cm_ac"],
            "breguet_endurance_s": endurance,
        },
        {
            "purpose": "self-case exercises corpus plumbing, not physical validation",
        },
    )


def _load_inputs(directory: Path, filename: str) -> dict:
    path = directory / filename
    with open(path, encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _naca4_section_model(directory: Path) -> tuple[dict[str, float], dict]:
    inputs = _load_inputs(directory, "sections.yaml")
    sections = inputs.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("section truth input requires a non-empty sections list")
    cl_max = float(inputs.get("cl_max_assumption", DEFAULT_CL_MAX_ASSUMPTION))
    raw_metrics = inputs.get("prediction_metrics")
    if not isinstance(raw_metrics, list) or not raw_metrics:
        raise ValueError("section input requires a non-empty prediction_metrics list")
    prediction_metrics = {str(metric) for metric in raw_metrics}
    predictions: dict[str, float] = {}
    domains: list[dict[str, object]] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("each section input must be a mapping")
        airfoil = str(section["airfoil"])
        reynolds_values = section.get("reynolds")
        if not isinstance(reynolds_values, list) or not reynolds_values:
            raise ValueError(f"{airfoil}: reynolds must be a non-empty list")
        for raw_reynolds in reynolds_values:
            reynolds = float(raw_reynolds)
            values, domain = evaluate_naca4_section(
                airfoil,
                reynolds,
                cl_max_assumption=cl_max,
            )
            code = str(domain["airfoil"])
            prefix = f"naca{code}_re{int(round(reynolds))}"
            unknown_metrics = prediction_metrics - values.keys()
            if unknown_metrics:
                raise ValueError(
                    f"section input requested unknown metrics: {sorted(unknown_metrics)}"
                )
            predictions.update(
                {
                    f"{prefix}_{name}": value
                    for name, value in values.items()
                    if name in prediction_metrics
                }
            )
            domains.append(domain)
    return predictions, {
        "model": "thin-airfoil + turbulent flat-plate section drag + assumed CLmax",
        "cl_max_assumption": cl_max,
        "prediction_metrics": sorted(prediction_metrics),
        "domains": domains,
    }


def _section_domain_refusal(directory: Path) -> tuple[dict[str, float], dict]:
    inputs = _load_inputs(directory, "request.yaml")
    try:
        evaluate_naca4_section(
            str(inputs["airfoil"]),
            float(inputs["reynolds"]),
        )
    except SectionDomainError as exc:
        message = str(exc)
        return (
            {
                "unsupported_airfoil_refused": 1.0,
                "refusal_is_actionable": float(
                    "four-digit NACA" in message
                    and "experimental polar adapter" in message
                ),
            },
            {"refusal": message},
        )
    return (
        {
            "unsupported_airfoil_refused": 0.0,
            "refusal_is_actionable": 0.0,
        },
        {"refusal": None},
    )


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _diana2_ground_model(directory: Path) -> tuple[dict[str, float], dict]:
    """Evaluate the visible L1 beam overlay and calibration-channel contract."""
    inputs = _load_inputs(directory, "evaluation.yaml")
    design_path = RESULTS_DIR.parent / str(inputs["design"])
    spec = VehicleSpec.model_validate(load_yaml(design_path))
    modal = run_modal_analysis(spec)
    if not modal.get("ok"):
        raise ValueError(
            "Diana 2 modal overlay does not close its visible calibration: "
            f"{modal.get('calibration_comparisons')}"
        )
    requested = inputs["modal_observable"]
    family = str(requested["family"])
    order = int(requested["order"])
    mode = next(
        item for item in modal[family] if int(item["order"]) == order
    )
    calibration = inputs.get("load_to_strain")
    if not isinstance(calibration, dict) or not calibration:
        raise ValueError("Diana ground input requires load_to_strain coefficients")
    predictions = {
        str(key): float(value) for key, value in calibration.items()
    }
    predictions[str(requested["id"])] = float(mode["frequency_hz"])
    predictions["strain_channel_mapping_count"] = float(
        modal["strain_mapping"]["total_channel_count"]
    )
    return predictions, {
        "role": "visible aircraft-specific L1 ground calibration",
        "model": modal["method"],
        "calibration_comparisons": modal["calibration_comparisons"],
        "calibration_archive": inputs["calibration_archive"],
        "strain_mapping_supported_channels": modal["strain_mapping"][
            "supported_channel_count"
        ],
        "limitations": modal["limitations"],
    }


def _least_squares_slope(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        raise ValueError("at least two distinct points are required for a slope")
    x_mean = sum(point[0] for point in points) / len(points)
    y_mean = sum(point[1] for point in points) / len(points)
    denominator = sum((point[0] - x_mean) ** 2 for point in points)
    if denominator <= 0.0:
        raise ValueError("slope abscissae must not all be equal")
    return (
        sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in points)
        / denominator
    )


def _pitching_moment(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list) and len(value) >= 2:
        return float(value[1])
    raise ValueError(f"unsupported pitching-moment value: {value!r}")


def _gtm_capstone_results(directory: Path) -> tuple[dict[str, float], dict]:
    """Read delivered artifacts only; truth remains scorer-side.

    Mechanical separation survives, but this case is post-hoc verification
    because initial failed residuals informed later implementation work.
    """
    inputs = _load_inputs(directory, "evaluation.yaml")
    concept = str(inputs.get("results_concept", "gtm-t2"))
    phase = str(inputs.get("phase", "optimized"))
    result_dir = RESULTS_DIR / concept / phase
    design_path = result_dir / "design.yaml"
    if not design_path.is_file():
        raise FileNotFoundError(
            f"GTM verification result is missing: {design_path}; run the canonical "
            "pipeline before evaluating the GTM case"
        )

    spec = VehicleSpec.model_validate(load_yaml(design_path))
    geometry = _load_json(result_dir / "geometry.json")
    aero = _load_json(result_dir / "aero.json")
    structures = _load_json(result_dir / "structures.json")
    validation = _load_json(result_dir / "validation.json")
    report = _load_json(result_dir / "report.json")
    current_model_hash = model_source_sha256()
    stage_payloads = {
        "geometry": geometry,
        "aero": aero,
        "structures": structures,
        "validation": validation,
        "report": report,
    }
    producer_hashes = {
        payload.get("model_source_sha256") for payload in stage_payloads.values()
    }
    pipeline_run_ids = {
        payload.get("pipeline_run_id") for payload in stage_payloads.values()
    }
    if producer_hashes != {current_model_hash}:
        raise ValueError(
            "GTM stages were generated by a different model-source revision; "
            "rerun the canonical pipeline before truth evaluation"
        )
    if len(pipeline_run_ids) != 1 or None in pipeline_run_ids:
        raise ValueError(
            "GTM stages do not share one canonical pipeline run id; rerun the "
            "full pipeline before truth evaluation"
        )
    pipeline_run_id = next(iter(pipeline_run_ids))
    polar = aero.get("polar")
    if not isinstance(polar, list):
        raise ValueError(f"{result_dir / 'aero.json'} has no polar list")
    attached = [
        item
        for item in polar
        if isinstance(item, dict) and 0.0 <= float(item.get("alpha_deg", -999.0)) <= 6.0
    ]
    wing_reference_scales = []
    for item in attached:
        surfaces = item.get("surfaces") or {}
        wing = surfaces.get("wing") or {}
        wing_reference_scales.append(float(item["S_ref"]) / float(wing["S_ref"]))
    cl_points = [
        (
            float(item["alpha_deg"]),
            float(item["CL"]) * reference_scale,
        )
        for item, reference_scale in zip(attached, wing_reference_scales, strict=True)
    ]
    cm_points = [
        (float(item["alpha_deg"]), _pitching_moment(item["CM"])) for item in attached
    ]
    cl_alpha = _least_squares_slope(cl_points)
    cm_alpha = _least_squares_slope(cm_points)

    stability = aero.get("stability") or {}
    if stability.get("method") == "hybrid_component" and isinstance(
        stability.get("cl_alpha_per_deg"), (int, float)
    ):
        cl_alpha = float(stability["cl_alpha_per_deg"])
        if isinstance(stability.get("dcm_dcl"), (int, float)):
            cm_alpha = float(stability["dcm_dcl"]) * cl_alpha
    balance = aero.get("balance") or {}
    cruise = aero.get("cruise") or {}
    reported_oas_lod = (report.get("desires") or {}).get("trimmed_oas_cruise_lod")
    if (
        not isinstance(reported_oas_lod, (int, float))
        or abs(float(reported_oas_lod) - float(cruise["lod"])) > 1e-9
    ):
        raise ValueError(
            "GTM report must label and trace the same-phase trimmed OAS cruise L/D"
        )
    x_np_m = float(
        stability.get("x_np_m")
        or stability.get("x_np_measured_m")
        or stability.get("x_np_model_m")
    )
    neutral_point_mac = (x_np_m - spec.wing.x_le_mac_m) / spec.wing.mac_m
    shape = shape_fidelity_report(spec)

    predictions = {
        "cl_alpha_per_deg": cl_alpha,
        "neutral_point_mac": neutral_point_mac,
        "cm_alpha_sign_correct": float(cm_alpha < 0.0),
        "trim_alpha_deg": float(cruise["alpha_deg"]),
        "cruise_lod": float(cruise["lod"]),
        "stall_speed_mps": float(balance["vstall_mps"]),
        "mtow_kg": float(aero["mtow_kg"]),
        "span_m": spec.wing.span_m,
        "wing_area_m2": spec.wing.area_m2,
        "mac_m": spec.wing.mac_m,
        "fuselage_length_m": spec.fuselage.length_m,
        "geometry_requirement_ok": float(bool(shape["ok"])),
    }
    return predictions, {
        "concept": concept,
        "phase": phase,
        "artifacts": {
            "design": str(design_path),
            "geometry": str(result_dir / "geometry.json"),
            "aero": str(result_dir / "aero.json"),
            "structures": str(result_dir / "structures.json"),
            "validation": str(result_dir / "validation.json"),
            "report": str(result_dir / "report.json"),
        },
        "artifact_sha256": {
            "design": _sha256_file(design_path),
            "geometry": _sha256_file(result_dir / "geometry.json"),
            "aero": _sha256_file(result_dir / "aero.json"),
            "structures": _sha256_file(result_dir / "structures.json"),
            "validation": _sha256_file(result_dir / "validation.json"),
            "report": _sha256_file(result_dir / "report.json"),
        },
        "producer_model_source_sha256": current_model_hash,
        "pipeline_run_id": pipeline_run_id,
        "fit_alpha_range_deg": [0.0, 6.0],
        "fit_points": len(attached),
        "coefficient_reference": "delivered wing area",
        "total_to_wing_reference_scales": wing_reference_scales,
        "cm_alpha_per_deg": cm_alpha,
        "mission_drag_buildup_lod": (report.get("desires") or {}).get("cruise_lod"),
        "trimmed_oas_cruise_lod": reported_oas_lod,
        "shape": shape,
    }


def _ntnu_x8_model(directory: Path) -> tuple[dict[str, float], dict]:
    """Freeze a gates-passing X8 model; the scorer later supplies maneuvers."""
    inputs = _load_inputs(directory, "evaluation.yaml")
    concept = str(inputs.get("results_concept", "ntnu-x8"))
    phase = str(inputs.get("phase", "optimized"))
    result_dir = RESULTS_DIR / concept / phase
    design_path = result_dir / "design.yaml"
    if not design_path.is_file():
        raise FileNotFoundError(
            f"X8 capstone model is missing: {design_path}; run the canonical "
            "pipeline before evaluating the flight case"
        )
    stage_names = (
        "geometry",
        "aero",
        "flightdyn",
        "structures",
        "validation",
        "report",
    )
    stage_paths = {name: result_dir / f"{name}.json" for name in stage_names}
    stages = {name: _load_json(path) for name, path in stage_paths.items()}
    failed = [name for name, payload in stages.items() if not payload.get("ok")]
    if failed:
        raise ValueError(f"X8 model has failing optimized stages: {failed}")
    current_model_hash = model_source_sha256()
    producer_hashes = {
        payload.get("model_source_sha256") for payload in stages.values()
    }
    pipeline_run_ids = {payload.get("pipeline_run_id") for payload in stages.values()}
    if producer_hashes != {current_model_hash}:
        raise ValueError("X8 stages are stale relative to the current model source")
    if len(pipeline_run_ids) != 1 or None in pipeline_run_ids:
        raise ValueError("X8 stages do not share one canonical pipeline run id")
    gate_path = RESULTS_DIR / concept / "gate_feedback.json"
    gate_feedback = _load_json(gate_path)
    required_gates = int(inputs.get("required_internal_gates", 12))
    if (
        not gate_feedback.get("ok")
        or int(gate_feedback.get("passed", 0)) != required_gates
    ):
        raise ValueError(
            f"X8 capstone requires {required_gates} passing internal gates; "
            f"got {gate_feedback.get('passed')}"
        )
    artifacts = {
        "design": design_path,
        **stage_paths,
        "gate_feedback": gate_path,
    }
    pipeline_run_id = next(iter(pipeline_run_ids))
    return {}, {
        "concept": concept,
        "phase": phase,
        "scorer_completes_predictions": True,
        "pipeline_run_id": pipeline_run_id,
        "producer_model_source_sha256": current_model_hash,
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "artifact_sha256": {
            name: _sha256_file(path) for name, path in artifacts.items()
        },
        "holdout_boundary": (
            "runner opens design artifacts only; scorer later consumes raw "
            "maneuvers and destroys temporary control/replay files"
        ),
    }


def _diana2_model(directory: Path) -> tuple[dict[str, float], dict]:
    """Freeze a gates-passing Diana 2 model before scorer-side MAT access."""

    inputs = _load_inputs(directory, "evaluation.yaml")
    concept = str(inputs.get("results_concept", "diana2"))
    phase = str(inputs.get("phase", "optimized"))
    result_dir = RESULTS_DIR / concept / phase
    design_path = result_dir / "design.yaml"
    if not design_path.is_file():
        raise FileNotFoundError(
            f"Diana 2 capstone model is missing: {design_path}; run the canonical "
            "pipeline before evaluating the flight case"
        )
    stage_names = (
        "geometry",
        "aero",
        "flightdyn",
        "structures",
        "validation",
        "report",
    )
    stage_paths = {name: result_dir / f"{name}.json" for name in stage_names}
    stages = {name: _load_json(path) for name, path in stage_paths.items()}
    failed = [name for name, payload in stages.items() if not payload.get("ok")]
    if failed:
        raise ValueError(f"Diana 2 model has failing optimized stages: {failed}")
    aeroelastic = stages["flightdyn"].get("aeroelastic") or {}
    if (
        aeroelastic.get("status") != "quasi-steady-modal"
        or not aeroelastic.get("frfs")
    ):
        raise ValueError("Diana 2 flightdyn artifact has no scoreable aeroelastic FRFs")
    current_model_hash = model_source_sha256()
    producer_hashes = {
        payload.get("model_source_sha256") for payload in stages.values()
    }
    pipeline_run_ids = {payload.get("pipeline_run_id") for payload in stages.values()}
    if producer_hashes != {current_model_hash}:
        raise ValueError(
            "Diana 2 stages are stale relative to the current model source"
        )
    if len(pipeline_run_ids) != 1 or None in pipeline_run_ids:
        raise ValueError("Diana 2 stages do not share one canonical pipeline run id")
    gate_path = RESULTS_DIR / concept / "gate_feedback.json"
    gate_feedback = _load_json(gate_path)
    required_gates = int(inputs.get("required_internal_gates", 12))
    if (
        not gate_feedback.get("ok")
        or int(gate_feedback.get("passed", 0)) != required_gates
    ):
        raise ValueError(
            f"Diana 2 capstone requires {required_gates} passing internal gates; "
            f"got {gate_feedback.get('passed')}"
        )
    artifacts = {
        "design": design_path,
        **stage_paths,
        "gate_feedback": gate_path,
    }
    return {}, {
        "concept": concept,
        "phase": phase,
        "scorer_completes_predictions": True,
        "pipeline_run_id": next(iter(pipeline_run_ids)),
        "producer_model_source_sha256": current_model_hash,
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "artifact_sha256": {
            name: _sha256_file(path) for name, path in artifacts.items()
        },
        "holdout_boundary": (
            "runner opens design artifacts only; scorer later opens MAT flights "
            "and forces the frozen FRFs with measured encoder deflections"
        ),
    }


def _crm_equivalent_trapezoid(directory: Path) -> tuple[dict[str, float], dict]:
    """Evaluate the public CRM planform without reading its held-out polar."""
    inputs = _load_inputs(directory, "model.yaml")
    wing = inputs["wing"]
    condition = inputs["condition"]
    evaluator = inputs["evaluator"]
    spec, abstraction = equivalent_trapezoid(
        span_m=float(wing["span_m"]),
        area_m2=float(wing["area_m2"]),
        taper=float(wing["taper"]),
        le_sweep_deg=float(wing["le_sweep_deg"]),
        reported_mac_m=float(wing["mac_m"]),
    )
    spec.name = "NASA CRM wing/body equivalent-trapezoid evaluator"
    spec.wing.twist_root_deg = float(wing["twist_root_deg"])
    spec.wing.twist_tip_deg = float(wing["twist_tip_deg"])
    spec.wing.t_over_c = float(wing["mean_t_over_c"])
    spec.wing.airfoil = str(evaluator["naca4_surrogate"])
    spec.structures.n_spanwise = int(evaluator["n_spanwise"])
    spec.structures.n_chordwise = int(evaluator["n_chordwise"])
    spec.solver.oas_with_viscous = False
    spec.solver.oas_with_wave = False

    mach = float(condition["mach"])
    chord_reynolds = float(condition["reynolds"])
    alpha_values = [float(value) for value in condition["alpha_deg"]]
    atmosphere = isa(0.0)
    tas_mps = mach * atmosphere.speed_of_sound_mps
    reynolds_per_m = chord_reynolds / float(wing["mac_m"])
    x_ref_m = spec.wing.x_ac_m
    polar = [
        run_vlm(
            spec,
            0.0,
            tas_mps,
            alpha,
            x_ref_m=x_ref_m,
            mach_number=mach,
            reynolds_per_m=reynolds_per_m,
        )
        for alpha in alpha_values
    ]
    cl_points = [(float(item["alpha_deg"]), float(item["CL"])) for item in polar]
    cm_points = [
        (float(item["alpha_deg"]), _pitching_moment(item["CM"])) for item in polar
    ]
    cl_alpha = _least_squares_slope(cl_points)
    cm_alpha = _least_squares_slope(cm_points)
    return (
        {
            "cl_alpha_per_deg": cl_alpha,
            "neutral_point_mac": 0.25 - cm_alpha / cl_alpha,
        },
        {
            "model": "OpenAeroStruct VLM on an equivalent single trapezoid",
            "configuration": "wing-only surrogate for CRM wing/body",
            "condition": {
                "mach": mach,
                "chord_reynolds": chord_reynolds,
                "reynolds_per_m": reynolds_per_m,
            },
            "fit_alpha_deg": alpha_values,
            "cm_alpha_per_deg": cm_alpha,
            "reference_point": "equivalent-wing quarter MAC",
            "abstraction": abstraction,
            "polar": [
                {
                    "alpha_deg": float(item["alpha_deg"]),
                    "cl": float(item["CL"]),
                    "cm": _pitching_moment(item["CM"]),
                }
                for item in polar
            ],
        },
    )


def _ceras_csr01_mission(directory: Path) -> tuple[dict[str, float], dict]:
    """Evaluate public CSR-01 missions using only the declared sparse deck."""

    inputs = _load_inputs(directory, "model.yaml")
    engine = EngineSpec.model_validate(inputs["engine"])
    common = dict(inputs["mission_model"])
    model_notes = common.pop("notes", [])
    mission_rows = inputs.get("missions")
    if not isinstance(mission_rows, list) or not mission_rows:
        raise ValueError("CSR-01 mission input requires a non-empty missions list")

    predictions: dict[str, float] = {}
    results: list[dict] = []
    for row in mission_rows:
        if not isinstance(row, dict):
            raise ValueError("each CSR-01 mission must be a mapping")
        mission = BlockMissionSpec.model_validate({**common, **row})
        result = simulate_block_mission(engine, mission)
        prefix = mission.id
        predictions[f"{prefix}_block_fuel_kg"] = result.block_fuel_kg
        predictions[f"{prefix}_block_time_h"] = result.block_time_h
        predictions[f"{prefix}_requirement_met"] = float(result.requirement_met)
        results.append(result.model_dump(mode="json"))

    return predictions, {
        "model": str(inputs["model_scope"]),
        "engine_deck": engine.deck.model_dump(mode="json") if engine.deck else None,
        "mission_model_notes": model_notes,
        "missions": results,
        "schema_bound_relaxation_study": inputs["schema_bound_relaxation_study"],
        "optional_second_blind_run": inputs["optional_second_blind_run"],
    }


RUNNERS: dict[str, Runner] = {
    "analytical-self": _analytical_self,
    "ceras-csr01-mission": _ceras_csr01_mission,
    "crm-equivalent-trapezoid": _crm_equivalent_trapezoid,
    "diana2-ground-model": _diana2_ground_model,
    "diana2-model": _diana2_model,
    "gtm-capstone-results": _gtm_capstone_results,
    "naca4-section-model": _naca4_section_model,
    "ntnu-x8-model": _ntnu_x8_model,
    "section-domain-refusal": _section_domain_refusal,
}


def run_adapter(runner_name: str, public_inputs: Path) -> tuple[dict[str, float], dict]:
    try:
        runner = RUNNERS[runner_name]
    except KeyError as exc:
        raise ValueError(f"unsupported truth runner: {runner_name}") from exc
    return runner(public_inputs)
