"""Pydantic vehicle / case schema. YAML files deserialize into VehicleSpec.

All physical models carry `validate_assignment=True` plus field bounds, so
optimizer/trim code that mutates a `model_copy` cannot smuggle in nonsense
(negative chords, taper <= 0, ...) — it raises at the assignment site.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    computed_field,
    model_validator,
)


class PhysicalModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True)


class EngineDeckPoint(PhysicalModel):
    """One rated engine-deck point for the complete propulsion installation."""

    altitude_m: float = Field(ge=0.0, le=20000.0)
    mach: float = Field(ge=0.0, le=1.5)
    throttle: float = Field(gt=0.0, le=1.0)
    thrust_n: float = Field(ge=0.0)
    fuel_flow_kg_s: float = Field(ge=0.0)


class EngineDeckSpec(PhysicalModel):
    """Sparse condition curves interpolated in throttle, altitude, and Mach."""

    name: str
    points: list[EngineDeckPoint] = Field(min_length=4)
    interpolation: Literal["condition-idw"] = "condition-idw"
    extrapolation: Literal["clamp", "error"] = "clamp"
    altitude_scale_m: float = Field(10000.0, gt=0.0)
    mach_scale: float = Field(1.0, gt=0.0)

    @model_validator(mode="after")
    def validate_condition_curves(self) -> Self:
        curves: dict[tuple[float, float], list[EngineDeckPoint]] = {}
        triples: set[tuple[float, float, float]] = set()
        for point in self.points:
            key = (point.altitude_m, point.mach)
            triple = (*key, point.throttle)
            if triple in triples:
                raise ValueError(f"duplicate engine-deck point at {triple}")
            triples.add(triple)
            curves.setdefault(key, []).append(point)

        for condition, points in curves.items():
            ordered = sorted(points, key=lambda item: item.throttle)
            if len(ordered) < 2:
                raise ValueError(
                    f"engine-deck condition {condition} needs at least two "
                    "throttle points"
                )
            if any(
                right.thrust_n <= left.thrust_n
                for left, right in zip(ordered, ordered[1:])
            ):
                raise ValueError(
                    f"engine-deck thrust must increase with throttle at {condition}"
                )
            if any(
                right.fuel_flow_kg_s < left.fuel_flow_kg_s
                for left, right in zip(ordered, ordered[1:])
            ):
                raise ValueError(
                    f"engine-deck fuel flow must not decrease with throttle at "
                    f"{condition}"
                )
        return self


class EngineSpec(PhysicalModel):
    """Installed propulsion system, optionally represented by several nacelles.

    Mass, thrust and fuel-flow fields describe the *complete installation*.
    ``installation_count`` controls geometry only; it never multiplies those
    totals. This keeps legacy single-engine cases unchanged while allowing a
    twin-engine reference aircraft to retain two physical nacelles without
    double-counting an equivalent two-engine deck.
    """

    name: str = "KingTech K-450G5"
    energy_source: Literal["liquid_fuel", "electric"] = "liquid_fuel"
    diameter_m: float = Field(0.1526, gt=0)
    length_m: float = Field(0.374, gt=0)
    dry_mass_kg: float = Field(4.0, gt=0)
    installation: Literal["internal", "external"] = "internal"
    installation_count: int = Field(1, ge=1, le=8)
    x_m: float | None = Field(None, ge=0.0, lt=100.0)
    lateral_offset_m: float = Field(0.0, ge=0.0, lt=50.0)
    z_m: float = Field(0.0, ge=-20.0, le=20.0)
    max_thrust_sl_n: float = Field(441.299, gt=0)  # 45 kgf
    fuel_flow_max_kg_s: float = Field(0.018333, ge=0)  # 1100 g/min
    # Thrust lapse: T = T0 * sigma * max(floor, 1 - k_mach * M)
    thrust_lapse_k_mach: float = 0.35
    thrust_lapse_floor: float = 0.08
    # Part-throttle TSFC: c = c_max * (a + b/throttle) * sqrt(T/Tsl) * (1 + kM*M)
    tsfc_part_a: float = 0.80
    tsfc_part_b: float = 0.20
    tsfc_mach_k: float = 0.15
    min_throttle: float = 0.18
    fuel_density_kg_m3: float = 800.0  # Jet-A / kerosene
    # Frontal-area form/base coefficient for each external nacelle. Small
    # turbojet pods retain the conservative 0.08 default; streamlined transport
    # turbofans may declare a lower sourced preliminary-design assumption.
    nacelle_frontal_cd: float = Field(0.08, ge=0.0, le=0.5)
    deck: EngineDeckSpec | None = None

    @model_validator(mode="after")
    def validate_installation(self) -> Self:
        if self.installation_count > 1 and self.lateral_offset_m <= 0.0:
            raise ValueError(
                "a multi-nacelle installation requires a positive lateral_offset_m"
            )
        if self.installation == "external" and self.x_m is None:
            raise ValueError("an external engine installation requires x_m")
        if self.energy_source == "liquid_fuel":
            deck_flows = (
                [point.fuel_flow_kg_s for point in self.deck.points]
                if self.deck is not None
                else []
            )
            if self.fuel_flow_max_kg_s <= 0.0 and not any(
                flow > 0.0 for flow in deck_flows
            ):
                raise ValueError("liquid-fuel propulsion requires positive fuel flow")
        elif self.fuel_flow_max_kg_s != 0.0:
            raise ValueError("electric propulsion requires fuel_flow_max_kg_s = 0")
        return self


class WingSpec(PhysicalModel):
    span_m: float = Field(3.80, gt=0.2, lt=80.0)
    root_chord_m: float = Field(1.15, gt=0.05, lt=15.0)
    taper: float = Field(0.32, gt=0.03, le=1.0)
    le_sweep_deg: float = Field(32.0, ge=-45.0, le=60.0)
    dihedral_deg: float = Field(2.0, ge=-15.0, le=15.0)
    twist_root_deg: float = Field(2.0, ge=-15.0, le=15.0)
    twist_tip_deg: float = Field(-2.0, ge=-15.0, le=15.0)
    t_over_c: float = Field(0.12, gt=0.04, lt=0.30)
    airfoil: str = Field("2412", pattern=r"^\d{4}$")
    x_le_root_m: float = Field(0.85, ge=0.0)  # fuselage station of wing root LE
    z_root_m: float = 0.0

    @computed_field
    @property
    def tip_chord_m(self) -> float:
        return self.root_chord_m * self.taper

    @computed_field
    @property
    def area_m2(self) -> float:
        return 0.5 * (self.root_chord_m + self.tip_chord_m) * self.span_m

    @computed_field
    @property
    def aspect_ratio(self) -> float:
        return self.span_m**2 / self.area_m2

    @computed_field
    @property
    def mac_m(self) -> float:
        taper = self.taper
        return (
            (2.0 / 3.0) * self.root_chord_m * (1.0 + taper + taper**2) / (1.0 + taper)
        )

    @computed_field
    @property
    def y_mac_m(self) -> float:
        """Spanwise station of MAC from centerline, trapezoidal wing."""
        t = self.taper
        return (self.span_m / 6.0) * (1.0 + 2.0 * t) / (1.0 + t)

    @computed_field
    @property
    def x_le_mac_m(self) -> float:
        import math

        return self.x_le_root_m + self.y_mac_m * math.tan(
            math.radians(self.le_sweep_deg)
        )

    @computed_field
    @property
    def x_ac_m(self) -> float:
        """Approx aerodynamic center at 25% MAC."""
        return self.x_le_mac_m + 0.25 * self.mac_m


class FuselageStation(PhysicalModel):
    """One measured body section in SI units."""

    x_over_length: float = Field(..., ge=0.0, le=1.0)
    width_m: float = Field(..., ge=0.0)
    height_m: float = Field(..., ge=0.0)
    z_offset_m: float = 0.0
    side_power: float = Field(2.0, ge=0.5, le=10.0)
    top_power: float = Field(2.0, ge=0.5, le=10.0)
    bottom_power: float = Field(2.0, ge=0.5, le=10.0)

    @model_validator(mode="after")
    def nondegenerate_section(self) -> Self:
        if (self.width_m == 0.0) != (self.height_m == 0.0):
            raise ValueError(
                "a fuselage station must be a point or have both width and height"
            )
        return self


class FuselageSpec(PhysicalModel):
    length_m: float = Field(2.45, gt=0.3)
    max_width_m: float = Field(0.32, gt=0.05)
    max_height_m: float = Field(0.28, gt=0.05)
    nose_fine_ratio: float = 0.22  # fraction of length that is the nose taper
    tail_fine_ratio: float = 0.28
    payload_bay_length_m: float = 0.50
    payload_bay_width_m: float = 0.28
    payload_bay_height_m: float = 0.18
    payload_bay_x_m: float = 1.26  # station of bay front face (balance-driven)
    fuel_tank_x_m: float = 1.55  # fuselage tank centroid station
    stations: list[FuselageStation] | None = Field(
        default=None,
        min_length=4,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_stations(self) -> Self:
        if self.stations is None:
            return self
        xs = [station.x_over_length for station in self.stations]
        if abs(xs[0]) > 1e-9 or abs(xs[-1] - 1.0) > 1e-9:
            raise ValueError("fuselage stations must start at x/L=0 and end at x/L=1")
        if any(right - left <= 1e-6 for left, right in zip(xs, xs[1:])):
            raise ValueError("fuselage stations must be strictly increasing in x/L")
        if any(
            station.width_m <= 0.0 or station.height_m <= 0.0
            for station in self.stations[1:-1]
        ):
            raise ValueError(
                "interior fuselage stations must have positive width and height"
            )
        if max(station.width_m for station in self.stations) > self.max_width_m + 1e-9:
            raise ValueError("station width exceeds fuselage.max_width_m")
        if (
            max(station.height_m for station in self.stations)
            > self.max_height_m + 1e-9
        ):
            raise ValueError("station height exceeds fuselage.max_height_m")
        return self


class VerticalTailSpec(PhysicalModel):
    """One centerline fin or one member of a symmetric twin-fin pair."""

    count: Literal[1, 2] = 2
    span_m: float = Field(0.38, gt=0.01, lt=20.0)
    root_chord_m: float = Field(0.42, gt=0.02, lt=15.0)
    taper: float = Field(0.55, gt=0.03, le=1.0)
    le_sweep_deg: float = Field(35.0, ge=-45.0, le=75.0)
    cant_deg: float = Field(15.0, ge=0.0, le=75.0)  # outward
    t_over_c: float = Field(0.10, gt=0.04, lt=0.30)
    x_le_m: float = Field(1.95, ge=0.0)
    y_root_m: float = 0.14
    z_root_m: float = 0.08

    @computed_field
    @property
    def area_m2(self) -> float:
        return 0.5 * (self.root_chord_m + self.root_chord_m * self.taper) * self.span_m


class HorizontalTailSpec(PhysicalModel):
    """Optional. Sketches are tailless; keep area 0 unless needed for trim."""

    span_m: float = Field(0.0, ge=0.0, lt=30.0)
    root_chord_m: float = Field(0.30, gt=0.02, lt=15.0)
    taper: float = Field(0.50, gt=0.03, le=1.0)
    le_sweep_deg: float = Field(20.0, ge=-45.0, le=75.0)
    t_over_c: float = Field(0.10, gt=0.04, lt=0.30)
    x_le_m: float = Field(2.10, ge=0.0)
    z_m: float = 0.12
    incidence_deg: float = Field(-2.0, ge=-15.0, le=15.0)

    @computed_field
    @property
    def area_m2(self) -> float:
        if self.span_m <= 0:
            return 0.0
        return 0.5 * (self.root_chord_m + self.root_chord_m * self.taper) * self.span_m


class MissionSpec(PhysicalModel):
    endurance_s: float = Field(7200.0, gt=0)
    endurance_required: bool = True
    payload_kg: float = Field(22.7, ge=0)
    cruise_altitude_m: float = Field(1500.0, ge=0, le=20000.0)
    dash_altitude_m: float = Field(300.0, ge=0, le=20000.0)
    cruise_mach: float = 0.18  # overwritten by sizing if cruise_cl is used
    cruise_cl: float = Field(0.35, gt=0.05, lt=1.5)
    dash_mach_cap: float = Field(0.70, gt=0.1, le=0.95)
    limit_positive_g: float = 4.0
    limit_negative_g: float = -2.0
    safety_factor: float = 1.5
    # Tailless band: trim demands SM small; enforced at full AND reserve fuel.
    static_margin_min: float = 0.03
    static_margin_max: float = 0.10
    reserve_fuel_fraction: float = Field(0.08, ge=0, lt=0.5)
    cl_max: float = Field(1.2, gt=0.3, lt=3.0)
    # ``aircraft`` is an already finite-wing value. ``section`` requests the
    # documented finite-wing/sweep conversion in mission.balance.
    cl_max_basis: Literal["aircraft", "section"] = "aircraft"
    stall_speed_max_mps: float = Field(30.0, gt=5.0)


class MaterialSpec(PhysicalModel):
    name: str = "Al7050-T7451"
    E_pa: float = 71.7e9
    nu: float = 0.33
    yield_pa: float = 470.0e6
    density_kg_m3: float = 2830.0

    @computed_field
    @property
    def G_pa(self) -> float:
        return self.E_pa / (2.0 * (1.0 + self.nu))


class SpanwiseStructureStation(PhysicalModel):
    """One semi-span structural-property station, root (0) to tip (1)."""

    eta: float = Field(ge=0.0, le=1.0)
    ei_bend_n_m2: float = Field(gt=0.0)
    gj_n_m2: float = Field(gt=0.0)
    mass_per_span_kg_m: float = Field(gt=0.0)
    polar_mass_moment_per_span_kg_m: float | None = Field(default=None, gt=0.0)
    section_modulus_m3: float = Field(gt=0.0)


class ModalCalibrationTarget(PhysicalModel):
    """Visible ground-test target used only for aircraft-specific calibration."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    family: Literal["bending", "torsion"]
    order: int = Field(ge=1, le=10)
    frequency_hz: float = Field(gt=0.0)
    damping_fraction: float = Field(ge=0.0, lt=0.5)
    source: str = Field(min_length=1)


