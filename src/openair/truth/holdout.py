"""Access-controlled, hash-pinned truth held outside the development checkout."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from openair.paths import REPO_ROOT, TRUTH_DIR, truth_results_dir
from openair.provenance import sha256_file
from openair.truth.corpus import (
    execution_provenance,
    load_manifest,
    registry_entry,
)

HOLDOUT_ENV = "OPENAIR_TRUTH_HOLDOUT"
ACCESS_LOG_PATH = TRUTH_DIR / "access-log.yaml"
FROZEN_CLAIMS_DIR = TRUTH_DIR / "frozen-claims"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def holdout_root(*, create: bool = False) -> Path:
    """Return a repository-external holdout root and reject symlink indirection."""
    configured = os.environ.get(HOLDOUT_ENV)
    root = (
        Path(configured).expanduser()
        if configured
        else Path.home() / "openair-truth-holdout"
    )
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if root.exists() and root.is_symlink():
        raise ValueError(f"{HOLDOUT_ENV} may not be a symlink: {root}")
    resolved = root.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError(
            f"{HOLDOUT_ENV} must be outside the development checkout: {resolved}"
        )
    return resolved


def holdout_case_dir(case_id: str, *, create: bool = False) -> Path:
    directory = holdout_root(create=create) / case_id
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def verify_holdout_hashes(case_id: str) -> dict[str, str]:
    """Verify every externally held file without returning its contents."""
    entry = registry_entry(case_id)
    if not entry.holdout_sha256:
        raise ValueError(f"{case_id}: no external holdout is registered")
    base = holdout_case_dir(case_id)
    verified: dict[str, str] = {}
    for relative, expected in entry.holdout_sha256.items():
        path = (base / relative).resolve()
        path.relative_to(base.resolve())
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"external holdout evidence missing: {path}")
        got = sha256_file(path)
        if got != expected:
            raise ValueError(
                f"external holdout checksum mismatch for {case_id}/{relative}: "
                f"expected {expected}, got {got}"
            )
        verified[relative] = got
    return verified


def _prediction_freeze(case_id: str) -> dict[str, Any]:
    """Hash the exact prediction record and every model artifact it names."""
    prediction_path = truth_results_dir(case_id) / "results.json"
    if not prediction_path.is_file():
        raise FileNotFoundError(
            f"prediction missing for {case_id}; run the case before authorization"
        )
    with open(prediction_path, encoding="utf-8") as stream:
        prediction = json.load(stream)
    if not isinstance(prediction, dict):
        raise ValueError(f"{prediction_path} must contain a JSON object")
    metadata = prediction.get("metadata") or {}
    artifacts = metadata.get("artifacts") or {}
    declared_hashes = metadata.get("artifact_sha256") or {}
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError(f"{case_id}: prediction has no model artifacts to freeze")
    if not isinstance(declared_hashes, dict) or set(artifacts) != set(declared_hashes):
        raise ValueError(f"{case_id}: prediction artifact paths and hashes differ")
    verified: dict[str, str] = {}
    for name, raw_path in artifacts.items():
        path = Path(str(raw_path))
        expected = str(declared_hashes[name])
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"{case_id}: prediction artifact changed: {name}")
        verified[str(name)] = expected
    return {
        "prediction_sha256": sha256_file(prediction_path),
        "artifact_sha256": verified,
    }


def _load_access_log() -> dict[str, Any]:
    if not ACCESS_LOG_PATH.is_file():
        return {"version": 1, "attempts": []}
    with open(ACCESS_LOG_PATH, encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("truth/access-log.yaml must be a version-1 mapping")
    attempts = payload.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("truth/access-log.yaml must contain an attempts list")
    return payload


def _write_access_log(payload: dict[str, Any]) -> None:
    ACCESS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{ACCESS_LOG_PATH.name}.",
        dir=ACCESS_LOG_PATH.parent,
    )
    os.close(fd)
    temp = Path(raw_temp)
    try:
        with open(temp, "w", encoding="utf-8") as stream:
            yaml.safe_dump(payload, stream, sort_keys=False)
        os.replace(temp, ACCESS_LOG_PATH)
    finally:
        temp.unlink(missing_ok=True)


def _bound_scorecard(
    case_id: str,
    attempt: dict[str, Any],
    scorecard_path: Path,
) -> dict[str, Any]:
    """Validate a scorecard against its consumed holdout ledger entry."""
    if not scorecard_path.is_file() or scorecard_path.is_symlink():
        raise FileNotFoundError(f"frozen scorecard missing: {scorecard_path}")
    with open(scorecard_path, encoding="utf-8") as stream:
        scorecard = json.load(stream)
    if not isinstance(scorecard, dict) or scorecard.get("case_id") != case_id:
        raise ValueError(f"{scorecard_path}: scorecard case does not match {case_id}")
    evidence = scorecard.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError(f"{case_id}: scorecard evidence must be a mapping")
    if evidence.get("holdout_attempt_id") != attempt.get("id"):
        raise ValueError(f"{case_id}: scorecard holdout attempt does not match ledger")
    if evidence.get("holdout_consumed_at") != attempt.get("consumed_at"):
        raise ValueError(f"{case_id}: scorecard consumption time does not match ledger")
    execution = {
        key.removeprefix("execution:"): value
        for key, value in evidence.items()
        if key.startswith("execution:")
    }
    if execution != attempt.get("execution_provenance"):
        raise ValueError(f"{case_id}: scorecard execution provenance does not match ledger")
    holdout_hashes = {
        key.removeprefix("holdout:"): value
        for key, value in evidence.items()
        if key.startswith("holdout:")
    }
    if holdout_hashes != attempt.get("holdout_sha256"):
        raise ValueError(f"{case_id}: scorecard holdout hashes do not match ledger")
    return scorecard


def archive_consumed_scorecard(case_id: str, scorecard_path: Path) -> Path:
    """Persist a consumed one-shot scorecard and bind it into the ledger."""
    payload = _load_access_log()
    with open(scorecard_path, encoding="utf-8") as stream:
        scorecard = json.load(stream)
    evidence = scorecard.get("evidence") if isinstance(scorecard, dict) else None
    attempt_id = evidence.get("holdout_attempt_id") if isinstance(evidence, dict) else None
    matches = [
        item
        for item in payload["attempts"]
        if item.get("id") == attempt_id and item.get("case_id") == case_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{case_id}: scorecard must reference exactly one holdout ledger attempt"
        )
    attempt = matches[0]
    if attempt.get("status") != "consumed":
        raise ValueError(f"{case_id}: only consumed holdout scorecards may be archived")
    _bound_scorecard(case_id, attempt, scorecard_path)

    target = FROZEN_CLAIMS_DIR / f"{case_id}--{attempt_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved = target.resolve()
    resolved.relative_to(FROZEN_CLAIMS_DIR.resolve())
    fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(fd)
    temp = Path(raw_temp)
    try:
        shutil.copyfile(scorecard_path, temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)

    attempt["scorecard_path"] = target.relative_to(TRUTH_DIR).as_posix()
    attempt["scorecard_sha256"] = sha256_file(target)
    _write_access_log(payload)
    return target


def load_consumed_scorecard(
    case_id: str,
    candidate_path: Path | None = None,
    *,
    required: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Load a hash-pinned consumed scorecard without touching live artifacts.

    Multiple post-change attempts may coexist. With a live ``candidate_path``
    select the archive whose hash matches that candidate; otherwise return the
    most recently consumed attempt. Every archive is hash- and ledger-checked
    before one is selected, so adding a revalidation cannot hide tampering of
    an earlier primary claim.
    """
    payload = _load_access_log()
    matches = [
        item
        for item in payload["attempts"]
        if item.get("case_id") == case_id
        and item.get("status") == "consumed"
        and item.get("scorecard_path")
        and item.get("scorecard_sha256")
    ]
    if not matches and not required:
        return None
    if not matches:
        raise FileNotFoundError(f"{case_id}: no archived consumed scorecard")

    validated: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for attempt in matches:
        raw_path = Path(str(attempt["scorecard_path"]))
        if raw_path.is_absolute() or ".." in raw_path.parts:
            raise ValueError(f"{case_id}: unsafe frozen scorecard path")
        archive = (TRUTH_DIR / raw_path).resolve()
        archive.relative_to(TRUTH_DIR.resolve())
        expected = str(attempt["scorecard_sha256"])
        if not archive.is_file() or archive.is_symlink():
            raise FileNotFoundError(f"{case_id}: frozen scorecard archive is missing")
        if sha256_file(archive) != expected:
            raise ValueError(f"{case_id}: frozen scorecard checksum mismatch")
        validated.append(
            (_bound_scorecard(case_id, attempt, archive), attempt, expected)
        )

    if candidate_path is not None:
        candidate_sha = sha256_file(candidate_path)
        selected = [item for item in validated if item[2] == candidate_sha]
        if len(selected) != 1:
            raise ValueError(
                f"{case_id}: live scorecard does not identify exactly one "
                "frozen claim"
            )
        archived_scorecard, attempt, _ = selected[0]
        _bound_scorecard(case_id, attempt, candidate_path)
        return archived_scorecard, attempt

    archived_scorecard, attempt, _ = max(
        validated,
        key=lambda item: (
            str(item[1].get("consumed_at") or ""),
            str(item[1].get("id") or ""),
        ),
    )
    return archived_scorecard, attempt


