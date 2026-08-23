from pathlib import Path

from openair.cli import load_spec
from openair.io import dump_stage
from openair.mission.sizing import load_sized_spec
from openair.paths import configure_runtime, resolve_design, results_dir_for
from openair.reporting.presentation import build_presentation
from openair.reporting.report import run_report_stage

if __name__ == "__main__":
    configure_runtime()
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "present"])
    parser.add_argument("design", type=Path)
    args = parser.parse_args()
    _, design_yaml, _ = resolve_design(args.design)
    if args.command == "present":
        products = build_presentation(design_yaml)
        print(f"wrote {products['html']}")
        print(f"wrote {products['pdf']}")
    else:
        spec = load_sized_spec(design_yaml, load_spec(design_yaml))
        payload = run_report_stage(spec, results_dir_for(design_yaml), design_yaml)
        print(dump_stage(design_yaml, "report", payload))
