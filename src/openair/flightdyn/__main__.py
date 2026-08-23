import argparse
import json
import sys
from pathlib import Path

from openair.cli import stage_main
from openair.flightdyn.sixdof import replay_flightdyn
from openair.flightdyn.stage import run_flightdyn_stage


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        parser = argparse.ArgumentParser()
        parser.add_argument("command", choices=["replay"])
        parser.add_argument("flightdyn_json", type=Path)
        parser.add_argument("controls_csv", type=Path)
        parser.add_argument("outdir", type=Path)
        parser.add_argument("--dt", type=float, default=0.01)
        args = parser.parse_args()
        result = replay_flightdyn(
            args.flightdyn_json,
            args.controls_csv,
            args.outdir,
            dt_s=args.dt,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(0 if result.get("ok") else 1)
    stage_main("flightdyn", run_flightdyn_stage)