class SpanwiseSensorStation(PhysicalModel):
    """Measured semi-span location shared by a gauge/IMU station family."""

    id: str = Field(pattern=r"^[A-Z][A-Z0-9]*$")
    eta: float = Field(gt=0.0, le=1.0)
    source: str = Field(min_length=1)


class StructureSpec(PhysicalModel):
    fem_model_type: Literal["tube", "wingbox"] = "wingbox"
    spar_thickness_m: float = Field(0.0025, gt=1e-4, lt=0.05)
    skin_thickness_m: float = Field(0.0018, gt=1e-4, lt=0.05)
    tube_radius_m: float = 0.018
    tube_thickness_m: float = 0.0025
    wing_weight_ratio: float = 1.35  # fasteners, ribs, overlaps not in the box
    n_spanwise: int = 9  # odd full-span count for OAS generate_mesh
    n_chordwise: int = 3
    material: MaterialSpec = Field(default_factory=MaterialSpec)
    spanwise: list[SpanwiseStructureStation] | None = Field(
        default=None,
        min_length=2,
    )
    modal_calibration: list[ModalCalibrationTarget] = Field(default_factory=list)
    sensor_stations: list[SpanwiseSensorStation] = Field(default_factory=list)

    @model_validator(mode="after")
    def spanwise_station_order(self) -> Self:
        target_ids = [target.id for target in self.modal_calibration]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("structures.modal_calibration ids must be unique")
        sensor_ids = [station.id for station in self.sensor_stations]
        if len(sensor_ids) != len(set(sensor_ids)):
            raise ValueError("structures.sensor_stations ids must be unique")
        if self.spanwise is None:
            return self
        eta = [station.eta for station in self.spanwise]
        if abs(eta[0]) > 1e-12 or abs(eta[-1] - 1.0) > 1e-12:
            raise ValueError("structures.spanwise must start at eta=0 and end at eta=1")
        if any(right <= left for left, right in zip(eta, eta[1:])):
            raise ValueError("structures.spanwise eta values must be strictly increasing")
        return self


