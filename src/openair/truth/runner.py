"""Truth-case execution, scoring, and validation-envelope reporting."""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from openair.io import dump_json
from openair.paths import DOCS_DIR, TRUTH_DIR, truth_results_dir
from openair.truth.adapters import run_adapter
from openair.truth.corpus import (
    case_dir,
    execution_provenance,
    fetch_case,
    load_manifest,
    load_registry,
    registry_entry,
    verify_truth_hashes,
)
from openair.truth.corpus import sha256_file
from openair.truth.holdout import (
    archive_consumed_scorecard,
    consume_holdout,
    holdout_case_dir,
    load_consumed_scorecard,
    validate_access_log,
    verify_holdout_hashes,
)
from openair.truth.loaders import load_scorer_truth
from openair.truth.metrics import normalized_residual, residual_summary
from openair.truth.models import TruthPrediction, TruthScorecard


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_case(case_id: str) -> tuple[TruthPrediction, Path]:
    manifest = load_manifest(case_id)
    if manifest.status != "active":
        raise RuntimeError(
            f"{case_id} is {manifest.status}: {manifest.blocked_reason or 'not runnable'}"
        )
    public_inputs = case_dir(case_id) / "inputs"
    with tempfile.TemporaryDirectory(prefix=f"openair-{case_id}-inputs-") as raw:
        sandbox = Path(raw)
        if public_inputs.is_dir():
            shutil.copytree(public_inputs, sandbox, dirs_exist_ok=True)
        predictions, metadata = run_adapter(manifest.runner, sandbox)
    expected = {item.prediction_key or item.id for item in manifest.observables}
    missing = expected - predictions.keys()
    extra = predictions.keys() - expected
    if extra or (missing and not manifest.scorer_generates_predictions):
        raise ValueError(
            f"{case_id} runner prediction mismatch: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    payload = TruthPrediction(
        case_id=case_id,
        generated_at=_now(),
        predictions={key: float(value) for key, value in predictions.items()},
        provenance=execution_provenance(case_id),
        metadata=metadata,
    )
    target = truth_results_dir(case_id) / "results.json"
    dump_json(target, payload.model_dump(mode="json"))
    return payload, target


def _load_prediction(case_id: str) -> TruthPrediction:
    path = truth_results_dir(case_id) / "results.json"
    if not path.is_file():
        raise FileNotFoundError(f"prediction missing for {case_id}; run the case first")
    with open(path, encoding="utf-8") as stream:
        return TruthPrediction.model_validate(json.load(stream))


