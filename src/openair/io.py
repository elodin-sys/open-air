"""YAML in, JSON/CSV out. Every pipeline stage writes a JSON summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from openair.paths import results_dir_for


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Case file {path} did not contain a mapping")
    return data


def dump_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=_json_default)
        f.write("\n")
    return path


def dump_stage(case_path: str | Path, stage: str, payload: dict[str, Any]) -> Path:
    out = results_dir_for(case_path) / f"{stage}.json"
    return dump_json(out, payload)


def load_stage(case_path: str | Path, stage: str) -> dict[str, Any] | None:
    path = results_dir_for(case_path) / f"{stage}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _json_default(obj: Any) -> Any:
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.floating, np.integer)):
            return obj.item()
    except Exception:
        pass
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"Not JSON serializable: {type(obj)}")
