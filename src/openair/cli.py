"""Shared stage CLIs and the concept-level pipeline orchestrator."""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from openair.io import dump_json, dump_stage, load_stage, load_yaml
from openair.paths import (
    DESIGNS_DIR,
    configure_runtime,
    optimized_design_for,
    resolve_design,
    results_dir_for,
)
from openair.provenance import model_source_sha256
from openair.schemas import VehicleSpec

_PIPELINE_RUN_ID: str | None = None


def _wing_mass_retry(candidate: dict[str, Any]) -> dict[str, float] | None:
    measured = candidate.get("measured_wing_mass_kg")
    if not isinstance(measured, (int, float)) or measured <= 0:
        return None
    return {"wing_mass_override_kg": float(measured)}


AUTO_RETRY_REGISTRY: dict[str, Callable[[dict[str, Any]], dict[str, float] | None]] = {
    "wing_mass_buildup_vs_oas": _wing_mass_retry,
}


def _select_auto_retry(feedback: dict[str, Any]) -> dict[str, Any] | None:
    """Select at most one registered non-artifact retry from gate feedback."""
    for candidate in feedback.get("retry_candidates") or []:
        if candidate.get("tier") == "C":
            continue
        key = str(candidate.get("key") or "")
        handler = AUTO_RETRY_REGISTRY.get(key)
        overlay = handler(candidate) if handler else None
        if overlay:
            return {
                "trigger": key,
                "tier": candidate.get("tier"),
                "source": candidate.get("source"),
                "overlay": overlay,
            }
    return None


def load_spec(design_path: str | Path) -> VehicleSpec:
    """Load a spec from a concept directory, design YAML, or bare YAML."""
    _, design_yaml, _ = resolve_design(design_path)
    return VehicleSpec.model_validate(load_yaml(design_yaml))


def promote_design(design_path: str | Path, new_name: str) -> Path:
    """Promote a generated optimized design into a new immutable source bundle."""
    from openair.designer.server import concept_name

    promoted_name = concept_name(new_name)
    source_concept, source_yaml, _ = resolve_design(design_path)
    optimized_yaml = optimized_design_for(source_yaml)
    if not optimized_yaml.exists():
        raise FileNotFoundError(
            f"Optimized design not found: {optimized_yaml}. Run the pipeline first."
        )
    optimized = load_spec(optimized_yaml)
    destination = DESIGNS_DIR / promoted_name
    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing source concept: {destination}"
        )

    source_bundle = DESIGNS_DIR / source_concept
    staging = DESIGNS_DIR / f".{promoted_name}.promote-{uuid.uuid4().hex}"
    staging.mkdir(parents=False)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        promoted = optimized.model_copy(deep=True)
        promoted.name = promoted_name
        provenance = (
            f"Promoted from {source_concept} optimized output at {timestamp}; "
            f"source artifact: {optimized_yaml}."
        )
        promoted.notes = (
            f"{promoted.notes.rstrip()} {provenance}".strip()
            if promoted.notes
            else provenance
        )
        with open(staging / "design.yaml", "w", encoding="utf-8") as stream:
            yaml.safe_dump(
                promoted.model_dump(mode="python"),
                stream,
                sort_keys=False,
            )

        copied_sketches = []
        if source_bundle.is_dir():
            for sketch in sorted(source_bundle.glob("sketch-*.png")):
                shutil.copy2(sketch, staging / sketch.name)
                copied_sketches.append(sketch.name)
        prior_brief = source_bundle / "brief.md"
        prior_text = (
            prior_brief.read_text(encoding="utf-8")
            if prior_brief.exists()
            else "No prior source brief was available."
        )
        brief = (
            f"# {promoted_name} — promoted source concept\n\n"
            "## Promotion provenance\n\n"
            f"{provenance}\n\n"
            f"Copied sketches: {', '.join(copied_sketches) if copied_sketches else 'none'}.\n"
            "Generated results were not copied; this bundle is the explicit source "
            "for a new pipeline iteration.\n\n"
            "## Prior source brief\n\n"
            f"{prior_text.rstrip()}\n"
        )
        (staging / "brief.md").write_text(brief, encoding="utf-8")
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def _record_stage(design_path: str | Path, stage: str, payload: dict[str, Any]) -> Path:
    _, design_yaml, _ = resolve_design(design_path)
    payload.setdefault("design", str(design_yaml))
    payload.setdefault("case", str(design_yaml))  # Backward-compatible JSON key.
    payload.setdefault("stage", stage)
    payload.setdefault("model_source_sha256", model_source_sha256())
    payload.setdefault(
        "pipeline_run_id",
        _PIPELINE_RUN_ID or f"standalone-{uuid.uuid4().hex}",
    )
    return dump_stage(design_yaml, stage, payload)


