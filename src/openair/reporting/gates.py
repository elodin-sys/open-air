"""Canonical twelve-gate evaluation and actionable failure feedback."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from openair.atmosphere import isa
from openair.design_intent import shape_fidelity_report
from openair.io import load_yaml
from openair.paths import optimized_design_for, resolve_design, results_dir_for
from openair.schemas import VehicleSpec


TIER_NAMES = {
    "A": "design feasibility",
    "B": "model consistency",
    "C": "artifact truth",
}

GATE_GUIDANCE: dict[str, dict[str, str]] = {
    "schema": {
        "tier": "C",
        "meaning": "Source and delivered specifications deserialize and preserve invariant engine/payload requirements.",
        "knob": "Correct design.yaml values or schema violations; never patch generated JSON.",
    },
    "geometry_truth": {
        "tier": "C",
        "meaning": "The exported mesh—not only the intended parameters—matches the requested aircraft.",
        "knob": "Fix OpenVSP construction, section placement, or source geometry, then rerun geometry.",
    },
    "packing": {
        "tier": "A",
        "meaning": "Engine, payload, and fuel occupy non-overlapping usable volume.",
        "knob": "Move/resize bays, increase body or tank volume, or reduce required fuel.",
    },
    "balance": {
        "tier": "A",
        "meaning": "Measured static margin is inside the mission band at full and reserve fuel.",
        "knob": "Adjust wing, payload, fuel, or engine longitudinal stations; recalibrate NP only with OAS evidence.",
    },
    "pitch_trim": {
        "tier": "A",
        "meaning": "The aircraft closes lift and pitching moment at its selected wing twist or tail incidence.",
        "knob": "Adjust twist/tail incidence, airfoil moment, CG/wing station, or OAS-backed calibration.",
    },
    "stall": {
        "tier": "A",
        "meaning": "Wing loading remains compatible with the documented CLmax assumption.",
        "knob": "Increase wing area, reduce MTOW, or change CLmax only with aerodynamic evidence.",
    },
    "directional_stability": {
        "tier": "A",
        "meaning": "Cant-corrected vertical-tail volume is in the conceptual stability band.",
        "knob": "Adjust fin area, moment arm, cant, or CG—not the acceptance band.",
    },
    "structures": {
        "tier": "A",
        "meaning": "The OAS wingbox survives the positive limit load with the encoded safety factor.",
        "knob": "Increase skin/spar gauge, section depth, or material capability; reduce load only by changing requirements.",
    },
    "endurance_thrust": {
        "tier": "A",
        "meaning": "The closed fuel budget meets endurance and installed thrust covers modeled drag.",
        "knob": "Trade fuel, mass, drag, cruise condition, wing geometry, or propulsion assumptions upstream.",
    },
    "mdo_honesty": {
        "tier": "B",
        "meaning": "The selected optimum is feasible and reproduces in independent OAS verification.",
        "knob": "Fix scaling, bounds, derivatives, or the surrogate/OAS mismatch; do not trust driver success alone.",
    },
    "shape_fidelity": {
        "tier": "C",
        "meaning": "Delivered proportions stay inside the hard identity bound and every soft-prior departure is explained.",
        "knob": "Fix unjustified departures or the upstream physics; never widen the hard identity bound silently.",
    },
    "cross_checks_traceability": {
        "tier": "B",
        "meaning": "Required analytical identities and declared-scope solver checks pass, method spread is disclosed, and headline values reproduce from same-phase artifacts.",
        "knob": "Use the failed validation check name to fix its upstream model or calibration.",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, dict) else {}


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


_REPRODUCTION_ALLOWED_CHANGES = {
    ("htail", "incidence_deg"),
    ("solver", "np_shift_mac"),
    ("solver", "wing_body_np_mac"),
    ("solver", "wing_body_cl_alpha_per_deg"),
}


def _reproduction_changed_paths(
    source: VehicleSpec,
    delivered: VehicleSpec,
) -> list[str]:
    """Return source fields changed outside declared reproduction closure."""
    source_data = source.model_dump(mode="json", exclude_computed_fields=True)
    delivered_data = delivered.model_dump(mode="json", exclude_computed_fields=True)
    for path in _REPRODUCTION_ALLOWED_CHANGES:
        for data in (source_data, delivered_data):
            node: Any = data
            for key in path[:-1]:
                node = node.get(key, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict):
                node.pop(path[-1], None)

    changed: list[str] = []

    def compare(left: Any, right: Any, path: tuple[str, ...]) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    changed.append(".".join((*path, key)))
                else:
                    compare(left[key], right[key], (*path, key))
            return
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                changed.append(".".join(path))
                return
            for index, (left_item, right_item) in enumerate(
                zip(left, right, strict=True)
            ):
                compare(left_item, right_item, (*path, str(index)))
            return
        if left != right:
            changed.append(".".join(path))

    compare(source_data, delivered_data, ())
    return changed


def _metric_values(
    spec: VehicleSpec,
    data: dict[str, dict[str, Any]],
    supplied: dict[str, float] | None,
) -> dict[str, float]:
    if supplied is not None:
        return supplied
    desires = data["report"].get("desires") or {}
    best = data["mdo"].get("best") or {}
    endurance_hr = desires.get("endurance_hr_pred")
    if endurance_hr is None:
        endurance_hr = float(best.get("endurance_s") or 0.0) / 3600.0
    return {
        "endurance_hr": float(endurance_hr or 0.0),
        "dash_kmh": float(desires.get("dash_kmh") or 0.0),
        "mtow_kg": float(
            desires.get("mtow_kg")
            or data["aero"].get("mtow_kg")
            or best.get("mtow_kg")
            or 0.0
        ),
        "fuel_kg": float(
            desires.get("fuel_kg")
            or (best.get("dvs") or {}).get("fuel")
            or spec.mass.fuel_mass_kg
        ),
        "span_m": spec.wing.span_m,
        "lod": float(
            desires.get("cruise_lod")
            or (data["aero"].get("cruise") or {}).get("lod")
            or best.get("lod")
            or 0.0
        ),
    }


def evaluate_gates(
    spec: VehicleSpec,
    data: dict[str, dict[str, Any]],
    metrics: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate the canonical gate list from one delivered aircraft's artifacts."""
    metrics = _metric_values(spec, data, metrics)
    geometry = data["geometry"]
    aero = data["aero"]
    structures = data["structures"]
    validation = data["validation"]
    report = data["report"]
    mdo = data["mdo"]
    schema = data.get("_schema") or {}
    openvsp = geometry.get("openvsp") or {}
    mesh = openvsp.get("mesh_checks") or {}
    readback = openvsp.get("readback") or {}
    bbox = openvsp.get("stl_bbox") or {}
    packing = geometry.get("packing") or {}
    stability = aero.get("stability") or {}
    balance = aero.get("balance") or {}
    trim = aero.get("trim") or {}
    positive = structures.get("positive_g") or {}
    negative = structures.get("negative_g") or {}
    desires = report.get("desires") or {}
    best = mdo.get("best") or {}
    verify = mdo.get("oas_verify") or {}

    cruise = aero.get("cruise") or {}
    dash = aero.get("dash") or {}
    cruise_engine = cruise.get("engine") or {}
    dash_engine = dash.get("engine") or {}
    dash_drag = (dash.get("buildup") or {}).get("drag_n") or dash.get("drag_n")
    thrust_ok = float(cruise_engine.get("thrust_available_n") or 0.0) + 1e-4 >= float(
        cruise.get("drag_n") or 0.0
    ) and float(dash_engine.get("thrust_available_n") or 0.0) + 1e-3 >= float(
        dash_drag or 0.0
    )
    endurance_ok = bool(
        not spec.mission.endurance_required
        or metrics["endurance_hr"] + 1e-6 >= spec.mission.endurance_s / 3600.0
    )

    checks = validation.get("checks") or []
    core_failures = [
        str(check.get("name"))
        for check in checks
        if not check.get("ok")
        and not str(check.get("note") or "").startswith("stretch")
    ]
    vspaero = next(
        (check for check in checks if check.get("name") == "vspaero_vs_oas_CL"),
        {},
    )
    directional = next(
        (check for check in checks if check.get("name") == "fin_volume_coefficient"),
        {},
    )
    vspaero_ratio = vspaero.get(
        "CL_alpha_ratio_vspaero_over_oas",
        vspaero.get("CL_ratio_vspaero_over_oas"),
    )
    np_method_spread = vspaero.get(
        "component_vs_full_vspaero_np_disagreement_mac",
        vspaero.get("full_vehicle_neutral_point_disagreement_mac"),
    )
    core_total = int(validation.get("core_total") or 0)
    validation_ok = (
        core_total > 0
        and int(validation.get("core_passed") or 0) == core_total
        and bool(vspaero.get("ok"))
    )
    desires_dash = desires.get("dash_mps")
    desires_mach = desires.get("dash_mach")
    if isinstance(desires_dash, (int, float)) and isinstance(
        desires_mach, (int, float)
    ):
        mach_recomputed = (
            float(desires_dash) / isa(spec.mission.dash_altitude_m).speed_of_sound_mps
        )
        mach_trace_ok = abs(mach_recomputed - float(desires_mach)) < 0.005
    else:
        mach_recomputed = None
        mach_trace_ok = False

    def trace_close(
        reference: Any,
        candidate: Any,
        *,
        relative: float = 1e-3,
        absolute: float = 0.05,
    ) -> bool:
        return bool(
            isinstance(reference, (int, float))
            and isinstance(candidate, (int, float))
            and abs(float(reference) - float(candidate))
            <= max(abs(float(reference)) * relative, absolute)
        )

    report_mtow = desires.get("mtow_kg")
    aero_mtow = aero.get("mtow_kg")
    mdo_mtow = best.get("mtow_kg")
    aero_dash = (dash.get("buildup") or {}).get("tas_mps") or dash.get("tas_mps")
    mdo_dash = best.get("dash_mps")
    report_endurance_s = (
        float(desires.get("endurance_hr_pred")) * 3600.0
        if isinstance(desires.get("endurance_hr_pred"), (int, float))
        else None
    )
    mdo_endurance_s = best.get("endurance_s")
    report_fuel = desires.get("fuel_kg")
    mdo_fuel = (best.get("dvs") or {}).get("fuel")
    report_lod = desires.get("cruise_lod")
    aero_lod = cruise.get("buildup_lod")
    mdo_lod = best.get("lod")
    artifact_trace_ok = all(
        (
            trace_close(report_mtow, aero_mtow),
            trace_close(report_mtow, mdo_mtow),
            trace_close(desires_dash, aero_dash),
            trace_close(desires_dash, mdo_dash),
            trace_close(
                report_endurance_s,
                mdo_endurance_s,
                relative=1e-5,
                absolute=0.1,
            ),
            trace_close(report_fuel, mdo_fuel, relative=1e-8, absolute=1e-6),
            trace_close(
                report_fuel, spec.mass.fuel_mass_kg, relative=1e-8, absolute=1e-6
            ),
            trace_close(report_lod, aero_lod, relative=1e-6, absolute=1e-6),
            trace_close(report_lod, mdo_lod, relative=1e-6, absolute=1e-6),
        )
    )
    validation_ok = validation_ok and mach_trace_ok and artifact_trace_ok

    failure = positive.get("failure")
    sm_full = stability.get("sm_full")
    sm_reserve = stability.get("sm_reserve")
    vv = balance.get("vv")
    vstall = balance.get("vstall_mps")
    cm_residual = trim.get("cm_residual")
    tail_enabled = spec.htail.span_m > 0.05
    if tail_enabled:
        trim_value = trim.get("tail_incidence_trim_deg")
        trim_spec = spec.htail.incidence_deg
        trim_control = "tail incidence"
    else:
        trim_value = trim.get("washout_trim_deg")
        trim_spec = spec.wing.twist_root_deg - spec.wing.twist_tip_deg
        trim_control = "washout"
    trim_ok = (
        bool(trim.get("converged"))
        and cm_residual is not None
        and abs(float(cm_residual)) < 0.005
        and trim_value is not None
        and abs(float(trim_value) - trim_spec) <= 1.0
    )
    inspiration = bool(
        spec.sketch is not None and spec.sketch.treatment == "inspiration"
    )
    reproduction = bool(
        spec.sketch is not None and spec.sketch.treatment == "reproduction"
    )
    calibration_history = mdo.get("calibration_history") or []
    calibration_ok = bool(
        not inspiration
        or (
            mdo.get("calibration_converged")
            and calibration_history
            and calibration_history[-1].get("converged")
        )
    )
    departures = mdo.get("sketch_departures") or []
    shape = shape_fidelity_report(spec, departures)
    reproduction_frozen_ok = bool(
        not reproduction or schema.get("reproduction_frozen_ok")
    )
    requirements_ok = bool(
        desires.get("engine_met", True)
        and desires.get("payload_met", True)
        and reproduction_frozen_ok
    )
    departure_reasons = [
        str(item.get("reason"))
        for item in departures
        if isinstance(item, dict) and item.get("reason")
    ]

    def row(
        gate_id: str,
        name: str,
        ok: bool,
        evidence: str,
        source: str,
        *,
        failure_codes: list[str] | None = None,
        meaning: str | None = None,
        upstream_knob: str | None = None,
    ) -> dict[str, Any]:
        guidance = GATE_GUIDANCE[gate_id]
        tier = guidance["tier"]
        return {
            "id": gate_id,
            "name": name,
            "ok": bool(ok),
            "tier": tier,
            "tier_name": TIER_NAMES[tier],
            "meaning": meaning or guidance["meaning"],
            "upstream_knob": upstream_knob or guidance["knob"],
            "evidence": evidence,
            "source": source,
            "failure_codes": failure_codes or [],
        }

    return [
        row(
            "schema",
            "Schema",
            bool(
                schema.get("source_ok")
                and schema.get("optimized_ok")
                and requirements_ok
            ),
            f"source={_fmt(schema.get('source_ok'))}; "
            f"optimized={_fmt(schema.get('optimized_ok'))}; "
            f"engine requirement={_fmt(desires.get('engine_met'))}; "
            f"payload requirement={_fmt(desires.get('payload_met'))}"
            + (
                f"; reproduction frozen={_fmt(reproduction_frozen_ok)}"
                if reproduction
                else ""
            )
            + (
                f"; {'; '.join(str(error) for error in schema.get('errors') or [])}"
                if schema.get("errors")
                else ""
            ),
            "design.yaml",
            meaning=(
                "Source and delivered specifications deserialize; every "
                "source-locked field is unchanged except declared trim and "
                "same-run component-stability constants."
                if reproduction
                else None
            ),
        ),
        row(
            "geometry_truth",
            "Geometry truth",
            bool(readback.get("matches_spec") and bbox.get("ok") and mesh.get("ok")),
            f"read-back={_fmt(readback.get('matches_spec'))}; bbox={_fmt(bbox.get('ok'))}; mesh checks={len(mesh.get('checks') or [])}",
            "optimized/geometry.json",
        ),
        row(
            "packing",
            "Packing",
            bool(packing.get("ok")),
            f"fuel-volume margin {_fmt(packing.get('margin_fuel_m3'))} m³; engine/payload clear",
            "optimized/geometry.json",
        ),
        row(
            "balance",
            "Balance",
            bool(stability.get("ok")),
            (
                "independently measured"
                if stability.get("independent_measurement")
                else "component-model"
            )
            + f" SM full {_fmt(sm_full)}; reserve {_fmt(sm_reserve)} MAC",
            "optimized/aero.json",
            meaning=(
                "Same-run VSPAERO wing/body/nacelle evidence feeds the "
                "declared tail model; the resulting static margin is a "
                "component-model screen, not an independent measurement."
                if stability.get("method") == "hybrid_component"
                else None
            ),
        ),
        row(
            "pitch_trim",
            "Pitch trim",
            trim_ok,
            f"{trim_control} {_fmt(trim_value)}° vs spec {_fmt(trim_spec)}°; CM residual {_fmt(cm_residual, 4)}",
            "optimized/aero.json",
        ),
        row(
            "stall",
            "Stall",
            bool(balance.get("stall_ok")),
            f"Vstall {_fmt(vstall)} m/s ≤ {spec.mission.stall_speed_max_mps:.1f} m/s at CLmax {spec.mission.cl_max:.2f}",
            "optimized/aero.json",
        ),
        row(
            "directional_stability",
            "Directional authority" if reproduction else "Directional stability",
            bool(directional.get("ok", balance.get("vv_ok"))),
            (
                (
                    f"source Vv {_fmt(vv, 4)}; same-run Cnβ "
                    f"{_fmt((directional.get('directional_derivative_evidence') or {}).get('Cn_beta_per_rad'), 4)}, "
                    f"Cnr {_fmt((directional.get('directional_derivative_evidence') or {}).get('Cn_r'), 4)}"
                    if (directional.get("directional_derivative_evidence") or {}).get(
                        "ok"
                    )
                    else f"cant-corrected fin volume Vv {_fmt(vv, 4)} ≥ 0.02"
                )
                + " (source-locked reproduction)"
                if reproduction
                else f"cant-corrected fin volume Vv {_fmt(vv, 4)} in "
                f"{balance.get('vv_band') or [0.02, 0.09]}"
            ),
            "optimized/aero.json",
            meaning=(
                "Source-locked geometry clears either the minimum conceptual "
                "fin-volume screen or same-run restoring/damping derivative "
                "checks; no upper-band sizing claim or fin-sizing optimum is made."
                if reproduction
                else None
            ),
            upstream_knob=(
                "Correct the source geometry or remove the reproduction claim; "
                "do not resize a source-locked fin to make the screen pass."
                if reproduction
                else None
            ),
        ),
        row(
            "structures",
            "Structures",
            bool(structures.get("ok"))
            and failure is not None
            and float(failure) <= 0.0
            and bool(positive.get("lift_closure_ok"))
            and bool(positive.get("aerodynamic_domain_ok"))
            and bool(positive.get("mass_closure_ok"))
            and bool(negative.get("lift_closure_ok"))
            and bool(negative.get("aerodynamic_domain_ok"))
            and bool(negative.get("mass_closure_ok")),
            (
                f"unsupported domain: {structures.get('reason')}"
                if structures.get("status") == "unsupported-domain"
                else (
                    f"+{spec.mission.limit_positive_g:g}g failure index {_fmt(failure)}; "
                    f"CL {_fmt(positive.get('CL'))}/{_fmt(positive.get('required_CL'))}; "
                    f"lift closed={_fmt(positive.get('lift_closure_ok'))}; "
                    f"mass closed={_fmt(positive.get('mass_closure_ok'))}; "
                    f"tip deflection {_fmt(positive.get('tip_disp_m'))} m"
                    + (
                        "; linear-VLM incidence >12° (extrapolative load shape)"
                        if positive.get("linear_vlm_extrapolation")
                        else ""
                    )
                )
            ),
            "optimized/structures.json",
        ),
        row(
            "endurance_thrust",
            "Endurance & thrust",
            endurance_ok and thrust_ok,
            (
                "endurance not claimed for electric reproduction; "
                "cruise/dash thrust ≥ buildup drag"
                if not spec.mission.endurance_required
                else f"{metrics['endurance_hr']:.2f} h; "
                "cruise/dash thrust ≥ buildup drag"
            ),
            "optimized/aero.json + baseline/mdo.json",
        ),
        row(
            "mdo_honesty",
            "Reproduction closure honesty" if reproduction else "MDO honesty",
            bool(
                mdo.get("ok")
                and best.get("feasible")
                and best.get("driver_success")
                and verify.get("ok")
                and calibration_ok
                and reproduction_frozen_ok
            ),
            f"feasible={_fmt(best.get('feasible'))}; "
            f"driver={_fmt(best.get('driver_success'))}; "
            f"post-delivery verify={_fmt(verify.get('ok'))}; "
            f"calibration={_fmt(calibration_ok)}; "
            f"frozen={_fmt(reproduction_frozen_ok)}; "
            f"{len(mdo.get('starts') or [])} starts",
            "baseline/mdo.json",
            meaning=(
                "Source coordinates remain frozen while a separate OAS solve "
                "checks trim and structures; stability retains its declared "
                "independent-derivative or component-model evidence label."
                if reproduction
                else None
            ),
            upstream_knob=(
                "Fix source serialization, trim/structures verification, or "
                "stability provenance; do not optimize frozen reproduction "
                "coordinates."
                if reproduction
                else None
            ),
        ),
        row(
            "shape_fidelity",
            "Shape fidelity",
            bool(shape.get("ok")),
            f"span/L {spec.wing.span_m / spec.fuselage.length_m:.2f}; "
            f"root/L {spec.wing.root_chord_m / spec.fuselage.length_m:.2f}; "
            f"sweep {spec.wing.le_sweep_deg:.1f}°; "
            f"{shape.get('departure_count', 0)} scored shape departures; "
            f"{len(departures)} total audit records"
            + (f" ({'; '.join(departure_reasons[:2])})" if departure_reasons else ""),
            "optimized/design.yaml + baseline/mdo.json",
        ),
        row(
            "cross_checks_traceability",
            "Cross-checks & traceability",
            validation_ok,
            f"core {validation.get('core_passed', 0)}/{core_total}; "
            f"VSPAERO/OAS CLα ratio {_fmt(vspaero_ratio)}; "
            f"NP method spread {_fmt(np_method_spread)} MAC (diagnostic); "
            f"report Mach {_fmt(desires_mach)} vs recomputed {_fmt(mach_recomputed)}; "
            f"MTOW report/aero/MDO {_fmt(report_mtow)}/{_fmt(aero_mtow)}/{_fmt(mdo_mtow)} kg; "
            f"L/D report/aero/MDO {_fmt(report_lod)}/{_fmt(aero_lod)}/{_fmt(mdo_lod)}",
            "optimized/validation.json + optimized/report.json",
            failure_codes=core_failures,
        ),
    ]


