from openair.paths import configure_runtime

configure_runtime()


def test_core_imports():
    import gmsh
    import meshio
    import openaerostruct
    import openmdao
    import openvsp
    import pydantic

    assert openmdao.__version__
    assert openaerostruct.__version__
    assert "OpenVSP" in openvsp.GetVSPVersion()
    assert gmsh.__version__
    assert meshio.__version__
    assert pydantic.VERSION


def test_tiny_oas_vlm():
    import numpy as np
    import openmdao.api as om
    from openaerostruct.aerodynamics.aero_groups import AeroPoint
    from openaerostruct.geometry.geometry_group import Geometry
    from openaerostruct.meshing.mesh_generator import generate_mesh

    mesh = generate_mesh(
        {
            "num_y": 7,
            "num_x": 3,
            "wing_type": "rect",
            "symmetry": True,
            "span": 4.0,
            "root_chord": 0.5,
        }
    )
    surf = {
        "name": "wing",
        "symmetry": True,
        "S_ref_type": "projected",
        "mesh": mesh,
        "CL0": 0.0,
        "CD0": 0.01,
        "k_lam": 0.05,
        "t_over_c_cp": np.array([0.12]),
        "c_max_t": 0.3,
        "with_viscous": True,
        "with_wave": False,
    }
    prob = om.Problem()
    iv = om.IndepVarComp()
    iv.add_output("v", val=50.0, units="m/s")
    iv.add_output("alpha", val=3.0, units="deg")
    iv.add_output("Mach_number", val=0.15)
    iv.add_output("re", val=1e6, units="1/m")
    iv.add_output("rho", val=1.225, units="kg/m**3")
    iv.add_output("cg", val=np.zeros(3), units="m")
    prob.model.add_subsystem("iv", iv, promotes=["*"])
    prob.model.add_subsystem("wing", Geometry(surface=surf))
    prob.model.add_subsystem(
        "aero",
        AeroPoint(surfaces=[surf]),
        promotes_inputs=["v", "alpha", "Mach_number", "re", "rho", "cg"],
    )
    prob.model.connect("wing.mesh", "aero.wing.def_mesh")
    prob.model.connect("wing.mesh", "aero.aero_states.wing_def_mesh")
    prob.model.connect("wing.t_over_c", "aero.wing_perf.t_over_c")
    prob.setup()
    prob.run_model()
    cl = float(np.ravel(prob.get_val("aero.CL"))[0])
    cd = float(np.ravel(prob.get_val("aero.CD"))[0])
    assert cl > 0.05
    assert cd > 0.0