def stage_main(stage: str, run: Callable[[VehicleSpec, Path], dict[str, Any]]) -> None:
    configure_runtime()
    parser = argparse.ArgumentParser(prog=f"python -m openair.{stage}")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("design", type=Path, help="concept folder or design YAML")
    args = parser.parse_args()
    _, design_yaml, _ = resolve_design(args.design)
    spec = load_spec(design_yaml)
    from openair.mission.sizing import load_sized_spec

    spec = load_sized_spec(design_yaml, spec)
    outdir = results_dir_for(design_yaml)
    payload = run(spec, outdir)
    path = _record_stage(design_yaml, stage, payload)
    print(f"wrote {path}")


def _run_stretch(design_yaml: Path, spec: VehicleSpec) -> None:
    """Run calibration solvers without turning them into flight-worthiness gates."""
    from openair.mdo.problem import evaluate_design
    from openair.structures.tacs_backend import run_tacs_stage
    from openair.validation.su2_backend import run_su2_stage

    outdir = results_dir_for(design_yaml)
    aero = load_stage(design_yaml, "aero") or {}
    sizing = load_stage(design_yaml, "sizing") or {}
    metrics = evaluate_design(spec)
    mtow = float(sizing.get("mtow_kg") or aero.get("mtow_kg") or metrics["mtow_kg"])
    cruise = aero.get("cruise") or {
        "mach": 0.2,
        "alpha_deg": 3.0,
        "CL": 0.3,
        "CD": 0.03,
    }
    dash = aero.get("dash") or {
        "mach": 0.4,
        "alpha_deg": 1.0,
        "CL": 0.15,
        "CD": 0.025,
    }

    try:
        tacs = run_tacs_stage(
            spec,
            outdir,
            lift_n=mtow * 9.80665 * spec.mission.limit_positive_g,
        )
    except Exception as exc:
        tacs = {"ok": False, "error": str(exc), "calibration_only": True}
    _record_stage(design_yaml, "tacs", tacs)

    try:
        su2 = run_su2_stage(spec, outdir / "su2", cruise, dash)
    except Exception as exc:
        su2 = {"ok": False, "error": str(exc), "calibration_only": True}
    _record_stage(design_yaml, "su2", su2)


def _run_core(
    design_yaml: Path,
    *,
    sizing: bool,
    mdo: bool,
    wing_mass_override_kg: float | None = None,
) -> VehicleSpec:
    from openair.aero.oas_backend import run_aero_stage
    from openair.flightdyn.stage import run_flightdyn_stage
    from openair.geometry.openvsp_model import run_geometry_stage
    from openair.mdo.problem import run_mdo_stage
    from openair.mission.sizing import load_sized_spec, run_sizing_stage
    from openair.structures.oas_wingbox import run_structures_stage

    outdir = results_dir_for(design_yaml)
    spec = load_spec(design_yaml)
    spec._wing_mass_override_kg = wing_mass_override_kg
    if sizing:
        _record_stage(design_yaml, "sizing", run_sizing_stage(spec, outdir))
        fallback = load_spec(design_yaml)
        fallback._wing_mass_override_kg = wing_mass_override_kg
        spec = load_sized_spec(design_yaml, fallback)
        spec._wing_mass_override_kg = wing_mass_override_kg
    _record_stage(design_yaml, "geometry", run_geometry_stage(spec, outdir))
    _record_stage(design_yaml, "aero", run_aero_stage(spec, outdir))
    if spec.flight_dynamics.enabled:
        _record_stage(
            design_yaml,
            "flightdyn",
            run_flightdyn_stage(spec, outdir),
        )
    _record_stage(design_yaml, "structures", run_structures_stage(spec, outdir))
    if mdo:
        _record_stage(
            design_yaml,
            "mdo",
            run_mdo_stage(spec, outdir, design_yaml),
        )
    return spec


def _run_reviews(
    design_yaml: Path,
    spec: VehicleSpec,
    *,
    requirements_path: Path | None = None,
) -> None:
    from openair.reporting.report import run_report_stage
    from openair.validation.runner import run_validation_stage

    outdir = results_dir_for(design_yaml)
    _record_stage(
        design_yaml,
        "validation",
        run_validation_stage(spec, outdir, design_yaml),
    )
    _record_stage(
        design_yaml,
        "report",
        run_report_stage(
            spec,
            outdir,
            design_yaml,
            requirements_path=requirements_path,
        ),
    )


def _clear_pipeline_products(results_root: Path) -> None:
    for phase in ("baseline", "optimized"):
        shutil.rmtree(results_root / phase, ignore_errors=True)
    for artifact in (
        "report.html",
        "executive_brief.pdf",
        "gate_feedback.json",
    ):
        (results_root / artifact).unlink(missing_ok=True)


