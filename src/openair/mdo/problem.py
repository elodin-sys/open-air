"""OpenMDAO optimization of the target UAV (max dash speed).

Design intent (see docs/guidebook/_research/qa-audit.md):

- DV bounds encode the desires.md shape requirement ("see sketches"):
  span/length 1.31-1.80, root-chord/length 0.41-0.55, LE sweep 28-36 deg,
  taper 0.25-0.40. The optimizer trades size and detail inside the sketch
  envelope instead of designing to arbitrary bounds.
- Balance is physical: component-CG buildup, neutral point at the calibrated
  wing AC, static margin constrained at full AND reserve fuel.
- Trim is enforced: washout must match the tailless trim requirement.
- Stall speed is capped (documented CLmax assumption).
- After optimization the chosen point is re-verified with OpenAeroStruct
  (pitch trim + wingbox at limit load); the stage fails if verification fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import openmdao.api as om
import yaml

from openair.design_intent import (
    fidelity_penalty,
    fin_trailing_edge_overhang_m,
    sketch_prior_rows,
)
from openair.controls import (
    pitch_control_surface,
    pitch_trim_control,
    set_pitch_trim_deflection,
    trim_control_values,
    within_travel,
)
from openair.geometry.packing import packing_report
from openair.mission.balance import balance_report
from openair.mission.engine import breguet_endurance_s
from openair.mission.mass import closed_mass_breakdown
from openair.mission.sizing import aero_point, cruise_tas, max_dash_speed
from openair.paths import optimized_design_for
from openair.schemas import VehicleSpec
from openair.units import G0

DV_BOUNDS: dict[str, tuple[float, float]] = {
    # sketch-envelope planform (fuselage length 2.45 m)
    "span": (3.20, 4.40),
    "root_chord": (1.00, 1.35),
    "taper": (0.25, 0.40),
    "sweep": (28.0, 36.0),
    "t_over_c": (0.09, 0.14),
    "twist_root": (0.0, 3.0),
    "twist_tip": (-8.0, 0.0),
    "skin_t": (0.0008, 0.004),
    "spar_t": (0.0012, 0.006),
    "fuel": (8.0, 45.0),
    "cruise_alt": (300.0, 4000.0),
    # placement (balance levers)
    "x_le_root": (0.70, 1.00),
    "payload_bay_x": (0.90, 1.34),
    "fuel_tank_x": (1.30, 1.80),
}

# Keep serialized/re-evaluated hard constraints just inside their gates
# instead of relying on exact active values at SLSQP's numerical tolerance.
VV_CONSTRAINT_MARGIN = 1e-4
ENDURANCE_CONSTRAINT_MARGIN_S = 1.0
STALL_CONSTRAINT_MARGIN_MPS = 0.02


def dv_bounds_for(spec: VehicleSpec) -> dict[str, tuple[float, float]]:
    """Planform bounds come from the concept sketch when one is declared.

    Concepts without a `sketch:` block keep the original KingTech target
    envelope encoded in `DV_BOUNDS` (audit F5).
    """
    bounds = {k: tuple(v) for k, v in DV_BOUNDS.items()}
    if spec.sketch is not None and spec.sketch.treatment == "reproduction":
        return {}
    length = spec.fuselage.length_m
    fuel = spec.mass.fuel_mass_kg
    if spec.mass.fuel_mass_mode == "fixed":
        bounds.pop("fuel")
    else:
        bounds["fuel"] = (
            max(0.1, min(DV_BOUNDS["fuel"][0], 0.5 * fuel)),
            max(DV_BOUNDS["fuel"][1], 1.5 * fuel),
        )
    for key, station in (
        ("payload_bay_x", spec.fuselage.payload_bay_x_m),
        ("fuel_tank_x", spec.fuselage.fuel_tank_x_m),
    ):
        lo, hi = bounds[key]
        margin = 0.05 * length
        bounds[key] = (
            max(0.0, min(lo, station - margin)),
            min(length, max(hi, station + margin)),
        )
    env = spec.sketch
    if env is None:
        if spec.htail.span_m > 0.05:
            bounds["htail_incidence"] = (-10.0, 10.0)
            bounds.pop("twist_root", None)
            bounds.pop("twist_tip", None)
        return bounds
    scale = env.hard_scale if env.treatment == "inspiration" else 1.0
    bounds["span"] = (
        max(0.21, length * (env.span_over_length - scale * env.span_over_length_tol)),
        min(
            19.5,
            length * (env.span_over_length + scale * env.span_over_length_tol),
        ),
    )
    bounds["root_chord"] = (
        max(0.051, length * (env.root_over_length - scale * env.root_over_length_tol)),
        min(
            4.9,
            length * (env.root_over_length + scale * env.root_over_length_tol),
        ),
    )
    bounds["sweep"] = (
        max(-44.5, env.le_sweep_deg - scale * env.le_sweep_tol_deg),
        min(59.5, env.le_sweep_deg + scale * env.le_sweep_tol_deg),
    )
    bounds["taper"] = (
        max(0.031, env.taper - scale * env.taper_tol),
        min(0.99, env.taper + scale * env.taper_tol),
    )
    bounds["x_le_root"] = (
        max(
            0.0,
            length
            * (env.x_le_root_over_length - scale * env.x_le_root_over_length_tol),
        ),
        length * (env.x_le_root_over_length + scale * env.x_le_root_over_length_tol),
    )
    if env.payload_bay_x_lo_m is not None and env.payload_bay_x_hi_m is not None:
        bounds["payload_bay_x"] = (env.payload_bay_x_lo_m, env.payload_bay_x_hi_m)
    if env.fuel_tank_x_lo_m is not None and env.fuel_tank_x_hi_m is not None:
        bounds["fuel_tank_x"] = (env.fuel_tank_x_lo_m, env.fuel_tank_x_hi_m)
    if env.twist_tip_lo_deg is not None and env.twist_tip_hi_deg is not None:
        twist_center = 0.5 * (env.twist_tip_lo_deg + env.twist_tip_hi_deg)
        twist_half = 0.5 * (env.twist_tip_hi_deg - env.twist_tip_lo_deg)
        bounds["twist_tip"] = (
            max(-14.5, twist_center - scale * twist_half),
            min(14.5, twist_center + scale * twist_half),
        )
    inspiration = env.treatment == "inspiration"
    if inspiration:
        root_center = 0.5 * sum(DV_BOUNDS["twist_root"])
        root_half = 0.5 * (DV_BOUNDS["twist_root"][1] - DV_BOUNDS["twist_root"][0])
        bounds["twist_root"] = (
            max(-14.5, root_center - scale * root_half),
            min(14.5, root_center + scale * root_half),
        )

    def prior_bounds(
        target: float | None,
        tol: float | None,
        fallback: tuple[float, float],
        physical: tuple[float, float],
    ) -> tuple[float, float]:
        lo, hi = (
            (target - scale * tol, target + scale * tol)
            if target is not None and tol is not None
            else fallback
        )
        return max(physical[0], lo), min(physical[1], hi)

    if inspiration or (env.fin_span_m is not None and env.fin_span_tol_m is not None):
        bounds["fin_span"] = prior_bounds(
            env.fin_span_m,
            env.fin_span_tol_m,
            (0.5 * spec.vtail.span_m, 2.0 * spec.vtail.span_m),
            (0.02, min(4.9, length)),
        )
    if inspiration or (
        env.fin_root_chord_m is not None and env.fin_root_chord_tol_m is not None
    ):
        bounds["fin_root_chord"] = prior_bounds(
            env.fin_root_chord_m,
            env.fin_root_chord_tol_m,
            (0.5 * spec.vtail.root_chord_m, 1.5 * spec.vtail.root_chord_m),
            (0.03, min(4.9, length)),
        )
    if inspiration or (
        env.fin_le_sweep_deg is not None and env.fin_le_sweep_tol_deg is not None
    ):
        bounds["fin_sweep"] = prior_bounds(
            env.fin_le_sweep_deg,
            env.fin_le_sweep_tol_deg,
            (spec.vtail.le_sweep_deg - 20.0, spec.vtail.le_sweep_deg + 20.0),
            (-44.5, 74.5),
        )
    if inspiration or (
        env.fin_cant_deg is not None and env.fin_cant_tol_deg is not None
    ):
        bounds["fin_cant"] = prior_bounds(
            env.fin_cant_deg,
            env.fin_cant_tol_deg,
            (spec.vtail.cant_deg - 20.0, spec.vtail.cant_deg + 20.0),
            (0.0, 74.5),
        )
    if inspiration or (env.fin_x_le_m is not None and env.fin_x_le_tol_m is not None):
        bounds["fin_x_le"] = prior_bounds(
            env.fin_x_le_m,
            env.fin_x_le_tol_m,
            (spec.vtail.x_le_m - 0.15 * length, spec.vtail.x_le_m + 0.15 * length),
            (0.0, length),
        )
    if spec.htail.span_m > 0.05:
        bounds["htail_incidence"] = (-10.0, 10.0)
        # Tail incidence is the pitch-control DV in this topology. The
        # low-order MDA has no independent wing-twist response once the
        # tail is enabled, so exposing twist would permit arbitrary
        # zero-gradient motion.
        bounds.pop("twist_root", None)
        bounds.pop("twist_tip", None)
    return bounds


def _f(value) -> float:
    return float(np.ravel(value)[0])


def _apply_dvs(base: VehicleSpec, inputs) -> VehicleSpec:
    spec = base.model_copy(deep=True)
    spec.wing.span_m = _f(inputs["span"])
    spec.wing.root_chord_m = _f(inputs["root_chord"])
    spec.wing.taper = _f(inputs["taper"])
    spec.wing.le_sweep_deg = _f(inputs["sweep"])
    spec.wing.t_over_c = _f(inputs["t_over_c"])
    if "twist_root" in inputs:
        spec.wing.twist_root_deg = _f(inputs["twist_root"])
    if "twist_tip" in inputs:
        spec.wing.twist_tip_deg = _f(inputs["twist_tip"])
    spec.wing.x_le_root_m = _f(inputs["x_le_root"])
    spec.fuselage.payload_bay_x_m = _f(inputs["payload_bay_x"])
    spec.fuselage.fuel_tank_x_m = _f(inputs["fuel_tank_x"])
    spec.structures.skin_thickness_m = _f(inputs["skin_t"])
    spec.structures.spar_thickness_m = _f(inputs["spar_t"])
    if spec.mass.fuel_mass_mode == "sized" and "fuel" in inputs:
        spec.mass.fuel_mass_kg = _f(inputs["fuel"])
    spec.mission.cruise_altitude_m = _f(inputs["cruise_alt"])
    if "dihedral" in inputs:
        spec.wing.dihedral_deg = _f(inputs["dihedral"])
    if "fin_span" in inputs:
        spec.vtail.span_m = _f(inputs["fin_span"])
    if "fin_root_chord" in inputs:
        spec.vtail.root_chord_m = _f(inputs["fin_root_chord"])
    if "fin_sweep" in inputs:
        spec.vtail.le_sweep_deg = _f(inputs["fin_sweep"])
    if "fin_cant" in inputs:
        spec.vtail.cant_deg = _f(inputs["fin_cant"])
    if "fin_x_le" in inputs:
        spec.vtail.x_le_m = _f(inputs["fin_x_le"])
    if "htail_incidence" in inputs:
        spec.htail.incidence_deg = _f(inputs["htail_incidence"])
    return spec


def _box_failure(spec: VehicleSpec, mtow_kg: float, n: float) -> float:
    """KS-like scalar: max von Mises / allowable - 1, box-beam root."""
    b2 = 0.5 * spec.wing.span_m
    cr = spec.wing.root_chord_m
    w = 0.50 * cr
    h = spec.wing.t_over_c * cr
    tsk = spec.structures.skin_thickness_m
    tsp = spec.structures.spar_thickness_m
    inertia = 2.0 * (w * tsk) * (0.5 * h) ** 2 + 2.0 * (h * tsp) * (0.5 * w) ** 2 / 12.0
    inertia = max(inertia, 1e-12)
    M = (n * mtow_kg * G0 / 2.0) * (4.0 * b2 / (3.0 * np.pi))
    sigma = M * (0.5 * h) / inertia
    allow = spec.structures.material.yield_pa / spec.mission.safety_factor
    return float(sigma / allow - 1.0)


def evaluate_design(spec: VehicleSpec) -> dict[str, float]:
    """Closed-form MDA shared by the optimizer, the fallback, and tests."""
    fuel = spec.mass.fuel_mass_kg
    masses = closed_mass_breakdown(spec, fuel)
    mtow = masses.mtow_kg
    v_c, _ = cruise_tas(spec, mtow)
    cruise = aero_point(spec, mtow, spec.mission.cruise_altitude_m, v_c)
    dash = max_dash_speed(spec, mtow)
    usable = max(fuel - masses.reserve_fuel_kg, 0.0)
    endurance = (
        breguet_endurance_s(
            cruise["tsfc_weight_per_s"],
            cruise["lod"],
            mtow / max(mtow - usable, 1.0),
        )
        if spec.mission.endurance_required
        else 0.0
    )
    endurance_deficit = (
        spec.mission.endurance_s - endurance if spec.mission.endurance_required else 0.0
    )
    pack = packing_report(spec, fuel)
    bal = balance_report(spec, mtow, fuel)
    f = spec.fuselage
    engine_bay_front = (
        f.length_m - 0.20 - spec.engine.length_m - 0.05
        if spec.engine.installation == "internal"
        else f.length_m
    )
    bay_clearance = engine_bay_front - (f.payload_bay_x_m + f.payload_bay_length_m)
    wash_req = bal.washout_required_deg
    washout = spec.wing.twist_root_deg - spec.wing.twist_tip_deg
    if bal.trim_control == "elevon" and bal.elevon_required_deg is not None:
        trim_gap = float(bal.elevon_spec_deg or 0.0) - float(bal.elevon_required_deg)
    elif bal.tail_incidence_required_deg is not None:
        trim_gap = spec.htail.incidence_deg - bal.tail_incidence_required_deg
    else:
        trim_gap = washout - wash_req
    vv_lo, vv_hi = bal.vv_band
    return {
        "mtow_kg": mtow,
        "dash_mps": dash["tas_mps"],
        "dash_mach": dash["mach"],
        "endurance_s": endurance,
        "endurance_deficit_s": endurance_deficit,
        "endurance_applicable": spec.mission.endurance_required,
        "lod": cruise["lod"],
        "thrust_margin_cruise": (cruise["thrust_avail_n"] - cruise["drag_n"])
        / max(cruise["drag_n"], 1.0),
        "thrust_margin_dash": (dash["thrust_avail_n"] - dash["drag_n"])
        / max(dash["drag_n"], 1.0),
        "failure": _box_failure(spec, mtow, spec.mission.limit_positive_g),
        "packing_violation": float(
            pack["fuel_volume_m3"] - pack["volume_left_for_fuel_m3"]
        ),
        "bay_clearance_m": bay_clearance,
        "sm_full": bal.sm_full,
        "sm_reserve": bal.sm_reserve,
        "vstall_margin_mps": bal.vstall_mps - spec.mission.stall_speed_max_mps,
        "vstall_mps": bal.vstall_mps,
        "washout_gap_deg": trim_gap,
        "washout_required_deg": wash_req,
        "tail_incidence_required_deg": (
            bal.tail_incidence_required_deg
            if bal.tail_incidence_required_deg is not None
            else 0.0
        ),
        "elevon_required_deg": (
            bal.elevon_required_deg if bal.elevon_required_deg is not None else 0.0
        ),
        "vv_lower_violation": vv_lo - bal.vv,
        "vv_upper_violation": bal.vv - vv_hi,
        "fin_te_overhang_m": fin_trailing_edge_overhang_m(spec),
        "fidelity_penalty": fidelity_penalty(spec),
    }


_MDA_OUTPUTS = [
    ("objective", None),
    ("neg_dash_mps", "m/s"),
    ("endurance_s", "s"),
    ("endurance_deficit_s", "s"),
    ("thrust_margin_cruise", None),
    ("thrust_margin_dash", None),
    ("failure", None),
    ("packing_violation", None),
    ("bay_clearance_m", "m"),
    ("sm_full", None),
    ("sm_reserve", None),
    ("vstall_margin_mps", "m/s"),
    ("washout_gap_deg", "deg"),
    ("vv_lower_violation", None),
    ("vv_upper_violation", None),
    ("fin_te_overhang_m", "m"),
    ("fidelity_penalty", None),
    ("mtow_kg", "kg"),
    ("lod", None),
]


class VehicleMDA(om.ExplicitComponent):
    """Closed-form aero + mass + engine + balance + box-beam structures."""

    def initialize(self):
        self.options.declare("spec", types=VehicleSpec)

    def setup(self):
        s = self.options["spec"]
        defaults = _spec_dvs(s)
        for name in dv_bounds_for(s):
            self.add_input(name, val=defaults[name])
        for name, _units in _MDA_OUTPUTS:
            self.add_output(name)
        self.declare_partials(
            "*", "*", method="fd", form="forward", step=1e-3, step_calc="rel"
        )

    def compute(self, inputs, outputs):
        spec = _apply_dvs(self.options["spec"], inputs)
        r = evaluate_design(spec)
        outputs["neg_dash_mps"] = -r["dash_mps"]
        weight = spec.sketch.fidelity_weight if spec.sketch is not None else 0.0
        outputs["objective"] = -r["dash_mps"] / 100.0 + weight * r["fidelity_penalty"]
        for key in (
            "endurance_s",
            "endurance_deficit_s",
            "thrust_margin_cruise",
            "thrust_margin_dash",
            "failure",
            "packing_violation",
            "bay_clearance_m",
            "sm_full",
            "sm_reserve",
            "vstall_margin_mps",
            "washout_gap_deg",
            "vv_lower_violation",
            "vv_upper_violation",
            "fin_te_overhang_m",
            "fidelity_penalty",
            "mtow_kg",
            "lod",
        ):
            outputs[key] = r[key]


def _add_dvs_and_cons(
    p: om.Problem, spec: VehicleSpec, sm_bounds: tuple[float, float] | None = None
) -> None:
    sm_lo, sm_hi = sm_bounds or (
        spec.mission.static_margin_min,
        spec.mission.static_margin_max,
    )
    for dv, (lo, hi) in dv_bounds_for(spec).items():
        # SLSQP operates on the driver-scaled values. Without this, the
        # inspiration problem mixes millimetre gauges, degree angles, and a
        # 4,000 m altitude in one vector; the Merlin v2 branches exhausted
        # 75 iterations while the same problem converged in 24 iterations
        # after normalization.
        p.model.add_design_var(
            dv,
            lower=lo,
            upper=hi,
            ref0=lo,
            ref=hi,
        )
    if spec.mission.endurance_required:
        p.model.add_constraint(
            "endurance_deficit_s",
            upper=-ENDURANCE_CONSTRAINT_MARGIN_S,
            ref=100.0,
        )
    p.model.add_constraint("thrust_margin_cruise", lower=0.05)
    p.model.add_constraint("thrust_margin_dash", lower=0.0)
    p.model.add_constraint("failure", upper=0.0)
    p.model.add_constraint("packing_violation", upper=0.0, ref=0.01)
    p.model.add_constraint("bay_clearance_m", lower=0.0, ref=0.1)
    p.model.add_constraint("sm_full", lower=sm_lo, upper=sm_hi)
    p.model.add_constraint("sm_reserve", lower=sm_lo, upper=sm_hi)
    p.model.add_constraint(
        "vstall_margin_mps",
        upper=-STALL_CONSTRAINT_MARGIN_MPS,
        ref=5.0,
    )
    p.model.add_constraint("washout_gap_deg", lower=-0.5, upper=0.5)
    fin_geometry_is_variable = "fin_span" in dv_bounds_for(spec)
    if fin_geometry_is_variable:
        p.model.add_constraint(
            "vv_lower_violation",
            upper=-VV_CONSTRAINT_MARGIN,
            ref=0.02,
        )
        p.model.add_constraint("vv_upper_violation", upper=0.0, ref=0.05)
        p.model.add_constraint("fin_te_overhang_m", upper=0.0, ref=0.1)
    if spec.sketch is not None and spec.sketch.treatment == "inspiration":
        p.model.add_objective("objective")
    else:
        p.model.add_objective("neg_dash_mps", ref=100.0)


def _candidate(p: om.Problem, label, spec: VehicleSpec) -> dict[str, Any]:
    cand = {
        "start": label,
        "objective": float(p["objective"][0]),
        "dash_mps": float(-p["neg_dash_mps"][0]),
        "endurance_s": float(p["endurance_s"][0]),
        "endurance_deficit_s": float(p["endurance_deficit_s"][0]),
        "failure": float(p["failure"][0]),
        "packing_violation": float(p["packing_violation"][0]),
        "bay_clearance_m": float(p["bay_clearance_m"][0]),
        "thrust_margin_cruise": float(p["thrust_margin_cruise"][0]),
        "sm_full": float(p["sm_full"][0]),
        "sm_reserve": float(p["sm_reserve"][0]),
        "vstall_margin_mps": float(p["vstall_margin_mps"][0]),
        "washout_gap_deg": float(p["washout_gap_deg"][0]),
        "vv_lower_violation": float(p["vv_lower_violation"][0]),
        "vv_upper_violation": float(p["vv_upper_violation"][0]),
        "fin_te_overhang_m": float(p["fin_te_overhang_m"][0]),
        "fidelity_penalty": float(p["fidelity_penalty"][0]),
        "mtow_kg": float(p["mtow_kg"][0]),
        "lod": float(p["lod"][0]),
        "dvs": {
            name: float(np.ravel(p[name])[0])
            for name in p.model.get_design_vars(recurse=True)
        },
    }
    cand["dvs"].setdefault("fuel", spec.mass.fuel_mass_kg)
    cand["feasible"] = _is_feasible(cand)
    return cand


def _is_feasible(c: dict[str, Any], spec: VehicleSpec | None = None) -> bool:
    sm_lo, sm_hi = (
        (0.03, 0.10)
        if spec is None
        else (
            spec.mission.static_margin_min,
            spec.mission.static_margin_max,
        )
    )
    # The wing+tail balance model is deliberately low order, while the
    # delivered incidence is replaced by the independently OAS-trimmed value.
    # Keep this post-verify check aligned with balance_report.trim_ok; SLSQP
    # still drives its pre-verify tail-incidence gap inside ±0.5 degree. The
    # closed-form elevon model shares the wider band for the same reason.
    trim_gap_limit = (
        1.5
        if spec is not None and pitch_trim_control(spec) in {"tail_incidence", "elevon"}
        else 0.75
    )
    reproduction = bool(
        spec is not None
        and spec.sketch is not None
        and spec.sketch.treatment == "reproduction"
    )
    endurance_ok = (
        bool(spec is not None and not spec.mission.endurance_required)
        or c["endurance_deficit_s"] <= 0.0
    )
    base_ok = (
        endurance_ok
        and c["failure"] <= 0.05
        and c["packing_violation"] <= 0.001
        and c["bay_clearance_m"] >= -0.005
        and c["thrust_margin_cruise"] >= -0.02
        and sm_lo - 0.01 <= c["sm_full"] <= sm_hi + 0.01
        and sm_lo - 0.01 <= c["sm_reserve"] <= sm_hi + 0.01
        and c["vstall_margin_mps"] <= 0.0
        and (reproduction or abs(c["washout_gap_deg"]) <= trim_gap_limit)
    )
    inspiration = bool(
        spec is not None
        and spec.sketch is not None
        and spec.sketch.treatment == "inspiration"
    )
    fin_geometry_is_variable = bool(
        spec is not None and "fin_span" in dv_bounds_for(spec)
    )
    if not (inspiration or fin_geometry_is_variable):
        return base_ok
    return (
        base_ok
        and c.get("vv_lower_violation", 1.0) <= 1e-6
        and c.get("vv_upper_violation", 1.0) <= 1e-4
        and c.get("fin_te_overhang_m", 1.0) <= 1e-4
    )


def _calibrated_np_shift_mac(
    spec: VehicleSpec,
    measured_np_m: float,
    modeled_np_m: float,
) -> float:
    """Invert the low-order NP offset against a same-geometry OAS measurement."""
    return (
        float(spec.solver.np_shift_mac)
        + (float(measured_np_m) - float(modeled_np_m)) / spec.wing.mac_m
    )


def _clip_start(
    start: dict[str, float], bounds: dict[str, tuple[float, float]]
) -> dict[str, float]:
    clipped = {}
    for key, val in start.items():
        if key not in bounds:
            continue
        lo, hi = bounds[key]
        clipped[key] = min(max(float(val), lo), hi)
    return clipped


def _spec_dvs(spec: VehicleSpec) -> dict[str, float]:
    return {
        "span": spec.wing.span_m,
        "root_chord": spec.wing.root_chord_m,
        "taper": spec.wing.taper,
        "sweep": spec.wing.le_sweep_deg,
        "t_over_c": spec.wing.t_over_c,
        "twist_root": spec.wing.twist_root_deg,
        "twist_tip": spec.wing.twist_tip_deg,
        "skin_t": spec.structures.skin_thickness_m,
        "spar_t": spec.structures.spar_thickness_m,
        "fuel": spec.mass.fuel_mass_kg,
        "cruise_alt": spec.mission.cruise_altitude_m,
        "x_le_root": spec.wing.x_le_root_m,
        "payload_bay_x": spec.fuselage.payload_bay_x_m,
        "fuel_tank_x": spec.fuselage.fuel_tank_x_m,
        "dihedral": spec.wing.dihedral_deg,
        "fin_span": spec.vtail.span_m,
        "fin_root_chord": spec.vtail.root_chord_m,
        "fin_sweep": spec.vtail.le_sweep_deg,
        "fin_cant": spec.vtail.cant_deg,
        "fin_x_le": spec.vtail.x_le_m,
        "htail_incidence": spec.htail.incidence_deg,
    }


def _optimize_starts(
    spec: VehicleSpec, outdir: Path, sm_bounds: tuple[float, float], record: bool
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    bounds = dv_bounds_for(spec)
    defaults = _spec_dvs(spec)
    bounded_defaults = _clip_start(
        {key: defaults[key] for key in bounds},
        bounds,
    )
    mda_spec = _apply_dvs(
        spec,
        {key: np.array([value]) for key, value in bounded_defaults.items()},
    )
    sweep0 = spec.wing.le_sweep_deg
    high_fuel = bounds.get("fuel", (spec.mass.fuel_mass_kg,) * 2)[1]

    def twist_seed(root_index: int, tip_index: int) -> dict[str, float]:
        if "twist_root" not in bounds or "twist_tip" not in bounds:
            return {}
        return {
            "twist_root": bounds["twist_root"][root_index],
            "twist_tip": bounds["twist_tip"][tip_index],
        }

    starts: list[dict[str, float]] = [
        bounded_defaults,
        _clip_start(
            {
                "span": spec.wing.span_m + 0.40,
                "root_chord": spec.wing.root_chord_m + 0.10,
                "sweep": sweep0 + 2.0,
                **twist_seed(0, 0),
                "fuel": high_fuel,
                "cruise_alt": bounds["cruise_alt"][1],
            },
            bounds,
        ),
        _clip_start(
            {
                "span": spec.wing.span_m - 0.40,
                "root_chord": spec.wing.root_chord_m - 0.10,
                "sweep": sweep0 - 3.0,
                **twist_seed(0, 1),
                "fuel": high_fuel,
                "cruise_alt": bounds["cruise_alt"][1],
            },
            bounds,
        ),
        _clip_start(
            {
                "span": bounds["span"][0]
                + 0.60 * (bounds["span"][1] - bounds["span"][0]),
                "root_chord": bounds["root_chord"][0],
                "taper": bounds["taper"][0],
                "sweep": sweep0,
                "t_over_c": bounds["t_over_c"][0],
                **twist_seed(0, 1),
                "skin_t": bounds["skin_t"][0],
                "spar_t": bounds["spar_t"][0],
                "fuel": high_fuel,
                "cruise_alt": bounds["cruise_alt"][1],
                "x_le_root": bounds["x_le_root"][1]
                - 0.10 * (bounds["x_le_root"][1] - bounds["x_le_root"][0]),
                "payload_bay_x": 0.5
                * (bounds["payload_bay_x"][0] + bounds["payload_bay_x"][1]),
                "fuel_tank_x": bounds["fuel_tank_x"][0]
                + 0.15 * (bounds["fuel_tank_x"][1] - bounds["fuel_tank_x"][0]),
            },
            bounds,
        ),
    ]
    inspiration = bool(
        spec.sketch is not None and spec.sketch.treatment == "inspiration"
    )
    if inspiration:
        starts.extend(
            [
                _clip_start(
                    {
                        "fin_span": bounds["fin_span"][0],
                        "fin_root_chord": bounds["fin_root_chord"][1],
                        "fin_sweep": bounds["fin_sweep"][0],
                        "fin_cant": min(
                            max(bounds["fin_cant"][0], 0.5),
                            bounds["fin_cant"][1],
                        ),
                        "fin_x_le": bounds["fin_x_le"][0],
                    },
                    bounds,
                ),
                _clip_start(
                    {
                        "fin_span": bounds["fin_span"][1],
                        "fin_root_chord": bounds["fin_root_chord"][1],
                        "fin_sweep": bounds["fin_sweep"][1],
                        "fin_cant": bounds["fin_cant"][1],
                        "fin_x_le": bounds["fin_x_le"][1],
                    },
                    bounds,
                ),
            ]
        )
    best = None
    histories = []
    for i, start in enumerate(starts):
        p = om.Problem()
        p.model.add_subsystem("mda", VehicleMDA(spec=mda_spec), promotes=["*"])
        p.driver = om.ScipyOptimizeDriver()
        p.driver.options["optimizer"] = "SLSQP"
        p.driver.options["maxiter"] = spec.solver.optimize_maxiter
        p.driver.options["tol"] = spec.solver.optimize_tol
        p.driver.options["disp"] = False
        _add_dvs_and_cons(p, spec, sm_bounds)
        if record and i == 0:
            rec = outdir / "mdo.db"
            rec.unlink(missing_ok=True)
            p.driver.add_recorder(om.SqliteRecorder(str(rec)))
            p.driver.recording_options["record_objectives"] = True
            p.driver.recording_options["record_constraints"] = True
            p.driver.recording_options["record_desvars"] = True
        p.setup()
        # OpenMDAO validates every promoted input before the per-start
        # overrides below. Seed all DVs inside their bounds first so a sized
        # fuel closure above the optimization cap does not emit an invalid
        # initial-condition warning on partial starts.
        for k, v in bounded_defaults.items():
            p[k] = v
        for k, v in start.items():
            p[k] = v
        p.run_driver()
        cand = _candidate(p, i, spec)
        driver_result = p.driver.result
        cand["driver_success"] = bool(getattr(driver_result, "success", False))
        cand["driver_status"] = str(getattr(driver_result, "exit_status", "unknown"))
        cand["driver_iterations"] = int(getattr(driver_result, "iter_count", 0) or 0)
        cand["feasible"] = _is_feasible(cand, spec)
        cand["sm_bounds_internal"] = list(sm_bounds)
        histories.append(cand)
        performance_score = (
            -float(cand["objective"]) if inspiration else float(cand["dash_mps"])
        )
        best_performance_score = (
            (-float(best["objective"]) if inspiration else float(best["dash_mps"]))
            if best
            else float("-inf")
        )
        cand_rank = (
            bool(cand["feasible"]),
            bool(cand["driver_success"]),
            performance_score,
        )
        best_rank = (
            bool(best and best["feasible"]),
            bool(best and best.get("driver_success")),
            best_performance_score,
        )
        if best is None or cand_rank > best_rank:
            best = cand
    return best, histories


def _recalibrated_constants(
    spec: VehicleSpec,
    verify: dict[str, Any],
) -> tuple[float, float]:
    """Infer target-sweep balance constants from one OAS-verified design."""
    import math

    from openair.mission.balance import horizontal_tail_aero, thin_airfoil_props

    measured = verify.get("stability_measured") or {}
    trim = verify.get("aero_trim") or {}
    x_np = measured.get("x_np_m")
    washout = trim.get("washout_trim_deg")
    if not isinstance(x_np, (int, float)):
        return spec.solver.np_shift_mac, spec.solver.cm_washout_per_deg

    reference_deg = spec.sketch.le_sweep_deg if spec.sketch is not None else 32.0
    reference_tan = math.tan(math.radians(reference_deg))
    current_tan = math.tan(math.radians(spec.wing.le_sweep_deg))
    ratio = current_tan / reference_tan if abs(reference_tan) > 1e-6 else 1.0
    abs_ratio = max(abs(ratio), 1e-6)
    calibrated_wing_ac = float(x_np)
    if spec.htail.span_m > 0.05:
        tail = horizontal_tail_aero(spec)
        wing_weight = tail["wing_lift_slope_per_rad"] * spec.wing.area_m2
        tail_weight = (
            tail["dynamic_pressure_ratio"]
            * tail["tail_lift_slope_per_rad"]
            * (1.0 - tail["downwash_gradient"])
            * spec.htail.area_m2
        )
        calibrated_wing_ac = (
            float(x_np) * (wing_weight + tail_weight) - tail_weight * tail["x_ac_m"]
        ) / max(wing_weight, 1e-9)
    np_shift = (
        (calibrated_wing_ac - spec.wing.x_le_mac_m) / spec.wing.mac_m - 0.25
    ) / abs_ratio

    cm_washout = spec.solver.cm_washout_per_deg
    if (
        spec.htail.span_m <= 0.05
        and isinstance(washout, (int, float))
        and abs(float(washout) * ratio) > 1e-5
    ):
        measured_sm = measured.get("sm_full")
        cl = trim.get("CL")
        if isinstance(measured_sm, (int, float)) and isinstance(cl, (int, float)):
            cm_ac = thin_airfoil_props(spec.wing.airfoil)["cm_ac"]
            cm_washout = (float(measured_sm) * float(cl) - cm_ac) / (
                float(washout) * ratio
            )
    return float(np_shift), float(cm_washout)


def _recalibrated_tail_incidence_offset(
    spec: VehicleSpec,
    verify: dict[str, Any],
    modeled_incidence_deg: float | None,
) -> float:
    """Shift the low-order fallback-tail trim target onto the OAS solution."""
    if spec.htail.span_m <= 0.05:
        return spec.solver.tail_incidence_offset_deg
    measured = (verify.get("aero_trim") or {}).get("tail_incidence_trim_deg")
    if not isinstance(measured, (int, float)) or not isinstance(
        modeled_incidence_deg, (int, float)
    ):
        return spec.solver.tail_incidence_offset_deg
    residual = float(measured) - float(modeled_incidence_deg)
    return float(spec.solver.tail_incidence_offset_deg + residual)


def _tighten_sm_bounds(
    bounds: tuple[float, float],
    measured: dict[str, Any],
    requested: tuple[float, float],
    modeled_after_recalibration: dict[str, float] | None = None,
) -> tuple[float, float]:
    """Offset the internal band by residual OAS-versus-recalibrated error.

    The NP constant is recalibrated before this adjustment. Applying the full
    pre-calibration OAS miss a second time drove Merlin's internal SM band to
    [0.09, 0.10], even though the new model already reproduced the measured
    neutral point. Use only the residual after recalibration and retain a small
    interior margin for the next optimization.
    """
    modeled = modeled_after_recalibration or {}
    residuals = []
    for key in ("sm_full", "sm_reserve"):
        observed = measured.get(key)
        predicted = modeled.get(key)
        if isinstance(observed, (int, float)) and isinstance(predicted, (int, float)):
            residuals.append(float(observed) - float(predicted))
    if not residuals:
        return bounds
    requested_lo, requested_hi = requested
    margin = 0.002
    lo_eff = max(requested_lo - error + margin for error in residuals)
    hi_eff = min(requested_hi - error - margin for error in residuals)
    if hi_eff - lo_eff < 0.01:
        center = 0.5 * (lo_eff + hi_eff)
        lo_eff, hi_eff = center - 0.005, center + 0.005
    return lo_eff, hi_eff


def _run_calibrated_branch(
    spec: VehicleSpec,
    outdir: Path,
    *,
    source_spec: VehicleSpec | None = None,
    record: bool = False,
) -> dict[str, Any]:
    """Optimize and recalibrate one fixed topology/airfoil branch."""
    sm_lo = spec.mission.static_margin_min
    sm_hi = spec.mission.static_margin_max
    sm_bounds = (sm_lo, sm_hi)
    requested_sm = (sm_lo, sm_hi)
    best: dict[str, Any] | None = None
    histories: list[dict[str, Any]] = []
    calibration_history: list[dict[str, Any]] = []
    verify: dict[str, Any] = {"ok": False}
    working_spec = spec.model_copy(deep=True)
    opt_spec = working_spec
    previous_dash: float | None = None
    inspiration = bool(
        spec.sketch is not None and spec.sketch.treatment == "inspiration"
    )
    calibration_converged = False
    for attempt in range(4):
        best, hist = _optimize_starts(
            working_spec,
            outdir,
            sm_bounds,
            record=record and attempt == 0,
        )
        for candidate in hist:
            candidate["calibration_attempt"] = attempt
        histories.extend(hist)
        best = _merge_fallback(working_spec, best)
        if best is None:
            break
        opt_spec = _apply_dvs(
            working_spec,
            {key: np.array([value]) for key, value in best["dvs"].items()},
        )
        verify = _verify_with_oas(opt_spec, best, source_spec or spec)
        meas = verify.get("stability_measured") or {}
        np_measured = meas.get("x_np_m")
        np_model = meas.get("x_np_model_m")
        np_error_mac = (
            abs(float(np_measured) - float(np_model)) / opt_spec.wing.mac_m
            if isinstance(np_measured, (int, float))
            and isinstance(np_model, (int, float))
            else None
        )
        dash_delta_fraction = (
            abs(float(best["dash_mps"]) - previous_dash) / max(abs(previous_dash), 1e-9)
            if previous_dash is not None
            else None
        )
        dash_stable = (
            dash_delta_fraction is not None and dash_delta_fraction < 0.005
        ) or (not inspiration and previous_dash is None)
        old_np = opt_spec.solver.np_shift_mac
        old_cm = opt_spec.solver.cm_washout_per_deg
        old_tail_offset = opt_spec.solver.tail_incidence_offset_deg
        new_np, new_cm = _recalibrated_constants(opt_spec, verify)
        recalibrated_spec = opt_spec.model_copy(deep=True)
        recalibrated_spec.solver.np_shift_mac = new_np
        recalibrated_spec.solver.cm_washout_per_deg = new_cm
        recalibrated_balance = balance_report(
            recalibrated_spec,
            best["mtow_kg"],
            best["dvs"]["fuel"],
        )
        tail_incidence_model_before_offset = (
            recalibrated_balance.tail_incidence_required_deg
        )
        new_tail_offset = _recalibrated_tail_incidence_offset(
            recalibrated_spec,
            verify,
            tail_incidence_model_before_offset,
        )
        recalibrated_spec.solver.tail_incidence_offset_deg = new_tail_offset
        recalibrated_balance = balance_report(
            recalibrated_spec,
            best["mtow_kg"],
            best["dvs"]["fuel"],
        )
        modeled_after = {
            "sm_full": recalibrated_balance.sm_full,
            "sm_reserve": recalibrated_balance.sm_reserve,
        }
        next_sm_bounds = _tighten_sm_bounds(
            sm_bounds,
            meas,
            requested_sm,
            modeled_after,
        )
        calibration_converged = bool(
            verify.get("ok")
            and np_error_mac is not None
            and np_error_mac <= 0.05
            and dash_stable
        )
        calibration_history.append(
            {
                "attempt": attempt,
                "sm_bounds_internal": list(sm_bounds),
                "sm_bounds_next": list(next_sm_bounds),
                "sm_measured_full": meas.get("sm_full"),
                "sm_measured_reserve": meas.get("sm_reserve"),
                "sm_measured_ok": bool(meas.get("ok")),
                "sm_model_after_recalibration_full": modeled_after["sm_full"],
                "sm_model_after_recalibration_reserve": modeled_after["sm_reserve"],
                "x_np_measured_m": np_measured,
                "x_np_model_m": np_model,
                "np_error_mac": np_error_mac,
                "np_shift_mac_before": old_np,
                "np_shift_mac_after": new_np,
                "cm_washout_per_deg_before": old_cm,
                "cm_washout_per_deg_after": new_cm,
                "tail_incidence_offset_deg_before": old_tail_offset,
                "tail_incidence_offset_deg_after": new_tail_offset,
                "tail_incidence_oas_deg": (verify.get("aero_trim") or {}).get(
                    "tail_incidence_trim_deg"
                ),
                "tail_incidence_model_before_offset_deg": (
                    tail_incidence_model_before_offset
                ),
                "tail_incidence_model_after_offset_deg": (
                    recalibrated_balance.tail_incidence_required_deg
                ),
                "dash_mps": best.get("dash_mps"),
                "dash_delta_fraction": dash_delta_fraction,
                "verify_ok": bool(verify.get("ok")),
                "converged": calibration_converged,
            }
        )
        opt_spec.solver.np_shift_mac = new_np
        opt_spec.solver.cm_washout_per_deg = new_cm
        opt_spec.solver.tail_incidence_offset_deg = new_tail_offset
        if (
            calibration_converged
            or not best.get("feasible")
            or not best.get(
                "driver_success",
                best.get("start") == "sized_fallback",
            )
        ):
            break
        if (
            attempt > 0
            and next_sm_bounds == sm_bounds
            and new_np == old_np
            and new_cm == old_cm
            and new_tail_offset == old_tail_offset
        ):
            break
        previous_dash = float(best["dash_mps"])
        working_spec = opt_spec.model_copy(deep=True)
        sm_bounds = next_sm_bounds

    # Publish the OAS-trimmed control setting so the delivered case is trimmed
    # as-specced, then verify the exact serialized setting below.
    trim_data = verify.get("aero_trim") or {}
    trim_washout = trim_data.get("washout_trim_deg")
    trim_incidence = trim_data.get("tail_incidence_trim_deg")
    trim_elevon = trim_data.get("elevon_trim_deg")
    published_control = False
    branch_control = pitch_trim_control(opt_spec)
    branch_surface = (
        pitch_control_surface(opt_spec) if branch_control == "elevon" else None
    )
    if (
        best is not None
        and verify.get("ok")
        and branch_control == "tail_incidence"
        and isinstance(trim_incidence, (int, float))
    ):
        opt_spec.htail.incidence_deg = float(round(trim_incidence, 2))
        best["dvs"]["htail_incidence"] = opt_spec.htail.incidence_deg
        published_control = True
    elif (
        best is not None
        and verify.get("ok")
        and branch_control == "elevon"
        and branch_surface is not None
        and isinstance(trim_elevon, (int, float))
        and within_travel(branch_surface, float(trim_elevon), 0.5)
    ):
        set_pitch_trim_deflection(opt_spec, float(round(trim_elevon, 2)))
        published_control = True
    elif (
        best is not None
        and verify.get("ok")
        and branch_control == "wing_twist"
        and isinstance(trim_washout, (int, float))
    ):
        opt_spec.wing.twist_tip_deg = float(
            round(opt_spec.wing.twist_root_deg - trim_washout, 2)
        )
        best["dvs"]["twist_tip"] = opt_spec.wing.twist_tip_deg
        published_control = True

    if best is None:
        best = {
            "start": "no_candidate",
            "feasible": False,
            "driver_success": False,
            "dvs": _spec_dvs(opt_spec),
        }
    else:
        refreshed = evaluate_design(opt_spec)
        for key, value in refreshed.items():
            if key in best:
                best[key] = value
        best["feasible"] = _is_feasible(best, opt_spec)
        if published_control:
            # The trim solve evaluated the setting we just published, but the
            # stored verification still described the pre-snap spec. Re-run
            # the complete OAS/wingbox check so mdo.json is evidence for the
            # exact serialized aircraft.
            verify = _verify_with_oas(opt_spec, best, source_spec or spec)
            final_measured = verify.get("stability_measured") or {}
            final_np_measured = final_measured.get("x_np_m")
            final_np_model = final_measured.get("x_np_model_m")
            final_np_error_mac = (
                abs(float(final_np_measured) - float(final_np_model))
                / opt_spec.wing.mac_m
                if isinstance(final_np_measured, (int, float))
                and isinstance(final_np_model, (int, float))
                else None
            )
            calibration_converged = bool(
                calibration_converged
                and verify.get("ok")
                and final_np_error_mac is not None
                and final_np_error_mac <= 0.05
            )
            if calibration_history:
                calibration_history[-1]["final_published_verify_ok"] = bool(
                    verify.get("ok")
                )
                calibration_history[-1]["final_published_np_error_mac"] = (
                    final_np_error_mac
                )
                calibration_history[-1]["converged"] = calibration_converged

    return {
        "ok": bool(best["feasible"])
        and bool(best.get("driver_success", best.get("start") == "sized_fallback"))
        and bool(verify.get("ok"))
        and bool(calibration_converged or not inspiration),
        "best": best,
        "starts": histories,
        "calibration_history": calibration_history,
        "calibration_converged": bool(calibration_converged or not inspiration),
        # Backward-compatible alias for consumers written before the general loop.
        "sm_calibration": calibration_history,
        "oas_verify": verify,
        "dv_bounds": {k: list(v) for k, v in dv_bounds_for(spec).items()},
        "_optimized_spec": opt_spec,
    }


def _enable_htail_fallback(spec: VehicleSpec) -> VehicleSpec:
    """Create the bounded small-tail repair topology from a tailless candidate."""
    from openair.mission.balance import balance_report

    repaired = spec.model_copy(deep=True)
    # A bounded tail should repair topology, not compound a nose-down camber
    # branch that already exhausted the tailless control range.
    repaired.wing.airfoil = "0012"
    length = repaired.fuselage.length_m
    repaired.htail.span_m = min(max(0.40 * repaired.wing.span_m, 0.70), 1.60)
    repaired.htail.root_chord_m = min(
        max(0.32 * repaired.wing.root_chord_m, 0.22),
        0.42,
    )
    repaired.htail.taper = 0.55
    repaired.htail.le_sweep_deg = 15.0
    repaired.htail.t_over_c = 0.10
    repaired.htail.x_le_m = max(
        0.55 * length,
        length - repaired.htail.root_chord_m - 0.04,
    )
    repaired.htail.z_m = max(repaired.wing.z_root_m + 0.12, 0.10)
    repaired.htail.incidence_deg = 0.0
    metrics = evaluate_design(repaired)
    bal = balance_report(
        repaired,
        metrics["mtow_kg"],
        repaired.mass.fuel_mass_kg,
    )
    if isinstance(bal.tail_incidence_required_deg, (int, float)):
        repaired.htail.incidence_deg = min(
            max(float(bal.tail_incidence_required_deg), -10.0),
            10.0,
        )
    return repaired


def _branch_rank(result: dict[str, Any]) -> tuple[bool, bool, bool, float]:
    best = result.get("best") or {}
    objective = best.get("objective")
    score = (
        -float(objective)
        if isinstance(objective, (int, float))
        else float(best.get("dash_mps", float("-inf")))
    )
    return (
        bool(result.get("ok")),
        bool(best.get("feasible")),
        bool(best.get("driver_success")),
        score,
    )


def _branch_record(
    name: str,
    result: dict[str, Any],
    topology: str,
    airfoil: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "topology": topology,
        "airfoil": airfoil,
        "ok": bool(result.get("ok")),
        "best": result.get("best"),
        "calibration_history": result.get("calibration_history", []),
        "calibration_converged": bool(result.get("calibration_converged")),
        "oas_verify": result.get("oas_verify"),
        "dv_bounds": result.get("dv_bounds"),
    }


def _set_prior_coordinate(
    spec: VehicleSpec,
    key: str,
    value: float,
) -> None:
    length = spec.fuselage.length_m
    setters = {
        "span_over_length": lambda: setattr(spec.wing, "span_m", value * length),
        "root_over_length": lambda: setattr(
            spec.wing,
            "root_chord_m",
            value * length,
        ),
        "le_sweep_deg": lambda: setattr(spec.wing, "le_sweep_deg", value),
        "taper": lambda: setattr(spec.wing, "taper", value),
        "x_le_root_over_length": lambda: setattr(
            spec.wing,
            "x_le_root_m",
            value * length,
        ),
        "fin_span_m": lambda: setattr(spec.vtail, "span_m", value),
        "fin_root_chord_m": lambda: setattr(
            spec.vtail,
            "root_chord_m",
            value,
        ),
        "fin_le_sweep_deg": lambda: setattr(
            spec.vtail,
            "le_sweep_deg",
            value,
        ),
        "fin_cant_deg": lambda: setattr(spec.vtail, "cant_deg", value),
        "fin_x_le_m": lambda: setattr(spec.vtail, "x_le_m", value),
    }
    setters[key]()


def _constraint_failures(
    metrics: dict[str, float],
    spec: VehicleSpec,
) -> list[str]:
    lo = spec.mission.static_margin_min
    hi = spec.mission.static_margin_max
    trim_gap_limit = 1.5 if spec.htail.span_m > 0.05 else 0.75
    checks = (
        (
            "endurance",
            not spec.mission.endurance_required
            or metrics["endurance_deficit_s"] <= 0.0,
        ),
        ("wing structure", metrics["failure"] <= 0.05),
        ("fuel packing", metrics["packing_violation"] <= 0.001),
        ("payload/engine clearance", metrics["bay_clearance_m"] >= -0.005),
        ("cruise thrust", metrics["thrust_margin_cruise"] >= -0.02),
        ("full-fuel static margin", lo - 0.01 <= metrics["sm_full"] <= hi + 0.01),
        (
            "reserve-fuel static margin",
            lo - 0.01 <= metrics["sm_reserve"] <= hi + 0.01,
        ),
        ("stall speed", metrics["vstall_margin_mps"] <= 0.0),
        ("pitch trim", abs(metrics["washout_gap_deg"]) <= trim_gap_limit),
        ("minimum fin volume", metrics["vv_lower_violation"] <= 1e-6),
        ("maximum fin volume", metrics["vv_upper_violation"] <= 1e-4),
        ("fin trailing edge within body", metrics["fin_te_overhang_m"] <= 1e-4),
    )
    return [name for name, passed in checks if not passed]


def _departure_audit(
    source: VehicleSpec,
    delivered: VehicleSpec,
    branches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Explain every delivered soft-prior departure with a clamp study."""
    delivered_metrics = evaluate_design(delivered)
    delivered_objective = (
        -delivered_metrics["dash_mps"] / 100.0
        + delivered.sketch.fidelity_weight * delivered_metrics["fidelity_penalty"]
        if delivered.sketch is not None
        else -delivered_metrics["dash_mps"] / 100.0
    )
    departures: list[dict[str, Any]] = []
    for key, row in sketch_prior_rows(delivered).items():
        if row["within_tolerance"]:
            continue
        direction = 1.0 if row["got"] > row["target"] else -1.0
        clamped_value = row["target"] + direction * row["tol"]
        clamped = delivered.model_copy(deep=True)
        _set_prior_coordinate(clamped, key, clamped_value)
        clamped_metrics = evaluate_design(clamped)
        failures = _constraint_failures(clamped_metrics, clamped)
        clamped_objective = (
            -clamped_metrics["dash_mps"] / 100.0
            + clamped.sketch.fidelity_weight * clamped_metrics["fidelity_penalty"]
        )
        dash_cost = delivered_metrics["dash_mps"] - clamped_metrics["dash_mps"]
        objective_cost = clamped_objective - delivered_objective
        if failures:
            reason_code = "constraint_repair"
            reason = (
                "Clamping to the one-tolerance sketch edge breaks "
                + ", ".join(failures)
                + "."
            )
        elif objective_cost > 1e-4:
            reason_code = "performance_trade"
            reason = (
                f"Clamping to the sketch edge worsens the weighted objective "
                f"by {objective_cost:.4f} and costs {dash_cost:.2f} m/s dash."
            )
        else:
            reason_code = "numerical_multivariate_trade"
            reason = (
                f"The value is only {row['excess_tolerance']:.4f} tolerance "
                "widths beyond the sketch edge. Its isolated clamp remains "
                f"feasible and changes the weighted objective by "
                f"{objective_cost:.2e}; retain transparently as optimizer "
                "numerical/multivariate tolerance."
            )
        departures.append(
            {
                "parameter": key,
                "sketch_target": row["target"],
                "sketch_tolerance": row["tol"],
                "delivered": row["got"],
                "deviation_tolerance_multiple": row["normalized_deviation"],
                "excess_tolerance_multiple": row["excess_tolerance"],
                "hard_limit_tolerance_multiple": (
                    delivered.sketch.hard_scale if delivered.sketch is not None else 1.0
                ),
                "clamped_value": clamped_value,
                "reason_code": reason_code,
                "reason": reason,
                "clamp_study": {
                    "constraint_failures": failures,
                    "dash_mps": clamped_metrics["dash_mps"],
                    "dash_cost_mps": dash_cost,
                    "objective_delta": objective_cost,
                },
            }
        )
    if source.wing.airfoil != delivered.wing.airfoil:
        selected = next(
            (
                branch
                for branch in branches
                if branch["airfoil"] == delivered.wing.airfoil
                and branch["topology"]
                == ("htail" if delivered.htail.span_m > 0.05 else "tailless")
            ),
            {},
        )
        departures.append(
            {
                "parameter": "airfoil_family",
                "sketch_target": source.wing.airfoil,
                "delivered": delivered.wing.airfoil,
                "reason_code": "discrete_branch_selection",
                "reason": (
                    "The delivered airfoil branch had the best verified weighted "
                    "objective among the 0012/2412/4412 candidates."
                ),
                "branch_ok": selected.get("ok"),
            }
        )
    if source.htail.span_m <= 0.05 and delivered.htail.span_m > 0.05:
        departures.append(
            {
                "parameter": "horizontal_tail_topology",
                "sketch_target": "tailless",
                "delivered": {
                    "span_m": delivered.htail.span_m,
                    "root_chord_m": delivered.htail.root_chord_m,
                    "x_le_m": delivered.htail.x_le_m,
                    "incidence_deg": delivered.htail.incidence_deg,
                },
                "reason_code": "trim_fallback",
                "reason": (
                    "All tailless airfoil branches failed the combined closed-form "
                    "and OAS trim/stability verification, so the bounded horizontal-"
                    "tail fallback was enabled."
                ),
            }
        )
    return departures


