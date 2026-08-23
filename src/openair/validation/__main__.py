from pathlib import Path

from openair.cli import load_spec
from openair.io import dump_stage
from openair.paths import configure_runtime, results_dir_for
from openair.validation.runner import run_validation_stage

if __name__ == "__main__":
    configure_runtime()
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    spec = load_spec(args.case)
    from openair.mission.sizing import load_sized_spec

    spec = load_sized_spec(args.case, spec)
    payload = run_validation_stage(spec, results_dir_for(args.case), args.case)
    print(dump_stage(args.case, "validation", payload))
