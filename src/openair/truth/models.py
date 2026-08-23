"""Validated contracts for external truth cases and scorecards."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TruthClass = Literal["A", "B", "C", "D", "E"]
CaseRole = Literal["calibration", "validation", "verification"]
CaseStatus = Literal["active", "deferred", "blocked-data-access"]
DownloadLocation = Literal["download", "case-truth", "external-holdout"]


class TruthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DownloadSpec(TruthModel):
    url: str
    sha256: str
    filename: str
    location: DownloadLocation = "download"


class SourceSpec(TruthModel):
    organization: str
    dataset: str
    revision: str
    license: str
    reference_url: str
    redistribution: str
    downloads: list[DownloadSpec] = Field(default_factory=list)


class ObservableSpec(TruthModel):
    id: str
    units: str
    description: str
    prediction_key: str | None = None


class AcceptanceSpec(TruthModel):
    max_abs_z: float = Field(2.0, gt=0.0)
    max_mean_abs_z: float = Field(1.5, gt=0.0)
    min_fraction_within_2sigma: float = Field(0.68, ge=0.0, le=1.0)
    provisional: bool = True


class TruthManifest(TruthModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    truth_class: TruthClass
    role: CaseRole
    status: CaseStatus = "active"
    intended_uses: list[str] = Field(min_length=1)
    runner: str
    source: SourceSpec
    observables: list[ObservableSpec] = Field(min_length=1)
    acceptance: AcceptanceSpec = Field(default_factory=AcceptanceSpec)
    stages: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    truth_loader: str = "observations-csv"
    scorer_generates_predictions: bool = False

    @model_validator(mode="after")
    def status_has_reason(self) -> TruthManifest:
        if self.status == "blocked-data-access" and not self.blocked_reason:
            raise ValueError("blocked-data-access cases require blocked_reason")
        ids = [item.id for item in self.observables]
        if len(ids) != len(set(ids)):
            raise ValueError("observable ids must be unique")
        if (
            self.scorer_generates_predictions
            and self.truth_loader == "observations-csv"
        ):
            raise ValueError(
                "scorer-generated predictions require a specialized truth loader"
            )
        return self


class RegistryEntry(TruthModel):
    id: str
    manifest: str
    status: CaseStatus = "active"
    truth_sha256: dict[str, str] = Field(default_factory=dict)
    holdout_sha256: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def evidence_paths_are_safe(self) -> RegistryEntry:
        for relative in (*self.truth_sha256, *self.holdout_sha256):
            path = relative.replace("\\", "/")
            if path.startswith("/") or ".." in path.split("/"):
                raise ValueError(f"unsafe evidence path: {relative}")
        overlap = set(self.truth_sha256) & set(self.holdout_sha256)
        if overlap:
            raise ValueError(
                f"evidence cannot be both committed and external: {sorted(overlap)}"
            )
        return self


class TruthRegistry(TruthModel):
    version: int = 1
    cases: list[RegistryEntry]

    @model_validator(mode="after")
    def unique_cases(self) -> TruthRegistry:
        ids = [item.id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("truth registry case ids must be unique")
        return self


class TruthPrediction(TruthModel):
    case_id: str
    generated_at: str
    predictions: dict[str, float]
    provenance: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Residual(TruthModel):
    observable: str
    units: str
    predicted: float
    truth: float
    residual: float
    uncertainty: float
    z: float
    within_2sigma: bool


class TruthScorecard(TruthModel):
    case_id: str
    truth_class: TruthClass
    role: CaseRole
    status: Literal["pass", "provisional", "fail", "blocked"]
    generated_at: str
    residuals: list[Residual]
    summary: dict[str, float | bool | int]
    acceptance: AcceptanceSpec
    evidence: dict[str, str] = Field(default_factory=dict)