class DragSpec(PhysicalModel):
    """Declared non-component parasite-drag assumptions."""

    interference_fraction: float = Field(0.08, ge=0.0, le=0.5)
    protuberance_cd0: float = Field(0.004, ge=0.0, le=0.05)


class SketchEnvelopeSpec(PhysicalModel):
    """Per-concept sketch priors for MDO bounds and shape fidelity.

    Omit this block to keep the original KingTech target envelope
    (span/L 1.5±0.2, root/L 0.47±0.07, LE sweep 32±4 deg), recorded in
    docs/history/2026-08-19-1549-pipeline-bootstrap.md.

    ``requirement`` preserves the measured envelope as a hard bound.
    ``inspiration`` treats one tolerance as a no-penalty visual prior and lets
    MDO move as far as ``hard_scale`` tolerances when flight physics requires
    it. ``reproduction`` freezes source geometry and mass properties; only a
    deterministic trim-control closure may alter the delivered reference
    aircraft. Optional fin priors extend the same contract to the vertical tail.
    """

    treatment: Literal["requirement", "inspiration", "reproduction"] = "requirement"
    hard_scale: float = Field(3.0, ge=1.0, le=10.0)
    fidelity_weight: float = Field(1.0, ge=0.0, le=100.0)
    span_over_length: float = Field(..., gt=0.5, lt=4.0)
    span_over_length_tol: float = Field(0.20, gt=0.0, lt=1.5)
    root_over_length: float = Field(..., gt=0.02, lt=1.5)
    root_over_length_tol: float = Field(0.07, gt=0.0, lt=0.8)
    le_sweep_deg: float = Field(..., ge=-45.0, le=60.0)
    le_sweep_tol_deg: float = Field(4.0, gt=0.0, lt=25.0)
    taper: float = Field(0.32, gt=0.03, le=1.0)
    taper_tol: float = Field(0.08, gt=0.0, lt=0.5)
    x_le_root_over_length: float = Field(0.35, ge=0.05, le=0.90)
    x_le_root_over_length_tol: float = Field(0.08, gt=0.0, lt=0.4)
    payload_bay_x_lo_m: float | None = None
    payload_bay_x_hi_m: float | None = None
    fuel_tank_x_lo_m: float | None = None
    fuel_tank_x_hi_m: float | None = None
    twist_tip_lo_deg: float | None = None
    twist_tip_hi_deg: float | None = None
    fin_span_m: float | None = Field(None, gt=0.0, lt=10.0)
    fin_span_tol_m: float | None = Field(None, gt=0.0, lt=5.0)
    fin_root_chord_m: float | None = Field(None, gt=0.0, lt=10.0)
    fin_root_chord_tol_m: float | None = Field(None, gt=0.0, lt=5.0)
    fin_le_sweep_deg: float | None = Field(None, ge=-45.0, le=75.0)
    fin_le_sweep_tol_deg: float | None = Field(None, gt=0.0, lt=45.0)
    fin_cant_deg: float | None = Field(None, ge=0.0, le=75.0)
    fin_cant_tol_deg: float | None = Field(None, gt=0.0, lt=45.0)
    fin_x_le_m: float | None = Field(None, ge=0.0, lt=50.0)
    fin_x_le_tol_m: float | None = Field(None, gt=0.0, lt=10.0)


