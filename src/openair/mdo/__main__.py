from pathlib import Path

from openair.cli import load_spec
from openair.io import dump_stage
from openair.mission.sizing import load_sized_spec
from openair.mdo.problem import run_mdo_stage
from openair.paths import configure_runtime, resolve_design, results_dir_for

if __name__ == "__main__":
    configure_runtime()
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("design", type=Path)
    args = parser.parse_args()
    _, design_yaml, _ = resolve_design(args.design)
    spec = load_sized_spec(design_yaml, load_spec(design_yaml))
    outdir = results_dir_for(design_yaml)
    payload = run_mdo_stage(spec, outdir, design_yaml)
    path = dump_stage(design_yaml, "mdo", payload)
    print(f"wrote {path}")
