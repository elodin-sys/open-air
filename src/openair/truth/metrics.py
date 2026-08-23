"""Shared physical-accuracy and design-effectiveness metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.stats import kendalltau, spearmanr

from openair.truth.models import Residual


def normalized_residual(
    *,
    observable: str,
    units: str,
    predicted: float,
    truth: float,
    u_exp: float,
    u_input: float,
    u_num: float,
) -> Residual:
    uncertainty = math.sqrt(u_exp**2 + u_input**2 + u_num**2)
    if not math.isfinite(uncertainty) or uncertainty <= 0.0:
        raise ValueError(f"{observable}: combined uncertainty must be positive")
    residual = predicted - truth
    z = residual / uncertainty
    return Residual(
        observable=observable,
        units=units,
        predicted=predicted,
        truth=truth,
        residual=residual,
        uncertainty=uncertainty,
        z=z,
        within_2sigma=abs(z) <= 2.0,
    )


def residual_summary(residuals: Sequence[Residual]) -> dict[str, float | bool | int]:
    if not residuals:
        raise ValueError("cannot summarize an empty residual set")
    values = np.asarray([item.z for item in residuals], dtype=float)
    absolute = np.abs(values)
    return {
        "count": len(residuals),
        "bias_z": float(np.mean(values)),
        "mean_abs_z": float(np.mean(absolute)),
        "rms_z": float(np.sqrt(np.mean(values**2))),
        "p95_abs_z": float(np.percentile(absolute, 95)),
        "max_abs_z": float(np.max(absolute)),
        "fraction_within_2sigma": float(np.mean(absolute <= 2.0)),
    }


def ranking_metrics(
    predicted_scores: Sequence[float],
    truth_scores: Sequence[float],
    *,
    maximize: bool = True,
    top_k: int = 5,
) -> dict[str, float]:
    if len(predicted_scores) != len(truth_scores) or len(truth_scores) < 2:
        raise ValueError("ranking metrics require equal sequences of length >= 2")
    predicted = np.asarray(predicted_scores, dtype=float)
    truth = np.asarray(truth_scores, dtype=float)
    sign = -1.0 if maximize else 1.0
    predicted_order = np.argsort(sign * predicted)
    truth_order = np.argsort(sign * truth)
    k = min(top_k, len(truth))
    overlap = len(set(predicted_order[:k]) & set(truth_order[:k])) / k
    selected_truth = truth[predicted_order[0]]
    best_truth = truth[truth_order[0]]
    regret = (
        (best_truth - selected_truth) if maximize else (selected_truth - best_truth)
    )
    return {
        "spearman_rho": float(spearmanr(predicted, truth).statistic),
        "kendall_tau": float(kendalltau(predicted, truth).statistic),
        "top_k_recall": float(overlap),
        "selected_regret": float(regret),
    }


def decision_metrics(
    predicted_pass: Sequence[bool],
    truth_pass: Sequence[bool],
) -> dict[str, float | int]:
    if len(predicted_pass) != len(truth_pass) or not truth_pass:
        raise ValueError("decision metrics require equal non-empty sequences")
    false_pass = sum(p and not t for p, t in zip(predicted_pass, truth_pass))
    false_fail = sum(not p and t for p, t in zip(predicted_pass, truth_pass))
    true_pass = sum(p and t for p, t in zip(predicted_pass, truth_pass))
    predicted_positive = true_pass + false_pass
    actual_positive = true_pass + false_fail
    return {
        "count": len(truth_pass),
        "false_pass": false_pass,
        "false_fail": false_fail,
        "precision": true_pass / predicted_positive if predicted_positive else 1.0,
        "recall": true_pass / actual_positive if actual_positive else 1.0,
    }
