from __future__ import annotations

import pytest
import yaml

from openair.paths import TRUTH_DIR
from openair.truth.corpus import (
    load_manifest,
    load_truth_rows,
    load_truth_table,
    verify_truth_hashes,
)


CASE_DIR = TRUTH_DIR / "cases" / "gtm-t2"


def _slope(points: list[tuple[float, float]]) -> float:
    x_mean = sum(x for x, _ in points) / len(points)
    y_mean = sum(y for _, y in points) / len(points)
    return sum((x - x_mean) * (y - y_mean) for x, y in points) / sum(
        (x - x_mean) ** 2 for x, _ in points
    )


@pytest.mark.truth
def test_gtm_truth_is_pinned_and_margins_are_frozen() -> None:
    manifest = load_manifest("gtm-t2")
    hashes = verify_truth_hashes("gtm-t2")

    assert manifest.role == "verification"
    assert manifest.truth_class == "C"
    assert manifest.acceptance.provisional is False
    assert "sampled polynomial" in manifest.source.dataset
    assert "endurance_s" not in {row["observable"] for row in load_truth_rows("gtm-t2")}
    assert set(hashes) == {
        "truth/README.md",
        "truth/observations.csv",
        "truth/static_longitudinal.csv",
    }


@pytest.mark.truth
def test_gtm_static_table_reproduces_held_out_longitudinal_metrics() -> None:
    rows = load_truth_table("gtm-t2", "static_longitudinal.csv")
    attached = [row for row in rows if float(row["alpha_deg"]) in {0.0, 2.0, 4.0, 6.0}]
    cl_alpha = _slope([(float(row["alpha_deg"]), float(row["cl"])) for row in attached])
    cm_alpha = _slope([(float(row["alpha_deg"]), float(row["cm"])) for row in attached])
    truth = {
        row["observable"]: float(row["value"]) for row in load_truth_rows("gtm-t2")
    }

    assert cl_alpha == pytest.approx(truth["cl_alpha_per_deg"], abs=1e-8)
    assert 0.25 - cm_alpha / cl_alpha == pytest.approx(
        truth["neutral_point_mac"], abs=1e-8
    )
    assert cm_alpha < 0.0


@pytest.mark.truth
def test_gtm_designer_pack_excludes_held_out_aerodynamic_answers() -> None:
    with open(
        CASE_DIR / "inputs" / "design-time-input-pack.yaml",
        encoding="utf-8",
    ) as stream:
        pack = yaml.safe_load(stream)

    assert pack["geometry"]["wing"]["span_m"] == pytest.approx(2.08751424)
    assert pack["mass_properties"]["takeoff_mass_kg"] == pytest.approx(26.1949593675)
    assert pack["designer_boundary"]["held_out"]
    serialized = yaml.safe_dump(pack)
    assert "cl_alpha_per_deg" not in serialized
    assert "neutral_point_mac" not in serialized
    assert "cruise_lod" not in serialized