def _fidelity_sweep(
    delivered: VehicleSpec,
    selected: dict[str, Any],
    outdir: Path,
) -> list[dict[str, Any]]:
    """Run cheap closed-form alternatives around the OAS-verified delivery."""
    if delivered.sketch is None or delivered.sketch.treatment != "inspiration":
        return []
    records: list[dict[str, Any]] = []
    for weight in (2.0, 1.0, 0.25):
        if weight == 1.0:
            metrics = evaluate_design(delivered)
            records.append(
                {
                    "fidelity_weight": weight,
                    "delivered": True,
                    "verification": "OAS",
                    "ok": bool(selected.get("ok")),
                    "dash_mps": metrics["dash_mps"],
                    "fidelity_penalty": metrics["fidelity_penalty"],
                    "objective": (
                        -metrics["dash_mps"] / 100.0
                        + weight * metrics["fidelity_penalty"]
                    ),
                    "dvs": (selected.get("best") or {}).get("dvs"),
                }
            )
            continue
        sweep_spec = delivered.model_copy(deep=True)
        sweep_spec.sketch.fidelity_weight = weight
        best, starts = _optimize_starts(
            sweep_spec,
            outdir,
            (
                sweep_spec.mission.static_margin_min,
                sweep_spec.mission.static_margin_max,
            ),
            record=False,
        )
        best = _merge_fallback(sweep_spec, best)
        candidate_spec = (
            _apply_dvs(
                sweep_spec,
                {
                    key: np.array([value])
                    for key, value in (best.get("dvs") or {}).items()
                },
            )
            if best is not None
            else sweep_spec
        )
        metrics = evaluate_design(candidate_spec)
        records.append(
            {
                "fidelity_weight": weight,
                "delivered": False,
                "verification": "closed_form_only",
                "ok": bool(
                    best
                    and best.get("feasible")
                    and best.get(
                        "driver_success",
                        best.get("start") == "sized_fallback",
                    )
                ),
                "dash_mps": metrics["dash_mps"],
                "fidelity_penalty": metrics["fidelity_penalty"],
                "objective": (
                    -metrics["dash_mps"] / 100.0 + weight * metrics["fidelity_penalty"]
                ),
                "dvs": best.get("dvs") if best else None,
                "start_count": len(starts),
            }
        )
    return records


