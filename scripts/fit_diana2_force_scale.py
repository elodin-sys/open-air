#!/usr/bin/env python3
"""Fit Diana 2's one training-only generalized-force scale.

The three predeclared response-gain observables are linear in the shared
aileron generalized-force scale. Frequency and damping observables are not
fit. This script reads a calibration-role scorecard produced at a known seed
scale and reports the uncertainty-weighted least-squares scale; it never
edits model code or reads a validation holdout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GAIN_OBSERVABLES = {
    "outer_to_ro_strain_peak_gain",
    "outer_to_ro_accel_gain_at_mode",
    "outer_to_rm_accel_gain_at_mode",
}


def fit_scale(scorecard: dict[str, Any], seed_scale: float) -> dict[str, Any]:
    if scorecard.get("case_id") != "diana2-training":
        raise ValueError("force-scale fit requires the diana2-training scorecard")
    if scorecard.get("role") != "calibration":
        raise ValueError("force-scale fit may only read calibration-role evidence")
    rows = [
        row
        for row in scorecard.get("residuals", [])
        if row.get("observable") in GAIN_OBSERVABLES
    ]
    found = {str(row["observable"]) for row in rows}
    if found != GAIN_OBSERVABLES:
        raise ValueError(
            f"gain observable mismatch: missing={sorted(GAIN_OBSERVABLES - found)}"
        )
    numerator = 0.0
    denominator = 0.0
    evidence = []
    for row in rows:
        predicted = float(row["predicted"])
        truth = float(row["truth"])
        uncertainty = float(row["uncertainty"])
        if predicted <= 0.0 or truth <= 0.0 or uncertainty <= 0.0:
            raise ValueError(f"{row['observable']}: gains and uncertainty must be positive")
        weight = 1.0 / uncertainty**2
        numerator += predicted * truth * weight
        denominator += predicted**2 * weight
        evidence.append(
            {
                "observable": row["observable"],
                "predicted": predicted,
                "truth": truth,
                "uncertainty": uncertainty,
                "truth_over_prediction": truth / predicted,
                "weight": weight,
            }
        )
    raw_scale = seed_scale * numerator / denominator
    return {
        "case_id": "diana2-training",
        "role": "calibration",
        "method": (
            "uncertainty-weighted least squares on the three predeclared "
            "response-gain observables; frequency and damping excluded"
        ),
        "seed_scale": seed_scale,
        "fitted_scale_raw": raw_scale,
        "fitted_scale_2dp": round(raw_scale, 2),
        "observables": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scorecard",
        type=Path,
        default=Path("results/truth/diana2-training/scorecard.json"),
    )
    parser.add_argument("--seed-scale", type=float, required=True)
    arguments = parser.parse_args()
    if arguments.seed_scale <= 0.0:
        raise ValueError("--seed-scale must be positive")
    with arguments.scorecard.open(encoding="utf-8") as stream:
        scorecard = json.load(stream)
    print(json.dumps(fit_scale(scorecard, arguments.seed_scale), indent=2))


if __name__ == "__main__":
    main()
