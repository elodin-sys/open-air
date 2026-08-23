import pytest
from pydantic import ValidationError

from openair.mission.engine import (
    available_thrust,
    lookup_engine_deck,
    operate,
)
from openair.schemas import EngineDeckSpec, EngineSpec


def _deck() -> EngineDeckSpec:
    return EngineDeckSpec.model_validate(
        {
            "name": "test equivalent pair",
            "points": [
                {
                    "altitude_m": 0.0,
                    "mach": 0.0,
                    "throttle": 0.2,
                    "thrust_n": 40.0,
                    "fuel_flow_kg_s": 0.4,
                },
                {
                    "altitude_m": 0.0,
                    "mach": 0.0,
                    "throttle": 1.0,
                    "thrust_n": 200.0,
                    "fuel_flow_kg_s": 1.6,
                },
                {
                    "altitude_m": 10000.0,
                    "mach": 0.8,
                    "throttle": 0.2,
                    "thrust_n": 10.0,
                    "fuel_flow_kg_s": 0.2,
                },
                {
                    "altitude_m": 10000.0,
                    "mach": 0.8,
                    "throttle": 1.0,
                    "thrust_n": 50.0,
                    "fuel_flow_kg_s": 0.6,
                },
            ],
        }
    )


def test_sparse_deck_interpolates_throttle_and_exact_conditions() -> None:
    deck = _deck()

    sea_level = lookup_engine_deck(deck, 0.0, 0.0, 0.6)
    cruise = lookup_engine_deck(deck, 10000.0, 0.8, 1.0)

    assert sea_level.thrust_n == pytest.approx(120.0)
    assert sea_level.fuel_flow_kg_s == pytest.approx(1.0)
    assert sea_level.clamped is False
    assert cruise.thrust_n == pytest.approx(50.0)
    assert cruise.fuel_flow_kg_s == pytest.approx(0.6)


def test_deck_drives_available_thrust_and_cruise_throttle() -> None:
    engine = EngineSpec(deck=_deck(), min_throttle=0.2)

    state = operate(engine, 10000.0, 0.8, 30.0)

    assert available_thrust(engine, 10000.0, 0.8) == pytest.approx(50.0)
    assert state.thrust_available_n == pytest.approx(50.0)
    assert state.thrust_used_n == pytest.approx(30.0)
    assert state.throttle == pytest.approx(0.6)
    assert state.fuel_flow_kg_s == pytest.approx(0.4)
    assert state.deck_name == "test equivalent pair"
    assert state.deck_clamped is False


def test_deck_clamps_conditions_and_rejects_malformed_curves() -> None:
    deck = _deck()
    clamped = lookup_engine_deck(deck, 25000.0, 1.2, 1.0)
    assert clamped.thrust_n == pytest.approx(50.0)
    assert clamped.clamped is True

    payload = deck.model_dump(mode="python")
    payload["points"][1]["throttle"] = 0.2
    with pytest.raises(ValidationError, match="duplicate engine-deck point"):
        EngineDeckSpec.model_validate(payload)
