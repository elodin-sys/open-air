#!/usr/bin/env python3
"""Download and mechanically partition the frozen Diana 2 flight archive.

Only ZIP member names are inspected before the committed split is applied.
Training payloads are extracted into the corpus checkout; validation and
reserve payloads are written beneath the repository-external holdout root.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SPLIT_PATH = (
    REPO_ROOT / "truth/cases/diana2-flight/inputs/holdout-split.yaml"
)
TRAINING_ROOT = REPO_ROOT / "truth/cases/diana2-flight/truth/training"
INTAKE_RECORD = (
    REPO_ROOT / "truth/cases/diana2-flight/inputs/intake-record.yaml"
)
FLIGHT_ARCHIVE_URL = (
    "https://data.4tu.nl/file/"
    "0c3fcef0-5b63-480c-ae40-3ff726c657e9/"
    "ca3846ca-d3dd-4ce2-8dc6-ebe4f358fc06"
)
CHUNK_BYTES = 16 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _holdout_root(configured: Path | None) -> Path:
    root = configured or Path(
        os.environ.get(
            "OPENAIR_TRUTH_HOLDOUT",
            str(Path.home() / "openair-truth-holdout"),
        )
    )
    root = root.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError(f"holdout root may not be a symlink: {root}")
    resolved = root.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"holdout root must be outside the repository: {resolved}")


def _load_split(path: Path) -> dict:
    with open(path, encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError(f"{path} must contain a version-1 split mapping")
    if payload.get("state") != "frozen-before-flight-payload":
        raise ValueError(f"{path} is not frozen before payload access")
    partition = payload.get("partition")
    if not isinstance(partition, dict):
        raise ValueError(f"{path} has no partition mapping")
    expected = [str(value) for value in payload["dataset"]["expected_flights"]]
    assigned = [
        str(value)
        for group in ("training", "validation_holdout", "reserve")
        for value in partition.get(group, [])
    ]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(expected):
        raise ValueError("Diana 2 split must assign each expected flight exactly once")
    if len(partition["validation_holdout"]) != 2 or len(partition["reserve"]) != 1:
        raise ValueError("Diana 2 split must contain two holdouts and one reserve")
    return payload


def _require_committed_split(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT)
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(relative)],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", str(relative)],
        cwd=REPO_ROOT,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _download(
    url: str,
    target: Path,
    *,
    expected_size: int,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    offset = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": "open-air-truth-intake/1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        ranged = response.status == 206
        if offset and not ranged:
            offset = 0
        mode = "ab" if offset and ranged else "wb"
        with open(partial, mode) as stream:
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                stream.write(chunk)
    actual_size = partial.stat().st_size
    if actual_size != expected_size:
        raise ValueError(
            f"archive size mismatch: expected {expected_size}, got {actual_size}"
        )
    os.replace(partial, target)
    return target


def _digests(path: Path) -> dict[str, str]:
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            sha256.update(chunk)
            md5.update(chunk)
    return {"sha256": sha256.hexdigest(), "md5": md5.hexdigest()}


def _safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe ZIP member path: {name}")
    return path


def _flight_members(
    archive: zipfile.ZipFile,
    expected_flights: list[str],
) -> tuple[dict[str, zipfile.ZipInfo], list[str]]:
    member_names = []
    by_flight: dict[str, zipfile.ZipInfo] = {}
    expected = set(expected_flights)
    for info in archive.infolist():
        path = _safe_member_name(info.filename)
        member_names.append(info.filename)
        flight_id = path.stem.upper()
        if not info.is_dir() and path.suffix.lower() == ".mat" and flight_id in expected:
            if flight_id in by_flight:
                raise ValueError(f"duplicate archive member for {flight_id}")
            by_flight[flight_id] = info
    missing = sorted(expected - by_flight.keys())
    if missing:
        raise ValueError(f"flight archive is missing expected members: {missing}")
    return by_flight, member_names


def _copy_and_hash(source: BinaryIO, destination: Path) -> dict[str, str | int]:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"refusing to replace immutable evidence: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    try:
        with open(temporary, "wb") as target:
            while True:
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _extract_split(
    archive_path: Path,
    split: dict,
    holdout_root: Path,
) -> tuple[dict[str, dict[str, dict[str, str | int]]], list[str]]:
    partition = split["partition"]
    destinations = {
        **{
            str(flight): ("training", TRAINING_ROOT / f"{flight}.mat")
            for flight in partition["training"]
        },
        **{
            str(flight): (
                "validation_holdout",
                holdout_root / "diana2-flight" / f"{flight}.mat",
            )
            for flight in partition["validation_holdout"]
        },
        **{
            str(flight): (
                "reserve",
                holdout_root / "diana2-reserve" / f"{flight}.mat",
            )
            for flight in partition["reserve"]
        },
    }
    extracted: dict[str, dict[str, dict[str, str | int]]] = {
        "training": {},
        "validation_holdout": {},
        "reserve": {},
    }
    with zipfile.ZipFile(archive_path) as archive:
        members, member_names = _flight_members(
            archive,
            [str(value) for value in split["dataset"]["expected_flights"]],
        )
        for flight_id, (group, destination) in destinations.items():
            with archive.open(members[flight_id]) as source:
                extracted[group][destination.name] = _copy_and_hash(
                    source,
                    destination,
                )
    return extracted, member_names


def _write_yaml_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            yaml.safe_dump(payload, stream, sort_keys=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def seal_intake(
    *,
    archive_url: str,
    archive_path: Path | None = None,
    configured_holdout_root: Path | None = None,
    require_committed_split: bool = True,
) -> Path:
    split = _load_split(SPLIT_PATH)
    split_revision = (
        _require_committed_split(SPLIT_PATH)
        if require_committed_split
        else "test-uncommitted-split"
    )
    holdout_root = _holdout_root(configured_holdout_root)
    intake_root = holdout_root / "diana2-intake"
    downloaded = archive_path is None
    if archive_path is None:
        archive_path = _download(
            archive_url,
            intake_root / str(split["dataset"]["flight_archive_name"]),
            expected_size=int(split["dataset"]["publisher_size_bytes"]),
        )
    archive_path = Path(archive_path)
    archive_hashes = _digests(archive_path)
    expected_md5 = str(split["dataset"]["publisher_md5"])
    if archive_hashes["md5"] != expected_md5:
        raise ValueError(
            "publisher archive MD5 mismatch: "
            f"expected {expected_md5}, got {archive_hashes['md5']}"
        )
    extracted, member_names = _extract_split(archive_path, split, holdout_root)
    record = {
        "version": 1,
        "sealed_at": _now(),
        "source": {
            "doi": split["dataset"]["doi"],
            "archive_url": archive_url,
            "license": "CC-BY-4.0",
            "attribution": (
                "Jurisson, Eussen, de Visser, and de Breuker (2026), "
                "Flexible Diana 2 Scaled Glider UAV - Aeroelastic Flight "
                "Test Measurements, 4TU.ResearchData"
            ),
            "archive_size_bytes": archive_path.stat().st_size,
            "archive_md5": archive_hashes["md5"],
            "archive_sha256": archive_hashes["sha256"],
        },
        "split": {
            "path": str(SPLIT_PATH.relative_to(REPO_ROOT)),
            "committed_revision": split_revision,
            "state": split["state"],
        },
        "zip_member_names": member_names,
        "partition": extracted,
        "boundaries": {
            "training": str(TRAINING_ROOT.relative_to(REPO_ROOT)),
            "validation_holdout": "external:diana2-flight",
            "reserve": "external:diana2-reserve",
        },
        "payload_inspection": (
            "ZIP member names only before partition; no MAT payload was opened"
        ),
        "archive_deleted_after_extraction": downloaded,
    }
    _write_yaml_atomic(INTAKE_RECORD, record)
    _write_yaml_atomic(intake_root / "intake-record.yaml", record)
    if downloaded:
        archive_path.unlink()
    return INTAKE_RECORD


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-url", default=FLIGHT_ARCHIVE_URL)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use a local archive instead of downloading (testing/recovery only)",
    )
    parser.add_argument(
        "--holdout-root",
        type=Path,
        help="Override OPENAIR_TRUTH_HOLDOUT",
    )
    arguments = parser.parse_args()
    try:
        target = seal_intake(
            archive_url=arguments.archive_url,
            archive_path=arguments.archive,
            configured_holdout_root=arguments.holdout_root,
        )
    except Exception as exc:
        print(f"Diana 2 intake failed: {exc}", file=sys.stderr)
        return 1
    print(f"Diana 2 intake sealed: {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
