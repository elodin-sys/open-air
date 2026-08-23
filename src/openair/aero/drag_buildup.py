"""Component drag buildup (Raymer / Hoerner style, conceptual fidelity)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from openair.atmosphere import Atmosphere, reynolds_per_m
from openair.geometry.fuselage import (
    fuselage_profile,
    fuselage_section_shape,
    section_perimeter_m,
)
from openair.schemas import VehicleSpec


@dataclass
class DragBuildup:
    cd0_total: float
    cd_components: dict[str, float] = field(default_factory=dict)
    swet_m2: dict[str, float] = field(default_factory=dict)
    form_factors: dict[str, float] = field(default_factory=dict)
    cf: dict[str, float] = field(default_factory=dict)


def _turbulent_cf(re: float, mach: float) -> float:
    """Schlichting / Raymer flat-plate Cf with a simple compressibility factor."""
    re = max(re, 1.0e5)
    cf = 0.455 / (math.log10(re) ** 2.58)
    cf *= 1.0 / (1.0 + 0.144 * mach**2) ** 0.65
    return cf


def section_profile_cd0(
    reynolds: float,
    t_over_c: float,
    mach: float = 0.0,
) -> float:
    """Smooth fully turbulent 2-D profile-drag estimate at zero lift.

    This is the section analogue of the flat-plate skin-friction and thickness
    form factor used by the component buildup. It intentionally has no
    transition or laminar-separation-bubble model.
    """
    form_factor = 1.0 + 0.6 / 0.3 * t_over_c + 100.0 * t_over_c**4
    return 2.0 * _turbulent_cf(reynolds, mach) * form_factor


def fuselage_wetted_area(spec: VehicleSpec) -> float:
    """Approximate skin area from the lofted section perimeter."""
    f = spec.fuselage
    if f.stations is not None:
        profile = fuselage_profile(spec)
        area = 0.0
        for left, right in zip(profile, profile[1:]):
            left_perimeter = section_perimeter_m(fuselage_section_shape(spec, left[0]))
            right_perimeter = section_perimeter_m(
                fuselage_section_shape(spec, right[0])
            )
            centerline_distance = math.hypot(
                right[0] - left[0],
                right[3] - left[3],
            )
            area += 0.5 * (left_perimeter + right_perimeter) * centerline_distance
        return area
    a = 0.5 * f.length_m
    b = 0.5 * f.max_width_m
    c = 0.5 * f.max_height_m
    # Knud Thomsen approximation
    p = 1.6075
    return (
        4.0 * math.pi * ((a**p * b**p + a**p * c**p + b**p * c**p) / 3.0) ** (1.0 / p)
    )


def wing_wetted_area(spec: VehicleSpec) -> float:
    # Exposed wing minus a crude fuselage carry-through
    exposed_span = max(
        spec.wing.span_m - spec.fuselage.max_width_m, 0.4 * spec.wing.span_m
    )
    exposed_s = spec.wing.area_m2 * (exposed_span / spec.wing.span_m)
    return 2.0 * exposed_s * (1.0 + 0.2 * spec.wing.t_over_c)


def tail_wetted_area(spec: VehicleSpec) -> float:
    sv = spec.vtail.count * spec.vtail.area_m2
    sh = spec.htail.area_m2
    return 2.0 * sv * (1.0 + 0.2 * spec.vtail.t_over_c) + 2.0 * sh * (
        1.0 + 0.2 * spec.htail.t_over_c
    )


def parasite_cd0(spec: VehicleSpec, atm: Atmosphere, tas_mps: float) -> DragBuildup:
    """CD0 referenced to wing planform area S_ref."""
    sref = max(spec.wing.area_m2, 1e-6)
    mach = tas_mps / atm.speed_of_sound_mps
    re_m = reynolds_per_m(atm, tas_mps)

    parts: dict[str, float] = {}
    swet: dict[str, float] = {}
    ff: dict[str, float] = {}
    cfs: dict[str, float] = {}

    # Fuselage
    sw_f = fuselage_wetted_area(spec)
    f_len = spec.fuselage.length_m
    f_dia = math.sqrt(spec.fuselage.max_width_m * spec.fuselage.max_height_m)
    fineness = f_len / max(f_dia, 1e-3)
    ff_f = 1.0 + 60.0 / fineness**3 + fineness / 400.0
    cf_f = _turbulent_cf(re_m * f_len, mach)
    parts["fuselage"] = cf_f * ff_f * sw_f / sref
    swet["fuselage"] = sw_f
    ff["fuselage"] = ff_f
    cfs["fuselage"] = cf_f

    # Wing (also counted in OAS viscous; we keep a buildup for sizing and CD0 seed)
    sw_w = wing_wetted_area(spec)
    tc = spec.wing.t_over_c
    sweep = math.radians(spec.wing.le_sweep_deg)
    ff_w = (1.0 + 0.6 / 0.3 * tc + 100.0 * tc**4) * (
        1.34 * mach**0.18 * (math.cos(sweep) ** 0.28)
    )
    cf_w = _turbulent_cf(re_m * spec.wing.mac_m, mach)
    parts["wing"] = cf_w * ff_w * sw_w / sref
    swet["wing"] = sw_w
    ff["wing"] = ff_w
    cfs["wing"] = cf_w

    # One or two verticals + optional HT
    sw_t = tail_wetted_area(spec)
    ff_t = 1.0 + 0.6 / 0.3 * spec.vtail.t_over_c + 100.0 * spec.vtail.t_over_c**4
    cf_t = _turbulent_cf(re_m * spec.vtail.root_chord_m, mach)
    parts["tails"] = cf_t * ff_t * sw_t / sref
    swet["tails"] = sw_t
    ff["tails"] = ff_t
    cfs["tails"] = cf_t

    # Propulsion installation. Internal turbojets retain the historical buried
    # inlet/nozzle allowance. External nacelles scale with their actual wetted
    # and frontal areas, avoiding an absolute CD penalty that does not scale
    # from a 3 m UAV to a 37 m transport.
    if spec.engine.installation == "external":
        count = spec.engine.installation_count
        nacelle_wetted = count * math.pi * spec.engine.diameter_m * spec.engine.length_m
        nacelle_fineness = spec.engine.length_m / spec.engine.diameter_m
        nacelle_ff = 1.0 + 0.35 / max(nacelle_fineness, 1.0)
        nacelle_cf = _turbulent_cf(re_m * spec.engine.length_m, mach)
        frontal_area = count * math.pi * (0.5 * spec.engine.diameter_m) ** 2
        parts["base_inlet"] = (
            nacelle_cf * nacelle_ff * nacelle_wetted / sref
            + spec.engine.nacelle_frontal_cd * frontal_area / sref
        )
        swet["nacelles"] = nacelle_wetted
        ff["nacelles"] = nacelle_ff
        cfs["nacelles"] = nacelle_cf
    else:
        parts["base_inlet"] = (
            0.006 + 0.004 * (spec.engine.diameter_m / max(f_dia, 1e-3)) ** 2
        )

    # Interference + protuberances (gear-up cruise)
    subtotal = sum(parts.values())
    parts["interference"] = spec.drag.interference_fraction * subtotal
    parts["protuberance"] = spec.drag.protuberance_cd0

    cd0 = sum(parts.values())
    return DragBuildup(
        cd0_total=cd0, cd_components=parts, swet_m2=swet, form_factors=ff, cf=cfs
    )


def induced_cd(cl: float, aspect_ratio: float, e: float = 0.82) -> float:
    return cl**2 / (math.pi * aspect_ratio * e)


def oswald_e(spec: VehicleSpec) -> float:
    """Kroo-ish sweep / AR correction, typical UAV band 0.75–0.90."""
    ar = spec.wing.aspect_ratio
    sweep = math.radians(spec.wing.le_sweep_deg)
    e = 1.78 * (1.0 - 0.045 * ar**0.68) - 0.64
    e *= math.cos(sweep) ** 0.15
    return min(max(e, 0.70), 0.92)
