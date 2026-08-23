"""Extract the attached-flow CRM wing/body anchor from NTF Test 197.

Usage:
    python extract_ntf197.py path/to/t197R44.csv

The source file is the public NASA run export.  This script deliberately uses
the wall-corrected columns and prints the normalized rows plus fitted scalar
observations; it does not modify committed truth files.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def slope(points: list[tuple[float, float]]) -> float:
    """Return the ordinary least-squares slope."""
    x_mean = sum(x for x, _ in points) / len(points)
    y_mean = sum(y for _, y in points) / len(points)
    return sum((x - x_mean) * (y - y_mean) for x, y in points) / sum(
        (x - x_mean) ** 2 for x, _ in points
    )


def intercept(points: list[tuple[float, float]], fitted_slope: float) -> float:
    """Return the ordinary least-squares intercept."""
    return sum(y for _, y in points) / len(points) - fitted_slope * sum(
        x for x, _ in points
    ) / len(points)


def main(source: Path) -> None:
    with open(source, encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    selected = [row for row in rows if -1.0 <= float(row["AWALL"]) <= 2.0]
    if len(selected) < 3:
        raise ValueError("expected at least three attached-flow points")
    if {int(float(row["CONFIG"])) for row in selected} != {1}:
        raise ValueError("NTF run 44 must contain configuration 1 (wing/body)")

    print("alpha_deg,cl,cd,cm,mach,reynolds_million,run,configuration")
    for row in selected:
        print(
            f"{float(row['AWALL']):.7f},"
            f"{float(row['CLWALL']):.7f},"
            f"{float(row['CDWALL']):.7f},"
            f"{float(row['CMWALL']):.7f},"
            f"{float(row['MWALL']):.7f},"
            f"{float(row['CREYN']):.7f},"
            f"{int(float(row['RUN']))},wing-body"
        )

    cl_points = [(float(row["AWALL"]), float(row["CLWALL"])) for row in selected]
    cm_points = [(float(row["AWALL"]), float(row["CMWALL"])) for row in selected]
    cl_alpha = slope(cl_points)
    cm_alpha = slope(cm_points)
    cl_intercept = intercept(cl_points, cl_alpha)
    print()
    print(f"cl_alpha_per_deg={cl_alpha:.12f}")
    print(f"cm_alpha_per_deg={cm_alpha:.12f}")
    print(f"alpha_l0_deg={-cl_intercept / cl_alpha:.12f}")
    print(f"neutral_point_mac={0.25 - cm_alpha / cl_alpha:.12f}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: extract_ntf197.py path/to/t197R44.csv")
    main(Path(sys.argv[1]))
