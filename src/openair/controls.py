"""Pitch-trim control selection and control-surface sign conventions.

One place decides which control closes cruise pitch trim and how a solved
setting compares with the serialized design, so the aero stage, the balance
model, the MDO reproduction closure, the gates, and the report cannot drift
apart.

Sign convention for wing control surfaces (``ControlSurfaceSpec``): trailing
edge UP is positive, the pilot's nose-up command. The OpenAeroStruct mesh
deflection and thin-airfoil flap theory use trailing edge DOWN positive;
``te_down_deg`` is the single conversion between the two.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from openair.schemas import ControlSurfaceSpec, VehicleSpec

PitchTrimControl = Literal["wing_twist", "tail_incidence", "elevon"]

TRIM_CONTROL_LABELS = {
    "wing_twist": "washout",
    "tail_incidence": "tail incidence",
    "elevon": "elevon deflection (TE up +)",
}


def pitch_trim_control(spec: VehicleSpec) -> PitchTrimControl:
    """Resolve ``mission.pitch_trim_control`` (``auto`` keeps the legacy rule)."""
    mode = spec.mission.pitch_trim_control
    if mode == "auto":
        return "tail_incidence" if spec.htail.span_m > 0.05 else "wing_twist"
    return mode


def pitch_control_surface(spec: VehicleSpec) -> ControlSurfaceSpec | None:
    """The wing control surface carrying the collective pitch mixing group."""
    for surface in spec.flight_dynamics.control_surfaces:
        if surface.host == "wing" and any(
            mix.mode == "collective" and mix.axis == "pitch" for mix in surface.mixing
        ):
            return surface
    return None


def elevon_travel_deg(surface: ControlSurfaceSpec) -> tuple[float, float]:
    """Admissible deflection band ``(lowest, highest)``, trailing edge up positive."""
    return (-float(surface.max_down_deg), float(surface.max_up_deg))


def within_travel(
    surface: ControlSurfaceSpec, deflection_te_up_deg: float, margin_deg: float = 0.0
) -> bool:
    lo, hi = elevon_travel_deg(surface)
    return lo + margin_deg <= deflection_te_up_deg <= hi - margin_deg


def te_down_deg(te_up_deg: float) -> float:
    """Convert a trailing-edge-up-positive deflection to trailing-edge-down positive."""
    return -float(te_up_deg)


def elevon_trim_deflection_deg(spec: VehicleSpec) -> float | None:
    """Serialized analysis deflection of the pitch control surface (TE up +)."""
    surface = pitch_control_surface(spec)
    return None if surface is None else float(surface.trim_deflection_deg)


def set_pitch_trim_deflection(spec: VehicleSpec, deflection_te_up_deg: float) -> None:
    """Write a solved trim deflection into the pitch control surface in place."""
    surface = pitch_control_surface(spec)
    if surface is None:
        raise ValueError(
            "spec has no wing control surface with collective pitch mixing"
        )
    if not within_travel(surface, deflection_te_up_deg):
        lo, hi = elevon_travel_deg(surface)
        raise ValueError(
            f"elevon trim deflection {deflection_te_up_deg:.3f} deg lies outside "
            f"the travel [{lo:g}, {hi:g}] deg"
        )
    surface.trim_deflection_deg = float(deflection_te_up_deg)


def trim_control_values(spec: VehicleSpec, trim: Mapping[str, Any]) -> dict[str, Any]:
    """Solved versus serialized setting of the active pitch-trim control.

    Accepts both the ``trim_pitch`` result (``trim_control`` key) and the
    aero-stage ``trim`` block (``control`` key). ``gap_deg`` is 99 when either
    side is missing so callers fail closed.
    """
    control = str(
        trim.get("trim_control") or trim.get("control") or pitch_trim_control(spec)
    )
    if control == "tail_incidence":
        solved = trim.get("tail_incidence_trim_deg")
        specified: float | None = float(spec.htail.incidence_deg)
    elif control == "elevon":
        solved = trim.get("elevon_trim_deg")
        specified = elevon_trim_deflection_deg(spec)
    else:
        control = "wing_twist"
        solved = trim.get("washout_trim_deg")
        specified = float(spec.wing.twist_root_deg - spec.wing.twist_tip_deg)
    gap = (
        abs(float(solved) - float(specified))
        if isinstance(solved, (int, float)) and isinstance(specified, (int, float))
        else 99.0
    )
    return {
        "control": control,
        "label": TRIM_CONTROL_LABELS.get(control, control),
        "solved_deg": float(solved) if isinstance(solved, (int, float)) else None,
        "spec_deg": specified,
        "gap_deg": gap,
    }