class MassGuessSpec(PhysicalModel):
    """Optional overrides; sizing fills these in."""

    fuel_mass_kg: float = Field(18.0, ge=0)
    fuel_mass_mode: Literal["sized", "fixed"] = "sized"
    # When supplied, this audited reference value replaces the small-UAV
    # component regression. It includes installed engines but excludes payload
    # and usable fuel, matching conventional operating-empty-mass bookkeeping.
    operating_empty_mass_kg: float | None = Field(None, gt=0.0)
    operating_empty_cg_x_m: float | None = Field(None, ge=0.0, lt=100.0)
    systems_kg: float = 6.5
    landing_gear_fraction: float = 0.035
    avionics_kg: float = 3.0
    contingency_fraction: float = 0.08

    @model_validator(mode="after")
    def validate_reference_mass(self) -> Self:
        if (self.operating_empty_cg_x_m is None) != (
            self.operating_empty_mass_kg is None
        ):
            raise ValueError(
                "operating_empty_mass_kg and operating_empty_cg_x_m "
                "must be supplied together"
            )
        return self


class InertiaSpec(PhysicalModel):
    """Rigid-body inertia about the declared CG in body axes."""

    ixx_kg_m2: float = Field(gt=0.0)
    iyy_kg_m2: float = Field(gt=0.0)
    izz_kg_m2: float = Field(gt=0.0)
    ixy_kg_m2: float = 0.0
    ixz_kg_m2: float = 0.0
    iyz_kg_m2: float = 0.0
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def positive_definite(self) -> Self:
        first_minor = self.ixx_kg_m2 * self.iyy_kg_m2 - self.ixy_kg_m2**2
        determinant = (
            self.ixx_kg_m2 * self.iyy_kg_m2 * self.izz_kg_m2
            + 2.0 * self.ixy_kg_m2 * self.ixz_kg_m2 * self.iyz_kg_m2
            - self.ixx_kg_m2 * self.iyz_kg_m2**2
            - self.iyy_kg_m2 * self.ixz_kg_m2**2
            - self.izz_kg_m2 * self.ixy_kg_m2**2
        )
        if first_minor <= 0.0 or determinant <= 0.0:
            raise ValueError("inertia tensor must be positive definite")
        return self


