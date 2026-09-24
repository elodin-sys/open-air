# racing-quad-streamlined-baseline — Betaflight SITL integration

This package is **geometry-correlated**, not wind-tunnel or flight validated.
The loader must verify every SHA-256 entry before creating the Elodin world.

## 1. Load and verify

```python
import hashlib, json
from pathlib import Path
import numpy as np

def load_multirotor_package(root: Path):
    model_path = root / "elodin_model.json"
    model = json.loads(model_path.read_text())
    assert model["schema_version"] == "1.0"
    assert model["vehicle_family"] == "multirotor"
    for name, entry in model["manifest"].items():
        asset = (root / entry["path"]).resolve()
        assert root.resolve() in asset.parents and asset.is_file() and not asset.is_symlink()
        assert asset.stat().st_size == entry["size_bytes"]
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == entry["sha256"], name
    tables = dict(np.load(root / model["airframe_aero"]["table_asset"], allow_pickle=False))
    return model, tables
```

## 2. Replace `DroneConfig` aircraft constants

Use package data rather than repeating it elsewhere:

```python
mass = 1
inertia_diagonal = np.array([0.011720006697076816, 0.01162480378156742, 0.012138939539590674])
motor_positions = np.array([[-0.12209993433859745, -0.12310393420384019, -0.021871177713846328], [0.12277591785334467, -0.12312539219346227, -0.02164353124433919], [-0.12211232623522908, 0.12158181040770874, -0.021825764300194485], [0.12267485152806816, 0.12172103066845183, -0.02140034394729872]])  # native BF order BR, FR, BL, FL
motor_spin_directions = np.array([-1, 1, 1, -1])
motor_max_thrust = 15
motor_time_constant = 0.02
motor_torque_coeff = 0.012
```

Keep the example's native packet order `[BR, FR, BL, FL]`. The package GLB is
the manifest's `render_glb` asset:

```python
glb_path = root / model["manifest"]["render_glb"]["path"]
```

It is the package's only geometry asset and is already body FLU at CG: X
forward, Y left, Z up. Load it with absolute identity orientation and no Y-up
asset rotation.

## 3. Replace aggregate drag/damping with the table wrench

Delete `create_drag_system(config)` from the physics effector chain and do not
also apply `config.linear_drag` or `config.angular_drag`. That would double
count passive-airframe effects. Load the NPZ once, convert arrays to JAX, then
use this interpolation inside an `@el.map` system:

```python
import typing as ty

import elodin as el
import jax.numpy as jnp

AirframeWrench = ty.Annotated[
    el.SpatialForce,
    el.Component("airframe_wrench", metadata={"element_names": "tx,ty,tz,fx,fy,fz"}),
]

theta = jnp.asarray(tables["theta_deg"])
phi = jnp.asarray(tables["phi_deg"])
force_area = jnp.asarray(tables["force_area_body_m2"])
moment_volume = jnp.asarray(tables["moment_area_length_body_m3"])
force_rate = jnp.asarray(tables["force_rate_derivative_m2_s"])
moment_rate = jnp.asarray(tables["moment_rate_derivative_m3_s"])
rotational = jnp.asarray(tables["rotational_damping_m5"])
rho = float(model["airframe_aero"]["reference_air_density_kg_m3"])

def interp(values, velocity):
    speed = jnp.linalg.norm(velocity)
    unit = velocity / jnp.maximum(speed, 1e-9)
    theta_value = jnp.degrees(jnp.arccos(jnp.clip(unit[2], -1.0, 1.0)))
    phi_value = jnp.mod(jnp.degrees(jnp.arctan2(unit[1], unit[0])), 360.0)
    dt, dp = theta[1] - theta[0], phi[1] - phi[0]
    ti = jnp.minimum(jnp.floor(theta_value / dt).astype(jnp.int32), theta.size - 2)
    pi = jnp.mod(jnp.floor(phi_value / dp).astype(jnp.int32), phi.size)
    pj = jnp.mod(pi + 1, phi.size)
    tf = (theta_value - theta[ti]) / dt
    pf = (phi_value - phi[pi]) / dp
    return ((1-tf)*(1-pf)*values[ti,pi] + (1-tf)*pf*values[ti,pj]
            + tf*(1-pf)*values[ti+1,pi] + tf*pf*values[ti+1,pj])

@el.map
def airframe_aero(pos: el.WorldPos, vel: el.WorldVel) -> AirframeWrench:
    velocity_body = pos.angular().inverse() @ vel.linear()
    omega_body = pos.angular().inverse() @ vel.angular()
    speed = jnp.linalg.norm(velocity_body)
    qbar = 0.5 * rho * speed**2
    moving_force = qbar * (interp(force_area, velocity_body)
                           + interp(force_rate, velocity_body) @ omega_body)
    moving_moment = qbar * (interp(moment_volume, velocity_body)
                            + interp(moment_rate, velocity_body) @ omega_body)
    still_moment = -0.5 * rho * rotational * jnp.abs(omega_body) * omega_body
    moving = speed > 1e-6
    return el.SpatialForce(
        linear=jnp.where(moving, moving_force, jnp.zeros(3)),
        torque=jnp.where(moving, moving_moment, still_moment),
    )
```

Add `airframe: AirframeWrench` to the example's force system and apply
`pos.angular() @ airframe` exactly once. Thrust remains a separate body-frame
wrench. The table input is **vehicle velocity relative to air**, not incoming
wind; its force already opposes that velocity.

## 4. Validity and A/B comparison

Publish an `aero_valid` flag when speed leaves
`model.airframe_aero.validity_speed_mps`; do not clamp table angles or force.
Run the existing C0 and physical-axis audit unchanged, then replay the same
manual/scripted commands with (A) the old constants and (B) this package. Any
controller, sensor, timing, Betaflight EEPROM, or scenario change invalidates
attribution to the airframe model.