def authorize_holdout(case_id: str, attempt_id: str) -> dict[str, Any]:
    """Freeze one scorer attempt against current code, inputs, and acceptance."""
    if not attempt_id or any(char.isspace() for char in attempt_id):
        raise ValueError("attempt id must be a non-empty token without whitespace")
    manifest = load_manifest(case_id)
    if manifest.role != "validation":
        raise ValueError(f"{case_id}: only validation-role cases use a holdout")
    verified = verify_holdout_hashes(case_id)
    prediction_freeze = _prediction_freeze(case_id)
    payload = _load_access_log()
    attempts = payload["attempts"]
    if any(item.get("id") == attempt_id for item in attempts):
        raise ValueError(f"holdout attempt id already exists: {attempt_id}")
    if any(
        item.get("case_id") == case_id and item.get("status") == "authorized"
        for item in attempts
    ):
        raise ValueError(f"{case_id}: an unconsumed holdout attempt already exists")
    attempt = {
        "id": attempt_id,
        "case_id": case_id,
        "status": "authorized",
        "authorized_at": _now(),
        "consumed_at": None,
        "execution_provenance": execution_provenance(case_id),
        "holdout_sha256": verified,
        **prediction_freeze,
    }
    attempts.append(attempt)
    _write_access_log(payload)
    return attempt


