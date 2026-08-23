from openair.cli import stage_main
from openair.geometry.openvsp_model import run_geometry_stage

if __name__ == "__main__":
    stage_main("geometry", run_geometry_stage)
