"""Shared thin-airfoil trailing-edge flap theory."""

from __future__ import annotations

import math


def plain_flap_theory(chord_fraction: float) -> dict[str, float]:
    """Return Glauert plain-flap derivatives for ``chord_fraction`` c.

    With the hinge at ``x_h = (1 - chord_fraction)c`` and
    ``cos(theta_h) = 1 - 2 x_h/c``:

    ``dCl/ddelta = 2(pi - theta_h + sin(theta_h))`` and
    ``dCm_c/4/ddelta = -sin(theta_h)(1 - cos(theta_h))/2``.

    Deflection is trailing-edge down positive. The inviscid, sealed-gap
    result is an upper-bound section model, not aircraft validation.
    """
    if not 0.0 < chord_fraction < 1.0:
        raise ValueError("chord_fraction must lie strictly between 0 and 1")
    x_hinge = 1.0 - chord_fraction
    theta_h = math.acos(1.0 - 2.0 * x_hinge)
    dcl_ddelta = 2.0 * (math.pi - theta_h + math.sin(theta_h))
    dcm_ddelta = -0.5 * math.sin(theta_h) * (1.0 - math.cos(theta_h))
    return {
        "theta_h_rad": theta_h,
        "dcl_ddelta_per_rad": dcl_ddelta,
        "dcm_ac_ddelta_per_rad": dcm_ddelta,
        "tau": dcl_ddelta / (2.0 * math.pi),
    }


def flap_effectiveness(chord_fraction: float) -> float:
    """Return Glauert's lift-effectiveness ratio ``tau``."""
    return plain_flap_theory(chord_fraction)["tau"]
