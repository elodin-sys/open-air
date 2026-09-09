"""Weight & balance, neutral point, pitch trim, and stall.

Tailless concepts trim with sweep and washout. Conventional-tail and
source-reproduction cases use explicit tail incidence and may use same-run
VSPAERO wing-body-nacelle constants. This module makes those assumptions
explicit:

- component CG buildup with documented station assumptions
- wing/body neutral point = 25% MAC + a sweep-scaled `solver.np_shift_mac`, or
  an opt-in same-run VSPAERO component result; an explicit horizontal tail is
  then combined by lift-curve-slope weighting
- static margin at full fuel and at reserve fuel (CG travel)
- washout required to trim: Cm_np(washout) + cm_ac(section) = SM * CL_cruise,
  with sweep-scaled `solver.cm_washout_per_deg` (OAS-calibrated at the sketch
  target; its sign reverses between aft and forward sweep)
- stall speed from a declared aircraft CLmax or a documented section-to-wing
  conversion (an assumption, not test data)

Station assumptions (fractions of fuselage length L unless noted):
  payload    bay center (spec field)
  engine     L - 0.20 (tailpipe) - engine_length/2
  wing mass  x_le_mac + 0.40 MAC
  fuselage   0.50 L (pointed nose is light; boat-tail, engine mounts and fin
             attach fittings bias the shell aft)
  fin(s)     vtail x_le + 0.5 root chord
  systems    at the fuselage fuel tank (pumps, valves, actuators)
  avionics   0.50 L (racked near the CG; only a small sensor in the nose)
  gear       0.58 L (nose + mains composite, mains just aft of CG)
  fuel sys   at the fuselage fuel tank
  contingency 0.50 L
  wing fuel  x_le_mac + 0.32 MAC (tanks span 10-55% chord, centroid held at
             the cruise CG so fuel burn barely moves the CG)
  fuselage fuel  spec.fuselage.fuel_tank_x_m (aft collector/feed tank)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from openair.aero.thin_airfoil import plain_flap_theory
from openair.controls import (
    elevon_travel_deg,
    pitch_control_surface,
    pitch_trim_control,
    te_down_deg,
)
from openair.geometry.packing import wing_tank_volume_m3
from openair.mission.mass import MassBreakdown, breakdown
from openair.schemas import ControlSurfaceSpec, VehicleSpec
from openair.units import G0


def thin_airfoil_props(naca4: str, n: int = 2000) -> dict[str, float]:
    """Thin-airfoil cm_ac and zero-lift alpha from a NACA 4-digit camber line.

    cm_ac = pi/4 (A2 - A1);  alpha_L0 = -(1/pi) integral dyc/dx (cos t - 1) dt.
    Returns zeros for symmetric sections.
    """
    m = int(naca4[0]) / 100.0
    p = int(naca4[1]) / 10.0
    if m == 0.0 or p == 0.0:
        return {"cm_ac": 0.0, "alpha_l0_deg": 0.0}
    theta = np.linspace(1e-6, math.pi - 1e-6, n)
    x = 0.5 * (1.0 - np.cos(theta))
    dyc = np.where(
        x < p,
        2.0 * m / p**2 * (p - x),
        2.0 * m / (1.0 - p) ** 2 * (p - x),
    )
    a1 = (2.0 / math.pi) * np.trapezoid(dyc * np.cos(theta), theta)
    a2 = (2.0 / math.pi) * np.trapezoid(dyc * np.cos(2.0 * theta), theta)
    cm_ac = (math.pi / 4.0) * (a2 - a1)
    alpha_l0 = -(1.0 / math.pi) * np.trapezoid(dyc * (np.cos(theta) - 1.0), theta)
    return {"cm_ac": float(cm_ac), "alpha_l0_deg": float(math.degrees(alpha_l0))}


def _sweep_calibration_ratio(spec: VehicleSpec) -> float:
    """Scale target-planform calibrations across the sketch sweep envelope.

    The longitudinal lever arm of a spanwise load perturbation scales to first
    order with tan(LE sweep). Concept-specific coefficients are measured at the
    sketch target sweep; legacy concepts use the original 32-degree reference.
    """
    reference_deg = spec.sketch.le_sweep_deg if spec.sketch is not None else 32.0
    reference = math.tan(math.radians(reference_deg))
    if abs(reference) < 1e-6:
        return 1.0
    return math.tan(math.radians(spec.wing.le_sweep_deg)) / reference


def neutral_point_x(spec: VehicleSpec) -> float:
    """Wing-only or wing-plus-tail neutral point."""
    w = spec.wing
    if spec.solver.wing_body_np_mac is not None:
        wing_ac = w.x_le_mac_m + spec.solver.wing_body_np_mac * w.mac_m
    else:
        shift = spec.solver.np_shift_mac * abs(_sweep_calibration_ratio(spec))
        wing_ac = w.x_le_mac_m + (0.25 + shift) * w.mac_m
    if spec.htail.span_m <= 0.05:
        return wing_ac
    tail = horizontal_tail_aero(spec)
    wing_weight = tail["wing_lift_slope_per_rad"] * w.area_m2
    tail_weight = (
        tail["dynamic_pressure_ratio"]
        * tail["tail_lift_slope_per_rad"]
        * (1.0 - tail["downwash_gradient"])
        * spec.htail.area_m2
    )
    return (wing_weight * wing_ac + tail_weight * tail["x_ac_m"]) / max(
        wing_weight + tail_weight, 1e-9
    )


def _lift_curve_slope_per_rad(aspect_ratio: float) -> float:
    """Finite-wing lift slope used by the conceptual wing+tail balance model."""
    ar = max(aspect_ratio, 0.2)
    return 2.0 * math.pi * ar / (2.0 + math.sqrt(4.0 + ar**2))


def horizontal_tail_aero(spec: VehicleSpec) -> dict[str, float]:
    """Documented low-order horizontal-tail geometry and effectiveness."""
    h = spec.htail
    taper = h.taper
    area = max(h.area_m2, 1e-9)
    mac = (2.0 / 3.0) * h.root_chord_m * (1.0 + taper + taper**2) / (1.0 + taper)
    y_mac = (h.span_m / 6.0) * (1.0 + 2.0 * taper) / (1.0 + taper)
    x_ac = h.x_le_m + y_mac * math.tan(math.radians(h.le_sweep_deg)) + 0.25 * mac
    wing_lift_slope = _lift_curve_slope_per_rad(spec.wing.aspect_ratio)
    if spec.solver.wing_body_cl_alpha_per_deg is not None:
        wing_lift_slope = spec.solver.wing_body_cl_alpha_per_deg * 180.0 / math.pi
    half_span = 0.5 * spec.wing.span_m
    tan_quarter = math.tan(math.radians(spec.wing.le_sweep_deg)) - 0.25 * (
        spec.wing.root_chord_m - spec.wing.tip_chord_m
    ) / max(half_span, 1e-9)
    quarter_sweep = math.atan(tan_quarter)
    # Prandtl's far-wake estimate d(epsilon)/d(alpha) = 2a/(pi*AR), with a
    # quarter-chord sweep correction and a bounded conceptual range.
    downwash_gradient = min(
        max(
            2.0
            * wing_lift_slope
            / (
                math.pi
                * max(spec.wing.aspect_ratio, 0.2)
                * max(math.cos(quarter_sweep), 0.2)
            ),
            0.0,
        ),
        0.75,
    )
    return {
        "area_m2": area,
        "mac_m": mac,
        "aspect_ratio": h.span_m**2 / area,
        "x_ac_m": x_ac,
        "wing_lift_slope_per_rad": wing_lift_slope,
        "tail_lift_slope_per_rad": _lift_curve_slope_per_rad(h.span_m**2 / area),
        # Conventional-tail conceptual default; OAS/VSPAERO verification remains
        # final. 0.80 is the conservative preliminary-design wake-loss factor.
        # A non-unity multiplier must carry an explicit source citation.
        "downwash_gradient": downwash_gradient,
        "dynamic_pressure_ratio": (0.80 * spec.solver.tail_lift_effectiveness_factor),
        "baseline_dynamic_pressure_ratio": 0.80,
        "tail_lift_effectiveness_factor": (spec.solver.tail_lift_effectiveness_factor),
        "tail_lift_effectiveness_source": (spec.solver.tail_lift_effectiveness_source),
    }


def aircraft_lift_curve_slope_per_deg(spec: VehicleSpec) -> float:
    """Full-aircraft lift slope on the main-wing reference area."""
    wing_slope = (
        spec.solver.wing_body_cl_alpha_per_deg
        if spec.solver.wing_body_cl_alpha_per_deg is not None
        else _lift_curve_slope_per_rad(spec.wing.aspect_ratio) * math.pi / 180.0
    )
    if spec.htail.span_m <= 0.05:
        return wing_slope
    tail = horizontal_tail_aero(spec)
    tail_contribution = (
        tail["dynamic_pressure_ratio"]
        * tail["tail_lift_slope_per_rad"]
        * (1.0 - tail["downwash_gradient"])
        * spec.htail.area_m2
        / spec.wing.area_m2
        * math.pi
        / 180.0
    )
    return wing_slope + tail_contribution


def tail_incidence_required_deg(
    spec: VehicleSpec,
    x_cg_m: float,
    cl_cruise: float,
) -> float:
    """Tail incidence that closes wing+tail lift and pitching moment."""
    if spec.htail.span_m <= 0.05:
        return spec.htail.incidence_deg
    tail = horizontal_tail_aero(spec)
    wing_ac = (
        spec.wing.x_le_mac_m + spec.solver.wing_body_np_mac * spec.wing.mac_m
        if spec.solver.wing_body_np_mac is not None
        else spec.wing.x_le_mac_m
        + (0.25 + spec.solver.np_shift_mac * abs(_sweep_calibration_ratio(spec)))
        * spec.wing.mac_m
    )
    area_ratio_eff = (
        tail["dynamic_pressure_ratio"] * spec.htail.area_m2 / spec.wing.area_m2
    )
    wing_arm = (x_cg_m - wing_ac) / spec.wing.mac_m
    tail_arm = (x_cg_m - tail["x_ac_m"]) / spec.wing.mac_m
    cm_ac = thin_airfoil_props(spec.wing.airfoil)["cm_ac"]
    denominator = area_ratio_eff * (tail_arm - wing_arm)
    if abs(denominator) < 1e-8:
        return 99.0
    cl_tail = -(cm_ac + cl_cruise * wing_arm) / denominator
    cl_wing = cl_cruise - area_ratio_eff * cl_tail
    alpha_wing = cl_wing / tail["wing_lift_slope_per_rad"]
    alpha_tail = cl_tail / tail["tail_lift_slope_per_rad"]
    incidence_rad = alpha_tail - alpha_wing * (1.0 - tail["downwash_gradient"])
    return math.degrees(incidence_rad) + spec.solver.tail_incidence_offset_deg


def elevon_pitch_derivative(
    spec: VehicleSpec, surface: ControlSurfaceSpec, x_cg_m: float
) -> dict[str, float]:
    """Closed-form dCm_cg/ddelta of a wing trailing-edge surface (TE down +).

    Strip integration of the thin-airfoil flap increments over the trapezoid
    planform between the surface's span fractions:

        dCL/ddelta   = CL_alpha_wing tau (S_e / S) cos(Lambda_hinge)
        dCm/ddelta   = dCm_ac/ddelta * integral(c^2 dy) / (S cbar)
                       - dCL/ddelta * (x_qc(eta_c) - x_cg) / cbar

    where eta_c is the area centroid of the elevon strip and x_qc its quarter
    chord. The wing lift slope is the same finite-wing value the balance model
    uses elsewhere (or the same-run VSPAERO value when calibrated). Results
    are scaled by ``solver.elevon_effectiveness_factor`` (source-cited when not
    unity). Per radian; ``per_deg`` keys are provided for reporting.
    """
    w = spec.wing
    flap = plain_flap_theory(surface.chord_fraction)
    semispan = 0.5 * w.span_m
    eta_s, eta_e = surface.span_start_fraction, surface.span_end_fraction
    c_r, c_t = w.root_chord_m, w.tip_chord_m

    def chord(eta: float) -> float:
        return c_r + (c_t - c_r) * eta

    # Exact trapezoid integrals over [eta_s, eta_e], both wing halves.
    n = 400
    etas = np.linspace(eta_s, eta_e, n)
    chords = np.array([chord(e) for e in etas])
    strip_area = 2.0 * semispan * float(np.trapezoid(chords, etas))
    chord_sq_integral = 2.0 * semispan * float(np.trapezoid(chords**2, etas))
    eta_c = float(np.trapezoid(chords * etas, etas) / max(np.trapezoid(chords, etas), 1e-12))
    x_qc_c = w.x_le_root_m + eta_c * semispan * math.tan(math.radians(w.le_sweep_deg))
    x_qc_c += 0.25 * chord(eta_c)
    hinge_x_root = w.x_le_root_m + (1.0 - surface.chord_fraction) * c_r
    hinge_x_tip = (
        w.x_le_root_m
        + semispan * math.tan(math.radians(w.le_sweep_deg))
        + (1.0 - surface.chord_fraction) * c_t
    )
    hinge_sweep = math.atan2(hinge_x_tip - hinge_x_root, semispan)
    wing_slope = (
        spec.solver.wing_body_cl_alpha_per_deg * 180.0 / math.pi
        if spec.solver.wing_body_cl_alpha_per_deg is not None
        else _lift_curve_slope_per_rad(w.aspect_ratio)
    )
    dcl_ddelta = wing_slope * flap["tau"] * (strip_area / w.area_m2) * math.cos(hinge_sweep)
    dcm_ddelta = flap["dcm_ac_ddelta_per_rad"] * chord_sq_integral / (
        w.area_m2 * w.mac_m
    ) - dcl_ddelta * (x_qc_c - x_cg_m) / w.mac_m
    factor = float(spec.solver.elevon_effectiveness_factor)
    return {
        "surface_id": surface.id,
        "flap_effectiveness_tau": flap["tau"],
        "section_dcm_ac_ddelta_per_rad": flap["dcm_ac_ddelta_per_rad"],
        "strip_area_fraction": strip_area / w.area_m2,
        "strip_area_centroid_eta": eta_c,
        "hinge_sweep_deg": math.degrees(hinge_sweep),
        "dcl_ddelta_per_rad": dcl_ddelta * factor,
        "dcm_cg_ddelta_per_rad": dcm_ddelta * factor,
        "dcl_ddelta_per_deg": dcl_ddelta * factor * math.pi / 180.0,
        "dcm_cg_ddelta_per_deg": dcm_ddelta * factor * math.pi / 180.0,
        "effectiveness_factor": factor,
        "sign_convention": "trailing edge down positive",
    }


def elevon_required_deg(
    spec: VehicleSpec, surface: ControlSurfaceSpec, x_cg_m: float, sm: float, cl_cruise: float
) -> dict[str, float]:
    """Elevon deflection (TE up positive) that zeroes Cm_cg with twist frozen.

    The residual moment the frozen wing leaves at cruise is
    Cm_cg0 = k_w * washout + cm_ac - SM * CL (the same low-order model the
    washout closure inverts); the elevon supplies dCm_cg/ddelta * delta.
    """
    sect = thin_airfoil_props(spec.wing.airfoil)
    k_w = spec.solver.cm_washout_per_deg * _sweep_calibration_ratio(spec)
    washout = spec.wing.twist_root_deg - spec.wing.twist_tip_deg
    cm_cg0 = k_w * washout + sect["cm_ac"] - sm * cl_cruise
    derivative = elevon_pitch_derivative(spec, surface, x_cg_m)
    dcm = derivative["dcm_cg_ddelta_per_deg"]
    if abs(dcm) < 1e-7:
        dcm = -1e-7
    delta_te_down = -cm_cg0 / dcm
    return {
        "required_te_up_deg": te_down_deg(delta_te_down),
        "cm_cg_untrimmed": cm_cg0,
        **derivative,
    }


# Fin (vertical tail) volume coefficient band for a small UAV. Below 0.02 the
# yaw stiffness is doubtful; above ~0.09 the fins are oversized for this class
# (Raymer-class guidance).
VV_BAND = (0.02, 0.09)


def fin_volume_coefficient(spec: VehicleSpec, x_cg_m: float) -> float:
    """Vv = count * Sv * lv * cos(cant) / (S*b), using one-fin area Sv."""
    v = spec.vtail
    t = v.taper
    y_mac = (v.span_m / 3.0) * (1.0 + 2.0 * t) / (1.0 + t)
    mac = (2.0 / 3.0) * v.root_chord_m * (1.0 + t + t**2) / (1.0 + t)
    x_ac = v.x_le_m + y_mac * math.tan(math.radians(v.le_sweep_deg)) + 0.25 * mac
    lv = max(x_ac - x_cg_m, 0.01)
    eff = math.cos(math.radians(v.cant_deg))
    return v.count * v.area_m2 * lv * eff / (spec.wing.area_m2 * spec.wing.span_m)


@dataclass
class BalanceReport:
    x_np_m: float
    x_cg_full_m: float
    x_cg_reserve_m: float
    sm_full: float
    sm_reserve: float
    sm_min: float
    sm_max: float
    in_band: bool
    washout_required_deg: float
    washout_available_deg: float
    trim_ok: bool
    cm_ac_section: float
    vstall_mps: float
    cl_max_effective: float
    cl_alpha_per_deg: float
    vstall_limit_mps: float
    stall_ok: bool
    vv: float = 0.0
    vv_band: tuple = VV_BAND
    vv_ok: bool = False
    trim_control: str = "wing_twist"
    tail_incidence_required_deg: float | None = None
    # Elevon trim (mission.pitch_trim_control: elevon); trailing edge up +.
    elevon_required_deg: float | None = None
    elevon_spec_deg: float | None = None
    elevon_travel_deg: tuple | None = None
    elevon_model: dict | None = None
    items_full: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["items_full"] = [
            {"name": n, "mass_kg": m, "x_m": x} for n, m, x in self.items_full
        ]
        return d


def _component_items(
    spec: VehicleSpec, masses: MassBreakdown, fuel_kg: float
) -> list[tuple[str, float, float]]:
    f = spec.fuselage
    w = spec.wing
    L = f.length_m
    x_wing_struct = w.x_le_mac_m + 0.40 * w.mac_m
    x_wing_fuel = w.x_le_mac_m + 0.32 * w.mac_m
    x_tank = f.fuel_tank_x_m
    x_engine = (
        spec.engine.x_m
        if spec.engine.x_m is not None
        else L - 0.20 - 0.5 * spec.engine.length_m
    )
    # Fuel goes in the wing first (near the CG), overflow to the fuselage tank.
    wing_cap_kg = wing_tank_volume_m3(spec) * spec.engine.fuel_density_kg_m3
    fuel_wing = min(fuel_kg, wing_cap_kg)
    fuel_fuse = max(fuel_kg - fuel_wing, 0.0)
    if spec.mass.operating_empty_mass_kg is not None:
        x_empty = spec.mass.operating_empty_cg_x_m
        if x_empty is None:
            raise ValueError(
                "reference operating-empty mass requires an explicit CG station"
            )
        items = [
            ("operating_empty", masses.empty_kg, x_empty),
            (
                "payload",
                spec.mission.payload_kg,
                f.payload_bay_x_m + 0.5 * f.payload_bay_length_m,
            ),
            ("fuel_wing", fuel_wing, x_wing_fuel),
            ("fuel_fuselage", fuel_fuse, x_tank),
        ]
        return [(n, m, x) for n, m, x in items if m > 0.0]

    items = [
        (
            "payload",
            spec.mission.payload_kg,
            f.payload_bay_x_m + 0.5 * f.payload_bay_length_m,
        ),
        ("engine", spec.engine.dry_mass_kg, x_engine),
        ("wing", masses.wing_kg, x_wing_struct),
        ("fuselage", masses.fuselage_kg, 0.50 * L),
        ("fins", masses.vtail_kg, spec.vtail.x_le_m + 0.5 * spec.vtail.root_chord_m),
        (
            "htail",
            masses.htail_kg,
            spec.htail.x_le_m + 0.3 if masses.htail_kg > 0 else 0.0,
        ),
        ("systems", masses.systems_kg, x_tank),
        ("avionics", masses.avionics_kg, 0.50 * L),
        ("gear", masses.landing_gear_kg, 0.58 * L),
        ("fuel_system", masses.fuel_system_kg, x_tank),
        ("contingency", masses.contingency_kg, 0.50 * L),
        ("fuel_wing", fuel_wing, x_wing_fuel),
        ("fuel_fuselage", fuel_fuse, x_tank),
    ]
    return [(n, m, x) for n, m, x in items if m > 0.0]


def cg_x(spec: VehicleSpec, masses: MassBreakdown, fuel_kg: float) -> float:
    items = _component_items(spec, masses, fuel_kg)
    total = sum(m for _, m, _ in items)
    return sum(m * x for _, m, x in items) / max(total, 1e-9)


def washout_required_deg(spec: VehicleSpec, sm: float, cl_cruise: float) -> float:
    """Washout (twist_root - twist_tip) needed so Cm_cg = 0 at cruise CL.

    Cm about the NP must equal +SM*CL; the wing supplies k_w * washout and
    the section camber supplies cm_ac. k_w is positive for aft sweep (tips
    behind the CG) and negative for forward sweep (tips ahead of the CG).
    """
    sect = thin_airfoil_props(spec.wing.airfoil)
    k_w = spec.solver.cm_washout_per_deg * _sweep_calibration_ratio(spec)
    if abs(k_w) < 1e-5:
        k_w = 1e-5 if k_w >= 0.0 else -1e-5
    return (sm * cl_cruise - sect["cm_ac"]) / k_w


def effective_cl_max(spec: VehicleSpec) -> float:
    """Return aircraft CLmax from either an aircraft or 2-D section input.

    The section conversion is the conventional conceptual-design correction:
    a 0.9 finite-wing factor times cosine of quarter-chord sweep. It is a
    declared model-form transformation, not a truth-case calibration.
    """
    if spec.mission.cl_max_basis == "aircraft":
        return spec.mission.cl_max
    half_span = 0.5 * spec.wing.span_m
    tan_quarter = math.tan(math.radians(spec.wing.le_sweep_deg)) - 0.25 * (
        spec.wing.root_chord_m - spec.wing.tip_chord_m
    ) / max(half_span, 1e-9)
    quarter_sweep = math.atan(tan_quarter)
    return 0.90 * spec.mission.cl_max * math.cos(quarter_sweep)


def stall_speed_mps(spec: VehicleSpec, mtow_kg: float, rho: float = 1.225) -> float:
    w = mtow_kg * G0
    return math.sqrt(2.0 * w / (rho * spec.wing.area_m2 * effective_cl_max(spec)))


def balance_report(spec: VehicleSpec, mtow_kg: float, fuel_kg: float) -> BalanceReport:
    masses = breakdown(spec, mtow_kg, fuel_kg)
    x_np = neutral_point_x(spec)
    mac = spec.wing.mac_m
    xf = cg_x(spec, masses, fuel_kg)
    xr = cg_x(spec, masses, masses.reserve_fuel_kg)
    sm_f = (x_np - xf) / mac
    sm_r = (x_np - xr) / mac
    lo, hi = spec.mission.static_margin_min, spec.mission.static_margin_max
    in_band = (lo <= sm_f <= hi) and (lo <= sm_r <= hi)
    # The cruise pitch-trim solve and OAS verification use the full-fuel CG.
    # Reserve-fuel margin remains a separate stability gate; fixed twist cannot
    # close two different CG states without an explicit control-surface model.
    wash_avail = spec.wing.twist_root_deg - spec.wing.twist_tip_deg
    control = pitch_trim_control(spec)
    tail_enabled = control == "tail_incidence"
    tail_incidence_req = (
        tail_incidence_required_deg(spec, xf, spec.mission.cruise_cl)
        if tail_enabled
        else None
    )
    elevon_req: float | None = None
    elevon_spec: float | None = None
    elevon_travel: tuple[float, float] | None = None
    elevon_model: dict[str, float] | None = None
    if control == "elevon":
        surface = pitch_control_surface(spec)
        if surface is None:
            raise ValueError("elevon pitch trim requires a collective-pitch wing surface")
        elevon_model = elevon_required_deg(
            spec, surface, xf, sm_f, spec.mission.cruise_cl
        )
        elevon_req = float(elevon_model["required_te_up_deg"])
        elevon_spec = float(surface.trim_deflection_deg)
        elevon_travel = elevon_travel_deg(surface)
    # Twist is frozen whenever a movable control closes trim: the washout
    # "requirement" then equals what the wing has, and the control carries
    # the gap.
    wash_req = (
        wash_avail
        if control != "wing_twist"
        else washout_required_deg(spec, sm_f, spec.mission.cruise_cl)
    )
    vs = stall_speed_mps(spec, masses.mtow_kg)
    sect = thin_airfoil_props(spec.wing.airfoil)
    vv = fin_volume_coefficient(spec, xf)
    reproduction = bool(
        spec.sketch is not None and spec.sketch.treatment == "reproduction"
    )
    if control == "elevon":
        lo, hi = elevon_travel  # type: ignore[misc]
        trim_ok = (
            abs(elevon_spec - elevon_req) <= 1.5  # type: ignore[operator]
            and lo + 0.5 <= elevon_req <= hi - 0.5  # type: ignore[operator]
        )
    elif tail_incidence_req is not None:
        trim_ok = (
            abs(spec.htail.incidence_deg - tail_incidence_req) <= 1.5
            and abs(tail_incidence_req) <= 10.0
        )
    else:
        trim_ok = abs(wash_avail - wash_req) <= 1.5 and abs(wash_req) <= 10.0
    return BalanceReport(
        vv=vv,
        vv_band=VV_BAND,
        vv_ok=(vv >= VV_BAND[0] if reproduction else VV_BAND[0] <= vv <= VV_BAND[1]),
        trim_control=control,
        tail_incidence_required_deg=tail_incidence_req,
        elevon_required_deg=elevon_req,
        elevon_spec_deg=elevon_spec,
        elevon_travel_deg=elevon_travel,
        elevon_model=elevon_model,
        x_np_m=x_np,
        x_cg_full_m=xf,
        x_cg_reserve_m=xr,
        sm_full=sm_f,
        sm_reserve=sm_r,
        sm_min=lo,
        sm_max=hi,
        in_band=in_band,
        washout_required_deg=wash_req,
        washout_available_deg=wash_avail,
        trim_ok=bool(trim_ok),
        cm_ac_section=sect["cm_ac"],
        vstall_mps=vs,
        cl_max_effective=effective_cl_max(spec),
        cl_alpha_per_deg=aircraft_lift_curve_slope_per_deg(spec),
        vstall_limit_mps=spec.mission.stall_speed_max_mps,
        stall_ok=vs <= spec.mission.stall_speed_max_mps,
        items_full=_component_items(spec, masses, fuel_kg),
    )
