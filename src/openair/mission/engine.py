"""K-450G5 engine deck.

Published spec (KingTech):
  diameter 152.6 mm, length 374 mm, dry mass 4.0 kg
  max thrust 45 kgf (441.3 N), fuel flow 1100 g/min at that condition

Everything else is an explicit engineering model, not vendor data.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from openair.atmosphere import isa
from openair.schemas import EngineDeckPoint, EngineDeckSpec, EngineSpec
from openair.units import G0


@dataclass(frozen=True)
class EngineState:
    thrust_available_n: float
    thrust_used_n: float
    throttle: float
    tsfc_mass_kg_per_n_s: float
    tsfc_weight_per_s: float
    fuel_flow_kg_s: float
    sigma: float
    mach: float
    deck_name: str | None = None
    deck_clamped: bool = False


@dataclass(frozen=True)
class EngineDeckValue:
    """Interpolated propulsion-installation output at one operating point."""

    thrust_n: float
    fuel_flow_kg_s: float
    throttle: float
    clamped: bool


def _linear_curve_value(
    points: list[EngineDeckPoint],
    throttle: float,
    extrapolation: str,
) -> EngineDeckValue:
    ordered = sorted(points, key=lambda point: point.throttle)
    lower = ordered[0].throttle
    upper = ordered[-1].throttle
    if extrapolation == "error" and not lower <= throttle <= upper:
        raise ValueError(
            f"engine-deck throttle {throttle} is outside [{lower}, {upper}]"
        )
    effective = min(max(throttle, lower), upper)
    clamped = effective != throttle
    if effective <= lower:
        point = ordered[0]
        return EngineDeckValue(
            point.thrust_n,
            point.fuel_flow_kg_s,
            effective,
            clamped,
        )
    if effective >= upper:
        point = ordered[-1]
        return EngineDeckValue(
            point.thrust_n,
            point.fuel_flow_kg_s,
            effective,
            clamped,
        )
    for left, right in zip(ordered, ordered[1:]):
        if left.throttle <= effective <= right.throttle:
            fraction = (effective - left.throttle) / (right.throttle - left.throttle)
            return EngineDeckValue(
                thrust_n=left.thrust_n + fraction * (right.thrust_n - left.thrust_n),
                fuel_flow_kg_s=left.fuel_flow_kg_s
                + fraction * (right.fuel_flow_kg_s - left.fuel_flow_kg_s),
                throttle=effective,
                clamped=clamped,
            )
    raise RuntimeError("validated engine-deck curve could not be interpolated")


def lookup_engine_deck(
    deck: EngineDeckSpec,
    altitude_m: float,
    mach: float,
    throttle: float,
) -> EngineDeckValue:
    """Interpolate sparse rated curves without pretending they form a full grid.

    Throttle is interpolated linearly within each measured condition curve.
    Curves are then blended by inverse squared distance in scaled altitude/Mach
    space. Outside the tabulated box, inputs are either clamped or rejected.
    """

    curves: dict[tuple[float, float], list[EngineDeckPoint]] = {}
    for point in deck.points:
        curves.setdefault((point.altitude_m, point.mach), []).append(point)

    altitudes = [condition[0] for condition in curves]
    machs = [condition[1] for condition in curves]
    alt_lo, alt_hi = min(altitudes), max(altitudes)
    mach_lo, mach_hi = min(machs), max(machs)
    if deck.extrapolation == "error" and (
        not alt_lo <= altitude_m <= alt_hi or not mach_lo <= mach <= mach_hi
    ):
        raise ValueError(
            "engine-deck condition "
            f"(altitude={altitude_m}, Mach={mach}) is outside "
            f"altitude [{alt_lo}, {alt_hi}], Mach [{mach_lo}, {mach_hi}]"
        )
    query_altitude = min(max(altitude_m, alt_lo), alt_hi)
    query_mach = min(max(mach, mach_lo), mach_hi)
    condition_clamped = query_altitude != altitude_m or query_mach != mach

    values = {
        condition: _linear_curve_value(points, throttle, deck.extrapolation)
        for condition, points in curves.items()
    }
    for condition, value in values.items():
        if (
            abs(condition[0] - query_altitude) <= 1e-12
            and abs(condition[1] - query_mach) <= 1e-12
        ):
            return EngineDeckValue(
                value.thrust_n,
                value.fuel_flow_kg_s,
                value.throttle,
                condition_clamped or value.clamped,
            )

    weighted_thrust = 0.0
    weighted_fuel = 0.0
    weight_sum = 0.0
    throttle_clamped = False
    effective_throttle = throttle
    for (curve_altitude, curve_mach), value in values.items():
        distance_sq = (
            (query_altitude - curve_altitude) / deck.altitude_scale_m
        ) ** 2 + ((query_mach - curve_mach) / deck.mach_scale) ** 2
        weight = 1.0 / max(distance_sq, 1e-24)
        weighted_thrust += weight * value.thrust_n
        weighted_fuel += weight * value.fuel_flow_kg_s
        weight_sum += weight
        throttle_clamped = throttle_clamped or value.clamped
        effective_throttle = value.throttle
    return EngineDeckValue(
        thrust_n=weighted_thrust / weight_sum,
        fuel_flow_kg_s=weighted_fuel / weight_sum,
        throttle=effective_throttle,
        clamped=condition_clamped or throttle_clamped,
    )


def sea_level_tsfc_mass(engine: EngineSpec) -> float:
    """kg fuel / (N · s) at the published max-thrust point."""
    if engine.deck is not None:
        point = lookup_engine_deck(engine.deck, 0.0, 0.0, 1.0)
        return point.fuel_flow_kg_s / max(point.thrust_n, 1e-12)
    return engine.fuel_flow_max_kg_s / engine.max_thrust_sl_n


def available_thrust(engine: EngineSpec, altitude_m: float, mach: float) -> float:
    """T = T0 * sigma * max(floor, 1 - k M).

    Turbojet sea-level-static thrust scales first with inlet mass flow (density)
    and is then reduced by a linear Mach penalty. This is a conceptual-design
    lapse, not a cycle analysis.
    """
    if engine.deck is not None:
        return lookup_engine_deck(engine.deck, altitude_m, mach, 1.0).thrust_n
    atm = isa(altitude_m)
    lapse = max(
        engine.thrust_lapse_floor, 1.0 - engine.thrust_lapse_k_mach * max(mach, 0.0)
    )
    return engine.max_thrust_sl_n * atm.sigma * lapse


def tsfc_mass(
    engine: EngineSpec, altitude_m: float, mach: float, throttle: float
) -> float:
    """Mass TSFC [kg/(N·s)] at a given throttle.

    Part-power penalty: small turbojets run richer / less efficiently off the
    design point. c = c_max * (a + b/throttle) * sqrt(T/Tsl) * (1 + kM M).
    """
    if engine.deck is not None:
        point = lookup_engine_deck(engine.deck, altitude_m, mach, throttle)
        return point.fuel_flow_kg_s / max(point.thrust_n, 1e-12)
    atm = isa(altitude_m)
    thr = max(throttle, engine.min_throttle)
    c0 = sea_level_tsfc_mass(engine)
    part = engine.tsfc_part_a + engine.tsfc_part_b / thr
    temp = (atm.temperature_k / 288.15) ** 0.5
    mach_fac = 1.0 + engine.tsfc_mach_k * max(mach, 0.0)
    return c0 * part * temp * mach_fac


def operate(
    engine: EngineSpec,
    altitude_m: float,
    mach: float,
    drag_n: float,
) -> EngineState:
    """Solve throttle so thrust matches drag (cruise) or saturates at 1.0."""
    if engine.deck is not None:
        deck = engine.deck
        deck_min = min(point.throttle for point in deck.points)
        deck_max = max(point.throttle for point in deck.points)
        throttle_lo = min(max(engine.min_throttle, deck_min), deck_max)
        maximum = lookup_engine_deck(deck, altitude_m, mach, deck_max)
        minimum = lookup_engine_deck(deck, altitude_m, mach, throttle_lo)
        target = max(float(drag_n), 0.0)
        if target <= minimum.thrust_n:
            point = minimum
        elif target >= maximum.thrust_n:
            point = maximum
        else:
            lower = throttle_lo
            upper = deck_max
            for _ in range(48):
                middle = 0.5 * (lower + upper)
                candidate = lookup_engine_deck(deck, altitude_m, mach, middle)
                if candidate.thrust_n < target:
                    lower = middle
                else:
                    upper = middle
            point = lookup_engine_deck(deck, altitude_m, mach, upper)
        t_used = min(target, maximum.thrust_n)
        c_m = point.fuel_flow_kg_s / max(point.thrust_n, 1e-12)
        return EngineState(
            thrust_available_n=maximum.thrust_n,
            thrust_used_n=t_used,
            throttle=point.throttle,
            tsfc_mass_kg_per_n_s=c_m,
            tsfc_weight_per_s=c_m * G0,
            fuel_flow_kg_s=point.fuel_flow_kg_s,
            sigma=isa(altitude_m).sigma,
            mach=mach,
            deck_name=deck.name,
            deck_clamped=maximum.clamped or point.clamped,
        )

    t_avail = available_thrust(engine, altitude_m, mach)
    if t_avail <= 0.0:
        thr = 1.0
        t_used = 0.0
    else:
        thr = min(1.0, max(engine.min_throttle, drag_n / t_avail))
        t_used = min(drag_n, t_avail)
    c_m = tsfc_mass(engine, altitude_m, mach, thr)
    return EngineState(
        thrust_available_n=t_avail,
        thrust_used_n=t_used,
        throttle=thr,
        tsfc_mass_kg_per_n_s=c_m,
        tsfc_weight_per_s=c_m * G0,
        fuel_flow_kg_s=c_m * t_used,
        sigma=isa(altitude_m).sigma,
        mach=mach,
    )


def breguet_endurance_s(
    tsfc_weight_per_s: float, lift_to_drag: float, wi_wf: float
) -> float:
    """Jet endurance E = (1/c) (L/D) ln(Wi/Wf), c in 1/s (weight TSFC)."""
    if tsfc_weight_per_s <= 0.0 or lift_to_drag <= 0.0 or wi_wf <= 1.0:
        return 0.0
    return (1.0 / tsfc_weight_per_s) * lift_to_drag * math.log(wi_wf)


def fuel_fraction_for_endurance(
    tsfc_weight_per_s: float, lift_to_drag: float, endurance_s: float
) -> float:
    """Return (Wi - Wf)/Wi required to fly `endurance_s` at constant L/D and c."""
    if tsfc_weight_per_s <= 0.0 or lift_to_drag <= 0.0:
        return 1.0
    ln_ratio = endurance_s * tsfc_weight_per_s / lift_to_drag
    wi_wf = math.exp(ln_ratio)
    return 1.0 - 1.0 / wi_wf