def feedback_from_gates(
    gates: list[dict[str, Any]],
    validation: dict[str, Any],
    *,
    concept: str,
    auto_retries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checks = {
        str(check.get("name")): check
        for check in validation.get("checks") or []
        if isinstance(check, dict)
    }
    candidates: list[dict[str, Any]] = []
    for gate in gates:
        if gate["ok"] or gate["tier"] == "C":
            continue
        for code in gate.get("failure_codes") or []:
            check = checks.get(code) or {}
            candidate = {
                "key": code,
                "gate_id": gate["id"],
                "tier": gate["tier"],
                "source": gate["source"],
            }
            if code == "wing_mass_buildup_vs_oas" and isinstance(
                check.get("got"), (int, float)
            ):
                candidate["measured_wing_mass_kg"] = float(check["got"])
            candidates.append(candidate)
    return {
        "ok": all(gate["ok"] for gate in gates),
        "concept": concept,
        "passed": sum(gate["ok"] for gate in gates),
        "total": len(gates),
        "gates": gates,
        "retry_candidates": candidates,
        "auto_retries": auto_retries or [],
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def build_gate_feedback(
    design_path: str | Path,
    *,
    auto_retries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    concept, baseline_yaml, _ = resolve_design(design_path)
    optimized_yaml = optimized_design_for(baseline_yaml)
    baseline_dir = results_dir_for(baseline_yaml)
    optimized_dir = results_dir_for(optimized_yaml)
    schema_status: dict[str, Any] = {
        "source_ok": False,
        "optimized_ok": False,
        "errors": [],
    }
    source_spec: VehicleSpec | None = None
    try:
        source_spec = VehicleSpec.model_validate(load_yaml(baseline_yaml))
        schema_status["source_ok"] = True
    except Exception as exc:
        schema_status["errors"].append(f"source: {exc}")
    try:
        spec = VehicleSpec.model_validate(load_yaml(optimized_yaml))
        schema_status["optimized_ok"] = True
    except Exception as exc:
        schema_status["errors"].append(f"optimized: {exc}")
        spec = source_spec or VehicleSpec()
    if (
        source_spec is not None
        and schema_status["optimized_ok"]
        and source_spec.sketch is not None
        and source_spec.sketch.treatment == "reproduction"
    ):
        changed_paths = _reproduction_changed_paths(source_spec, spec)
        schema_status["reproduction_frozen_ok"] = not changed_paths
        schema_status["reproduction_changed_paths"] = changed_paths
        if changed_paths:
            schema_status["errors"].append(
                "reproduction changed frozen source fields: "
                + ", ".join(changed_paths[:8])
            )
    data = {
        name: _read_json(optimized_dir / f"{name}.json")
        for name in ("geometry", "aero", "structures", "validation", "report")
    }
    data["mdo"] = _read_json(baseline_dir / "mdo.json")
    data["_schema"] = schema_status
    gates = evaluate_gates(spec, data)
    return feedback_from_gates(
        gates,
        data["validation"],
        concept=concept,
        auto_retries=auto_retries,
    )


def format_gate_table(feedback: dict[str, Any]) -> str:
    lines = ["Tier  Status  Gate                         Upstream response"]
    for gate in feedback.get("gates") or []:
        status = "PASS" if gate.get("ok") else "FAIL"
        lines.append(
            f" {gate.get('tier', '?')}    {status:<4}   "
            f"{str(gate.get('name', '')):<28} {gate.get('upstream_knob', '')}"
        )
    lines.append(
        f"Verdict: {feedback.get('passed', 0)}/{feedback.get('total', 0)} gates pass"
    )
    return "\n".join(lines)