def _with_serialized_hybrid_calibration(
    spec: VehicleSpec,
    outdir: Path,
) -> tuple[VehicleSpec, dict[str, Any] | None]:
    """Carry baseline component evidence into the same-run MDO model."""
    calibrated = spec.model_copy(deep=True)
    if spec.solver.stability_method != "hybrid_component":
        return calibrated, None
    aero_path = outdir / "aero.json"
    if not aero_path.is_file():
        return calibrated, {"ok": False, "reason": "missing_baseline_aero_json"}
    try:
        aero = json.loads(aero_path.read_text(encoding="utf-8"))
        hybrid = (aero.get("stability") or {}).get("hybrid_component") or {}
        if not hybrid.get("ok"):
            return calibrated, hybrid or {
                "ok": False,
                "reason": "missing_hybrid_component_evidence",
            }
        from openair.aero.vspaero_backend import verify_hybrid_artifact

        hybrid = verify_hybrid_artifact(hybrid, outdir)
        if not hybrid.get("ok"):
            return calibrated, hybrid
        calibrated.solver.wing_body_np_mac = float(hybrid["neutral_point_mac"])
        calibrated.solver.wing_body_cl_alpha_per_deg = float(hybrid["cl_alpha_per_deg"])
        return calibrated, hybrid
    except Exception as exc:
        return calibrated, {
            "ok": False,
            "reason": f"invalid_baseline_hybrid_evidence: {exc}",
        }


