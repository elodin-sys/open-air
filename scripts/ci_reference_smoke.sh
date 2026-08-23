#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
LIBDIR="$ROOT/tools/libs/usr/lib/x86_64-linux-gnu"
if [[ ! -x "$PYTHON" ]]; then
  echo "error: project environment missing at .venv/bin/python" >&2
  exit 2
fi
if [[ ! -d "$LIBDIR" ]]; then
  echo "error: solver library directory missing at $LIBDIR" >&2
  exit 2
fi

export LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OPENMDAO_REPORTS=0
export PATH="$ROOT/tools/elodin/bin:$PATH"

exec "$PYTHON" - "$@" <<'PY'
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from openair.truth.holdout import load_consumed_scorecard


ROOT = Path.cwd()
EXPECTATIONS_PATH = ROOT / "scripts/ci_reference_expectations.yaml"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_expectations() -> dict:
    with open(EXPECTATIONS_PATH, encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("CI reference expectations must be a version-1 mapping")
    return payload


def preflight(expectations: dict) -> dict:
    failures: list[str] = []
    warnings: list[str] = []
    try:
        openvsp = importlib.import_module("openvsp")
    except Exception as exc:
        failures.append(f"OpenVSP Python module unavailable: {exc}")
    else:
        vspaero = Path(openvsp.__file__).resolve().parent / "vspaero"
        if not vspaero.is_file():
            failures.append(f"VSPAERO executable missing beside OpenVSP: {vspaero}")
    if shutil.which("elodin") is None:
        failures.append("Elodin executable missing from tools/elodin/bin")
    optional = {
        "TACS": ROOT / "tools/mamba/envs/tacs/bin/python",
        "SU2": ROOT / "tools/su2/bin/SU2_CFD",
    }
    for name, path in optional.items():
        if not path.is_file():
            warnings.append(f"{name} unavailable; stretch cross-check will warn")
    for case_id, definition in expectations["truth_cases"].items():
        required = definition.get("requires_local_path")
        if required and not (ROOT / str(required)).is_file():
            failures.append(
                f"{case_id} is re-runnable only with local evidence at {required}; "
                "run scripts/seal_diana2_intake.py on this self-hosted runner"
            )
    return {
        "ok": not failures,
        "failures": failures,
        "warnings": warnings,
        "python": sys.executable,
        "ld_library_path": os.environ.get("LD_LIBRARY_PATH", ""),
        "elodin": shutil.which("elodin"),
    }


def run_command(command: list[str], steps: list[dict]) -> None:
    started = time.monotonic()
    print(f"+ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    record = {
        "command": command,
        "returncode": result.returncode,
        "duration_s": round(time.monotonic() - started, 3),
    }
    steps.append(record)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with exit {result.returncode}: {' '.join(command)}"
        )


def assert_design(concept: str, expected: dict) -> dict:
    path = ROOT / "results" / concept / "gate_feedback.json"
    with open(path, encoding="utf-8") as stream:
        feedback = json.load(stream)
    failed = sorted(
        str(gate["id"]) for gate in feedback["gates"] if not gate["ok"]
    )
    expected_failed = sorted(str(value) for value in expected["failed_gate_ids"])
    actual = {
        "passed": int(feedback["passed"]),
        "total": int(feedback["total"]),
        "failed_gate_ids": failed,
    }
    wanted = {
        "passed": int(expected["passed"]),
        "total": int(expected["total"]),
        "failed_gate_ids": expected_failed,
    }
    if actual != wanted:
        raise AssertionError(f"{concept}: gates {actual} != expected {wanted}")
    return actual


def scorecard_status(case_id: str) -> str:
    path = ROOT / "results/truth" / case_id / "scorecard.json"
    with open(path, encoding="utf-8") as stream:
        return str(json.load(stream)["status"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "results/ci_reference_smoke.json",
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    expectations = load_expectations()
    summary = {
        "version": 1,
        "started_at": now(),
        "ok": False,
        "preflight": preflight(expectations),
        "designs": {},
        "truth_cases": {},
        "steps": [],
    }
    error: str | None = None
    try:
        if not summary["preflight"]["ok"]:
            raise RuntimeError("; ".join(summary["preflight"]["failures"]))
        for warning in summary["preflight"]["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
        if args.preflight_only:
            summary["ok"] = True
            return 0

        for concept, expected in expectations["designs"].items():
            run_command(
                [sys.executable, "-m", "openair", "run", str(expected["path"])],
                summary["steps"],
            )
            summary["designs"][concept] = assert_design(concept, expected)

        for case_id, expected in expectations["truth_cases"].items():
            action = str(expected["action"])
            if action == "rerun":
                run_command(
                    [sys.executable, "-m", "openair.truth", "run", case_id],
                    summary["steps"],
                )
                run_command(
                    [sys.executable, "-m", "openair.truth", "score", case_id],
                    summary["steps"],
                )
                status = scorecard_status(case_id)
                wanted = str(expected["expected_status"])
                if status != wanted:
                    raise AssertionError(
                        f"{case_id}: score {status!r} != expected {wanted!r}"
                    )
                summary["truth_cases"][case_id] = {
                    "action": action,
                    "status": status,
                }
            elif action == "frozen":
                archived = load_consumed_scorecard(case_id, required=True)
                assert archived is not None
                payload, attempt = archived
                status = str(payload["status"])
                wanted = str(expected["expected_status"])
                if status != wanted:
                    raise AssertionError(
                        f"{case_id}: frozen score {status!r} != {wanted!r}"
                    )
                summary["truth_cases"][case_id] = {
                    "action": action,
                    "status": status,
                    "attempt": attempt["id"],
                }
            elif action == "deferred":
                summary["truth_cases"][case_id] = {"action": action}
            else:
                raise ValueError(f"{case_id}: unknown smoke action {action!r}")

        run_command(
            [sys.executable, "-m", "openair.truth", "validate"],
            summary["steps"],
        )
        run_command(
            [sys.executable, "-m", "openair.truth", "report"],
            summary["steps"],
        )
        envelope = (ROOT / "docs/validation-envelope.md").read_text(
            encoding="utf-8"
        )
        for case_id in expectations["frozen_class_a_claims"]:
            archived = load_consumed_scorecard(str(case_id), required=True)
            assert archived is not None
            if archived[0]["status"] != "pass":
                raise AssertionError(f"{case_id}: frozen Class-A claim is not pass")
            expected_row_prefix = (
                f"| `{case_id}` | A — flight measurement | validation | pass"
            )
            if expected_row_prefix not in envelope:
                raise AssertionError(
                    f"{case_id}: frozen Class-A pass missing from validation envelope"
                )
        summary["ok"] = True
        return 0
    except Exception as exc:
        error = str(exc)
        print(f"CI reference smoke failed: {error}", file=sys.stderr)
        return 1
    finally:
        summary["finished_at"] = now()
        if error is not None:
            summary["error"] = error
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.summary.with_suffix(args.summary.suffix + ".tmp")
        temporary.write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, args.summary)
        print(f"wrote {args.summary}", flush=True)


raise SystemExit(main())
PY