def score_case(case_id: str) -> tuple[TruthScorecard, Path]:
    manifest = load_manifest(case_id)
    prediction = _load_prediction(case_id)
    current_provenance = execution_provenance(case_id)
    if prediction.provenance != current_provenance:
        raise ValueError(
            f"{case_id}: prediction provenance is stale; rerun before scoring"
        )
    artifacts = prediction.metadata.get("artifacts") or {}
    artifact_hashes = prediction.metadata.get("artifact_sha256") or {}
    if set(artifacts) != set(artifact_hashes):
        raise ValueError(f"{case_id}: artifact paths and hashes do not match")
    for name, raw_path in artifacts.items():
        path = Path(str(raw_path))
        if not path.is_file() or sha256_file(path) != artifact_hashes[name]:
            raise ValueError(f"{case_id}: evaluated artifact changed: {name}")
    entry = registry_entry(case_id)
    access = (
        consume_holdout(case_id) if entry.holdout_sha256 else nullcontext((None, {}))
    )
    with access as (holdout_dir, holdout_evidence):
        scorer_truth = load_scorer_truth(
            manifest.truth_loader,
            case_id,
            holdout_dir,
            prediction,
        )
    truth_rows = scorer_truth.rows
    scored_predictions = dict(prediction.predictions)
    overlap = set(scored_predictions) & set(scorer_truth.predictions)
    if any(scored_predictions[key] != scorer_truth.predictions[key] for key in overlap):
        raise ValueError(
            f"{case_id}: scorer-generated predictions conflict with runner output"
        )
    scored_predictions.update(scorer_truth.predictions)
    observable_specs = {item.id: item for item in manifest.observables}
    truth_observables = [row["observable"] for row in truth_rows]
    duplicates = sorted(
        {
            observable
            for observable in truth_observables
            if truth_observables.count(observable) > 1
        }
    )
    if duplicates:
        raise ValueError(f"{case_id}: duplicate truth rows: {duplicates}")
    expected_truth = set(observable_specs)
    actual_truth = set(truth_observables)
    if actual_truth != expected_truth:
        raise ValueError(
            f"{case_id}: truth coverage mismatch: "
            f"missing={sorted(expected_truth - actual_truth)}, "
            f"extra={sorted(actual_truth - expected_truth)}"
        )
    expected_predictions = {
        item.prediction_key or item.id for item in manifest.observables
    }
    if set(scored_predictions) != expected_predictions:
        raise ValueError(
            f"{case_id}: scored prediction coverage mismatch: "
            f"missing={sorted(expected_predictions - set(scored_predictions))}, "
            f"extra={sorted(set(scored_predictions) - expected_predictions)}"
        )
    residuals = []
    for row in truth_rows:
        observable = row["observable"]
        if observable not in observable_specs:
            raise ValueError(f"{case_id}: truth row {observable!r} is not in manifest")
        spec = observable_specs[observable]
        prediction_key = spec.prediction_key or spec.id
        if row["units"] != spec.units:
            raise ValueError(
                f"{case_id}/{observable}: truth units {row['units']!r} "
                f"do not match manifest units {spec.units!r}"
            )
        residuals.append(
            normalized_residual(
                observable=observable,
                units=spec.units,
                predicted=scored_predictions[prediction_key],
                truth=float(row["value"]),
                u_exp=float(row["u_exp"]),
                u_input=float(row["u_input"]),
                u_num=float(row["u_num"]),
            )
        )
    summary = residual_summary(residuals)
    acceptance = manifest.acceptance
    meets = bool(
        summary["max_abs_z"] <= acceptance.max_abs_z
        and summary["mean_abs_z"] <= acceptance.max_mean_abs_z
        and summary["fraction_within_2sigma"] >= acceptance.min_fraction_within_2sigma
    )
    status = (
        "provisional"
        if meets and acceptance.provisional
        else "pass"
        if meets
        else "fail"
    )
    verified = verify_truth_hashes(case_id)
    scorecard = TruthScorecard(
        case_id=case_id,
        truth_class=manifest.truth_class,
        role=manifest.role,
        status=status,
        generated_at=_now(),
        residuals=residuals,
        summary={**summary, "meets_acceptance": meets},
        acceptance=acceptance,
        evidence={
            **{key: value for key, value in verified.items()},
            **holdout_evidence,
            **scorer_truth.evidence,
            **{f"execution:{key}": value for key, value in current_provenance.items()},
        },
    )
    target = truth_results_dir(case_id) / "scorecard.json"
    dump_json(target, scorecard.model_dump(mode="json"))
    if scorecard.evidence.get("holdout_attempt_id"):
        archive_consumed_scorecard(case_id, target)
    return scorecard, target


TRUTH_CLASS_LABELS = {
    "A": "flight measurement",
    "B": "wind-tunnel / ground experiment",
    "C": "engineered reference solution",
    "D": "operational / handbook data",
    "E": "internal experiment",
}


