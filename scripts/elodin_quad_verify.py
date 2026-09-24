#!/usr/bin/env python3
"""Verify a multirotor package in the pinned isolated Elodin runtime."""

import argparse
import hashlib
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

VerificationMode = ty.Annotated[
    jax.Array,
    el.Component(
        "verification_mode",
        el.ComponentType(el.PrimitiveType.F64, (1,)),
        metadata={"element_names": "hover"},
    ),
]


@el.dataclass
class VerificationEntity(el.Archetype):
    verification_mode: VerificationMode = field(
        default_factory=lambda: jnp.zeros(1, dtype=jnp.float64)
    )


def _load_package(root: Path):
    model = json.loads((root / "elodin_model.json").read_text(encoding="utf-8"))
    if model.get("vehicle_family") != "multirotor":
        raise ValueError("package is not a multirotor model")
    for name, entry in model["manifest"].items():
        path = (root / entry["path"]).resolve()
        if root.resolve() not in path.parents or path.is_symlink() or not path.is_file():
            raise ValueError(f"invalid manifest path: {name}")
        if path.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"manifest size mismatch: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"manifest hash mismatch: {name}")
    table_path = root / model["airframe_aero"]["table_asset"]
    return model, dict(np.load(table_path, allow_pickle=False))


def _numpy_interp(tables, velocity):
    velocity = np.asarray(velocity, dtype=float)
    speed = np.linalg.norm(velocity)
    if speed <= 1e-12:
        return np.zeros(3)
    unit = velocity / speed
    theta_value = math.degrees(math.acos(float(np.clip(unit[2], -1.0, 1.0))))
    phi_value = math.degrees(math.atan2(unit[1], unit[0])) % 360.0
    theta, phi = tables["theta_deg"], tables["phi_deg"]
    dt, dp = float(theta[1] - theta[0]), float(phi[1] - phi[0])
    ti = min(int(math.floor(theta_value / dt)), len(theta) - 2)
    pi = int(math.floor(phi_value / dp)) % len(phi)
    pj = (pi + 1) % len(phi)
    tf = (theta_value - theta[ti]) / dt
    pf = (phi_value - phi[pi]) / dp
    values = tables["force_area_body_m2"]
    return (
        (1 - tf) * (1 - pf) * values[ti, pi]
        + (1 - tf) * pf * values[ti, pj]
        + tf * (1 - pf) * values[ti + 1, pi]
        + tf * pf * values[ti + 1, pj]
    )


def _make_force_system(tables, density: float, mass: float):
    theta = jnp.asarray(tables["theta_deg"])
    phi = jnp.asarray(tables["phi_deg"])
    force_area = jnp.asarray(tables["force_area_body_m2"])

    def interp(velocity):
        speed = jnp.linalg.norm(velocity)
        unit = velocity / jnp.maximum(speed, 1e-9)
        theta_value = jnp.degrees(jnp.arccos(jnp.clip(unit[2], -1.0, 1.0)))
        phi_value = jnp.mod(jnp.degrees(jnp.arctan2(unit[1], unit[0])), 360.0)
        dt, dp = theta[1] - theta[0], phi[1] - phi[0]
        ti = jnp.minimum(
            jnp.floor(theta_value / dt).astype(jnp.int32), theta.size - 2
        )
        pi = jnp.mod(jnp.floor(phi_value / dp).astype(jnp.int32), phi.size)
        pj = jnp.mod(pi + 1, phi.size)
        tf = (theta_value - theta[ti]) / dt
        pf = (phi_value - phi[pi]) / dp
        return (
            (1 - tf) * (1 - pf) * force_area[ti, pi]
            + (1 - tf) * pf * force_area[ti, pj]
            + tf * (1 - pf) * force_area[ti + 1, pi]
            + tf * pf * force_area[ti + 1, pj]
        )

    @el.map
    def apply(
        pos: el.WorldPos,
        vel: el.WorldVel,
        force: el.Force,
        mode: VerificationMode,
    ) -> el.Force:
        velocity_body = pos.angular().inverse() @ vel.linear()
        speed = jnp.linalg.norm(velocity_body)
        body_force = 0.5 * density * speed**2 * interp(velocity_body)
        body_force = jnp.where(speed > 1e-7, body_force, jnp.zeros(3))
        gravity = jnp.array([0.0, 0.0, -9.80665 * mass])
        thrust = jnp.array([0.0, 0.0, 9.80665 * mass * mode[0]])
        return force + el.SpatialForce(
            linear=gravity + pos.angular() @ (body_force + thrust),
            torque=jnp.zeros(3),
        )

    return apply


