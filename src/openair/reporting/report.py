"""Plots and the human-readable design report, scored against source requirements."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openair.atmosphere import isa
from openair.design_intent import (
    DEFAULT_SKETCH_SHAPE,
    shape_fidelity_report,
    sketch_prior_targets,
)
from openair.io import load_stage, load_yaml
from openair.paths import DESIGNS_DIR, resolve_design
from openair.provenance import model_source_sha256
from openair.reporting.plots import drag_bar, margins_bar, mass_bar, spanwise_cl
from openair.schemas import VehicleSpec
from openair.units import G0

# Original KingTech target proportions (top-view grid units): span ~21,
# length ~14, root chord ~8, LE sweep ~32 deg. Tolerances are the QA band.
SKETCH_SHAPE = DEFAULT_SKETCH_SHAPE


def _status(ok: bool) -> str:
    return "MET" if ok else "SHORT"


def _buildup_wing_kg(spec: VehicleSpec, sizing: dict | None, mtow: float, fuel: float):
    if sizing and sizing.get("masses"):
        return sizing["masses"].get("wing_kg")
    try:
        from openair.mission.mass import breakdown

        return breakdown(spec, mtow or 100.0, fuel or 30.0).wing_kg
    except Exception:
        return None


def sketch_shape_targets(spec: VehicleSpec) -> dict[str, tuple[float, float]]:
    """Shape-fidelity targets: concept sketch envelope, else the original target."""
    return sketch_prior_targets(spec)


def _shape_fidelity(
    spec: VehicleSpec,
    sketch_departures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return shape_fidelity_report(spec, sketch_departures)


def _requirement_spec(
    analyzed: VehicleSpec,
    concept: str | None,
    design_yaml: Path | None,
) -> VehicleSpec:
    """Load immutable source requirements; fall back to the analyzed spec."""
    candidates: list[Path] = []
    if design_yaml is not None:
        try:
            design_yaml.resolve().relative_to(DESIGNS_DIR.resolve())
        except ValueError:
            pass
        else:
            # An explicitly selected source variant (for example a capstone
            # reconstruction) owns its requirements even when a sibling
            # design.yaml exists in the same concept directory.
            candidates.append(design_yaml)
    if concept is not None:
        candidates.append(DESIGNS_DIR / concept / "design.yaml")
    if design_yaml is not None and design_yaml not in candidates:
        candidates.append(design_yaml)
    for candidate in candidates:
        if candidate.is_file():
            try:
                return VehicleSpec.model_validate(load_yaml(candidate))
            except Exception:
                continue
    return analyzed


def run_report_stage(
    spec: VehicleSpec,
    outdir: Path,
    case_path: Path | None = None,
    *,
    requirements_path: Path | None = None,
) -> dict[str, Any]:
    concept = None
    design_yaml = None
    results_root = None
    if case_path:
        concept, design_yaml, results_root = resolve_design(case_path)
    sizing = load_stage(case_path, "sizing") if case_path else None
    aero = load_stage(case_path, "aero") if case_path else None
    structures = load_stage(case_path, "structures") if case_path else None
    mdo = load_stage(case_path, "mdo") if case_path else None
    if (
        mdo is None
        and design_yaml is not None
        and results_root is not None
        and design_yaml.parent.name == "optimized"
    ):
        parent_mdo = results_root / "baseline" / "mdo.json"
        if parent_mdo.exists():
            with open(parent_mdo, encoding="utf-8") as stream:
                mdo = json.load(stream)
    geom = load_stage(case_path, "geometry") if case_path else None
    validation = load_stage(case_path, "validation") if case_path else None
    tacs = load_stage(case_path, "tacs") if case_path else None
    su2 = load_stage(case_path, "su2") if case_path else None

    # The report describes THIS case only (spec + this case's artifacts).
    # A case that carries mdo.json points at the child prototype case instead
    # of swapping numbers in (QA audit F10: never mix two aircraft).
    if sizing:
        dash_mps = sizing["dash"]["tas_mps"]
        endurance_s = sizing["endurance_s"]
        mtow = sizing["mtow_kg"]
        lod = sizing["cruise"]["lod"]
        fuel = sizing["fuel_kg"]
        span = sizing["span_m"]
        failure = packing = None
        bal_head = sizing.get("balance") or {}
        sm_full = bal_head.get("sm_full")
        sm_reserve = bal_head.get("sm_reserve")
    else:
        # Prototype case: closed-form metrics evaluated at the delivered spec.
        from openair.mdo.problem import evaluate_design

        m = evaluate_design(spec)
        dash_mps = m["dash_mps"]
        endurance_s = m["endurance_s"]
        mtow = m["mtow_kg"]
        lod = m["lod"]
        fuel = spec.mass.fuel_mass_kg
        span = spec.wing.span_m
        failure = m["failure"]
        packing = m["packing_violation"]
        sm_full = m["sm_full"]
        sm_reserve = m["sm_reserve"]

    # Honest dash Mach from this case's dash altitude (QA audit F10)
    a_dash = isa(spec.mission.dash_altitude_m).speed_of_sound_mps
    dash_mach = dash_mps / a_dash if dash_mps else 0.0
    mach_ok = dash_mach <= spec.mission.dash_mach_cap + 1e-6

    if sizing and sizing.get("masses"):
        mass_bar(sizing["masses"], outdir / "mass_breakdown.png")
    cd_comp = (
        (aero or {}).get("cd0_components")
        or ((sizing or {}).get("cruise") or {}).get("cd_components")
        or {}
    )
    if cd_comp:
        drag_bar(cd_comp, outdir / "drag_breakdown.png")
    cl_ref = float(
        ((aero or {}).get("cruise") or {}).get("CL") or spec.mission.cruise_cl
    )
    oas_cruise_lod = ((aero or {}).get("cruise") or {}).get("lod")
    spanwise_cl(spec.wing.span_m, cl_ref, outdir / "spanwise_loads.png")

    margins = {}
    if endurance_s:
        margins["endurance_s"] = endurance_s - spec.mission.endurance_s
    if failure is not None:
        margins["failure_(<=0)"] = -float(failure)
    if packing is not None:
        margins["packing_m3"] = -float(packing)
    if sm_full is not None:
        margins["SM_full-min"] = float(sm_full) - spec.mission.static_margin_min
        margins["max-SM_reserve"] = spec.mission.static_margin_max - float(
            sm_reserve or sm_full
        )
    if margins:
        margins_bar(margins, outdir / "margins.png")

    requirements = _requirement_spec(
        spec,
        concept,
        requirements_path or design_yaml,
    )
    endurance_applicable = requirements.mission.endurance_required
    endurance_met = bool(
        not endurance_applicable
        or endurance_s + 0.0036 >= requirements.mission.endurance_s
    )
    payload_met = abs(spec.mission.payload_kg - requirements.mission.payload_kg) < 1e-9
    engine_met = spec.engine.model_dump(
        mode="python"
    ) == requirements.engine.model_dump(mode="python")
    shape = _shape_fidelity(spec, (mdo or {}).get("sketch_departures"))

    trim = (
        (aero or {}).get("trim")
        or ((mdo or {}).get("oas_verify") or {}).get("aero_trim")
        or {}
    )
    balance = (aero or {}).get("balance") or (sizing or {}).get("balance") or {}
    verify = (mdo or {}).get("oas_verify") or {}
    if mdo:
        verify_ok = bool(verify.get("ok"))
    else:
        # Prototype case: verification = its own OAS aero + structures stages
        verify_ok = bool((aero or {}).get("ok")) and bool((structures or {}).get("ok"))
    sm_lo, sm_hi = spec.mission.static_margin_min, spec.mission.static_margin_max
    sm_ok = (
        sm_full is not None
        and sm_reserve is not None
        and sm_lo - 1e-9 <= sm_full <= sm_hi + 1e-9
        and sm_lo - 1e-9 <= sm_reserve <= sm_hi + 1e-9
    )
    tail_enabled = spec.htail.span_m > 0.05
    cm_residual = trim.get("cm_residual")
    if tail_enabled:
        trim_got = trim.get("tail_incidence_trim_deg")
        trim_spec = spec.htail.incidence_deg
        trim_control_name = "tail incidence"
    else:
        trim_got = trim.get("washout_trim_deg")
        trim_spec = spec.wing.twist_root_deg - spec.wing.twist_tip_deg
        trim_control_name = "wing washout"
    inspiration = bool(
        spec.sketch is not None and spec.sketch.treatment == "inspiration"
    )
    trim_ok = (
        bool(
            trim
            and trim.get("converged")
            and cm_residual is not None
            and abs(float(cm_residual)) < 0.005
            and trim_got is not None
            and abs(float(trim_got) - trim_spec) <= 1.0
        )
        if inspiration or tail_enabled
        else bool(trim.get("converged"))
    )
    vstall = balance.get("vstall_mps")
    stall_ok = bool(balance.get("stall_ok")) if balance else False
    vv = balance.get("vv")
    vv_band = balance.get("vv_band") or [0.02, 0.09]
    vv_ok = bool(balance.get("vv_ok")) if balance else False
    artifact_checks = ((geom or {}).get("openvsp") or {}).get("mesh_checks") or {}
    artifact_ok = bool(artifact_checks.get("ok"))
    n_artifact = len(artifact_checks.get("checks") or [])

    vsp_ok = False
    vsp_np_method_spread = None
    component_np_method_spread = None
    directional_derivative_evidence: dict[str, Any] = {}
    if validation:
        for c in validation.get("checks") or []:
            if c.get("name") == "vspaero_vs_oas_CL":
                vsp_ok = bool(c.get("ok"))
                vsp_np_method_spread = c.get(
                    "full_vehicle_neutral_point_disagreement_mac"
                )
                component_np_method_spread = c.get(
                    "component_vs_full_vspaero_np_disagreement_mac"
                )
            elif c.get("name") == "fin_volume_coefficient":
                vv_ok = bool(c.get("ok"))
                directional_derivative_evidence = (
                    c.get("directional_derivative_evidence") or {}
                )
    validation_core_total = int((validation or {}).get("core_total") or 0)
    validation_core_ok = (
        validation_core_total > 0
        and int((validation or {}).get("core_passed") or 0) == validation_core_total
    )

    tacs_ok = bool((tacs or {}).get("ok"))
    su2_ok = bool((su2 or {}).get("ok"))
    oas_positive = (structures or {}).get("positive_g") or {}
    oas_fail = oas_positive.get("failure")
    oas_mass = oas_positive.get("structural_mass_kg")
    tacs_mass = ((tacs or {}).get("analysis") or {}).get("maneuver_mass")
    tacs_ks = ((tacs or {}).get("analysis") or {}).get("maneuver_ks_vm")
    su2_c = (su2 or {}).get("cruise") or {}
    su2_d = (su2 or {}).get("dash") or {}
    cal = (su2 or {}).get("calibration") or {}

    desires = {
        "engine": spec.engine.name,
        "engine_required": requirements.engine.name,
        "engine_predicted": spec.engine.name,
        "payload_kg": spec.mission.payload_kg,
        "payload_kg_req": requirements.mission.payload_kg,
        "payload_kg_pred": spec.mission.payload_kg,
        "endurance_hr_req": requirements.mission.endurance_s / 3600.0,
        "endurance_hr_pred": endurance_s / 3600.0,
        "endurance_applicable": endurance_applicable,
        "payload_met": payload_met,
        "endurance_met": endurance_met,
        "engine_met": engine_met,
        "dash_mps": dash_mps,
        "dash_kmh": dash_mps * 3.6,
        "dash_mach": dash_mach,
        "mtow_kg": mtow,
        "fuel_kg": fuel,
        "cruise_lod": lod,
        "cruise_lod_method": "mission_drag_buildup",
        "trimmed_oas_cruise_lod": oas_cruise_lod,
        "dash_mach_cap": spec.mission.dash_mach_cap,
        "mach_cap_ok": mach_ok,
        "shape_ok": shape["ok"],
        "shape": shape,
        "sketch_departure_count": shape.get("departure_count", 0),
        "balance_ok": sm_ok,
        "trim_ok": trim_ok,
        "stall_ok": stall_ok,
        "vv_ok": vv_ok,
        "artifact_ok": artifact_ok,
    }

    def fmt(v, spec_="{:.3f}"):
        return spec_.format(v) if isinstance(v, (int, float)) else "n/a"

    span_t, span_tol = sketch_shape_targets(spec)["span_over_length"]
    root_t, root_tol = sketch_shape_targets(spec)["root_over_length"]
    sw_t, sw_tol = sketch_shape_targets(spec)["le_sweep_deg"]
    sweep_word = "forward-swept" if spec.wing.le_sweep_deg < 0 else "aft-swept"
    source_tail_required = requirements.htail.span_m > 0.05
    topology_text = (
        "with the required conventional horizontal tail"
        if tail_enabled and source_tail_required
        else "with the bounded horizontal-tail trim fallback"
        if tail_enabled
        else "tailless"
    )
    wing_trim_note = (
        "fixed while tail incidence closes pitch trim"
        if tail_enabled
        else "sized by the tailless trim solve"
    )
    tail_config = (
        f"horizontal tail span {spec.htail.span_m:.2f} m, root "
        f"{spec.htail.root_chord_m:.2f} m, incidence "
        f"{spec.htail.incidence_deg:+.1f}° "
        f"({'required topology' if source_tail_required else 'autonomous trim fallback'})"
        if tail_enabled
        else "no horizontal tail (per sketches)"
    )
    fin_topology = (
        "single centerline fin" if spec.vtail.count == 1 else "twin canted fins"
    )
    reproduction = bool(
        spec.sketch is not None and spec.sketch.treatment == "reproduction"
    )
    installation_text = (
        f"{spec.engine.installation_count} external nacelle"
        f"{'s' if spec.engine.installation_count != 1 else ''}"
        if spec.engine.installation == "external"
        else "buried/internal propulsion"
    )
    sketch_context = (
        "source geometry is frozen in reproduction mode"
        if reproduction
        else "concept sketches are soft priors in inspiration mode"
    )
    vv_requirement = (
        (
            "same-run Cnβ>0, Cnr<0, CYβ<0 (source-locked reproduction)"
            if directional_derivative_evidence.get("ok")
            else f">= {float(vv_band[0]):.2f} (source-locked reproduction)"
        )
        if reproduction
        else f"{float(vv_band[0]):.2f}-{float(vv_band[1]):.2f}"
    )
    directional_gate_name = (
        "Directional authority" if reproduction else "Directional stability"
    )
    if spec.engine.deck is not None:
        engine_lines = [
            f"Typed sparse deck: {spec.engine.deck.name} "
            f"({len(spec.engine.deck.points)} declared points; "
            f"{spec.engine.deck.interpolation}, "
            f"extrapolation={spec.engine.deck.extrapolation}).",
            f"Complete installed system: {spec.engine.max_thrust_sl_n:.1f} N "
            f"sea-level static rating across {installation_text}.",
            "Thrust and fuel flow are interpolated from the deck at "
            "altitude/Mach/throttle; the generic density-lapse and TSFC "
            "surrogate is not used while a deck is active.",
            (
                "Battery energy/endurance is outside this reproduction; the "
                "pipeline claims thrust closure only."
                if not endurance_applicable
                else "Pipeline endurance is a steady-cruise closure; block-mission "
                "fuel/time evidence is scored separately."
            ),
        ]
    else:
        static_thrust_kgf = spec.engine.max_thrust_sl_n / G0
        static_flow_g_min = spec.engine.fuel_flow_max_kg_s * 60_000.0
        static_tsfc = (
            spec.engine.fuel_flow_max_kg_s * 3600.0 / max(static_thrust_kgf, 1e-12)
        )
        engine_lines = [
            f"Encoded sea-level static point: {static_thrust_kgf:.1f} kgf / "
            f"{static_flow_g_min:.0f} g/min → TSFC "
            f"{static_tsfc:.3f} kg/(kgf·h).",
            "Lapse: T = T0 · σ · max(floor, 1 − kMach · M), using the "
            "declared engine coefficients.",
            "Part-throttle TSFC uses the declared inverse-throttle, "
            "temperature, and Mach factors.",
            "Dash is a capability point; the endurance budget assumes steady cruise.",
        ]
    if spec.mass.operating_empty_mass_kg is not None:
        buildup_mass_text = (
            "reference OE-mass mode; no independent component buildup is claimed"
        )
    else:
        buildup_mass_text = (
            f"buildup model: "
            f"{fmt(_buildup_wing_kg(spec, sizing, mtow, fuel), '{:.2f}')} kg"
        )
    su2_converged = bool(su2_c.get("converged")) and bool(su2_d.get("converged"))
    su2_status = (
        "converged"
        if su2_converged
        else "ran but did not meet the residual convergence criterion"
        if su2_ok
        else "not run / failed"
    )
    endurance_requirement_text = (
        f"{requirements.mission.endurance_s / 3600:.2f} h"
        if endurance_applicable
        else "not claimed (electric flight-dynamics reproduction)"
    )
    endurance_prediction_text = (
        f"{endurance_s / 3600:.2f} h" if endurance_applicable else "n/a"
    )

    lines = [
        "# open-air prototype design report",
        "",
        f"Vehicle: **{spec.name}** (case `{case_path}`)",
        "",
        "## Target (source design requirements)",
        "",
        f"- Engine: {requirements.engine.name} ({requirements.engine.max_thrust_sl_n:.1f} N SL static, {requirements.engine.dry_mass_kg} kg)",
        f"- Payload: {requirements.mission.payload_kg} kg",
        f"- Endurance required: {endurance_requirement_text}",
        f"- Dash: maximize TAS, VLM/Euler validity cap M = {spec.mission.dash_mach_cap}",
        f"- Shape: {sweep_word} trapezoidal wing, pointed fuselage, "
        f"{installation_text}, {topology_text} with {fin_topology} "
        f"({sketch_context})",
        "",
        "## Score vs source requirements",
        "",
        "| Criterion | Required | Predicted | Status |",
        "|---|---|---:|---|",
        f"| Engine | {requirements.engine.name} | {spec.engine.name} | {_status(engine_met)} |",
        f"| Payload | {requirements.mission.payload_kg:.1f} kg | {spec.mission.payload_kg:.1f} kg | {_status(payload_met)} |",
        f"| Endurance | {endurance_requirement_text} | {endurance_prediction_text} | {_status(endurance_met)} |",
        f"| Dash speed | maximize (M <= {spec.mission.dash_mach_cap}) | {dash_mps:.1f} m/s ({dash_mps * 3.6:.0f} km/h, M {dash_mach:.2f} at {spec.mission.dash_altitude_m:.0f} m) | {_status(mach_ok)} |",
        f"| Shape | sketch proportions | span/L {spec.wing.span_m / spec.fuselage.length_m:.2f} (tgt {span_t:.2f}±{span_tol:.2f}), root/L {spec.wing.root_chord_m / spec.fuselage.length_m:.2f} (tgt {root_t:.2f}±{root_tol:.2f}), sweep {spec.wing.le_sweep_deg:.1f}° (tgt {sw_t:.0f}±{sw_tol:.0f}) | {_status(shape['ok'])} |",
        "",
        "## Internal design-feasibility gates",
        "",
        "| Gate | Value | Requirement | Status |",
        "|---|---:|---|---|",
        f"| Static margin (full fuel) | {fmt(sm_full)} | {sm_lo:.2f}-{sm_hi:.2f} MAC | {_status(sm_ok)} |",
        f"| Static margin (reserve fuel) | {fmt(sm_reserve)} | {sm_lo:.2f}-{sm_hi:.2f} MAC | {_status(sm_ok)} |",
        f"| Pitch trim ({trim_control_name}) | {fmt(trim_got, '{:.1f}')}° vs spec {trim_spec:.1f}°, CM residual {fmt(cm_residual, '{:.4f}')} | converges, CM=0 at cruise | {_status(trim_ok)} |",
        f"| Stall speed | {fmt(vstall, '{:.1f}')} m/s | <= {spec.mission.stall_speed_max_mps:.0f} m/s (CLmax {spec.mission.cl_max}) | {_status(stall_ok)} |",
        f"| {directional_gate_name} | Vv = {fmt(vv, '{:.4f}')} | {vv_requirement} | {_status(vv_ok)} |",
        f"| Geometry artifact | {n_artifact} mesh-truth checks on the exported STL (extents, fin verticality, attachment) | all pass | {_status(artifact_ok)} |",
        f"| OAS verification | trim + wingbox at limit load | must pass | {_status(verify_ok)} |",
        "",
        "## Predicted performance",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Dash TAS | {dash_mps:.1f} m/s ({dash_mps * 3.6:.0f} km/h) |",
        f"| MTOW | {mtow:.1f} kg |",
        f"| Fuel | {fuel:.1f} kg |",
        f"| Cruise L/D (mission drag buildup) | {lod:.2f} |",
        *(
            [f"| Cruise L/D (trimmed OAS) | {float(oas_cruise_lod):.2f} |"]
            if isinstance(oas_cruise_lod, (int, float))
            else []
        ),
        f"| Span | {span:.2f} m |",
        f"| Wing area | {spec.wing.area_m2:.2f} m² |",
        f"| Aspect ratio | {spec.wing.aspect_ratio:.2f} |",
        f"| Wing loading | {mtow / spec.wing.area_m2 if spec.wing.area_m2 else 0:.1f} kg/m² |",
        "",
        "## Configuration",
        "",
        f"- Fuselage length × width × height: {spec.fuselage.length_m:.2f} × {spec.fuselage.max_width_m:.2f} × {spec.fuselage.max_height_m:.2f} m",
        f"- Wing: span {spec.wing.span_m:.2f} m, root {spec.wing.root_chord_m:.2f} m, taper {spec.wing.taper:.2f}, LE sweep {spec.wing.le_sweep_deg:.1f}°, t/c {spec.wing.t_over_c:.3f}, NACA {spec.wing.airfoil}",
        f"- Washout {spec.wing.twist_root_deg - spec.wing.twist_tip_deg:.1f}° (root {spec.wing.twist_root_deg:+.1f}°, tip {spec.wing.twist_tip_deg:+.1f}°) — {wing_trim_note}",
        f"- {fin_topology.title()}: span {spec.vtail.span_m:.2f} m, cant {spec.vtail.cant_deg:.1f}°, roots derived from the local aft-body section (see `geometry.json .openvsp.fin_attach`); {tail_config}",
        f"- Payload bay front face x={spec.fuselage.payload_bay_x_m:.2f} m; fuselage tank x={spec.fuselage.fuel_tank_x_m:.2f} m (balance-driven)",
        f"- Propulsion installation: {installation_text}; declared mass, thrust, "
        "and fuel flow represent the complete installed system",
        f"- CG: full {fmt(balance.get('x_cg_full_m'))} m, reserve {fmt(balance.get('x_cg_reserve_m'))} m; NP {fmt(balance.get('x_np_m'))} m",
        *(
            [
                "- Horizontal-tail lift-effectiveness calibration: "
                f"{spec.solver.tail_lift_effectiveness_factor:.3f} × the "
                "default conceptual value; source: "
                f"{spec.solver.tail_lift_effectiveness_source}"
            ]
            if abs(spec.solver.tail_lift_effectiveness_factor - 1.0) > 1e-12
            else []
        ),
        f"- Structure: {spec.structures.fem_model_type}, skin {1000 * spec.structures.skin_thickness_m:.2f} mm, spar {1000 * spec.structures.spar_thickness_m:.2f} mm, {spec.structures.material.name}",
        "",
        "## Engine model (assumptions)",
        "",
        *engine_lines,
        "",
        "## Structures",
        "",
        (
            f"- Structural method applicability: **refused** — {structures.get('reason')}"
            if (structures or {}).get("status") == "unsupported-domain"
            else "- Structural method applicability: inside the declared small-aircraft span/MTOW domain."
        ),
        f"- OAS +{spec.mission.limit_positive_g:g}g failure index: {fmt(oas_fail)} (≤ 0 required; KS of σ/allow − 1 with SF {spec.mission.safety_factor})",
        f"- Maneuver lift closure: CL {fmt(oas_positive.get('CL'))} vs required {fmt(oas_positive.get('required_CL'))}; "
        f"closed={bool(oas_positive.get('lift_closure_ok'))}, aerodynamic domain={bool(oas_positive.get('aerodynamic_domain_ok'))}, "
        f"reference-mass closure={bool(oas_positive.get('mass_closure_ok'))}"
        + (
            "; incidence exceeds 12°, so this linear-VLM structural result is refused"
            if oas_positive.get("linear_vlm_extrapolation")
            else ""
        ),
        f"- OAS wing structural mass: {fmt(oas_mass, '{:.2f}')} kg ({buildup_mass_text})",
        f"- TACS stretch: {'ran and parsed' if tacs_ok else 'not run / failed'}"
        + (
            f", KS failure {tacs_ks:.3f}, shell mass {tacs_mass:.2f} kg"
            if tacs_ok and tacs_ks is not None
            else ""
        ),
        "",
        "OAS wingbox vs TACS shell are different idealizations (smeared box vs coarse Gmsh shells); mass disagreement is expected.",
        "",
        "## Aero cross-checks",
        "",
        f"- Scope note: OAS trim/SM model the wing{' plus horizontal tail' if tail_enabled else ''}; structures remains the wingbox. The fins enter",
        "  as drag area, mass, and the Vv gate. The exported 3D geometry is",
        "  therefore verified separately by the mesh-truth checks above (QA audit F14/F15).",
        f"- VSPAERO vs OAS lift-curve slope: {'ok' if vsp_ok else 'weak / failed'} (CLα only; absolute CL carries different camber fidelity and VSPAERO CD is not comparable)",
        *(
            [
                "- Neutral-point method spread (diagnostic, not a pass/fail "
                f"claim): component model vs full VSPAERO {fmt(component_np_method_spread)} MAC; "
                f"OAS vs full VSPAERO {fmt(vsp_np_method_spread)} MAC"
            ]
            if component_np_method_spread is not None
            and vsp_np_method_spread is not None
            else []
        ),
        f"- SU2 2D Euler NACA {spec.wing.airfoil}: {su2_status} "
        "(stretch calibration data, never a design gate)",
    ]
    departures = (mdo or {}).get("sketch_departures") or []
    if departures:
        lines += ["", "## Documented sketch departures", ""]
        for departure in departures:
            lines.append(
                f"- `{departure.get('parameter')}`: {departure.get('reason', 'reason not recorded')}"
            )
    if su2_c.get("CL") is not None:
        lines.append(
            f"- SU2 cruise: CL={su2_c['CL']:.4f}, CD={fmt(su2_c.get('CD'), '{:.4f}')}, rmsρ={fmt(su2_c.get('rms_density'), '{:.2f}')}"
        )
    if su2_d.get("CL") is not None:
        lines.append(
            f"- SU2 dash: CL={su2_d['CL']:.4f}, CD={fmt(su2_d.get('CD'), '{:.4f}')}, rmsρ={fmt(su2_d.get('rms_density'), '{:.2f}')}"
        )
    if cal:
        bits = [f"{k}={v:.2f}" for k, v in cal.items() if isinstance(v, (int, float))]
        lines.append("- Calibration (2D section / 3D OAS): " + "; ".join(bits))
    if (mdo or {}).get("best"):
        b = mdo["best"]
        closure_label = "Deterministic reproduction closure" if reproduction else "MDO"
        lines += [
            "",
            "## Optimized prototype (child case)",
            "",
            f"{closure_label} produced `results/{concept}/optimized/design.yaml`: dash {b['dash_mps']:.1f} m/s, "
            f"endurance {b['endurance_s'] / 3600:.2f} h, MTOW {b['mtow_kg']:.1f} kg, feasible={b['feasible']}, "
            f"OAS-verified={bool((mdo.get('oas_verify') or {}).get('ok'))}. "
            f"Its own full report lives in `results/{concept}/optimized/design_report.md`.",
        ]
    lines += [
        "",
        "## Pipeline products",
        "",
        f"- Geometry backend: {(geom or {}).get('backend', 'n/a')}, read-back matches spec: {((geom or {}).get('openvsp') or {}).get('readback', {}).get('matches_spec', 'n/a')}",
        f"- Sizing closed: {sizing.get('ok') if sizing else 'not rerun for child; inherited from parent closure'}",
        f"- OAS aero (incl. trim + stability gates): {(aero or {}).get('ok', False)}",
        f"- OAS structures: {(structures or {}).get('ok', False)}",
        f"- MDO feasible + OAS-verified: {mdo.get('ok') if mdo else 'n/a (ran on the parent case)'}",
        f"- Validation: {(validation or {}).get('passed', 0)}/{(validation or {}).get('total', 0)}",
        f"- TACS stretch ran/parsed: {tacs_ok}",
        f"- SU2 stretch ran/parsed: {su2_ok}; converged: {su2_converged}",
        "",
        "Figures in the results directory: `threeview.png` (rendered from the exported STL — the",
        "artifact, not the intent), plus intent-derived `planform.png`, `polar.png`,",
        "`mass_breakdown.png`, `drag_breakdown.png`, `spanwise_loads.png`, `margins.png`.",
        "",
    ]
    report_md = outdir / "design_report.md"
    text = "\n".join(lines)
    report_md.write_text(text)
    gates_ok = (
        endurance_met
        and payload_met
        and engine_met
        and mach_ok
        and sm_ok
        and trim_ok
        and stall_ok
        and vv_ok
        and artifact_ok
        and verify_ok
        and validation_core_ok
        and shape["ok"]
    )
    return {
        "ok": gates_ok,
        "desires": desires,
        "report": str(report_md),
        "model_source_sha256": model_source_sha256(),
    }