def _run_pipeline_pass(
    design_yaml: Path,
    *,
    wing_mass_override_kg: float | None = None,
) -> tuple[VehicleSpec, VehicleSpec]:
    baseline_spec = _run_core(
        design_yaml,
        sizing=True,
        mdo=True,
        wing_mass_override_kg=wing_mass_override_kg,
    )
    optimized_yaml = optimized_design_for(design_yaml)
    if not optimized_yaml.exists():
        raise RuntimeError(
            f"MDO did not publish the optimized design: {optimized_yaml}"
        )
    optimized_spec = _run_core(
        optimized_yaml,
        sizing=False,
        mdo=False,
        wing_mass_override_kg=wing_mass_override_kg,
    )
    _run_stretch(optimized_yaml, optimized_spec)
    _run_reviews(design_yaml, baseline_spec)
    _run_reviews(
        optimized_yaml,
        optimized_spec,
        requirements_path=design_yaml,
    )
    return baseline_spec, optimized_spec


def _write_gate_feedback(
    design_yaml: Path,
    *,
    auto_retries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from openair.reporting.gates import build_gate_feedback, format_gate_table

    _, _, results_root = resolve_design(design_yaml)
    feedback = build_gate_feedback(design_yaml, auto_retries=auto_retries)
    dump_json(results_root / "gate_feedback.json", feedback)
    print(format_gate_table(feedback))
    return feedback


def top_main(argv: list[str] | None = None) -> int:
    """Run the full baseline → optimized → presentation concept workflow."""
    configure_runtime()
    parser = argparse.ArgumentParser(prog="openair")
    parser.add_argument("command", choices=["run", "optimize", "validate", "promote"])
    parser.add_argument("design", type=Path, help="concept folder or design YAML")
    parser.add_argument(
        "new_name",
        nargs="?",
        help="new source concept name (required by promote)",
    )
    args = parser.parse_args(argv)
    global _PIPELINE_RUN_ID
    _PIPELINE_RUN_ID = uuid.uuid4().hex

    if args.command == "promote":
        if not args.new_name:
            parser.error("promote requires <concept> <new-name>")
        destination = promote_design(args.design, args.new_name)
        print(f"promoted: {destination}")
        return 0
    if args.new_name is not None:
        parser.error(f"{args.command} does not accept <new-name>")

    concept, design_yaml, results_root = resolve_design(args.design)
    if args.command == "validate":
        from openair.mission.sizing import load_sized_spec

        spec = load_sized_spec(design_yaml, load_spec(design_yaml))
        _run_reviews(design_yaml, spec)
        print(f"done: validate {design_yaml}")
        return 0

    if args.command == "run":
        # A full run is reproducible: stale phase artifacts must not leak into
        # validation or the presentation.
        _clear_pipeline_products(results_root)

    baseline_spec = _run_core(design_yaml, sizing=True, mdo=True)
    if args.command == "optimize":
        print(f"done: optimize {design_yaml}")
        return 0

    optimized_yaml = optimized_design_for(design_yaml)
    if not optimized_yaml.exists():
        raise RuntimeError(
            f"MDO did not publish the optimized design: {optimized_yaml}"
        )
    optimized_spec = _run_core(optimized_yaml, sizing=False, mdo=False)
    _run_stretch(optimized_yaml, optimized_spec)
    _run_reviews(design_yaml, baseline_spec)
    _run_reviews(
        optimized_yaml,
        optimized_spec,
        requirements_path=design_yaml,
    )

    auto_retries: list[dict[str, Any]] = []
    feedback = _write_gate_feedback(design_yaml)
    retry = _select_auto_retry(feedback)
    if retry is not None:
        wing_override = retry["overlay"].get("wing_mass_override_kg")
        entry = {
            "attempt": 1,
            "trigger": retry["trigger"],
            "tier": retry["tier"],
            "source": retry["source"],
            "action": "Overlay the OAS-measured closed wing mass and rerun sizing through optimized validation once.",
            "overlay": retry["overlay"],
            "before": {
                "passed": feedback["passed"],
                "total": feedback["total"],
            },
        }
        auto_retries.append(entry)
        print(
            "auto-retry 1/1: wing_mass_buildup_vs_oas "
            f"with closed wing mass {float(wing_override):.3f} kg"
        )
        _clear_pipeline_products(results_root)
        _run_pipeline_pass(
            design_yaml,
            wing_mass_override_kg=float(wing_override),
        )
        from openair.reporting.gates import build_gate_feedback

        final_feedback = build_gate_feedback(
            design_yaml,
            auto_retries=auto_retries,
        )
        entry["after"] = {
            "passed": final_feedback["passed"],
            "total": final_feedback["total"],
            "trigger_cleared": not any(
                candidate.get("key") == retry["trigger"]
                for candidate in final_feedback.get("retry_candidates") or []
            ),
        }
        feedback = _write_gate_feedback(
            design_yaml,
            auto_retries=auto_retries,
        )

    from openair.reporting.presentation import build_presentation

    products = build_presentation(design_yaml)
    print(f"pipeline complete: {concept}")
    print(f"  baseline:  {results_root / 'baseline'}")
    print(f"  optimized: {results_root / 'optimized'}")
    print(f"  report:    {products['html']}")
    print(f"  brief:     {products['pdf']}")
    return 0


def main() -> None:
    sys.exit(top_main())
