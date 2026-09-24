"""Baseline-only multirotor pipeline orchestration."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from openair.io import dump_json, load_yaml
from openair.multirotor.buildup import run_aero_stage
from openair.multirotor.geometry import run_geometry_stage
from openair.multirotor.mass import run_mass_stage
from openair.multirotor.package import build_multirotor_package
from openair.multirotor.propulsion import run_propulsion_stage
from openair.multirotor.report import run_report_stage
from openair.multirotor.schema import MultirotorSpec
from openair.paths import results_dir_for, results_root_for
from openair.provenance import model_source_sha256


def _record_stage(
    design_path: Path,
    outdir: Path,
    name: str,
    payload: dict[str, Any],
    *,
    pipeline_run_id: str,
    source_hash: str,
) -> dict[str, Any]:
    stamped = {
        **payload,
        "design": str(design_path.resolve()),
        "case": str(design_path.resolve()),
        "stage": name,
        "pipeline_run_id": pipeline_run_id,
        "model_source_sha256": source_hash,
    }
    dump_json(outdir / f"{name}.json", stamped)
    return stamped


def run_multirotor_pipeline(
    design_path: Path,
    *,
    clean: bool,
    pipeline_run_id: str | None = None,
) -> dict[str, str]:
    design_path = design_path.resolve()
    spec = MultirotorSpec.model_validate(load_yaml(design_path))
    spec.assert_cross_model_invariants()
    run_id = pipeline_run_id or uuid.uuid4().hex
    source_hash = model_source_sha256()
    root = results_root_for(design_path)
    if clean:
        shutil.rmtree(root / "baseline", ignore_errors=True)
        (root / "report.html").unlink(missing_ok=True)
    outdir = results_dir_for(design_path)

    geometry = _record_stage(
        design_path,
        outdir,
        "multirotor_geometry",
        run_geometry_stage(spec, design_path, outdir),
        pipeline_run_id=run_id,
        source_hash=source_hash,
    )
    mass = _record_stage(
        design_path,
        outdir,
        "multirotor_mass",
        run_mass_stage(spec, geometry),
        pipeline_run_id=run_id,
        source_hash=source_hash,
    )
    propulsion = _record_stage(
        design_path,
        outdir,
        "multirotor_propulsion",
        run_propulsion_stage(spec, geometry, mass),
        pipeline_run_id=run_id,
        source_hash=source_hash,
    )
    aero = _record_stage(
        design_path,
        outdir,
        "multirotor_aero",
        run_aero_stage(spec, geometry, mass, outdir),
        pipeline_run_id=run_id,
        source_hash=source_hash,
    )
    failed = [
        name
        for name, payload in {
            "geometry": geometry,
            "mass": mass,
            "propulsion": propulsion,
            "aero": aero,
        }.items()
        if not payload.get("ok")
    ]
    if failed:
        raise RuntimeError(f"multirotor stages failed: {', '.join(failed)}")

    package = _record_stage(
        design_path,
        outdir,
        "multirotor_package",
        build_multirotor_package(spec, design_path, outdir),
        pipeline_run_id=run_id,
        source_hash=source_hash,
    )
    report = _record_stage(
        design_path,
        outdir,
        "multirotor_report",
        run_report_stage(
            spec,
            outdir,
            geometry,
            mass,
            propulsion,
            aero,
            package,
        ),
        pipeline_run_id=run_id,
        source_hash=source_hash,
    )
    if not report.get("ok"):
        raise RuntimeError("multirotor report contains a failed gate")
    return {
        "outdir": str(outdir),
        "package_dir": package["package_dir"],
        "report": report["report_html"],
    }

