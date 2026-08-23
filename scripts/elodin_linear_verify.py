#!/usr/bin/env python3
"""Verify Elodin RK4 against an independently evaluated linear mode."""

import argparse
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

ModeState = ty.Annotated[
    jax.Array,
    el.Component(
        "mode_state",
        el.ComponentType(el.PrimitiveType.F64, (2,)),
        metadata={"element_names": "angle,rate"},
    ),
]

OMEGA_N = 2.4
ZETA = 0.18


@el.dataclass
class Oscillator(el.Archetype):
    mode_state: ModeState = field(
        default_factory=lambda: jnp.zeros(2, dtype=jnp.float64)
    )


@el.map
def mode_state(pos: el.WorldPos, vel: el.WorldVel) -> ModeState:
    quaternion = pos.angular().vector()
    angle = 2.0 * jnp.arctan2(quaternion[1], quaternion[3])
    rate = (pos.angular().inverse() @ vel.angular())[1]
    return jnp.array([angle, rate])


@el.map
def restoring_torque(state: ModeState, force: el.Force) -> el.Force:
    angle, rate = state
    torque = -(OMEGA_N**2) * angle - 2.0 * ZETA * OMEGA_N * rate
    return force + el.SpatialForce(
        linear=jnp.zeros(3),
        torque=jnp.array([0.0, torque, 0.0]),
    )


def analytic_response(time_s: np.ndarray, initial_angle: float) -> np.ndarray:
    omega_d = OMEGA_N * math.sqrt(1.0 - ZETA**2)
    return (
        initial_angle
        * np.exp(-ZETA * OMEGA_N * time_s)
        * (
            np.cos(omega_d * time_s)
            + ZETA * OMEGA_N / omega_d * np.sin(omega_d * time_s)
        )
    )


def run(output: Path) -> None:
    dt = 0.0025
    duration = 8.0
    ticks = round(duration / dt)
    initial_angle = 0.10
    rotation = el.Quaternion(
        jnp.array(
            [
                0.0,
                math.sin(initial_angle / 2.0),
                0.0,
                math.cos(initial_angle / 2.0),
            ]
        )
    )
    world = el.World()
    world.spawn(
        [
            el.Body(
                world_pos=el.SpatialTransform(
                    angular=rotation,
                    linear=jnp.zeros(3),
                ),
                world_vel=el.SpatialMotion(
                    linear=jnp.zeros(3),
                    angular=jnp.zeros(3),
                ),
                inertia=el.SpatialInertia(1.0, jnp.ones(3)),
            ),
            Oscillator(mode_state=jnp.array([initial_angle, 0.0])),
        ],
        name="oscillator",
        id="oscillator",
    )
    system = mode_state | el.six_dof(
        sys=restoring_torque,
        integrator=el.Integrator.Rk4,
    )
    captured: list[float] = []

    def capture(_: int, context: el.StepContext) -> None:
        raw = context.read_component("oscillator.world_pos")
        captured.append(2.0 * math.atan2(float(raw[1]), float(raw[3])))

    database = output.parent / "linear-verification-db"
    shutil.rmtree(database, ignore_errors=True)
    world.run(
        system,
        simulation_rate=1.0 / dt,
        max_ticks=ticks,
        optimize=False,
        post_step=capture,
        db_path=str(database),
        interactive=False,
        start_timestamp=0,
        log_level="error",
        backend="cranelift",
    )
    values = np.asarray(captured)
    time_after_step = (np.arange(len(values)) + 1.0) * dt
    expected = analytic_response(time_after_step, initial_angle)
    errors = values - expected
    rms = float(np.sqrt(np.mean(errors**2)))
    maximum = float(np.max(np.abs(errors)))
    omega_d = OMEGA_N * math.sqrt(1.0 - ZETA**2)
    payload = {
        "ok": bool(rms <= 2e-4 and maximum <= 8e-4),
        "method": "Elodin six_dof Integrator.Rk4",
        "backend": "cranelift",
        "dt_s": dt,
        "duration_s": duration,
        "samples": len(values),
        "known_eigenvalues_per_s": [
            [-ZETA * OMEGA_N, omega_d],
            [-ZETA * OMEGA_N, -omega_d],
        ],
        "expected_natural_frequency_rad_s": OMEGA_N,
        "expected_damping_ratio": ZETA,
        "rms_angle_error_rad": rms,
        "max_angle_error_rad": maximum,
        "acceptance": {
            "rms_angle_error_rad_max": 2e-4,
            "max_angle_error_rad_max": 8e-4,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    args = parser.parse_args()
    if args.command == "run":
        run(Path(os.environ["OPENAIR_ELODIN_OUTPUT"]))


if __name__ == "__main__":
    main()