@contextmanager
def consume_holdout(case_id: str) -> Iterator[tuple[Path, dict[str, str]]]:
    """Consume exactly one frozen attempt before exposing its directory.

    The ledger is updated before yielding. A parser or scorer crash therefore
    consumes the attempt rather than silently granting a retry.
    """
    manifest = load_manifest(case_id)
    if manifest.role != "validation":
        raise ValueError(f"{case_id}: only validation-role cases use a holdout")
    verified = verify_holdout_hashes(case_id)
    prediction_freeze = _prediction_freeze(case_id)
    payload = _load_access_log()
    eligible = [
        item
        for item in payload["attempts"]
        if item.get("case_id") == case_id and item.get("status") == "authorized"
    ]
    if len(eligible) != 1:
        raise RuntimeError(
            f"{case_id}: expected one authorized holdout attempt, found {len(eligible)}"
        )
    attempt = eligible[0]
    current = execution_provenance(case_id)
    if attempt.get("execution_provenance") != current:
        raise RuntimeError(
            f"{case_id}: authorized attempt is stale; code, inputs, manifest, "
            "or runtime changed after the freeze"
        )
    if attempt.get("holdout_sha256") != verified:
        raise RuntimeError(f"{case_id}: holdout changed after authorization")
    if attempt.get("prediction_sha256") != prediction_freeze["prediction_sha256"]:
        raise RuntimeError(f"{case_id}: prediction changed after authorization")
    if attempt.get("artifact_sha256") != prediction_freeze["artifact_sha256"]:
        raise RuntimeError(f"{case_id}: model artifacts changed after authorization")
    attempt["status"] = "consumed"
    attempt["consumed_at"] = _now()
    _write_access_log(payload)
    evidence = {
        "holdout_attempt_id": str(attempt["id"]),
        "holdout_consumed_at": str(attempt["consumed_at"]),
        **{f"holdout:{key}": value for key, value in verified.items()},
    }
    yield holdout_case_dir(case_id), evidence


def validate_access_log() -> None:
    payload = _load_access_log()
    ids: list[str] = []
    for attempt in payload["attempts"]:
        required = {
            "id",
            "case_id",
            "status",
            "authorized_at",
            "consumed_at",
            "execution_provenance",
            "holdout_sha256",
            "prediction_sha256",
            "artifact_sha256",
        }
        if not isinstance(attempt, dict) or not required.issubset(attempt):
            raise ValueError(f"each holdout attempt requires {sorted(required)}")
        if attempt["status"] not in {"authorized", "consumed"}:
            raise ValueError(f"invalid holdout attempt status: {attempt['status']}")
        if attempt["status"] == "consumed" and not attempt["consumed_at"]:
            raise ValueError("consumed holdout attempts require consumed_at")
        frozen_fields = {"scorecard_path", "scorecard_sha256"} & set(attempt)
        if frozen_fields and frozen_fields != {"scorecard_path", "scorecard_sha256"}:
            raise ValueError(
                "frozen scorecard ledger fields scorecard_path and "
                "scorecard_sha256 must appear together"
            )
        if attempt.get("scorecard_path"):
            raw_path = Path(str(attempt["scorecard_path"]))
            if raw_path.is_absolute() or ".." in raw_path.parts:
                raise ValueError("frozen scorecard path must remain below truth/")
            scorecard_hash = str(attempt["scorecard_sha256"])
            if len(scorecard_hash) != 64 or any(
                char not in "0123456789abcdef" for char in scorecard_hash
            ):
                raise ValueError("frozen scorecard SHA-256 must be lowercase hexadecimal")
        ids.append(str(attempt["id"]))
    if len(ids) != len(set(ids)):
        raise ValueError("holdout attempt ids must be unique")
