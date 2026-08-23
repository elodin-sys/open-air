from openair.cli import stage_main
from openair.aero.oas_backend import run_aero_stage

if __name__ == "__main__":
    stage_main("aero", run_aero_stage)
