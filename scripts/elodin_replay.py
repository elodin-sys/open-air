#!/usr/bin/env python3
"""Isolated Elodin process for deterministic recorded-input 6-DOF replay."""

import argparse
import csv
import json
import math
import os
import shutil
import typing as ty
from dataclasses import field
from pathlib import Path

import elodin as el
import jax
import jax.numpy as jnp
import numpy as np

jax.config.update("jax_enable_x64", True)

RecordedControl = ty.Annotated[
    jax.Array,
    el.Component(
        "recorded_control",
        el.ComponentType(el.PrimitiveType.F64, (5,)),
        metadata={
            "element_names": (
                "collective_elevon,differential_elevon,throttle,airspeed,deck_thrust"
            ),
            "external_control": "true",
            "wait_for_write": "false",
        },
    ),
]
AeroState = ty.Annotated[
    jax.Array,
    el.Component(
        "aero_state",
        el.ComponentType(el.PrimitiveType.F64, (15,)),
        metadata={
            "element_names": ("alpha,beta,p,q,r,u,v,w,CL,CD,CY,Cl,Cm,Cn,airspeed")
        },
    ),
]

MODEL: dict[str, object] = {}
STATE: dict[str, dict[str, float]] = {}
COLLECTIVE: dict[str, float] = {}
DIFFERENTIAL: dict[str, float] = {}
BASE: dict[str, float] = {}
AREA = 1.0
SPAN = 1.0
CHORD = 1.0
DENSITY = 1.225
MASS = 1.0
GRAVITY = 9.80665
TRIM_THRUST = 0.0
TRIM_DECK_THRUST = 0.0
TRIM_ALPHA = 0.0
TRIM_CONTROL = np.zeros(5)


@el.dataclass
class ReplayAircraft(el.Archetype):
    recorded_control: RecordedControl = field(
        default_factory=lambda: jnp.zeros(5, dtype=jnp.float64)
    )
    aero_state: AeroState = field(
        default_factory=lambda: jnp.zeros(15, dtype=jnp.float64)
    )


def _coefficient(
    name: str,
    *,
    alpha_delta: jax.Array,
    beta: jax.Array,
    p_hat: jax.Array,
    q_hat: jax.Array,
    r_hat: jax.Array,
    collective: jax.Array,
    differential: jax.Array,
) -> jax.Array:
    derivatives = STATE[name]
    return (
        BASE[name]
        + derivatives["alpha"] * alpha_delta
        + derivatives["beta"] * beta
        + derivatives["p"] * p_hat
        + derivatives["q"] * q_hat
        + derivatives["r"] * r_hat
        + COLLECTIVE[name] * collective
        + DIFFERENTIAL[name] * differential
    )


@el.map
def aerodynamic_state(
    pos: el.WorldPos,
    vel: el.WorldVel,
    control: RecordedControl,
) -> AeroState:
    velocity_body = pos.angular().inverse() @ vel.linear()
    u, v_left, w_up = velocity_body
    dynamic_speed = jnp.maximum(jnp.linalg.norm(velocity_body), 1.0)
    forced_speed = jnp.where(control[3] > 1.0, control[3], dynamic_speed)
    alpha = jnp.arctan2(-w_up, jnp.maximum(u, 1e-6))
    beta = jnp.arcsin(jnp.clip(-v_left / dynamic_speed, -1.0, 1.0))
    angular_body = pos.angular().inverse() @ vel.angular()
    p_standard = angular_body[0]
    q_standard = -angular_body[1]
    r_standard = -angular_body[2]
    p_hat = p_standard * SPAN / (2.0 * forced_speed)
    q_hat = q_standard * CHORD / (2.0 * forced_speed)
    r_hat = r_standard * SPAN / (2.0 * forced_speed)
    collective = control[0] - TRIM_CONTROL[0]
    differential = control[1] - TRIM_CONTROL[1]
    arguments = {
        "alpha_delta": alpha - TRIM_ALPHA,
        "beta": beta,
        "p_hat": p_hat,
        "q_hat": q_hat,
        "r_hat": r_hat,
        "collective": collective,
        "differential": differential,
    }
    coefficients = jnp.array(
        [
            _coefficient(name, **arguments)
            for name in ("CL", "CD", "CY", "Cl", "Cm", "Cn")
        ]
    )
    return jnp.concatenate(
        (
            jnp.array(
                [
                    alpha,
                    beta,
                    p_standard,
                    q_standard,
                    r_standard,
                    u,
                    -v_left,
                    -w_up,
                ]
            ),
            coefficients,
            jnp.array([forced_speed]),
        )
    )


