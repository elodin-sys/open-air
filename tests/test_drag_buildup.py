import pytest

from conftest import BASELINE_DESIGN
from openair.aero.drag_buildup import parasite_cd0
from openair.atmosphere import isa
from openair.cli import load_spec
from openair.schemas import EngineSpec


def _external_engine(spec, *, count: int) -> EngineSpec:
    payload = spec.engine.model_dump(mode="python")
    payload.update(
        {
            "installation": "external",
            "installation_count": count,
            "x_m": 1.1,
            "lateral_offset_m": 0.36 if count > 1 else 0.0,
            "z_m": -0.15,
        }
    )
    return EngineSpec.model_validate(payload)


def test_external_nacelle_drag_scales_with_physical_installation_count():
    one = load_spec(BASELINE_DESIGN).model_copy(deep=True)
    one.engine = _external_engine(one, count=1)
    two = one.model_copy(deep=True)
    two.engine = _external_engine(two, count=2)
    atmosphere = isa(one.mission.cruise_altitude_m)

    one_drag = parasite_cd0(one, atmosphere, 50.0)
    two_drag = parasite_cd0(two, atmosphere, 50.0)

    assert two_drag.cd_components["base_inlet"] == pytest.approx(
        2.0 * one_drag.cd_components["base_inlet"]
    )
    assert two_drag.swet_m2["nacelles"] == pytest.approx(
        2.0 * one_drag.swet_m2["nacelles"]
    )
