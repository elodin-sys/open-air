"""Invoke package verification in open-air's pinned isolated Elodin runtime."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from openair.paths import REPO_ROOT, TOOLS_DIR

ELODIN_PYTHON = TOOLS_DIR / "elodin" / ".venv" / "bin" / "python"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "elodin_quad_verify.py"


def elodin_available() -> bool:
    return ELODIN_PYTHON.is_file() and VERIFY_SCRIPT.is_file()


def verify_multirotor_package(
    package_dir: Path,
    output: Path,
) -> dict[str, Any]:
    if not elodin_available():
        raise FileNotFoundError(
            "pinned Elodin runtime is unavailable; run scripts/install_elodin.sh"
        )
    environment = os.environ.copy()
    environment.update(
        {
            "OPENAIR_MULTIROTOR_PACKAGE": str(package_dir.resolve()),
            "OPENAIR_ELODIN_OUTPUT": str(output.resolve()),
            "OPENMDAO_REPORTS": "0",
            "PYTHONHASHSEED": "0",
        }
    )
    completed = subprocess.run(
        [str(ELODIN_PYTHON), str(VERIFY_SCRIPT), "run"],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Elodin multirotor verification failed:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    with output.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not payload.get("ok"):
        raise ValueError(f"Elodin multirotor verification did not pass: {payload}")
    return payload