def _run_reproduction_branch(
    spec: VehicleSpec,
    source_spec: VehicleSpec,
    hybrid_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Freeze source design coordinates and close only trim deterministically."""
    delivered = spec.model_copy(deep=True)
    control = pitch_trim_control(delivered)
    pitch_surface = pitch_control_surface(delivered) if control == "elevon" else None
    initial = evaluate_design(delivered)
    bal = balance_report(
        delivered,
        initial["mtow_kg"],
        delivered.mass.fuel_mass_kg,
    )
    if (
        control == "tail_incidence"
        and isinstance(bal.tail_incidence_required_deg, (int, float))
        and abs(float(bal.tail_incidence_required_deg)) <= 10.0
    ):
        delivered.htail.incidence_deg = float(bal.tail_incidence_required_deg)
    elif (
        control == "elevon"
        and pitch_surface is not None
        and isinstance(bal.elevon_required_deg, (int, float))
        and within_travel(pitch_surface, float(bal.elevon_required_deg), 0.5)
    ):
        # Closed-form thin-airfoil starting point; the OAS trim below is the
        # value that gets published.
        set_pitch_trim_deflection(delivered, float(bal.elevon_required_deg))

    metrics = evaluate_design(delivered)
    best: dict[str, Any] = {
        "start": "deterministic_reference_closure",
        **metrics,
        "dvs": _spec_dvs(delivered),
        "driver_success": True,
        "driver_status": "deterministic_reference_closure",
        "driver_iterations": 0,
    }
    best["feasible"] = _is_feasible(best, delivered)
    verify = _verify_with_oas(delivered, best, source_spec)
    np_calibration: dict[str, Any] | None = None

    # ``np_shift_mac`` is a low-order balance-model constant, not a source
    # coordinate.  A reproduction must keep its physical geometry frozen, but
    # may identify this constant from the same-run independent OAS derivative
    # before the low-order model is used as traceability evidence downstream.
    stability = verify.get("stability_measured") or {}
    measured_np = stability.get("x_np_m")
    modeled_np = stability.get("x_np_model_m")
    if (
        delivered.solver.stability_method == "lifting_surface"
        and isinstance(measured_np, (int, float))
        and isinstance(modeled_np, (int, float))
    ):
        old_shift = float(delivered.solver.np_shift_mac)
        correction_mac = (float(measured_np) - float(modeled_np)) / delivered.wing.mac_m
        delivered.solver.np_shift_mac = _calibrated_np_shift_mac(
            delivered,
            float(measured_np),
            float(modeled_np),
        )
        metrics = evaluate_design(delivered)
        best.update(metrics)
        best["dvs"] = _spec_dvs(delivered)
        best["feasible"] = _is_feasible(best, delivered)
        verify = _verify_with_oas(delivered, best, source_spec)
        final_stability = verify.get("stability_measured") or {}
        final_measured = final_stability.get("x_np_m")
        final_modeled = final_stability.get("x_np_model_m")
        final_error_mac = (
            abs(float(final_measured) - float(final_modeled)) / delivered.wing.mac_m
            if isinstance(final_measured, (int, float))
            and isinstance(final_modeled, (int, float))
            else float("inf")
        )
        np_calibration = {
            "parameter": "solver.np_shift_mac",
            "evidence": "same-run independent OAS dCM/dCL",
            "old_value": old_shift,
            "correction_mac": correction_mac,
            "new_value": float(delivered.solver.np_shift_mac),
            "error_before_mac": abs(float(measured_np) - float(modeled_np))
            / delivered.wing.mac_m,
            "error_after_mac": final_error_mac,
            "converged": final_error_mac <= 0.05,
        }

    # Publish the independently solved OAS trim setting, the one explicitly
    # permitted control closure in reproduction mode, then verify that exact
    # serialized setting.
    aero_trim = verify.get("aero_trim") or {}
    trim_incidence = aero_trim.get("tail_incidence_trim_deg")
    trim_elevon = aero_trim.get("elevon_trim_deg")
    if (
        control == "tail_incidence"
        and isinstance(trim_incidence, (int, float))
        and abs(float(trim_incidence)) <= 10.0
    ):
        delivered.htail.incidence_deg = float(round(trim_incidence, 4))
        metrics = evaluate_design(delivered)
        best.update(metrics)
        best["dvs"] = _spec_dvs(delivered)
        best["feasible"] = _is_feasible(best, delivered)
        verify = _verify_with_oas(delivered, best, source_spec)
    elif (
        control == "elevon"
        and pitch_surface is not None
        and isinstance(trim_elevon, (int, float))
        and within_travel(pitch_surface, float(trim_elevon), 0.5)
    ):
        set_pitch_trim_deflection(delivered, float(round(trim_elevon, 4)))
        metrics = evaluate_design(delivered)
        best.update(metrics)
        best["dvs"] = _spec_dvs(delivered)
        best["feasible"] = _is_feasible(best, delivered)
        verify = _verify_with_oas(delivered, best, source_spec)

    hybrid_ok = spec.solver.stability_method != "hybrid_component" or bool(
        hybrid_evidence and hybrid_evidence.get("ok")
    )
    calibration_ok = bool(
        hybrid_ok and (np_calibration is None or np_calibration.get("converged"))
    )
    calibration = {
        "kind": "same-run component analysis",
        "hybrid_evidence": hybrid_evidence,
        "lifting_surface_np_calibration": np_calibration,
        "ok": calibration_ok,
    }
    return {
        "ok": bool(best["feasible"] and verify.get("ok") and calibration_ok),
        "best": best,
        "starts": [best],
        "calibration_history": [calibration],
        "calibration_converged": calibration_ok,
        "sm_calibration": [calibration],
        "oas_verify": verify,
        "dv_bounds": {},
        "reference_closure": {
            "frozen_coordinates": [
                key
                for key in _spec_dvs(source_spec)
                if not (control == "tail_incidence" and key == "htail_incidence")
            ],
            "allowed_control": {
                "tail_incidence": "htail_incidence",
                "elevon": "elevon_deflection",
                "wing_twist": None,
            }[control],
            "pitch_trim_control": control,
            "elevon_surface_id": pitch_surface.id if pitch_surface else None,
            "elevon_trim_deflection_deg": (
                float(pitch_surface.trim_deflection_deg) if pitch_surface else None
            ),
            "twist_frozen": control != "wing_twist",
        },
        "_optimized_spec": delivered,
    }


def run_mdo_stage(
    spec: VehicleSpec,
    outdir: Path,
    case_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate discrete repair branches and publish the best verified design."""
    spec.assert_cross_model_invariants()
    outdir.mkdir(parents=True, exist_ok=True)
    inspiration = bool(
        spec.sketch is not None and spec.sketch.treatment == "inspiration"
    )
    primary_spec, hybrid_evidence = _with_serialized_hybrid_calibration(
        spec,
        outdir,
    )
    if inspiration:
        primary_spec.sketch.fidelity_weight = 1.0
    branch_results: list[tuple[str, str, str, dict[str, Any]]] = []
    reproduction = bool(
        spec.sketch is not None and spec.sketch.treatment == "reproduction"
    )
    if reproduction:
        topology = "htail" if primary_spec.htail.span_m > 0.05 else "tailless"
        result = _run_reproduction_branch(
            primary_spec,
            spec,
            hybrid_evidence,
        )
        branch_results.append(
            (
                f"reference-{topology}-{primary_spec.wing.airfoil}",
                topology,
                primary_spec.wing.airfoil,
                result,
            )
        )
    else:
        airfoils = ("0012", "2412", "4412") if inspiration else (spec.wing.airfoil,)
        for index, airfoil in enumerate(airfoils):
            branch_spec = primary_spec.model_copy(deep=True)
            branch_spec.wing.airfoil = airfoil
            topology = "htail" if branch_spec.htail.span_m > 0.05 else "tailless"
            name = f"{topology}-{airfoil}"
            result = _run_calibrated_branch(
                branch_spec,
                outdir,
                source_spec=spec,
                record=index == 0,
            )
            branch_results.append((name, topology, airfoil, result))

    successful_primary = [item for item in branch_results if item[3].get("ok")]
    if inspiration and primary_spec.htail.span_m <= 0.05 and not successful_primary:
        diagnostic = max(branch_results, key=lambda item: _branch_rank(item[3]))
        repaired = _enable_htail_fallback(diagnostic[3]["_optimized_spec"])
        name = f"htail-{repaired.wing.airfoil}"
        result = _run_calibrated_branch(
            repaired,
            outdir,
            source_spec=spec,
            record=False,
        )
        branch_results.append((name, "htail", repaired.wing.airfoil, result))

    selectable = successful_primary or branch_results
    selected_name, selected_topology, selected_airfoil, selected = max(
        selectable,
        key=lambda item: _branch_rank(item[3]),
    )
    opt_spec = selected["_optimized_spec"]
    branch_records = [
        _branch_record(name, result, topology, airfoil)
        for name, topology, airfoil, result in branch_results
    ]
    sketch_departures = (
        _departure_audit(spec, opt_spec, branch_records) if inspiration else []
    )
    fidelity_sweep = _fidelity_sweep(opt_spec, selected, outdir) if inspiration else []
    yaml_path = (
        optimized_design_for(case_path)
        if case_path is not None
        else outdir / "design.yaml"
    )
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(yaml_path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(opt_spec.model_dump(mode="python"), stream, sort_keys=False)

    public = {key: value for key, value in selected.items() if not key.startswith("_")}
    public.update(
        {
            "branch_selected": selected_name,
            "branch_topology": selected_topology,
            "branch_airfoil": selected_airfoil,
            "branches": branch_records,
            "sketch_departures": sketch_departures,
            "fidelity_sweep": fidelity_sweep,
            "optimized_yaml": str(yaml_path),
        }
    )
    return public


def _merge_fallback(spec: VehicleSpec, best: dict[str, Any] | None) -> dict[str, Any]:
    # If SLSQP never found a feasible point, fall back to the sized closed design
    # evaluated through the SAME physics (no hand-set numbers).
    sized_metrics = evaluate_design(spec)
    sized_cand = {
        "start": "sized_fallback",
        **{
            k: sized_metrics[k]
            for k in (
                "dash_mps",
                "endurance_s",
                "endurance_deficit_s",
                "failure",
                "packing_violation",
                "bay_clearance_m",
                "thrust_margin_cruise",
                "sm_full",
                "sm_reserve",
                "vstall_margin_mps",
                "washout_gap_deg",
                "vv_lower_violation",
                "vv_upper_violation",
                "fin_te_overhang_m",
                "fidelity_penalty",
                "mtow_kg",
                "lod",
            )
        },
        "dvs": _spec_dvs(spec),
    }
    sized_cand["feasible"] = _is_feasible(sized_cand, spec)
    if (best is None or not best.get("feasible")) and sized_cand["feasible"]:
        best = sized_cand
    return best


def _verify_with_oas(
    opt_spec: VehicleSpec, best: dict[str, Any], spec: VehicleSpec
) -> dict[str, Any]:
    """Post-opt trim/wingbox verification plus stability evidence.

    Lifting-surface mode measures dCM/dCL independently with OAS. Hybrid mode
    carries the same-run VSPAERO wing/body constants through the component
    balance model; that static margin is explicitly provenance-backed model
    output, not an independent OAS measurement.
    """
    try:
        from openair.aero.oas_backend import measure_neutral_point, trim_pitch
        from openair.mission.balance import balance_report as _bal
        from openair.mission.balance import thin_airfoil_props
        from openair.structures.oas_wingbox import run_aerostruct

        bal = _bal(opt_spec, best["mtow_kg"], best["dvs"]["fuel"])
        sect = thin_airfoil_props(opt_spec.wing.airfoil)
        v_c, _ = cruise_tas(opt_spec, best["mtow_kg"])
        trim = trim_pitch(
            opt_spec,
            opt_spec.mission.cruise_altitude_m,
            v_c,
            best["mtow_kg"] * G0,
            bal.x_cg_full_m,
            cm_offset=sect["cm_ac"],
        )
        lifting_surface_np = measure_neutral_point(
            opt_spec, opt_spec.mission.cruise_altitude_m, v_c, bal.x_cg_full_m
        )
        if (
            opt_spec.solver.stability_method == "hybrid_component"
            and opt_spec.solver.wing_body_np_mac is not None
            and opt_spec.solver.wing_body_cl_alpha_per_deg is not None
        ):
            np_meas = {
                "x_np_m": bal.x_np_m,
                "dcm_dcl": ((bal.x_cg_full_m - bal.x_np_m) / opt_spec.wing.mac_m),
                "method": "hybrid_component",
            }
        else:
            np_meas = {**lifting_surface_np, "method": "lifting_surface"}
        mac = opt_spec.wing.mac_m
        sm_full = (np_meas["x_np_m"] - bal.x_cg_full_m) / mac
        sm_reserve = (np_meas["x_np_m"] - bal.x_cg_reserve_m) / mac
        lo, hi = spec.mission.static_margin_min, spec.mission.static_margin_max
        sm_meas_ok = (lo <= sm_full <= hi) and (lo <= sm_reserve <= hi)
        struct = run_aerostruct(
            opt_spec,
            opt_spec.mission.cruise_altitude_m,
            v_c,
            opt_spec.mission.limit_positive_g,
            min(trim["alpha_deg"] * opt_spec.mission.limit_positive_g, 12.0),
            best["mtow_kg"],
            best["dvs"]["fuel"],
        )
        tail_enabled = opt_spec.htail.span_m > 0.05
        trim_values = trim_control_values(opt_spec, trim)
        trim_control_gap = float(trim_values["gap_deg"])
        return {
            "aero_trim": {
                "converged": trim.get("trim_converged"),
                "control": trim.get("trim_control", "wing_twist"),
                "alpha_deg": trim.get("alpha_deg"),
                "washout_trim_deg": trim.get("washout_trim_deg"),
                "washout_spec_deg": opt_spec.wing.twist_root_deg
                - opt_spec.wing.twist_tip_deg,
                "tail_incidence_trim_deg": trim.get("tail_incidence_trim_deg"),
                "tail_incidence_spec_deg": (
                    opt_spec.htail.incidence_deg if tail_enabled else None
                ),
                "elevon_trim_deg": trim.get("elevon_trim_deg"),
                "elevon_spec_deg": (
                    trim_values["spec_deg"]
                    if trim_values["control"] == "elevon"
                    else None
                ),
                "elevon_travel_deg": trim.get("elevon_travel_deg"),
                "elevon_within_travel": trim.get("elevon_within_travel"),
                "dcm_ddelta_per_deg": trim.get("dcm_ddelta_per_deg"),
                "twist_frozen": bool(trim.get("twist_frozen", False)),
                "control_gap_deg": trim_control_gap,
                "cm_residual": trim.get("cm_residual"),
                "CL": trim.get("CL"),
                "lod": trim.get("lift_n", 0.0) / max(trim.get("drag_n", 1.0), 1e-6),
            },
            "stability_measured": {
                "x_np_m": np_meas["x_np_m"],
                "x_np_model_m": bal.x_np_m,
                "method": np_meas["method"],
                "independent_measurement": np_meas["method"] == "lifting_surface",
                "evidence_kind": (
                    "independent_oas_derivative"
                    if np_meas["method"] == "lifting_surface"
                    else "same_run_component_model"
                ),
                "lifting_surface_diagnostic": lifting_surface_np,
                "sm_full": sm_full,
                "sm_reserve": sm_reserve,
                "band": [lo, hi],
                "ok": bool(sm_meas_ok),
            },
            "structures": {
                "ok": struct.get("ok"),
                "failure": struct.get("failure"),
                "structural_mass_kg": struct.get("structural_mass_kg"),
            },
            "ok": bool(
                trim.get("trim_converged")
                and sm_meas_ok
                and struct.get("ok")
                and struct.get("failure", 1.0) <= 0.0
                and trim_control_gap <= 1.0
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