@el.map
def apply_forces(
    pos: el.WorldPos,
    inertia: el.Inertia,
    force: el.Force,
    aero: AeroState,
    control: RecordedControl,
) -> el.Force:
    alpha = aero[0]
    cl, cd, cy, c_roll, cm, cn, speed = aero[8:15]
    dynamic_pressure = 0.5 * DENSITY * speed**2
    lift = cl * dynamic_pressure * AREA
    drag = cd * dynamic_pressure * AREA
    side = cy * dynamic_pressure * AREA
    cos_alpha = jnp.cos(alpha)
    sin_alpha = jnp.sin(alpha)
    force_standard = jnp.array(
        [
            -drag * cos_alpha + lift * sin_alpha,
            side,
            -lift * cos_alpha - drag * sin_alpha,
        ]
    )
    thrust = jnp.maximum(TRIM_THRUST + control[4] - TRIM_DECK_THRUST, 0.0)
    force_elodin = jnp.array(
        [
            force_standard[0] + thrust,
            -force_standard[1],
            -force_standard[2],
        ]
    )
    torque_elodin = jnp.array(
        [
            c_roll * dynamic_pressure * AREA * SPAN,
            -cm * dynamic_pressure * AREA * CHORD,
            -cn * dynamic_pressure * AREA * SPAN,
        ]
    )
    body_force = el.SpatialForce(linear=force_elodin, torque=torque_elodin)
    gravity = el.SpatialForce(linear=jnp.array([0.0, 0.0, -GRAVITY]) * inertia.mass())
    return force + pos.angular() @ body_force + gravity


def _load_controls(
    path: Path,
    dt: float,
    reference_airspeed: float,
    model: dict[str, object],
) -> tuple[np.ndarray, np.ndarray]:
    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) < 2:
        raise ValueError("recorded controls require at least two samples")
    required = {"time_s", "collective_elevon_rad", "differential_elevon_rad"}
    if not required.issubset(rows[0]):
        raise ValueError(f"recorded controls require columns {sorted(required)}")
    source_time = np.asarray([float(row["time_s"]) for row in rows])
    if source_time[0] != 0.0 or np.any(np.diff(source_time) <= 0.0):
        raise ValueError("control time must start at zero and strictly increase")
    simulation_time = np.arange(
        0.0,
        source_time[-1] + 0.5 * dt,
        dt,
        dtype=float,
    )

    def values(name: str, default: float) -> np.ndarray:
        source = np.asarray(
            [float(row[name]) if row.get(name, "") != "" else default for row in rows]
        )
        return np.interp(simulation_time, source_time, source)

    airspeed = values("airspeed_mps", reference_airspeed)
    throttle = values("throttle", 0.5)
    controls = np.column_stack(
        (
            values("collective_elevon_rad", 0.0),
            values("differential_elevon_rad", 0.0),
            throttle,
            airspeed,
            _deck_thrust(model, airspeed, throttle),
        )
    )
    return simulation_time, controls


def _linear_throttle_curve(
    points: list[dict[str, float]],
    throttle: np.ndarray,
) -> np.ndarray:
    ordered = sorted(points, key=lambda point: float(point["throttle"]))
    return np.interp(
        throttle,
        [float(point["throttle"]) for point in ordered],
        [float(point["thrust_n"]) for point in ordered],
    )


