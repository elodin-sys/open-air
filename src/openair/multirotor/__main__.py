"""CLI for the baseline-only multirotor pipeline."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from openair.io import load_yaml
from openair.multirotor.ingest import ingest_multirotor_reference
from openair.multirotor.schema import MultirotorSpec
from openair.paths import configure_runtime, resolve_design


def main(argv: list[str] | None = None) -> int:
    configure_runtime()
    parser = argparse.ArgumentParser(prog="python -m openair.multirotor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest = subparsers.add_parser(
        "ingest", help="segment and measure one assembled reference mesh"
    )
    ingest.add_argument("mesh", type=Path)
    ingest.add_argument(
        "--concept",
        type=Path,
        required=True,
        help="multirotor concept folder or design.yaml",
    )
    run = subparsers.add_parser("run", help="run the multirotor baseline pipeline")
    run.add_argument("design", type=Path)
    verify = subparsers.add_parser(
        "verify", help="run the package in the pinned isolated Elodin runtime"
    )
    verify.add_argument("design", type=Path)
    args = parser.parse_args(argv)

    design_argument = args.concept if args.command == "ingest" else args.design
    _, design_path, _ = resolve_design(design_argument)
    spec = MultirotorSpec.model_validate(load_yaml(design_path))
    if args.command == "ingest":
        result = ingest_multirotor_reference(
            spec,
            design_path,
            args.mesh,
        )
        print(f"wrote {result['reference']}")
        print(
            f"airframe: {result['faces']:,} faces, "
            f"extents {[round(value, 4) for value in result['extents_m']]} m"
        )
        print(
            "motors: "
            + ", ".join(
                str([round(value, 4) for value in position])
                for position in result["motor_positions_geometry_m"]
            )
        )
        print(f"propeller diameter: {result['prop_diameter_m']:.4f} m")
        return 0
    if args.command == "verify":
        from openair.multirotor.elodin_verify import verify_multirotor_package
        from openair.paths import results_dir_for

        outdir = results_dir_for(design_path)
        output = outdir / "elodin_verification.json"
        result = verify_multirotor_package(outdir / "elodin_package", output)
        print(
            f"wrote {output} "
            f"(terminal error {result['checks']['terminal_relative_error']:.3%})"
        )
        return 0

    from openair.multirotor.pipeline import run_multirotor_pipeline

    products = run_multirotor_pipeline(
        design_path,
        clean=True,
        pipeline_run_id=uuid.uuid4().hex,
    )
    print(f"wrote {products['package_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
