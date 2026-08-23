"""ISA troposphere / lower stratosphere atmosphere."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from openair.units import G0

R_AIR = 287.05287
GAMMA = 1.4
T0 = 288.15
P0 = 101325.0
RHO0 = 1.225
L_TROP = 0.0065
T_STRAT = 216.65
H_TROP = 11000.0
H_STRAT = 20000.0


@dataclass(frozen=True)
class Atmosphere:
    altitude_m: float
    temperature_k: float
    pressure_pa: float
    density_kg_m3: float
    speed_of_sound_mps: float
    viscosity_pa_s: float

    @property
    def sigma(self) -> float:
        return self.density_kg_m3 / RHO0


def sutherland_mu(temperature_k: float) -> float:
    return 1.458e-6 * temperature_k**1.5 / (temperature_k + 110.4)


def isa(altitude_m: float) -> Atmosphere:
    h = float(altitude_m)
    if h < 0.0:
        h = 0.0
    if h <= H_TROP:
        t = T0 - L_TROP * h
        p = P0 * (t / T0) ** (G0 / (L_TROP * R_AIR))
    elif h <= H_STRAT:
        t = T_STRAT
        p_trop = P0 * (T_STRAT / T0) ** (G0 / (L_TROP * R_AIR))
        p = p_trop * (2.718281828459045 ** (-G0 * (h - H_TROP) / (R_AIR * T_STRAT)))
    else:
        raise ValueError(f"ISA model limited to {H_STRAT} m, got {h}")
    rho = p / (R_AIR * t)
    a = sqrt(GAMMA * R_AIR * t)
    return Atmosphere(h, t, p, rho, a, sutherland_mu(t))


def reynolds_per_m(atm: Atmosphere, tas_mps: float) -> float:
    return atm.density_kg_m3 * tas_mps / atm.viscosity_pa_s
