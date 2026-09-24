"""Typed source contracts for multirotor concepts and mesh assemblies."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EvidenceClass = Literal["A", "B", "C", "D"]
Vector3 = tuple[float, float, float]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ReferenceSpec(ContractModel):
    generated: str = "reference/reference.json"
    units: Literal["mm", "cm", "m", "in"] = "mm"
    axes: str = "x:+x,y:+y,z:+z"
    propeller_radial_min_m: float = Field(default=0.13, gt=0.0)
    propeller_planar_span_min_m: float = Field(default=0.12, gt=0.0)
    motor_radial_min_m: float = Field(default=0.145, gt=0.0)
    arm_radial_min_m: float = Field(default=0.07, gt=0.0)
    frame_planar_span_min_m: float = Field(default=0.25, gt=0.0)
    body_longitudinal_extent_min_m: float = Field(default=0.07, gt=0.0)
    tail_fin_count: int = Field(default=4, ge=0, le=12)


class FramesSpec(ContractModel):
    """Geometry-to-Elodin body convention.

    The source mesh has its rotor/thrust axis along geometry +Z.  Body +X is
    selected in the rotor plane by ``forward_azimuth_deg`` and body +Y is left.
    """

    thrust_axis_geometry: Vector3 = (0.0, 0.0, 1.0)
    forward_azimuth_deg: float = Field(default=45.0, ge=-360.0, le=360.0)
    world: Literal["ENU_Z_UP"] = "ENU_Z_UP"
    body: Literal["X_FORWARD_Y_LEFT_Z_UP"] = "X_FORWARD_Y_LEFT_Z_UP"

    @field_validator("thrust_axis_geometry")
    @classmethod
    def unit_thrust_axis(cls, value: Vector3) -> Vector3:
        norm = math.sqrt(sum(component * component for component in value))
        if abs(norm - 1.0) > 1e-6:
            raise ValueError("frames.thrust_axis_geometry must be a unit vector")
        return value


class MotorsSpec(ContractModel):
    layout: Literal["quad_x"] = "quad_x"
    betaflight_order: tuple[
        Literal["BR"], Literal["FR"], Literal["BL"], Literal["FL"]
    ] = ("BR", "FR", "BL", "FL")
    spin: Literal["props_out"] = "props_out"
    positions: Literal["measured"] | list[Vector3] = "measured"
    prop_diameter_m: Literal["measured"] | float = "measured"

    @model_validator(mode="after")
    def validate_layout(self) -> "MotorsSpec":
        if len(set(self.betaflight_order)) != 4:
            raise ValueError("motors.betaflight_order must contain four unique labels")
        if isinstance(self.positions, list) and len(self.positions) != 4:
            raise ValueError("motors.positions must contain four vectors")
        if isinstance(self.prop_diameter_m, float) and self.prop_diameter_m <= 0.0:
            raise ValueError("motors.prop_diameter_m must be positive")
        return self


class PropulsionSpec(ContractModel):
    max_thrust_n: float = Field(gt=0.0)
    time_constant_s: float = Field(gt=0.0)
    torque_coefficient_m: float = Field(gt=0.0)
    command_exponent: float = Field(default=1.0, gt=0.0)
    source: str = Field(min_length=1)
    evidence_class: EvidenceClass = "D"


class MassComponentSpec(ContractModel):
    name: str = Field(min_length=1)
    mass_kg: float = Field(gt=0.0)
    shape: Literal["reference_group", "point", "box"] = "point"
    group: str | None = None
    position_m: Literal["measured"] | Vector3 = "measured"
    dimensions_m: Vector3 | None = None
    source: str = Field(min_length=1)
    evidence_class: EvidenceClass = "D"

    @model_validator(mode="after")
    def shape_inputs(self) -> "MassComponentSpec":
        if self.shape == "reference_group" and not self.group:
            raise ValueError(f"{self.name}: reference_group requires group")
        if self.shape == "box":
            if self.dimensions_m is None or any(value <= 0 for value in self.dimensions_m):
                raise ValueError(f"{self.name}: box requires positive dimensions_m")
            if self.position_m == "measured" and not self.group:
                raise ValueError(
                    f"{self.name}: measured box position requires a reference group"
                )
        if self.shape == "point" and self.position_m == "measured" and not self.group:
            raise ValueError(
                f"{self.name}: measured point position requires a reference group"
            )
        return self


class MassSpec(ContractModel):
    components: list[MassComponentSpec] = Field(min_length=1)
    source: str = Field(min_length=1)
    evidence_class: EvidenceClass = "D"

    @property
    def total_mass_kg(self) -> float:
        return sum(component.mass_kg for component in self.components)


class AeroComponentOverride(ContractModel):
    cd_axes: Vector3 | None = None
    area_axes_m2: Vector3 | None = None

    @field_validator("cd_axes", "area_axes_m2")
    @classmethod
    def nonnegative(cls, value: Vector3 | None) -> Vector3 | None:
        if value is not None and any(item < 0.0 for item in value):
            raise ValueError("aerodynamic component values must be non-negative")
        return value


class AeroSpec(ContractModel):
    air_density_kg_m3: float = Field(default=1.225, gt=0.0)
    dynamic_viscosity_pa_s: float = Field(default=1.789e-5, gt=0.0)
    reference_speed_mps: float = Field(default=20.0, gt=0.0)
    grid_step_deg: int = Field(default=5, ge=5, le=30)
    include_rate_derivatives: bool = True
    body_crossflow_cd: float = Field(default=1.2, gt=0.0)
    plate_normal_cd: float = Field(default=1.28, gt=0.0)
    component_overrides: dict[str, AeroComponentOverride] = Field(
        default_factory=dict
    )
    uncertainty_fraction: float = Field(default=0.5, ge=0.0, le=2.0)
    evidence_class: EvidenceClass = "D"

    @field_validator("grid_step_deg")
    @classmethod
    def divides_direction_grid(cls, value: int) -> int:
        if 180 % value or 360 % value:
            raise ValueError("aero.grid_step_deg must divide both 180 and 360")
        return value


class ValiditySpec(ContractModel):
    speed_mps: tuple[float, float] = (2.0, 60.0)
    extrapolation_policy: Literal["flag_invalid_do_not_clamp"] = (
        "flag_invalid_do_not_clamp"
    )

    @model_validator(mode="after")
    def increasing_speed(self) -> "ValiditySpec":
        if self.speed_mps[0] < 0.0 or self.speed_mps[1] <= self.speed_mps[0]:
            raise ValueError("validity.speed_mps must be an increasing nonnegative pair")
        return self


class MultirotorSpec(ContractModel):
    family: Literal["multirotor"]
    name: str = Field(min_length=1)
    notes: str = ""
    reference: ReferenceSpec = Field(default_factory=ReferenceSpec)
    frames: FramesSpec = Field(default_factory=FramesSpec)
    motors: MotorsSpec = Field(default_factory=MotorsSpec)
    propulsion: PropulsionSpec
    mass: MassSpec
    aero: AeroSpec = Field(default_factory=AeroSpec)
    validity: ValiditySpec = Field(default_factory=ValiditySpec)

    def assert_cross_model_invariants(self) -> None:
        if self.mass.total_mass_kg <= 0.0:
            raise ValueError("mass component total must be positive")
        if self.motors.layout != "quad_x":
            raise ValueError("v1 supports only the Betaflight quad_x layout")
        if not np_allclose(self.frames.thrust_axis_geometry, (0.0, 0.0, 1.0)):
            raise ValueError("multirotor v1 requires geometry thrust axis +Z")

    def resolve_reference_path(self, design_path: Path) -> Path:
        return (design_path.parent / self.reference.generated).resolve()


def np_allclose(first: tuple[float, ...], second: tuple[float, ...]) -> bool:
    return all(abs(left - right) <= 1e-9 for left, right in zip(first, second))