class ControlMixSpec(PhysicalModel):
    """One logical derivative group driven by a physical control surface."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    mode: Literal["collective", "differential", "single"]
    axis: Literal["pitch", "roll", "yaw", "lift"]
    gain: float = Field(1.0, ge=-2.0, le=2.0)


class ControlSurfaceSpec(PhysicalModel):
    """Trailing-edge control subsurface and its logical VSPAERO mixing."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    host: Literal["wing", "htail", "vtail"]
    span_start_fraction: float = Field(ge=0.0, lt=1.0)
    span_end_fraction: float = Field(gt=0.0, le=1.0)
    chord_fraction: float = Field(gt=0.02, lt=0.6)
    max_up_deg: float = Field(gt=0.0, le=60.0)
    max_down_deg: float = Field(gt=0.0, le=60.0)
    source: str = Field(min_length=1)
    mixing: list[ControlMixSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def span_order(self) -> Self:
        if self.span_end_fraction <= self.span_start_fraction:
            raise ValueError(
                "control-surface span_end_fraction must exceed span_start_fraction"
            )
        ids = [mix.id for mix in self.mixing]
        if len(ids) != len(set(ids)):
            raise ValueError("control-surface mixing ids must be unique per surface")
        if self.host == "vtail" and any(
            mix.mode == "differential" for mix in self.mixing
        ):
            raise ValueError("vtail controls cannot use mirrored differential mixing")
        return self


class AeroelasticSpec(PhysicalModel):
    enabled: bool = False
    strip_count: int = Field(48, ge=12, le=200)
    modes_per_family: int = Field(1, ge=1, le=4)
    frequency_min_hz: float = Field(0.5, gt=0.0)
    frequency_max_hz: float = Field(30.0, gt=0.0)
    frequency_points: int = Field(160, ge=32, le=1000)
    maximum_reduced_frequency: float = Field(0.30, gt=0.05, le=1.0)
    elastic_axis_fraction_chord: float = Field(0.40, ge=0.20, le=0.60)
    lift_curve_slope_per_rad: float | None = Field(default=None, gt=1.0, le=8.0)
    calibration_id: Literal["none", "diana2-training-aeroelastic-v1"] = "none"

    @model_validator(mode="after")
    def frequency_order(self) -> Self:
        if self.frequency_max_hz <= self.frequency_min_hz:
            raise ValueError(
                "aeroelastic frequency_max_hz must exceed frequency_min_hz"
            )
        return self


class FlightDynamicsSpec(PhysicalModel):
    """Optional measured mass properties and flight-control geometry."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    enabled: bool = False
    reference_airspeed_mps: float = Field(18.0, gt=1.0, le=250.0)
    reference_altitude_m: float = Field(0.0, ge=0.0, le=20000.0)
    inertia: InertiaSpec | None = None
    control_surfaces: list[ControlSurfaceSpec] = Field(default_factory=list)
    aeroelastic: AeroelasticSpec = Field(default_factory=AeroelasticSpec)
    allow_diagonal_inertia_approximation: bool = False
    calibration_id: Literal[
        "none",
        "ntnu-x8-low-re-elevon-v1",
        "diana2-training-aeroelastic-v1",
    ] = "none"

    @model_validator(mode="after")
    def enabled_contract(self) -> Self:
        if self.enabled and (self.inertia is None or not self.control_surfaces):
            raise ValueError(
                "enabled flight dynamics requires inertia and control_surfaces"
            )
        surface_ids = [surface.id for surface in self.control_surfaces]
        if len(surface_ids) != len(set(surface_ids)):
            raise ValueError("flight-dynamics control-surface ids must be unique")
        groups: dict[str, tuple[str, str]] = {}
        for surface in self.control_surfaces:
            for mix in surface.mixing:
                signature = (mix.mode, mix.axis)
                previous = groups.setdefault(mix.id, signature)
                if previous != signature:
                    raise ValueError(
                        f"control group {mix.id!r} has inconsistent mode or axis"
                    )
        if (
            self.enabled
            and self.inertia is not None
            and any(
                abs(value) > 1e-12
                for value in (
                    self.inertia.ixy_kg_m2,
                    self.inertia.ixz_kg_m2,
                    self.inertia.iyz_kg_m2,
                )
            )
            and not self.allow_diagonal_inertia_approximation
        ):
            raise ValueError(
                "non-diagonal inertia requires an explicit diagonal approximation "
                "allowance for the Elodin backend"
            )
        return self


class SolverSpec(PhysicalModel):
    oas_with_viscous: bool = True
    oas_with_wave: bool = True
    optimize_maxiter: int = 35
    optimize_tol: float = 1e-5
    fd_step: float = 1e-3
    vspaero_wake_iters: int = 5
    su2_maxiter: int = 200
    gmsh_lc_m: float = 0.08
    stability_method: Literal["lifting_surface", "hybrid_component"] = "lifting_surface"
    # OAS-calibrated constants at the sketch target sweep for the closed-form
    # balance/trim model. The balance model scales them across that concept's
    # sweep envelope; aero re-measures and validation gates the result.
    np_shift_mac: float = 0.043  # corrected-mesh 32° reference, aft of 25% MAC
    # Generated hybrid-component calibrations. Source designs normally leave
    # these unset; the baseline aero stage measures them from its own geometry
    # before the MDO/reproduction stage serializes the delivered aircraft.
    wing_body_np_mac: float | None = Field(None, ge=-2.0, le=3.0)
    wing_body_cl_alpha_per_deg: float | None = Field(None, gt=0.0, le=0.5)
    cm_washout_per_deg: float = 0.00362  # corrected-mesh dCm per degree of washout
    tail_incidence_offset_deg: float = 0.0  # OAS minus low-order htail trim incidence
    # Optional source-backed correction to the default conventional-tail lift
    # effectiveness. Keep this at 1.0 for uncalibrated concepts.
    tail_lift_effectiveness_factor: float = Field(1.0, ge=0.3, le=1.2)
    tail_lift_effectiveness_source: str | None = None

    @model_validator(mode="after")
    def validate_tail_effectiveness_calibration(self) -> Self:
        if (
            abs(self.tail_lift_effectiveness_factor - 1.0) > 1e-12
            and not self.tail_lift_effectiveness_source
        ):
            raise ValueError(
                "tail_lift_effectiveness_factor requires a source citation"
            )
        return self


class VehicleSpec(PhysicalModel):
    _wing_mass_override_kg: float | None = PrivateAttr(default=None)

    name: str = "openair-target"
    notes: str = ""
    sketch: SketchEnvelopeSpec | None = None
    engine: EngineSpec = Field(default_factory=EngineSpec)
    wing: WingSpec = Field(default_factory=WingSpec)
    fuselage: FuselageSpec = Field(default_factory=FuselageSpec)
    vtail: VerticalTailSpec = Field(default_factory=VerticalTailSpec)
    htail: HorizontalTailSpec = Field(default_factory=HorizontalTailSpec)
    mission: MissionSpec = Field(default_factory=MissionSpec)
    structures: StructureSpec = Field(default_factory=StructureSpec)
    drag: DragSpec = Field(default_factory=DragSpec)
    mass: MassGuessSpec = Field(default_factory=MassGuessSpec)
    flight_dynamics: FlightDynamicsSpec = Field(default_factory=FlightDynamicsSpec)
    solver: SolverSpec = Field(default_factory=SolverSpec)

    @model_validator(mode="after")
    def validate_reference_vehicle(self) -> Self:
        empty = self.mass.operating_empty_mass_kg
        empty_cg = self.mass.operating_empty_cg_x_m
        if empty is not None and empty < self.engine.dry_mass_kg:
            raise ValueError(
                "operating_empty_mass_kg cannot be less than installed engine mass"
            )
        if empty_cg is not None and empty_cg > self.fuselage.length_m:
            raise ValueError(
                "operating_empty_cg_x_m must lie within the fuselage length"
            )
        if self.engine.energy_source == "electric":
            if self.mass.fuel_mass_mode != "fixed" or self.mass.fuel_mass_kg != 0.0:
                raise ValueError(
                    "electric reproduction requires fixed zero liquid-fuel mass"
                )
        if not self.mission.endurance_required:
            reproduction = bool(
                self.sketch is not None and self.sketch.treatment == "reproduction"
            )
            if not reproduction or self.engine.energy_source != "electric":
                raise ValueError(
                    "endurance may be not-applicable only for an electric "
                    "source-locked reproduction"
                )
        for surface in self.flight_dynamics.control_surfaces:
            if surface.host == "htail" and self.htail.span_m <= 0.05:
                raise ValueError("htail control surface requires a horizontal tail")
            if surface.host == "vtail" and self.vtail.count != 1:
                raise ValueError(
                    "vtail control surfaces currently require one centerline fin"
                )
            for mix in surface.mixing:
                if mix.mode == "single" and surface.host != "vtail":
                    raise ValueError("single mixing is reserved for centerline vtail")
                if mix.mode in {"collective", "differential"} and surface.host == "vtail":
                    raise ValueError(
                        "centerline vtail controls require single mixing"
                    )
        return self

    @computed_field
    @property
    def n_ult(self) -> float:
        return self.mission.limit_positive_g * self.mission.safety_factor