def _deck_thrust(
    model: dict[str, object],
    airspeed_mps: np.ndarray,
    throttle: np.ndarray,
) -> np.ndarray:
    propulsion = ty.cast(dict[str, object], model["propulsion"])
    deck = propulsion.get("deck")
    if not isinstance(deck, dict):
        return float(propulsion["max_thrust_sl_n"]) * throttle
    raw_points = deck.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError("propulsion deck has no points")
    curves: dict[tuple[float, float], list[dict[str, float]]] = {}
    for raw_point in raw_points:
        point = ty.cast(dict[str, float], raw_point)
        condition = (float(point["altitude_m"]), float(point["mach"]))
        curves.setdefault(condition, []).append(point)
    trim = ty.cast(dict[str, float], model["trim_state"])
    altitude = float(trim["altitude_m"])
    reference_mach = max(float(trim.get("mach", 0.0)), 1e-6)
    speed_of_sound = float(trim["airspeed_mps"]) / reference_mach
    altitudes = [condition[0] for condition in curves]
    machs = [condition[1] for condition in curves]
    query_altitude = float(np.clip(altitude, min(altitudes), max(altitudes)))
    query_mach = np.clip(
        airspeed_mps / speed_of_sound,
        min(machs),
        max(machs),
    )
    weighted = np.zeros_like(airspeed_mps)
    weight_sum = np.zeros_like(airspeed_mps)
    altitude_scale = float(deck.get("altitude_scale_m", 10_000.0))
    mach_scale = float(deck.get("mach_scale", 1.0))
    for (curve_altitude, curve_mach), points in curves.items():
        thrust = _linear_throttle_curve(points, throttle)
        distance_sq = ((query_altitude - curve_altitude) / altitude_scale) ** 2 + (
            (query_mach - curve_mach) / mach_scale
        ) ** 2
        weight = 1.0 / np.maximum(distance_sq, 1e-24)
        weighted += weight * thrust
        weight_sum += weight
    return weighted / weight_sum


def _configure_model(model: dict[str, object], trim_control: np.ndarray) -> None:
    global MODEL, STATE, COLLECTIVE, DIFFERENTIAL, BASE
    global AREA, SPAN, CHORD, DENSITY, MASS, TRIM_THRUST
    global TRIM_DECK_THRUST
    global TRIM_ALPHA, TRIM_CONTROL

    MODEL = model
    derivatives = ty.cast(dict[str, object], model["derivatives"])
    STATE = ty.cast(dict[str, dict[str, float]], derivatives["state"])
    controls = ty.cast(dict[str, dict[str, float]], derivatives["controls"])
    COLLECTIVE = controls["collective_elevon"]
    DIFFERENTIAL = controls["differential_elevon"]
    raw_base = ty.cast(dict[str, float], derivatives["base"])
    references = ty.cast(dict[str, float], model["references"])
    trim = ty.cast(dict[str, float], model["trim_state"])
    mass_properties = ty.cast(dict[str, object], model["mass_properties"])
    AREA = float(references["area_m2"])
    SPAN = float(references["span_m"])
    CHORD = float(references["chord_m"])
    DENSITY = float(trim["density_kg_m3"])
    MASS = float(mass_properties["mass_kg"])
    trim_speed = float(trim["airspeed_mps"])
    TRIM_ALPHA = math.radians(float(trim["alpha_deg"]))
    TRIM_CONTROL = trim_control
    dynamic_pressure = 0.5 * DENSITY * trim_speed**2
    equilibrium_cl = MASS * GRAVITY / (dynamic_pressure * AREA)
    BASE = {
        "CL": equilibrium_cl,
        "CD": max(float(raw_base["CD"]), 0.001),
        "CY": 0.0,
        "Cl": 0.0,
        "Cm": 0.0,
        "Cn": 0.0,
    }
    TRIM_THRUST = BASE["CD"] * dynamic_pressure * AREA
    TRIM_DECK_THRUST = float(trim_control[4])


def _euler_from_quaternion(raw: np.ndarray) -> tuple[float, float, float]:
    x, y, z, w = raw[:4]
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch_up = math.asin(float(np.clip(2.0 * (x * z - w * y), -1.0, 1.0)))
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return roll, pitch_up, yaw


