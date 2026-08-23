"""Explicit, training-only calibrations for low-Re flight dynamics."""

from __future__ import annotations

import copy
from typing import Any

from openair.atmosphere import isa, reynolds_per_m
from openair.schemas import VehicleSpec

NTNU_X8_LOW_RE_ELEVON_V1 = {
    "id": "ntnu-x8-low-re-elevon-v1",
    "source_case": "ntnu-x8-training",
    "source_split": "13 publisher-designated training maneuvers",
    "frozen_on": "2026-08-22",
    "method": (
        "median control-normalized p/q peak and RMS response fit; four factors "
        "fit to eight training observables"
    ),
    "factors": {
        "collective_elevon": 0.75,
        "differential_elevon": 0.70,
        "Cm_q": 1.20,
        "Cl_p": 1.20,
    },
    "applicability": {
        "configuration": "tailless low-Re elevon aircraft",
        "reference_reynolds_max": 750_000.0,
    },
    "untouched_holdout": "ntnu-x8-flight validation split",
}


def apply_named_calibration(
    spec: VehicleSpec,
    derivatives: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Apply only an explicitly selected, provenance-carrying calibration."""
    calibration_id = spec.flight_dynamics.calibration_id
    if calibration_id == "none":
        return derivatives, None
    if calibration_id != NTNU_X8_LOW_RE_ELEVON_V1["id"]:
        raise ValueError(f"unsupported flight-dynamics calibration: {calibration_id}")
    surfaces = spec.flight_dynamics.control_surfaces
    group_ids = {
        mix.id for surface in surfaces for mix in surface.mixing
    }
    if (
        spec.htail.span_m > 0.05
        or len(surfaces) != 1
        or surfaces[0].host != "wing"
        or group_ids != {"collective_elevon", "differential_elevon"}
    ):
        raise ValueError(
            f"{calibration_id} applies only to tailless elevon configurations"
        )
    atmosphere = isa(spec.flight_dynamics.reference_altitude_m)
    reference_reynolds = (
        reynolds_per_m(
            atmosphere,
            spec.flight_dynamics.reference_airspeed_mps,
        )
        * spec.wing.mac_m
    )
    limit = float(NTNU_X8_LOW_RE_ELEVON_V1["applicability"]["reference_reynolds_max"])
    if reference_reynolds > limit:
        raise ValueError(
            f"{calibration_id} reference Reynolds {reference_reynolds:.0f} "
            f"exceeds its {limit:.0f} applicability limit"
        )
    calibrated = copy.deepcopy(derivatives)
    factors = NTNU_X8_LOW_RE_ELEVON_V1["factors"]
    calibrated["controls"]["collective_elevon"] = {
        name: float(value) * factors["collective_elevon"]
        for name, value in calibrated["controls"]["collective_elevon"].items()
    }
    calibrated["controls"]["differential_elevon"] = {
        name: float(value) * factors["differential_elevon"]
        for name, value in calibrated["controls"]["differential_elevon"].items()
    }
    calibrated["state"]["Cm"]["q"] *= factors["Cm_q"]
    calibrated["state"]["Cl"]["p"] *= factors["Cl_p"]
    provenance = copy.deepcopy(NTNU_X8_LOW_RE_ELEVON_V1)
    provenance["reference_reynolds"] = reference_reynolds
    return calibrated, provenance
