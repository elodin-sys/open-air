"""Truth corpus discovery, immutable evidence checks, and pinned downloads."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import tempfile
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml

from openair.paths import REPO_ROOT, TRUTH_DIR
from openair.provenance import model_source_sha256, sha256_file, sha256_tree
from openair.truth.models import TruthManifest, TruthRegistry


REGISTRY_PATH = TRUTH_DIR / "registry.yaml"


def _yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def execution_provenance(case_id: str) -> dict[str, str]:
    """Bind predictions to public inputs, manifest, model source, and runtime."""
    entry = registry_entry(case_id)
    manifest = (TRUTH_DIR / entry.manifest).resolve()
    inputs = case_dir(case_id) / "inputs"
    packages: dict[str, str] = {"python": platform.python_version()}
    for package in (
        "numpy",
        "openmdao",
        "openaerostruct",
        "pydantic",
        "scipy",
    ):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not-installed"
    environment = json.dumps(packages, sort_keys=True).encode()
    entry_payload = json.dumps(
        entry.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "manifest_sha256": sha256_file(manifest),
        "registry_entry_sha256": hashlib.sha256(entry_payload).hexdigest(),
        "public_inputs_sha256": sha256_tree(inputs),
        "model_source_sha256": model_source_sha256(),
        "project_config_sha256": sha256_file(REPO_ROOT / "pyproject.toml"),
        "runtime_sha256": hashlib.sha256(environment).hexdigest(),
    }


def load_registry(path: Path = REGISTRY_PATH) -> TruthRegistry:
    return TruthRegistry.model_validate(_yaml(path))


def registry_entry(case_id: str):
    registry = load_registry()
    for entry in registry.cases:
        if entry.id == case_id:
            return entry
    raise KeyError(f"unknown truth case: {case_id}")


def case_dir(case_id: str) -> Path:
    entry = registry_entry(case_id)
    directory = (TRUTH_DIR / entry.manifest).resolve().parent
    directory.relative_to(TRUTH_DIR.resolve())
    return directory


def load_manifest(case_id: str) -> TruthManifest:
    entry = registry_entry(case_id)
    path = (TRUTH_DIR / entry.manifest).resolve()
    path.relative_to(TRUTH_DIR.resolve())
    manifest = TruthManifest.model_validate(_yaml(path))
    if manifest.id != entry.id:
        raise ValueError(
            f"registry id {entry.id!r} does not match manifest id {manifest.id!r}"
        )
    if manifest.status != entry.status:
        raise ValueError(
            f"registry status {entry.status!r} does not match manifest "
            f"status {manifest.status!r}"
        )
    return manifest


def verify_truth_hashes(case_id: str) -> dict[str, str]:
    entry = registry_entry(case_id)
    base = case_dir(case_id)
    verified: dict[str, str] = {}
    for relative, expected in entry.truth_sha256.items():
        path = (base / relative).resolve()
        path.relative_to(base)
        if not path.is_file():
            raise FileNotFoundError(f"truth evidence missing: {path}")
        got = sha256_file(path)
        if got != expected:
            raise ValueError(
                f"truth evidence checksum mismatch for {case_id}/{relative}: "
                f"expected {expected}, got {got}"
            )
        verified[relative] = got
    return verified


def fetch_case(case_id: str) -> list[Path]:
    """Download pinned source assets atomically and reject checksum drift."""
    manifest = load_manifest(case_id)
    entry = registry_entry(case_id)
    registered_holdout = entry.holdout_sha256
    declared_holdout = {
        item.filename: item.sha256
        for item in manifest.source.downloads
        if item.location == "external-holdout"
    }
    if declared_holdout != registered_holdout:
        raise ValueError(
            f"{case_id}: manifest external-holdout downloads do not match "
            "registry holdout_sha256"
        )
    for item in manifest.source.downloads:
        if item.location != "case-truth":
            continue
        relative = f"truth/{item.filename}"
        if entry.truth_sha256.get(relative) != item.sha256:
            raise ValueError(
                f"{case_id}: case-truth download {item.filename} does not match "
                "registry truth_sha256"
            )
    written: list[Path] = []
    for item in manifest.source.downloads:
        if item.location == "external-holdout":
            from openair.truth.holdout import holdout_case_dir

            target_dir = holdout_case_dir(case_id, create=True)
        elif item.location == "case-truth":
            target_dir = case_dir(case_id) / "truth"
            target_dir.mkdir(parents=True, exist_ok=True)
        else:
            target_dir = TRUTH_DIR / "downloads" / case_id
            target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / item.filename
        target.resolve().relative_to(target_dir.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and sha256_file(target) == item.sha256:
            written.append(target)
            continue
        fd, raw_temp = tempfile.mkstemp(prefix=f".{item.filename}.", dir=target_dir)
        os.close(fd)
        temp = Path(raw_temp)
        try:
            request = urllib.request.Request(
                item.url,
                headers={"User-Agent": "open-air-truth/0.1"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                with open(temp, "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
            got = sha256_file(temp)
            if got != item.sha256:
                raise ValueError(
                    f"download checksum mismatch for {item.filename}: "
                    f"expected {item.sha256}, got {got}"
                )
            os.replace(temp, target)
            written.append(target)
        finally:
            temp.unlink(missing_ok=True)
    return written


def load_truth_rows(case_id: str) -> list[dict[str, str]]:
    verify_truth_hashes(case_id)
    path = case_dir(case_id) / "truth" / "observations.csv"
    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    required = {
        "observable",
        "value",
        "units",
        "u_exp",
        "u_input",
        "u_num",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{path} must contain columns {sorted(required)}")
    return rows


def load_truth_table(case_id: str, filename: str) -> list[dict[str, str]]:
    """Scorer-side access to a checksum-pinned auxiliary truth CSV."""
    relative = f"truth/{filename}"
    entry = registry_entry(case_id)
    if relative not in entry.truth_sha256:
        raise ValueError(f"{case_id}: auxiliary truth file is not pinned: {relative}")
    verify_truth_hashes(case_id)
    path = (case_dir(case_id) / relative).resolve()
    path.relative_to(case_dir(case_id).resolve())
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))