def _run_cases(
    root: Path,
    model,
    tables,
    *,
    duration_s: float,
    rate_hz: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mass = float(model["mass_properties"]["mass_kg"])
    inertia = jnp.asarray(model["mass_properties"]["elodin_diagonal_kg_m2"])
    density = float(model["airframe_aero"]["reference_air_density_kg_m3"])
    world = el.World()
    def body(position, hover):
        return [
            el.Body(
                world_pos=el.SpatialTransform(
                    linear=jnp.asarray(position),
                    angular=el.Quaternion(jnp.array([0.0, 0.0, 0.0, 1.0])),
                ),
                world_vel=el.SpatialMotion(
                    linear=jnp.zeros(3),
                    angular=jnp.zeros(3),
                ),
                inertia=el.SpatialInertia(mass=mass, inertia=inertia),
            ),
            VerificationEntity(verification_mode=jnp.array([float(hover)])),
        ]

    world.spawn(body([0.0, 0.0, 0.0], True), name="hover", id="hover")
    world.spawn(body([10.0, 0.0, 0.0], False), name="terminal", id="terminal")
    system = el.six_dof(
        sys=_make_force_system(tables, density, mass),
        integrator=el.Integrator.SemiImplicit,
    )
    hover_position = np.zeros(3)
    hover_velocity = np.zeros(3)
    terminal_velocity = np.zeros(3)

    def capture(_: int, context: el.StepContext) -> None:
        nonlocal hover_position, hover_velocity, terminal_velocity
        hover_pos_raw = np.asarray(context.read_component("hover.world_pos"))
        hover_vel_raw = np.asarray(context.read_component("hover.world_vel"))
        terminal_vel_raw = np.asarray(context.read_component("terminal.world_vel"))
        hover_position = hover_pos_raw[4:7]
        hover_velocity = hover_vel_raw[3:6]
        terminal_velocity = terminal_vel_raw[3:6]

    database = root / "verify-multirotor-db"
    shutil.rmtree(database, ignore_errors=True)
    world.run(
        system,
        simulation_rate=rate_hz,
        max_ticks=round(duration_s * rate_hz),
        optimize=False,
        post_step=capture,
        db_path=str(database),
        interactive=False,
        start_timestamp=0,
        log_level="error",
        backend="cranelift",
    )
    shutil.rmtree(database, ignore_errors=True)
    return hover_position, hover_velocity, terminal_velocity


def run(package_root: Path, output: Path) -> None:
    model, tables = _load_package(package_root)
    sign_rows = []
    for velocity in (
        np.array([1.0, 0.0, 0.0]),
        np.array([-1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, -1.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        np.array([0.0, 0.0, -1.0]),
    ):
        force_area = _numpy_interp(tables, velocity)
        sign_rows.append(
            {
                "velocity": velocity.tolist(),
                "force_area": force_area.tolist(),
                "power_area": float(force_area @ velocity),
            }
        )
    mass = float(model["mass_properties"]["mass_kg"])
    density = float(model["airframe_aero"]["reference_air_density_kg_m3"])
    minus_z_area = float(
        -_numpy_interp(tables, np.array([0.0, 0.0, -1.0]))
        @ np.array([0.0, 0.0, -1.0])
    )
    terminal_speed = math.sqrt(2.0 * mass * 9.80665 / (density * minus_z_area))
    duration = 12.0
    expected_finite_time = terminal_speed * math.tanh(
        9.80665 * duration / terminal_speed
    )
    hover_position, hover_velocity, terminal_velocity = _run_cases(
        output.parent, model, tables, duration_s=duration, rate_hz=400.0
    )
    terminal_observed = abs(float(terminal_velocity[2]))
    relative_error = abs(terminal_observed - expected_finite_time) / expected_finite_time
    motors = model["propulsion"]["motors"]
    checks = {
        "manifest_verified": True,
        "force_signs": all(row["power_area"] < 0.0 for row in sign_rows),
        "motor_order": [item["label"] for item in motors] == ["BR", "FR", "BL", "FL"],
        "motor_spins": [item["spin_direction"] for item in motors] == [-1, 1, 1, -1],
        "hover_position_norm_m": float(np.linalg.norm(hover_position)),
        "hover_velocity_norm_mps": float(np.linalg.norm(hover_velocity)),
        "hover_equilibrium": bool(
            np.linalg.norm(hover_position) < 1e-6
            and np.linalg.norm(hover_velocity) < 1e-6
        ),
        "terminal_expected_mps": expected_finite_time,
        "terminal_observed_mps": terminal_observed,
        "terminal_relative_error": relative_error,
        "terminal_speed_ok": relative_error < 0.02,
    }
    payload = {
        "ok": all(
            checks[key]
            for key in (
                "manifest_verified",
                "force_signs",
                "motor_order",
                "motor_spins",
                "hover_equilibrium",
                "terminal_speed_ok",
            )
        ),
        "method": "Elodin 0.18 six_dof SemiImplicit package-table verification",
        "sign_battery": sign_rows,
        "checks": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    args = parser.parse_args()
    if args.command == "run":
        run(
            Path(os.environ["OPENAIR_MULTIROTOR_PACKAGE"]).resolve(),
            Path(os.environ["OPENAIR_ELODIN_OUTPUT"]).resolve(),
        )


if __name__ == "__main__":
    main()
