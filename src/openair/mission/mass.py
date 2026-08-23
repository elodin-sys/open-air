"""Transparent empty-mass buildup for a small turbojet UAV."""

from __future__ import annotations

from dataclasses import dataclass, asdict

from openair.aero.drag_buildup import fuselage_wetted_area
from openair.schemas import VehicleSpec


@dataclass
class MassBreakdown:
    payload_kg: float
    engine_kg: float
    fuel_kg: float
    reserve_fuel_kg: float
    wing_kg: float
    fuselage_kg: float
    vtail_kg: float
    htail_kg: float
    systems_kg: float
    avionics_kg: float
    landing_gear_kg: float
    fuel_system_kg: float
    contingency_kg: float
    empty_kg: float
    mtow_kg: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def wing_mass_regression_kg(spec: VehicleSpec, mtow_kg: float) -> float:
    """Legacy Raymer-style sanity estimate, retained only as a cross-check.

    W_wing ~ S^0.76 * AR^0.55 * (n_ult W)^0.40 * (t/c)^-0.3
    Coefficient 0.14 is calibrated so the 3.8 m / 2.9 m^2 aluminum wing on a
    ~100 kg, 6g-ultimate UAV weighs ~9-10 kg (8-12% of MTOW, typical band).
    The first-run coefficient (0.028) produced a 1.9 kg wing — 10x light —
    which made every MTOW and endurance closure optimistic (QA audit F9).
    """
    s = spec.wing.area_m2
    ar = spec.wing.aspect_ratio
    tc = max(spec.wing.t_over_c, 0.06)
    n = spec.n_ult
    return 0.14 * (s**0.76) * (ar**0.55) * ((n * mtow_kg) ** 0.40) * (0.12 / tc) ** 0.30


def wing_panel_mass_components(spec: VehicleSpec) -> dict[str, float]:
    """Gauge-aware material buildup matching the OAS wingbox idealization.

    The box occupies 50% of local chord. Its top and bottom skins therefore
    total one full planform area. Two spar webs each integrate the local box
    depth ``t/c * chord`` over the full span. ``wing_weight_ratio`` carries
    ribs, fasteners, overlaps, and other material omitted by the ideal box.
    """
    area = spec.wing.area_m2
    skin_area = 2.0 * 0.50 * area
    spar_web_area = 2.0 * spec.wing.t_over_c * area
    skin_volume = skin_area * spec.structures.skin_thickness_m
    spar_volume = spar_web_area * spec.structures.spar_thickness_m
    density = spec.structures.material.density_kg_m3
    ratio = spec.structures.wing_weight_ratio
    return {
        "skin_area_m2": skin_area,
        "spar_web_area_m2": spar_web_area,
        "skin_volume_m3": skin_volume,
        "spar_volume_m3": spar_volume,
        "material_mass_kg": (skin_volume + spar_volume) * density,
        "wing_weight_ratio": ratio,
        "total_kg": (skin_volume + spar_volume) * density * ratio,
    }


def wing_mass_kg(spec: VehicleSpec, mtow_kg: float) -> float:
    """Primary gauge-aware wing mass used by sizing, balance, and MDO.

    ``mtow_kg`` remains in the signature for compatibility with the legacy
    regression and callers. The panel mass is driven by geometry, gauges,
    material density, and the same weight ratio used by OAS.
    """
    override = spec._wing_mass_override_kg
    if override is not None:
        if override <= 0:
            raise ValueError("closed wing-mass override must be positive")
        return float(override)
    del mtow_kg
    return wing_panel_mass_components(spec)["total_kg"]


def fuselage_mass_kg(spec: VehicleSpec, mtow_kg: float) -> float:
    """Skin + frames as a fraction of a notional aluminum shell, plus payload floor."""
    swet = fuselage_wetted_area(spec)
    t_skin = 0.0012  # m, typical small-UAV aluminum / composite equivalent
    shell = swet * t_skin * spec.structures.material.density_kg_m3 * 0.55
    frames = 0.025 * mtow_kg
    return shell + frames + 1.5  # 1.5 kg engine mount / firewall


def tail_mass_kg(spec: VehicleSpec) -> tuple[float, float]:
    sv = spec.vtail.count * spec.vtail.area_m2
    sh = spec.htail.area_m2
    w_v = 4.8 * sv**0.9
    w_h = 4.2 * sh**0.9 if sh > 0 else 0.0
    return w_v, w_h


