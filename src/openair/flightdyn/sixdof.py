"""Driver for the isolated, hash-pinned Elodin replay process."""

from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from openair.paths import REPO_ROOT
from openair.provenance import sha256_file

ELODIN_ROOT = REPO_ROOT / "tools" / "elodin"
ELODIN_PYTHON = ELODIN_ROOT / ".venv" / "bin" / "python"
ELODIN_PROVENANCE = ELODIN_ROOT / "provenance.json"
REPLAY_SCRIPT = REPO_ROOT / "scripts" / "elodin_replay.py"
LINEAR_VERIFY_SCRIPT = REPO_ROOT / "scripts" / "elodin_linear_verify.py"


def elodin_available() -> bool:
    return ELODIN_PYTHON.is_file() and ELODIN_PROVENANCE.is_file()


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _control_summary(path: Path) -> dict[str, float | int]:
    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or "time_s" not in rows[0]:
        raise ValueError(f"{path} has no time_s control history")
    return {
        "samples": len(rows),
        "duration_s": float(rows[-1]["time_s"]),
    }


def _deterministic_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "JAX_ENABLE_X64": "true",
            "XLA_FLAGS": "--xla_cpu_multi_thread_eigen=false "
            "intra_op_parallelism_threads=1",
        }
    )
    return environment


def verify_elodin_linear_model(
    outdir: Path,
    *,
    timeout_s: int = 300,
) -> dict[str, Any]:
    """Exercise Elodin's complete six_dof path on a known damped mode."""
    if not elodin_available():
        return {
            "ok": False,
            "status": "unavailable",
            "reason": "run scripts/install_elodin.sh",
        }
    outdir.mkdir(parents=True, exist_ok=True)
    output = outdir / "linear-verification.json"
    environment = _deterministic_environment()
    environment["OPENAIR_ELODIN_OUTPUT"] = str(output.resolve())
    completed = subprocess.run(
        [str(ELODIN_PYTHON), str(LINEAR_VERIFY_SCRIPT), "run"],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "status": "failed",
            "reason": "Elodin linear verification process failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    payload = _load_json(output)
    payload["artifact"] = str(output)
    payload["artifact_sha256"] = sha256_file(output)
    payload["script_sha256"] = sha256_file(LINEAR_VERIFY_SCRIPT)
    payload["elodin"] = _load_json(ELODIN_PROVENANCE)
    payload["runtime_environment"] = {
        "JAX_ENABLE_X64": environment["JAX_ENABLE_X64"],
        "XLA_FLAGS": environment["XLA_FLAGS"],
    }
    return payload


def replay_flightdyn(
    model_path: Path,
    controls_path: Path,
    outdir: Path,
    *,
    dt_s: float = 0.01,
    timeout_s: int = 900,
) -> dict[str, Any]:
    """Replay recorded controls through Elodin's RK4 rigid-body integrator."""
    if not elodin_available():
        return {
            "ok": False,
            "status": "unavailable",
            "reason": "run scripts/install_elodin.sh",
        }
    if dt_s <= 0.0 or dt_s > 0.05:
        raise ValueError("Elodin replay timestep must be in (0, 0.05] seconds")
    model = _load_json(model_path)
    if not model.get("ok"):
        raise ValueError("flightdyn model must be a passing stage artifact")
    control_summary = _control_summary(controls_path)
    outdir.mkdir(parents=True, exist_ok=True)
    output = outdir / "replay.csv"
    request_path = outdir / "replay-request.json"
    database = outdir / "elodin-db"
    request = {
        "model": str(model_path.resolve()),
        "controls": str(controls_path.resolve()),
        "output": str(output.resolve()),
        "db_path": str(database.resolve()),
        "dt_s": dt_s,
    }
    with open(request_path, "w", encoding="utf-8") as stream:
        json.dump(request, stream, indent=2, sort_keys=True)
        stream.write("\n")

    environment = _deterministic_environment()
    environment["OPENAIR_ELODIN_REQUEST"] = str(request_path.resolve())
    completed = subprocess.run(
        [str(ELODIN_PYTHON), str(REPLAY_SCRIPT), "run"],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "status": "failed",
            "reason": "Elodin replay process failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    if not output.is_file():
        return {
            "ok": False,
            "status": "failed",
            "reason": "Elodin replay did not produce replay.csv",
        }

    elodin = _load_json(ELODIN_PROVENANCE)
    payload = {
        "ok": True,
        "status": "complete",
        "method": "Elodin six_dof with Integrator.Rk4 and open-air force system",
        "backend": "cranelift",
        "interactive": False,
        "fixed_timestep_s": dt_s,
        "runtime_environment": {
            "JAX_ENABLE_X64": environment["JAX_ENABLE_X64"],
            "XLA_FLAGS": environment["XLA_FLAGS"],
        },
        "recorded_forcing": [
            "collective_elevon_rad",
            "differential_elevon_rad",
            "throttle",
            "airspeed_mps",
            "engine-deck thrust derived from throttle and airspeed",
        ],
        "control_history": control_summary,
        "elodin": elodin,
        "inputs": {
            "flightdyn_json": str(model_path),
            "controls_csv": str(controls_path),
        },
        "input_sha256": {
            "flightdyn_json": sha256_file(model_path),
            "controls_csv": sha256_file(controls_path),
            "replay_script": sha256_file(REPLAY_SCRIPT),
        },
        "artifacts": {
            "replay_csv": str(output),
            "replay_request": str(request_path),
            "database": str(database),
        },
        "artifact_sha256": {
            "replay_csv": sha256_file(output),
            "replay_request": sha256_file(request_path),
        },
    }
    summary_path = outdir / "replay.json"
    with open(summary_path, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return payload
