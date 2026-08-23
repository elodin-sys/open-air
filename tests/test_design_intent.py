import pytest

from openair.design_intent import (
    fidelity_penalty,
    fin_trailing_edge_overhang_m,
    sketch_prior_rows,
)
from openair.mdo.problem import evaluate_design
from openair.mdo.problem import _departure_audit
from openair.schemas import SketchEnvelopeSpec, VehicleSpec


def _inspiration_spec() -> VehicleSpec:
    spec = VehicleSpec()
    length = spec.fuselage.length_m
    spec.sketch = SketchEnvelopeSpec(
        treatment="inspiration",
        hard_scale=3.0,
        span_over_length=spec.wing.span_m / length,
        span_over_length_tol=0.1,
        root_over_length=spec.wing.root_chord_m / length,
        root_over_length_tol=0.05,
        le_sweep_deg=spec.wing.le_sweep_deg,
        le_sweep_tol_deg=4.0,
        taper=spec.wing.taper,
        taper_tol=0.05,
        x_le_root_over_length=spec.wing.x_le_root_m / length,
        x_le_root_over_length_tol=0.05,
        fin_span_m=spec.vtail.span_m,
        fin_span_tol_m=0.05,
    )
    return spec


def test_fidelity_penalty_is_free_inside_tolerance_and_quadratic_beyond_it():
    spec = _inspiration_spec()
    assert fidelity_penalty(spec) == 0.0

    spec.wing.span_m += 2.0 * spec.sketch.span_over_length_tol * spec.fuselage.length_m
    rows = sketch_prior_rows(spec)

    assert rows["span_over_length"]["normalized_deviation"] == pytest.approx(2.0)
    assert rows["span_over_length"]["within_hard_bound"]
    assert fidelity_penalty(spec) == pytest.approx(1.0 / len(rows))


def test_fin_overhang_and_volume_margins_are_continuous_mdo_metrics():
    spec = _inspiration_spec()
    spec.vtail.span_m = 0.08
    spec.vtail.x_le_m = spec.fuselage.length_m - 0.1
    spec.vtail.root_chord_m = 0.3

    metrics = evaluate_design(spec)

    assert fin_trailing_edge_overhang_m(spec) > 0.0
    assert metrics["fin_te_overhang_m"] > 0.0
    assert metrics["vv_lower_violation"] > 0.0
    assert metrics["vv_upper_violation"] < 0.0


def test_outboard_fin_attachment_is_bounded_by_local_wing_trailing_edge():
    spec = _inspiration_spec()
    spec.vtail.y_root_m = 0.45 * spec.wing.span_m
    eta = abs(spec.vtail.y_root_m) / (0.5 * spec.wing.span_m)
    # Use an unswept wing so the expected support station is explicit.
    spec.wing.le_sweep_deg = 0.0
    local_le = spec.wing.x_le_root_m
    local_chord = spec.wing.root_chord_m + eta * (
        spec.wing.tip_chord_m - spec.wing.root_chord_m
    )
    spec.vtail.x_le_m = local_le + local_chord - spec.vtail.root_chord_m

    assert fin_trailing_edge_overhang_m(spec) == pytest.approx(0.0, abs=1e-12)
    spec.vtail.x_le_m += 0.02
    assert fin_trailing_edge_overhang_m(spec) == pytest.approx(0.02)


def test_departure_audit_records_clamp_evidence_and_reason():
    source = _inspiration_spec()
    source.vtail.span_m = 0.08
    source.sketch.fin_span_m = 0.08
    source.sketch.fin_span_tol_m = 0.03
    delivered = source.model_copy(deep=True)
    delivered.vtail.span_m = 0.20

    departures = _departure_audit(source, delivered, [])
    fin = next(row for row in departures if row["parameter"] == "fin_span_m")

    assert fin["deviation_tolerance_multiple"] == pytest.approx(4.0)
    assert fin["excess_tolerance_multiple"] == pytest.approx(3.0)
    assert fin["reason"]
    assert fin["clamp_study"]["constraint_failures"]