def run(request_path: Path) -> None:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    model_path = Path(request["model"])
    controls_path = Path(request["controls"])
    output_path = Path(request["output"])
    db_path = Path(request["db_path"])
    dt = float(request["dt_s"])
    model = json.loads(model_path.read_text(encoding="utf-8"))
    trim_state = model["trim_state"]
    simulation_time, controls = _load_controls(
        controls_path,
        dt,
        float(trim_state["airspeed_mps"]),
        model,
    )
    trim_window = controls[simulation_time <= min(1.0, simulation_time[-1])]
    trim_control = np.median(trim_window, axis=0)
    _configure_model(model, trim_control)

    inertia = np.asarray(
        model["mass_properties"]["elodin_diagonal_kg_m2"],
        dtype=float,
    )
    pitch = TRIM_ALPHA
    initial_rotation = el.Quaternion(
        jnp.array([0.0, -math.sin(pitch / 2.0), 0.0, math.cos(pitch / 2.0)])
    )
    speed = float(controls[0, 3])
    world = el.World()
    world.spawn(
        [
            el.Body(
                world_pos=el.SpatialTransform(
                    angular=initial_rotation,
                    linear=jnp.array([0.0, 0.0, float(trim_state["altitude_m"])]),
                ),
                world_vel=el.SpatialMotion(
                    linear=jnp.array([speed, 0.0, 0.0]),
                    angular=jnp.zeros(3),
                ),
                inertia=el.SpatialInertia(MASS, jnp.asarray(inertia)),
            ),
            ReplayAircraft(recorded_control=jnp.asarray(controls[0])),
        ],
        name="x8",
        id="x8",
    )
    system = aerodynamic_state | el.six_dof(
        sys=apply_forces,
        integrator=el.Integrator.Rk4,
    )
    captured: list[dict[str, float]] = []

    def inject(tick: int, context: el.StepContext) -> None:
        index = min(tick, len(controls) - 1)
        context.write_component("x8.recorded_control", controls[index])

    def capture(tick: int, context: el.StepContext) -> None:
        values = context.component_batch_operation(
            reads=[
                "x8.world_pos",
                "x8.world_vel",
                "x8.aero_state",
                "x8.recorded_control",
            ]
        )
        pos = values["x8.world_pos"]
        aero = values["x8.aero_state"]
        control = values["x8.recorded_control"]
        roll, pitch_up, yaw = _euler_from_quaternion(pos)
        captured.append(
            {
                # ``post_step`` observes the state after advancing one RK4
                # interval. Label it at that physical endpoint rather than at
                # the interval's control-sample time.
                "time_s": (tick + 1) * dt,
                "x_m": float(pos[4]),
                "y_m": float(pos[5]),
                "z_m": float(pos[6]),
                "roll_rad": roll,
                "pitch_rad": pitch_up,
                "yaw_rad": yaw,
                "alpha_rad": float(aero[0]),
                "beta_rad": float(aero[1]),
                "p_rad_s": float(aero[2]),
                "q_rad_s": float(aero[3]),
                "r_rad_s": float(aero[4]),
                "u_mps": float(aero[5]),
                "v_mps": float(aero[6]),
                "w_mps": float(aero[7]),
                "cl": float(aero[8]),
                "cd": float(aero[9]),
                "cy": float(aero[10]),
                "c_roll": float(aero[11]),
                "cm": float(aero[12]),
                "cn": float(aero[13]),
                "collective_elevon_rad": float(control[0]),
                "differential_elevon_rad": float(control[1]),
                "throttle": float(control[2]),
                "forced_airspeed_mps": float(control[3]),
                "deck_thrust_n": float(control[4]),
            }
        )

    shutil.rmtree(db_path, ignore_errors=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    world.run(
        system,
        simulation_rate=1.0 / dt,
        # The source grid includes both t=0 and the final endpoint. Advancing
        # once per interval therefore requires N-1 ticks.
        max_ticks=len(simulation_time) - 1,
        optimize=False,
        pre_step=inject,
        post_step=capture,
        db_path=str(db_path),
        interactive=False,
        start_timestamp=0,
        log_level="error",
        backend="cranelift",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(captured[0]))
        writer.writeheader()
        writer.writerows(captured)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    args = parser.parse_args()
    if args.command == "run":
        run(Path(os.environ["OPENAIR_ELODIN_REQUEST"]))


if __name__ == "__main__":
    main()
