from openair.cli import stage_main
from openair.mission.sizing import run_sizing_stage

if __name__ == "__main__":
    stage_main("sizing", run_sizing_stage)