def generate_envelope(output: Path | None = None) -> Path:
    registry = load_registry()
    target = output or (DOCS_DIR / "validation-envelope.md")
    scored: dict[str, TruthScorecard] = {}
    frozen_attempts: dict[str, dict[str, Any]] = {}
    for entry in registry.cases:
        score_path = truth_results_dir(entry.id) / "scorecard.json"
        manifest = load_manifest(entry.id)
        current = execution_provenance(entry.id)
        if score_path.is_file():
            with open(score_path, encoding="utf-8") as stream:
                score = TruthScorecard.model_validate(json.load(stream))
            recorded = {
                key.removeprefix("execution:"): value
                for key, value in score.evidence.items()
                if key.startswith("execution:")
            }
            if score.evidence.get("holdout_attempt_id"):
                archived = load_consumed_scorecard(entry.id, score_path)
                if archived is None:  # pragma: no cover - required=True
                    raise RuntimeError(f"{entry.id}: frozen scorecard archive missing")
                payload, attempt = archived
                score = TruthScorecard.model_validate(payload)
                recorded = {
                    key.removeprefix("execution:"): value
                    for key, value in score.evidence.items()
                    if key.startswith("execution:")
                }
                frozen_attempts[entry.id] = attempt
            elif recorded != current:
                raise RuntimeError(
                    f"{entry.id}: stale scorecard; rerun and rescore before reporting"
                )
        else:
            archived = load_consumed_scorecard(entry.id, required=False)
            if archived is None:
                continue
            payload, attempt = archived
            score = TruthScorecard.model_validate(payload)
            recorded = {
                key.removeprefix("execution:"): value
                for key, value in score.evidence.items()
                if key.startswith("execution:")
            }
            frozen_attempts[entry.id] = attempt

        if score.role != manifest.role or score.truth_class != manifest.truth_class:
            raise RuntimeError(
                f"{entry.id}: scorecard role or truth class no longer matches manifest"
            )
        if entry.id in frozen_attempts:
            immutable_scope = (
                "manifest_sha256",
                "registry_entry_sha256",
                "public_inputs_sha256",
            )
            changed_scope = [
                key
                for key in immutable_scope
                if recorded.get(key) != current.get(key)
            ]
            if changed_scope:
                raise RuntimeError(
                    f"{entry.id}: frozen claim scope changed: {changed_scope}"
                )
        scored[entry.id] = score

    class_a_passes = [
        score
        for score in scored.values()
        if score.truth_class == "A"
        and score.role == "validation"
        and score.status == "pass"
    ]
    class_b_passes = [
        score
        for score in scored.values()
        if score.truth_class == "B"
        and score.role == "validation"
        and score.status == "pass"
    ]
    class_c_passes = [
        score
        for score in scored.values()
        if score.truth_class == "C" and score.status == "pass"
    ]
    physical_evidence_summary = (
        "A sealed, access-logged Class-A flight-measurement holdout has passed "
        "for the intended uses and acceptance bands named by its manifest. "
        "That bounded result does not validate behavior outside the tested "
        "vehicle, maneuvers, conditions, or observables."
        if class_a_passes
        else "All current physical datasets are visible calibration or post-hoc "
        "verification cases; there is no passed sealed independent holdout."
    )
    lines = [
        "# open-air validation envelope",
        "",
        f"Generated: {_now()}",
        "",
        "This report scopes evidence by intended use and truth class. Agreement with",
        "class C/D references is verification or plausibility evidence, not independent",
        f"physical validation. {physical_evidence_summary}",
        "",
        "The legacy `z` field is a normalized tolerance residual `r/u`, where `u`",
        "combines declared experimental, input/model-form, and numerical allowances.",
        "Those terms are not all statistical standard deviations and their independence",
        "is not established, so `2u` must not be read as a statistical 2σ confidence band.",
        "",
        "## Evidence synthesis",
        "",
        (
            f"- Class-A passes: {len(class_a_passes)}. "
            "No flight-measurement claim is established."
            if not class_a_passes
            else f"- Class-A passes: {len(class_a_passes)}."
        ),
        (
            f"- Class-B validation passes: {len(class_b_passes)}. "
            "No class-B case is claim-eligible: all current physical datasets "
            "are consumed calibration benchmarks."
            if not class_b_passes
            else f"- Class-B validation passes: {len(class_b_passes)}."
        ),
        (
            f"- Class-C passes: {len(class_c_passes)}. These establish corpus, "
            "refusal, or engineered-reference consistency only."
        ),
        "- Per-observable agreement is useful bounded evidence, but calibration or "
        "post-hoc agreement does not create an independent validation claim.",
        "",
        "## Case scorecards",
        "",
        "| Case | Truth class | Role | Status | Mean |r|/u | Max |r|/u | Within 2u |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    details: list[str] = []
    for entry in registry.cases:
        manifest = load_manifest(entry.id)
        score = scored.get(entry.id)
        if score is not None:
            summary = score.summary
            status_label = (
                score.status
                if score.role == "validation"
                else f"{score.role} {score.status}"
            )
            if entry.id in frozen_attempts:
                revision = str(
                    frozen_attempts[entry.id]["execution_provenance"][
                        "model_source_sha256"
                    ]
                )
                status_label = f"{status_label} (frozen `{revision[:12]}`)"
            lines.append(
                f"| `{entry.id}` | {score.truth_class} — "
                f"{TRUTH_CLASS_LABELS[score.truth_class]} | {score.role} | "
                f"{status_label} | {float(summary['mean_abs_z']):.3f} | "
                f"{float(summary['max_abs_z']):.3f} | "
                f"{100.0 * float(summary['fraction_within_2sigma']):.1f}% |"
            )
        else:
            status = (
                f"{entry.status}: {manifest.blocked_reason}"
                if manifest.blocked_reason
                else entry.status
            )
            lines.append(
                f"| `{entry.id}` | {manifest.truth_class} — "
                f"{TRUTH_CLASS_LABELS[manifest.truth_class]} | {manifest.role} | "
                f"{status} | — | — | — |"
            )
        details.extend(
            [
                "",
                f"## {manifest.title}",
                "",
                f"- Case: `{manifest.id}`",
                f"- Truth class: {manifest.truth_class} — "
                f"{TRUTH_CLASS_LABELS[manifest.truth_class]}",
                f"- Intended uses: {', '.join(manifest.intended_uses)}",
                f"- Source revision: {manifest.source.revision}",
                f"- Reference: {manifest.source.reference_url}",
            ]
        )
        if score is not None:
            summary = score.summary
            verdict_label = (
                score.status
                if score.role == "validation"
                else f"{score.role} benchmark {score.status}"
            )
            details.extend(
                [
                    f"- Verdict: **{verdict_label}**; "
                    f"{int(summary['count'])} observables, "
                    f"mean |r|/u {float(summary['mean_abs_z']):.3f}, "
                    f"max |r|/u {float(summary['max_abs_z']):.3f}, "
                    f"{100.0 * float(summary['fraction_within_2sigma']):.1f}% "
                    "within 2u.",
                ]
            )
            if entry.id in frozen_attempts:
                attempt = frozen_attempts[entry.id]
                revision = str(
                    attempt["execution_provenance"]["model_source_sha256"]
                )
                details.append(
                    "- Frozen historical claim: consumed attempt "
                    f"`{attempt['id']}` at model-source revision `{revision}`; "
                    "the archived scorecard and ledger hashes were verified "
                    "without re-reading regenerated model artifacts."
                )
            within = [
                residual.observable
                for residual in score.residuals
                if residual.within_2sigma
            ]
            outside = [
                f"{residual.observable} ({residual.z:+.2f}u)"
                for residual in sorted(
                    score.residuals,
                    key=lambda item: abs(item.z),
                    reverse=True,
                )
                if not residual.within_2sigma
            ]
            if within:
                details.append(f"- Within 2u: {', '.join(within)}.")
            if outside:
                details.append(f"- Outside 2u: {', '.join(outside)}.")
        if manifest.notes:
            details.append(f"- Notes: {' '.join(manifest.notes)}")
    lines.extend(details)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def validate_corpus() -> dict[str, Any]:
    registry = load_registry()
    validate_access_log()
    cases: dict[str, Any] = {}
    for entry in registry.cases:
        manifest = load_manifest(entry.id)
        hashes = verify_truth_hashes(entry.id)
        declared_holdout = {
            item.filename: item.sha256
            for item in manifest.source.downloads
            if item.location == "external-holdout"
        }
        if declared_holdout != entry.holdout_sha256:
            raise ValueError(
                f"{entry.id}: manifest external-holdout downloads do not match "
                "registry holdout_sha256"
            )
        if entry.holdout_sha256 and (
            manifest.role != "validation" or manifest.truth_class != "A"
        ):
            raise ValueError(
                f"{entry.id}: external holdouts are reserved for class-A "
                "validation-role cases"
            )
        holdout_status = "not applicable"
        if entry.holdout_sha256:
            external = holdout_case_dir(entry.id)
            expected_paths = [external / relative for relative in entry.holdout_sha256]
            present = [path.is_file() for path in expected_paths]
            if not external.is_dir() or not any(present):
                holdout_status = "holdout not mounted"
            elif not all(present):
                missing = [
                    str(path.relative_to(external))
                    for path, exists in zip(expected_paths, present, strict=True)
                    if not exists
                ]
                raise FileNotFoundError(
                    f"{entry.id}: external holdout mount is incomplete: {missing}"
                )
            else:
                verify_holdout_hashes(entry.id)
                holdout_status = "verified"
            load_consumed_scorecard(entry.id, required=False)
        cases[entry.id] = {
            "status": manifest.status,
            "truth_class": manifest.truth_class,
            "hashes_verified": len(hashes),
            "holdout_files_registered": len(entry.holdout_sha256),
            "holdout_status": holdout_status,
        }
    calibration_path = TRUTH_DIR / "calibration-log.yaml"
    with open(calibration_path, encoding="utf-8") as stream:
        calibration_log = yaml.safe_load(stream)
    if not isinstance(calibration_log, dict) or not isinstance(
        calibration_log.get("entries"), list
    ):
        raise ValueError("truth/calibration-log.yaml must contain an entries list")
    required_calibration_fields = {
        "id",
        "case_id",
        "source_role",
        "observables_viewed",
        "changes",
        "rationale",
        "untouched_validation_holdout",
        "evidence_boundary",
    }
    calibration_ids: list[str] = []
    for item in calibration_log["entries"]:
        if not isinstance(item, dict) or not required_calibration_fields.issubset(item):
            raise ValueError(
                f"each calibration entry requires {sorted(required_calibration_fields)}"
            )
        calibration_ids.append(str(item["id"]))
        manifest = load_manifest(str(item["case_id"]))
        if manifest.role == "validation":
            raise ValueError(
                f"validation-role case {item['case_id']} cannot be a calibration source"
            )
        if item["source_role"] != manifest.role:
            raise ValueError(
                f"{item['id']}: source_role does not match the current manifest"
            )
        if (
            not isinstance(item["observables_viewed"], list)
            or not item["observables_viewed"]
        ):
            raise ValueError(f"{item['id']}: observables_viewed must be non-empty")
        if not isinstance(item["changes"], list) or not item["changes"]:
            raise ValueError(f"{item['id']}: changes must be non-empty")
    if len(calibration_ids) != len(set(calibration_ids)):
        raise ValueError("calibration log ids must be unique")
    return {"ok": True, "cases": cases}


__all__ = [
    "fetch_case",
    "generate_envelope",
    "run_case",
    "score_case",
    "validate_corpus",
]