def breakdown(spec: VehicleSpec, mtow_kg: float, fuel_kg: float) -> MassBreakdown:
    if spec.mass.operating_empty_mass_kg is not None:
        # Reference/reproduction mode: preserve the audited operating-empty
        # mass instead of applying small-UAV shell, tail and gauge regressions
        # outside their domain. The installed-engine line remains visible and
        # the balance is carried as an explicitly lumped systems residual.
        empty = float(spec.mass.operating_empty_mass_kg)
        engine = float(spec.engine.dry_mass_kg)
        if engine > empty:
            raise ValueError(
                "reference operating-empty mass is below installed engine mass"
            )
        reserve = spec.mission.reserve_fuel_fraction * fuel_kg
        return MassBreakdown(
            payload_kg=spec.mission.payload_kg,
            engine_kg=engine,
            fuel_kg=fuel_kg,
            reserve_fuel_kg=reserve,
            wing_kg=0.0,
            fuselage_kg=0.0,
            vtail_kg=0.0,
            htail_kg=0.0,
            systems_kg=empty - engine,
            avionics_kg=0.0,
            landing_gear_kg=0.0,
            fuel_system_kg=0.0,
            contingency_kg=0.0,
            empty_kg=empty,
            mtow_kg=empty + spec.mission.payload_kg + fuel_kg,
        )

    w_wing = wing_mass_kg(spec, mtow_kg)
    w_fuse = fuselage_mass_kg(spec, mtow_kg)
    w_v, w_h = tail_mass_kg(spec)
    reserve = spec.mission.reserve_fuel_fraction * fuel_kg
    w_sys = spec.mass.systems_kg
    w_avion = spec.mass.avionics_kg
    w_gear = spec.mass.landing_gear_fraction * mtow_kg
    w_fsys = 0.08 * fuel_kg + 0.4
    empty_wo_cont = (
        w_wing
        + w_fuse
        + w_v
        + w_h
        + w_sys
        + w_avion
        + w_gear
        + w_fsys
        + spec.engine.dry_mass_kg
    )
    cont = spec.mass.contingency_fraction * empty_wo_cont
    empty = empty_wo_cont + cont
    mtow = empty + spec.mission.payload_kg + fuel_kg
    return MassBreakdown(
        payload_kg=spec.mission.payload_kg,
        engine_kg=spec.engine.dry_mass_kg,
        fuel_kg=fuel_kg,
        reserve_fuel_kg=reserve,
        wing_kg=w_wing,
        fuselage_kg=w_fuse,
        vtail_kg=w_v,
        htail_kg=w_h,
        systems_kg=w_sys,
        avionics_kg=w_avion,
        landing_gear_kg=w_gear,
        fuel_system_kg=w_fsys,
        contingency_kg=cont,
        empty_kg=empty,
        mtow_kg=mtow,
    )


def closed_mass_breakdown(
    spec: VehicleSpec,
    fuel_kg: float,
    *,
    initial_mtow_kg: float | None = None,
    tolerance_kg: float = 1e-8,
    max_iterations: int = 50,
) -> MassBreakdown:
    """Close MTOW-dependent component masses to a fixed point.

    ``breakdown`` evaluates components at a supplied MTOW; fuselage frames,
    landing gear, and contingency therefore make one call only an iteration,
    not a closed vehicle. All headline/stage calculations use this helper so
    the MDO, aero, structures, validation, and report describe the same mass.
    """
    if spec.mass.operating_empty_mass_kg is not None:
        return breakdown(
            spec,
            spec.mass.operating_empty_mass_kg + spec.mission.payload_kg + fuel_kg,
            fuel_kg,
        )

    mtow = (
        float(initial_mtow_kg)
        if initial_mtow_kg is not None
        else spec.mission.payload_kg + spec.engine.dry_mass_kg + float(fuel_kg) + 25.0
    )
    if mtow <= 0.0:
        raise ValueError("initial MTOW must be positive")
    for _ in range(max_iterations):
        masses = breakdown(spec, mtow, fuel_kg)
        if abs(masses.mtow_kg - mtow) <= tolerance_kg:
            return breakdown(spec, masses.mtow_kg, fuel_kg)
        mtow = masses.mtow_kg
    raise RuntimeError(
        f"mass closure did not converge in {max_iterations} iterations "
        f"(last MTOW {mtow:.6f} kg)"
    )
