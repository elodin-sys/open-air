"""Unit helpers. Internal SI; conversions are explicit."""

from __future__ import annotations

G0 = 9.80665  # m/s^2, standard gravity
DEG2RAD = 0.017453292519943295
RAD2DEG = 57.29577951308232
KT_TO_MPS = 0.514444
FT_TO_M = 0.3048
LBF_TO_N = 4.4482216152605
KG_TO_LBF = 2.20462262185  # kg mass -> lbf weight at g0, not used as mass


def kgf_to_n(kgf: float) -> float:
    """Kilogram-force (engine spec 'kg' thrust) to newtons."""
    return kgf * G0


def n_to_kgf(newton: float) -> float:
    return newton / G0
