"""Reproduce GTM T-2 static rows from the pinned NASA MATLAB database.

This provenance helper prints to stdout and never mutates committed truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import loadmat


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.polyfit(x, y, 1)[0])


def extract(path: Path) -> tuple[list[dict[str, float | str]], dict[str, float]]:
    source = loadmat(path, squeeze_me=True, struct_as_record=False)["C6_bas"]
    beta_index = int(np.flatnonzero(np.asarray(source.beta) == 0)[0])
    alpha = np.asarray(source.alpha, dtype=float)
    data = np.asarray(source.data, dtype=float)[:, beta_index, :]
    alpha_rad = np.deg2rad(alpha)
    cx = data[:, 0]
    cz = data[:, 2]
    cm = data[:, 4]
    cl = -cz * np.cos(alpha_rad) + cx * np.sin(alpha_rad)
    cd = -cx * np.cos(alpha_rad) - cz * np.sin(alpha_rad)

    rows = [
        {
            "alpha_deg": float(a),
            "beta_deg": 0.0,
            "cx": float(x),
            "cz": float(z),
            "cm": float(m),
            "cl": float(lift),
            "cd": float(drag),
            "configuration": "baseline",
        }
        for a, x, z, m, lift, drag in zip(alpha, cx, cz, cm, cl, cd, strict=True)
    ]
    fit = np.isin(alpha, [0.0, 2.0, 4.0, 6.0])
    cl_alpha = _slope(alpha[fit], cl[fit])
    cm_alpha = _slope(alpha[fit], cm[fit])
    trim_alpha = float(
        4.0
        + (0.0 - cm[alpha == 4.0][0])
        * 2.0
        / (cm[alpha == 6.0][0] - cm[alpha == 4.0][0])
    )
    trim_cl = float(np.interp(trim_alpha, alpha, cl))
    trim_cd = float(np.interp(trim_alpha, alpha, cd))
    metrics = {
        "cl_alpha_per_deg": cl_alpha,
        "cm_alpha_per_deg": cm_alpha,
        "neutral_point_mac": 0.25 - cm_alpha / cl_alpha,
        "trim_alpha_deg": trim_alpha,
        "cruise_lod": trim_cl / trim_cd,
    }
    return rows, metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mat_file", type=Path)
    parser.add_argument(
        "--rows",
        action="store_true",
        help="emit all zero-sideslip rows as CSV instead of derived JSON",
    )
    args = parser.parse_args()
    rows, metrics = extract(args.mat_file)
    if args.rows:
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    else:
        print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
