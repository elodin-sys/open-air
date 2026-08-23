"""Analytic checks used by the validation suite and unit tests."""

from __future__ import annotations

import math

from openair.atmosphere import isa
from openair.mission.engine import (
    breguet_endurance_s,
    fuel_fraction_for_endurance,
    sea_level_tsfc_mass,
)
from openair.schemas import EngineSpec
from openair.units import G0


def elliptical_induced_drag(cl: float, aspect_ratio: float) -> float:
    return cl**2 / (math.pi * aspect_ratio)


def cantilever_tip_deflection(
    load_n: float, length_m: float, e_pa: float, i_m4: float
) -> float:
    """Tip deflection of a cantilever with uniform load totaling load_n: PL^3/(8EI)."""
    return load_n * length_m**3 / (8.0 * e_pa * i_m4)


def k450_tsfc_hand_calc() -> dict[str, float]:
    """Reproduce the spec-sheet TSFC from 1100 g/min at 45 kgf."""
    eng = EngineSpec()
    c_m = sea_level_tsfc_mass(eng)
    c_w = c_m * G0
    # traditional kg/(kgf·hr)
    kg_per_kgf_hr = (eng.fuel_flow_max_kg_s * 3600.0) / (eng.max_thrust_sl_n / G0)
    return {
        "tsfc_mass_kg_per_n_s": c_m,
        "tsfc_weight_per_s": c_w,
        "tsfc_kg_per_kgf_hr": kg_per_kgf_hr,
        "expected_kg_per_kgf_hr": 1.4667,
    }


def breguet_round_trip() -> dict[str, float]:
    """Invert endurance -> fuel fraction -> endurance."""
    c = 0.00045
    lod = 10.0
    e = 7200.0
    ff = fuel_fraction_for_endurance(c, lod, e)
    wi_wf = 1.0 / (1.0 - ff)
    e2 = breguet_endurance_s(c, lod, wi_wf)
    return {"fuel_fraction": ff, "endurance_s": e2, "target_s": e}


def isa_sl_check() -> dict[str, float]:
    sl = isa(0.0)
    return {
        "T": sl.temperature_k,
        "p": sl.pressure_pa,
        "rho": sl.density_kg_m3,
        "a": sl.speed_of_sound_mps,
    }
