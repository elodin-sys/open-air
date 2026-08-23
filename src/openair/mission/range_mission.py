"""Low-order block mission integration for sparse engine-deck truth cases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from openair.atmosphere import isa
from openair.mission.engine import lookup_engine_deck, operate
from openair.schemas import EngineSpec
from openair.units import G0

NM_TO_M = 1852.0


class BlockMissionSpec(BaseModel):
    """Inputs known before a block mission is evaluated."""

    model_config = ConfigDict(extra="forbid")

    id: str
    range_nm: float = Field(gt=0.0)
    payload_kg: float = Field(ge=0.0)
    takeoff_mass_kg: float = Field(gt=0.0)
    maximum_takeoff_mass_kg: float = Field(gt=0.0)
    required_payload_kg: float = Field(ge=0.0)
    cruise_altitude_m: float = Field(ge=0.0, le=20000.0)
    cruise_mach: float = Field(gt=0.0, le=0.95)
    cruise_lod: float = Field(gt=0.0)
    airborne_overhead_s: float = Field(ge=0.0)
    taxi_out_s: float = Field(ge=0.0)
    taxi_in_s: float = Field(ge=0.0)
    taxi_throttle: float = Field(gt=0.0, le=1.0)
    integration_step_s: float = Field(30.0, gt=0.0, le=300.0)


class BlockMissionResult(BaseModel):
    """Predicted block totals and explicit feasibility calls."""

    model_config = ConfigDict(extra="forbid")

    mission_id: str
    block_fuel_kg: float
    flight_fuel_kg: float
    taxi_fuel_kg: float
    block_time_h: float
    flight_time_h: float
    landing_mass_kg: float
    thrust_requirement_met: bool
    payload_requirement_met: bool
    takeoff_mass_requirement_met: bool
    requirement_met: bool
    initial_cruise_throttle: float
    final_cruise_throttle: float


def simulate_block_mission(
    engine: EngineSpec,
    mission: BlockMissionSpec,
) -> BlockMissionResult:
    """Integrate constant-condition cruise plus declared block-time overhead.

    This is intentionally not a climb/descent trajectory optimizer. The overhead
    represents the net time not captured by range divided by cruise speed; it
    still consumes fuel at the rated cruise condition. Taxi uses the sea-level
    deck directly.
    """

    if engine.deck is None:
        raise ValueError("block mission requires a typed engine deck")
    atmosphere = isa(mission.cruise_altitude_m)
    cruise_speed_mps = mission.cruise_mach * atmosphere.speed_of_sound_mps
    flight_time_s = (
        mission.range_nm * NM_TO_M / cruise_speed_mps + mission.airborne_overhead_s
    )

    remaining_s = flight_time_s
    mass_kg = mission.takeoff_mass_kg
    flight_fuel_kg = 0.0
    thrust_requirement_met = True
    first_throttle: float | None = None
    final_throttle = 0.0
    while remaining_s > 1e-12:
        duration_s = min(mission.integration_step_s, remaining_s)
        drag_n = mass_kg * G0 / mission.cruise_lod
        state = operate(
            engine,
            mission.cruise_altitude_m,
            mission.cruise_mach,
            drag_n,
        )
        if first_throttle is None:
            first_throttle = state.throttle
        final_throttle = state.throttle
        thrust_requirement_met = (
            thrust_requirement_met and state.thrust_available_n + 1e-9 >= drag_n
        )
        burned_kg = min(state.fuel_flow_kg_s * duration_s, mass_kg)
        mass_kg -= burned_kg
        flight_fuel_kg += burned_kg
        remaining_s -= duration_s

    taxi = lookup_engine_deck(
        engine.deck,
        0.0,
        0.0,
        mission.taxi_throttle,
    )
    taxi_time_s = mission.taxi_out_s + mission.taxi_in_s
    taxi_fuel_kg = taxi.fuel_flow_kg_s * taxi_time_s
    payload_ok = mission.payload_kg + 1e-9 >= mission.required_payload_kg
    takeoff_mass_ok = mission.takeoff_mass_kg <= mission.maximum_takeoff_mass_kg + 1e-9
    requirement_met = thrust_requirement_met and payload_ok and takeoff_mass_ok
    return BlockMissionResult(
        mission_id=mission.id,
        block_fuel_kg=flight_fuel_kg + taxi_fuel_kg,
        flight_fuel_kg=flight_fuel_kg,
        taxi_fuel_kg=taxi_fuel_kg,
        block_time_h=(flight_time_s + taxi_time_s) / 3600.0,
        flight_time_h=flight_time_s / 3600.0,
        landing_mass_kg=mass_kg,
        thrust_requirement_met=thrust_requirement_met,
        payload_requirement_met=payload_ok,
        takeoff_mass_requirement_met=takeoff_mass_ok,
        requirement_met=requirement_met,
        initial_cruise_throttle=first_throttle or 0.0,
        final_cruise_throttle=final_throttle,
    )


__all__ = [
    "BlockMissionResult",
    "BlockMissionSpec",
    "simulate_block_mission",
]
