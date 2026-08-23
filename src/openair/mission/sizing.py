"""Conceptual sizing: close mass and 2-hour jet endurance."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

from openair.aero.drag_buildup import induced_cd, oswald_e, parasite_cd0
from openair.atmosphere import isa
from openair.io import dump_json
from openair.mission.engine import (
    fuel_fraction_for_endurance,
    operate,
)
from openair.mission.mass import closed_mass_breakdown
from openair.paths import results_dir_for
from openair.schemas import VehicleSpec
from openair.units import G0


def cruise_tas(spec: VehicleSpec, mtow_kg: float) -> tuple[float, float]:
    """Return (V, Mach) at the requested cruise CL, or the YAML cruise Mach."""
    atm = isa(spec.mission.cruise_altitude_m)
    s = spec.wing.area_m2
    w = mtow_kg * G0
    cl = spec.mission.cruise_cl
    q = w / (s * cl)
    v = math.sqrt(2.0 * q / atm.density_kg_m3)
    mach = v / atm.speed_of_sound_mps
    if spec.mission.cruise_mach > 0 and spec.mission.cruise_cl <= 0:
        v = spec.mission.cruise_mach * atm.speed_of_sound_mps
        mach = spec.mission.cruise_mach
    return v, mach


def aero_point(
    spec: VehicleSpec, mtow_kg: float, altitude_m: float, tas_mps: float
) -> dict[str, float]:
    atm = isa(altitude_m)
    q = 0.5 * atm.density_kg_m3 * tas_mps**2
    cl = (mtow_kg * G0) / (q * spec.wing.area_m2)
    buildup = parasite_cd0(spec, atm, tas_mps)
    e = oswald_e(spec)
    cdi = induced_cd(cl, spec.wing.aspect_ratio, e)
    cd = buildup.cd0_total + cdi
    drag = cd * q * spec.wing.area_m2
    lift = cl * q * spec.wing.area_m2
    lod = lift / max(drag, 1e-6)
    mach = tas_mps / atm.speed_of_sound_mps
    eng = operate(spec.engine, altitude_m, mach, drag)
    return {
        "tas_mps": tas_mps,
        "mach": mach,
        "cl": cl,
        "cd0": buildup.cd0_total,
        "cdi": cdi,
        "cd": cd,
        "oswald_e": e,
        "lift_n": lift,
        "drag_n": drag,
        "lod": lod,
        "q_pa": q,
        "thrust_avail_n": eng.thrust_available_n,
        "throttle": eng.throttle,
        "tsfc_weight_per_s": eng.tsfc_weight_per_s,
        "fuel_flow_kg_s": eng.fuel_flow_kg_s,
        "cd_components": buildup.cd_components,
    }


def max_dash_speed(spec: VehicleSpec, mtow_kg: float) -> dict[str, float]:
    """1-D search for the highest TAS with T >= D, capped at dash_mach_cap."""
    atm = isa(spec.mission.dash_altitude_m)
    v_min = 40.0
    v_max = spec.mission.dash_mach_cap * atm.speed_of_sound_mps
    best = aero_point(spec, mtow_kg, spec.mission.dash_altitude_m, v_min)
    # Binary search the highest V with T>=D
    lo, hi = v_min, v_max
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        pt = aero_point(spec, mtow_kg, spec.mission.dash_altitude_m, mid)
        if pt["thrust_avail_n"] >= pt["drag_n"]:
            lo = mid
            best = pt
        else:
            hi = mid
    best["tas_mps"] = lo
    best["mach"] = lo / atm.speed_of_sound_mps
    return best


def size_vehicle(spec: VehicleSpec) -> dict[str, Any]:
    fuel = spec.mass.fuel_mass_kg
    fixed_fuel = spec.mass.fuel_mass_mode == "fixed"
    endurance_applicable = spec.mission.endurance_required
    mtow = spec.mission.payload_kg + spec.engine.dry_mass_kg + fuel + 25.0
    history = []
    for it in range(1 if fixed_fuel else 40):
        masses = closed_mass_breakdown(spec, fuel, initial_mtow_kg=mtow)
        mtow = masses.mtow_kg
        v_c, _ = cruise_tas(spec, mtow)
        cruise = aero_point(spec, mtow, spec.mission.cruise_altitude_m, v_c)
        # Fuel to fly the requested endurance at this L/D and TSFC, plus reserve
        if endurance_applicable:
            ff = fuel_fraction_for_endurance(
                cruise["tsfc_weight_per_s"],
                cruise["lod"],
                spec.mission.endurance_s,
            )
            fuel_needed = ff * mtow / (1.0 - spec.mission.reserve_fuel_fraction)
        else:
            ff = 0.0
            fuel_needed = fuel
        if not fixed_fuel:
            fuel = 0.5 * fuel + 0.5 * fuel_needed
            fuel = min(max(fuel, 2.0), 80.0)
        history.append(
            {
                "iter": it,
                "mtow_kg": mtow,
                "fuel_kg": fuel,
                "fuel_needed_kg": fuel_needed,
                "fuel_mass_mode": spec.mass.fuel_mass_mode,
                "lod": cruise["lod"],
                "fuel_fraction_mission": ff,
            }
        )
        if fixed_fuel or (abs(fuel - fuel_needed) < 0.15 and it > 4):
            break

    masses = closed_mass_breakdown(spec, fuel, initial_mtow_kg=mtow)
    mtow = masses.mtow_kg
    v_c, m_c = cruise_tas(spec, mtow)
    cruise = aero_point(spec, mtow, spec.mission.cruise_altitude_m, v_c)
    dash = max_dash_speed(spec, mtow)
    from openair.mission.engine import breguet_endurance_s

    wi_wf = mtow / max(mtow - (fuel - masses.reserve_fuel_kg), 1.0)
    endurance = (
        breguet_endurance_s(
            cruise["tsfc_weight_per_s"],
            cruise["lod"],
            wi_wf,
        )
        if endurance_applicable
        else 0.0
    )

    # Packing: fuel volume vs available fuselage tank volume
    fuel_vol = fuel / spec.engine.fuel_density_kg_m3
    from openair.geometry.packing import packing_report

    pack = packing_report(spec, fuel_kg=fuel)

    from openair.mission.balance import balance_report

    bal = balance_report(spec, mtow, fuel)
    balance_deferred = bool(
        spec.solver.stability_method == "hybrid_component"
        and (
            spec.solver.wing_body_np_mac is None
            or spec.solver.wing_body_cl_alpha_per_deg is None
        )
    )

    sized_spec = spec.model_copy(deep=True)
    sized_spec.mass.fuel_mass_kg = float(fuel)

    return {
        "ok": (
            (not endurance_applicable or endurance >= 0.95 * spec.mission.endurance_s)
            and pack["ok"]
            and cruise["thrust_avail_n"] >= cruise["drag_n"]
            and (bal.in_band or balance_deferred)
            and bal.stall_ok
        ),
        "balance_deferred_to_component_analysis": balance_deferred,
        "balance": bal.as_dict(),
        "mtow_kg": mtow,
        "fuel_kg": fuel,
        "fuel_volume_m3": fuel_vol,
        "masses": masses.as_dict(),
        "cruise": {k: v for k, v in cruise.items() if k != "cd_components"}
        | {"cd_components": cruise["cd_components"]},
        "dash": {k: v for k, v in dash.items() if k != "cd_components"},
        "endurance_s": endurance,
        "endurance_hr": endurance / 3600.0,
        "endurance_applicable": endurance_applicable,
        "wing_area_m2": spec.wing.area_m2,
        "aspect_ratio": spec.wing.aspect_ratio,
        "span_m": spec.wing.span_m,
        "n_ult": spec.n_ult,
        "packing": pack,
        "history": history[-8:],
        "sized_spec": sized_spec.model_dump(mode="python"),
    }


def write_sized_yaml(case_path: Path, sized_spec: VehicleSpec) -> Path:
    out = results_dir_for(case_path) / "target_sized.yaml"
    with open(out, "w", encoding="utf-8") as f:
        yaml.safe_dump(sized_spec.model_dump(mode="python"), f, sort_keys=False)
    return out


def load_sized_spec(case_path: Path, fallback: VehicleSpec) -> VehicleSpec:
    """Overlay ONLY the quantity sizing closes (fuel mass) onto the case spec.

    The overlay used to replace the whole spec, so edits to the case YAML were
    silently shadowed by a stale results/<case>/target_sized.yaml (QA audit
    F13). The case file stays the single source of truth for geometry,
    stations, and bands.
    """
    if fallback.mass.fuel_mass_mode == "fixed":
        return fallback
    path = results_dir_for(case_path) / "target_sized.yaml"
    if not path.exists():
        return fallback
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    spec = fallback.model_copy(deep=True)
    fuel = (
        ((data.get("mass") or {}).get("fuel_mass_kg"))
        if isinstance(data, dict)
        else None
    )
    if isinstance(fuel, (int, float)) and fuel > 0:
        spec.mass.fuel_mass_kg = float(fuel)
    return spec


def run_sizing_stage(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    result = size_vehicle(spec)
    sized = VehicleSpec.model_validate(result["sized_spec"])
    yaml_path = outdir / "target_sized.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(sized.model_dump(mode="python"), f, sort_keys=False)
    dump_json(outdir / "mass_breakdown.json", result["masses"])
    return result
