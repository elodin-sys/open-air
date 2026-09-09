"""CLI: ``python -m openair.reference ingest|compare``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openair.paths import DESIGNS_DIR, configure_runtime, resolve_design


def _ingest(args: argparse.Namespace) -> int:
    from openair.designer.server import WorkspaceError, concept_name
    from openair.reference.ingest import ReferenceInputError, ingest_reference

    try:
        concept = concept_name(args.concept)
    except WorkspaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else DESIGNS_DIR / concept / "reference"
    sketch_dir = Path(args.sketch_dir) if args.sketch_dir else out_dir.parent
    acceptance = {}
    if args.fidelity_p95_mm is not None:
        acceptance["p95_m"] = args.fidelity_p95_mm / 1000.0
    if args.fidelity_iou is not None:
        acceptance["iou_top"] = args.fidelity_iou
        acceptance["iou_side"] = args.fidelity_iou
    try:
        summary = ingest_reference(
            args.mesh,
            concept=concept,
            out_dir=out_dir,
            sketch_dir=sketch_dir,
            units=args.units,
            sidecar_path=Path(args.sidecar) if args.sidecar else None,
            axes=args.axes,
            datum=args.datum,
            expect_span_m=args.expect_span_m,
            anchor_tolerance=args.anchor_tolerance,
            target_faces=args.target_faces,
            mm_per_px=args.mm_per_px,
            min_component_fraction=args.min_component_fraction,
            dry_run=args.dry_run,
            force=args.force,
            acceptance=acceptance or None,
        )
    except ReferenceInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print_summary(summary)
    return 0


def _print_summary(summary: dict) -> None:
    overall = summary["measurements"]["overall"]
    align = summary["alignment"]
    print(f"reference model for {summary['concept']}{' (dry run)' if summary.get('dry_run') else ''}")
    print(
        f"  source {summary['provenance']['source_name']} sha256 {summary['provenance']['source_sha256'][:12]}… "
        f"{summary['provenance']['raw_faces']} faces, {summary['provenance']['declared_units']}"
    )
    cleaning = summary["cleaning"]
    print(
        f"  cleaning: kept {cleaning.get('components_kept')} of {cleaning.get('components_total')} shells"
        + (f", dropped {cleaning.get('dropped_count')} (largest {1000 * cleaning.get('dropped_largest_extent_m', 0):.0f} mm)" if cleaning.get("dropped_count") else "")
    )
    sym = align.get("symmetry") or {}
    if sym:
        print(
            f"  symmetry plane: yaw {sym['yaw_deg']:.3f}°, roll {sym['roll_deg']:.3f}°, "
            f"residual median {1000 * sym['residual_median_m']:.2f} mm, p90 {1000 * sym['residual_p90_m']:.2f} mm"
        )
    level = align.get("datum_leveling") or {}
    print(f"  datum {level.get('mode')}: pitch rotation {level.get('pitch_rotation_applied_deg', 0.0):.3f}°")
    anchor = summary.get("anchor_check") or {}
    if anchor.get("anchor_span_m"):
        print(f"  span {overall['span_m']:.4f} m vs anchor {anchor['anchor_span_m']:.4f} m ({100 * anchor['relative_deviation']:.2f}%) ok={anchor['ok']}")
    else:
        print(f"  span {overall['span_m']:.4f} m (no anchor supplied)")
    print(f"  length {overall['length_m']:.4f} m, height {overall['height_m']:.4f} m, resolution {1000 * align['resolution_m']:.2f} mm")
    suggested = summary.get("suggested") or {}
    for key in ("wing", "fuselage", "vtail", "sketch"):
        block = suggested.get(key)
        if not block:
            continue
        if key == "fuselage":
            print(f"  fuselage: length {block['length_m']} max w/h {block['max_width_m']}/{block['max_height_m']} stations {len(block['stations'])}")
        else:
            print(f"  {key}: " + ", ".join(f"{k}={v}" for k, v in block.items() if not isinstance(v, (list, dict))))
    for note in suggested.get("notes") or []:
        print(f"  note: {note}")
    for path in summary.get("written") or []:
        print(f"  wrote {path}")


def _compare(args: argparse.Namespace) -> int:
    from openair.cli import load_spec
    from openair.reference.compare import compare_reference

    concept, design_yaml, results_root = resolve_design(args.concept)
    phase_dir = results_root / args.phase
    geometry_json = phase_dir / "geometry.json"
    if not geometry_json.is_file():
        print(f"error: {geometry_json} not found; run python -m openair.geometry run first", file=sys.stderr)
        return 2
    with open(geometry_json, encoding="utf-8") as stream:
        geometry = json.load(stream)
    openvsp = geometry.get("openvsp") or {}
    stl = openvsp.get("stl")
    if not stl:
        print("error: geometry.json has no exported STL", file=sys.stderr)
        return 2
    spec_path = phase_dir / "design.yaml" if args.phase == "optimized" and (phase_dir / "design.yaml").exists() else design_yaml
    spec = load_spec(spec_path)
    result = compare_reference(
        spec,
        phase_dir,
        stl_path=stl,
        component_stls=(openvsp.get("mesh_checks") or {}).get("component_stls") or {},
        reference_dir=DESIGNS_DIR / concept / "reference",
    )
    if not result.get("available"):
        print(f"no reference model: {result.get('reason')}")
        return 1
    m2r = result["distance_model_to_reference"]
    print(f"reference fidelity for {concept}/{args.phase}: ok={result['ok']}")
    print(f"  model->reference p50 {1000 * m2r['p50_m']:.1f} mm, p95 {1000 * m2r['p95_m']:.1f} mm, max {1000 * m2r['max_m']:.1f} mm")
    for view, item in result["silhouettes"].items():
        print(f"  {view}: IoU {item['iou']:.3f}, reference-only {1e4 * item['reference_only_m2']:.1f} cm², model-only {1e4 * item['model_only_m2']:.1f} cm²")
    for name, stats in result["components"].items():
        if "p95_m" in stats:
            print(f"  {name}: p95 {1000 * stats['p95_m']:.1f} mm, mean {1000 * stats['mean_m']:.1f} mm")
    for key, check in result["checks"].items():
        basis = f" ({check['basis']})" if check.get("basis") else ""
        print(f"  check {key}{basis}: {check['got']:.4f} vs {check['limit']:.4f} -> {'ok' if check['ok'] else 'FAIL'}")
    if result.get("overlay"):
        print(f"  wrote {result['overlay']}")
    print(f"  wrote {result.get('json')}")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    configure_runtime()
    parser = argparse.ArgumentParser(prog="python -m openair.reference")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="align and measure a reference triangle mesh")
    ingest.add_argument("mesh", help="STL/PLY/OBJ/3MF/GLB triangle mesh")
    ingest.add_argument("--concept", required=True, help="concept name (designs/<name>)")
    ingest.add_argument("--units", choices=["mm", "cm", "m", "in"], help="length unit of the mesh (or from sidecar)")
    ingest.add_argument("--sidecar", help="path to a <stem>.reference.json sidecar (auto-detected by default)")
    ingest.add_argument("--axes", default=None, help="open-air axis <- signed source axis, e.g. 'x:-z,y:-x,z:+y' (default identity)")
    ingest.add_argument("--datum", choices=["root-chord", "body-axis"], default="root-chord")
    ingest.add_argument("--expect-span-m", type=float, default=None, help="anchor span for the unit cross-check")
    ingest.add_argument("--anchor-tolerance", type=float, default=0.03)
    ingest.add_argument("--target-faces", type=int, default=150000)
    ingest.add_argument("--mm-per-px", type=float, default=0.5)
    ingest.add_argument("--min-component-fraction", type=float, default=0.01, help="drop shells below this fraction of the largest shell's area")
    ingest.add_argument("--fidelity-p95-mm", type=float, default=None, help="acceptance band for the geometry compare (default 15 mm)")
    ingest.add_argument("--fidelity-iou", type=float, default=None, help="acceptance IoU for top/side silhouettes")
    ingest.add_argument("--out", default=None, help="output directory (default designs/<concept>/reference)")
    ingest.add_argument("--sketch-dir", default=None, help="where sketch-*.png go (default parent of --out)")
    ingest.add_argument("--dry-run", action="store_true", help="measure and write only the review figure")
    ingest.add_argument("--force", action="store_true", help="replace existing sketch-*.png")
    ingest.set_defaults(func=_ingest)

    compare = sub.add_parser("compare", help="score an exported OpenVSP artifact against the reference")
    compare.add_argument("concept", help="concept folder, name, or design YAML")
    compare.add_argument("--phase", choices=["baseline", "optimized"], default="baseline")
    compare.set_defaults(func=_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
