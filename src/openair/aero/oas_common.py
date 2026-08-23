"""Shared OpenAeroStruct surface dictionaries and flight-condition helpers."""

from __future__ import annotations

import numpy as np

from openair.aero.drag_buildup import parasite_cd0
from openair.atmosphere import isa, reynolds_per_m
from openair.geometry.mesh import (
    generate_oas_htail_rect_mesh,
    generate_oas_rect_mesh,
    naca4_coords,
)
from openair.schemas import VehicleSpec


def flight_state(
    spec: VehicleSpec, altitude_m: float, tas_mps: float
) -> dict[str, float]:
    atm = isa(altitude_m)
    return {
        "v": tas_mps,
        "rho": atm.density_kg_m3,
        "Mach_number": tas_mps / atm.speed_of_sound_mps,
        "re": reynolds_per_m(atm, tas_mps),
        "speed_of_sound": atm.speed_of_sound_mps,
        "altitude_m": altitude_m,
    }


def extra_cd0(spec: VehicleSpec, altitude_m: float, tas_mps: float) -> float:
    """Fuselage + tails + base, excluding wing (OAS viscous covers the wing)."""
    atm = isa(altitude_m)
    bu = parasite_cd0(spec, atm, tas_mps)
    parts = bu.cd_components
    return (
        parts.get("fuselage", 0.0)
        + parts.get("tails", 0.0)
        + parts.get("base_inlet", 0.0)
        + parts.get("interference", 0.0)
        + parts.get("protuberance", 0.0)
    )


def oas_shear_for_le_sweep_deg(
    root_chord_m: float,
    taper: float,
    span_m: float,
    le_sweep_deg: float,
) -> float:
    """Convert a requested LE sweep to OAS's post-taper x-shear angle.

    OAS tapers its rectangular seed about the quarter-chord before applying
    ``sweep`` as a spanwise x shear. Passing LE sweep directly therefore adds
    the taper-induced quarter-chord offset a second time.
    """
    semispan = 0.5 * span_m
    taper_le_offset = 0.25 * root_chord_m * (1.0 - taper)
    wanted_le_offset = semispan * np.tan(np.radians(le_sweep_deg))
    return float(np.degrees(np.arctan2(wanted_le_offset - taper_le_offset, semispan)))


def wing_surface_dict(spec: VehicleSpec, *, aero_only: bool, cd0_extra: float) -> dict:
    mesh = generate_oas_rect_mesh(spec)
    coords = naca4_coords(spec.wing.airfoil)
    ncp = 3
    twist = np.linspace(spec.wing.twist_tip_deg, spec.wing.twist_root_deg, ncp)
    # OAS symmetry mesh is tip -> root, so twist_cp[0] is tip
    surf: dict = {
        "name": "wing",
        "symmetry": True,
        "S_ref_type": "projected",
        "mesh": mesh,
        "taper": spec.wing.taper,
        "sweep": oas_shear_for_le_sweep_deg(
            spec.wing.root_chord_m,
            spec.wing.taper,
            spec.wing.span_m,
            spec.wing.le_sweep_deg,
        ),
        "dihedral": spec.wing.dihedral_deg,
        "twist_cp": twist,
        "t_over_c_cp": np.array(
            [spec.wing.t_over_c, spec.wing.t_over_c, spec.wing.t_over_c]
        ),
        "CL0": 0.0,
        "CD0": float(cd0_extra),
        "k_lam": 0.05,
        "c_max_t": coords["x_max_t"],
        "with_viscous": spec.solver.oas_with_viscous,
        "with_wave": spec.solver.oas_with_wave,
    }
    if aero_only:
        return surf

    mat = spec.structures.material
    surf.update(
        {
            "fem_model_type": spec.structures.fem_model_type,
            "E": mat.E_pa,
            "G": mat.G_pa,
            "yield": mat.yield_pa,
            "safety_factor": spec.mission.safety_factor,
            "mrho": mat.density_kg_m3,
            "fem_origin": 0.35,
            "wing_weight_ratio": spec.structures.wing_weight_ratio,
            "exact_failure_constraint": False,
            "struct_weight_relief": True,
            "distributed_fuel_weight": False,
        }
    )
    if spec.structures.fem_model_type == "wingbox":
        tskin = spec.structures.skin_thickness_m
        tspar = spec.structures.spar_thickness_m
        surf.update(
            {
                "data_x_upper": coords["upper_x"],
                "data_x_lower": coords["lower_x"],
                "data_y_upper": coords["upper_y"],
                "data_y_lower": coords["lower_y"],
                "original_wingbox_airfoil_t_over_c": coords["t_over_c"],
                "spar_thickness_cp": np.array([tspar * 0.7, tspar * 0.85, tspar]),
                "skin_thickness_cp": np.array([tskin * 0.7, tskin * 0.85, tskin]),
                "strength_factor_for_upper_skin": 1.0,
            }
        )
    else:
        r = spec.structures.tube_radius_m
        t = spec.structures.tube_thickness_m
        surf.update(
            {
                "radius_cp": np.ones(4) * r,
                "thickness_cp": np.array([t * 0.7, t * 0.85, t]),
            }
        )
    return surf


def htail_surface_dict(spec: VehicleSpec) -> dict:
    """Aerodynamic-only symmetric tail surface for fallback pitch control."""
    incidence = np.full(3, spec.htail.incidence_deg)
    return {
        "name": "htail",
        "symmetry": True,
        "S_ref_type": "projected",
        "mesh": generate_oas_htail_rect_mesh(spec),
        "taper": spec.htail.taper,
        "sweep": oas_shear_for_le_sweep_deg(
            spec.htail.root_chord_m,
            spec.htail.taper,
            spec.htail.span_m,
            spec.htail.le_sweep_deg,
        ),
        "dihedral": 0.0,
        "twist_cp": incidence,
        "t_over_c_cp": np.full(3, spec.htail.t_over_c),
        "CL0": 0.0,
        # Parasite tail drag already lives in the wing's extra-CD0 buildup.
        "CD0": 0.0,
        "k_lam": 0.05,
        "c_max_t": 0.30,
        "with_viscous": False,
        "with_wave": False,
    }
