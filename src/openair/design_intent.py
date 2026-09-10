"""Sketch-prior metrics shared by optimization, reporting, and validation."""

from __future__ import annotations

import math
from typing import Any

from openair.schemas import VehicleSpec


DEFAULT_SKETCH_SHAPE: dict[str, tuple[float, float]] = {
    "span_over_length": (1.50, 0.20),
    "root_over_length": (0.47, 0.07),
    "le_sweep_deg": (32.0, 4.0),
}


def sketch_prior_targets(spec: VehicleSpec) -> dict[str, tuple[float, float]]:
    """Return every measured shape prior that has both target and tolerance."""
    env = spec.sketch
    if env is None:
        return dict(DEFAULT_SKETCH_SHAPE)
    targets = {
        "span_over_length": (env.span_over_length, env.span_over_length_tol),
        "root_over_length": (env.root_over_length, env.root_over_length_tol),
        "le_sweep_deg": (env.le_sweep_deg, env.le_sweep_tol_deg),
        "taper": (env.taper, env.taper_tol),
        "x_le_root_over_length": (
            env.x_le_root_over_length,
            env.x_le_root_over_length_tol,
        ),
    }
    optional = {
        "fin_span_m": (env.fin_span_m, env.fin_span_tol_m),
        "fin_root_chord_m": (env.fin_root_chord_m, env.fin_root_chord_tol_m),
        "fin_le_sweep_deg": (
            env.fin_le_sweep_deg,
            env.fin_le_sweep_tol_deg,
        ),
        "fin_cant_deg": (env.fin_cant_deg, env.fin_cant_tol_deg),
        "fin_x_le_m": (env.fin_x_le_m, env.fin_x_le_tol_m),
    }
    targets.update(
        {
            key: (float(target), float(tol))
            for key, (target, tol) in optional.items()
            if target is not None and tol is not None
        }
    )
    return targets


def sketch_prior_values(spec: VehicleSpec) -> dict[str, float]:
    """Return current design values in the same coordinates as sketch priors."""
    length = spec.fuselage.length_m
    return {
        "span_over_length": spec.wing.span_m / length,
        "root_over_length": spec.wing.root_chord_m / length,
        "le_sweep_deg": spec.wing.le_sweep_deg,
        "taper": spec.wing.taper,
        "x_le_root_over_length": spec.wing.x_le_root_m / length,
        "fin_span_m": spec.vtail.span_m,
        "fin_root_chord_m": spec.vtail.root_chord_m,
        "fin_le_sweep_deg": spec.vtail.le_sweep_deg,
        "fin_cant_deg": spec.vtail.cant_deg,
        "fin_x_le_m": spec.vtail.x_le_m,
    }


def sketch_prior_rows(spec: VehicleSpec) -> dict[str, dict[str, Any]]:
    """Measure deviation from the no-penalty and hard identity envelopes."""
    targets = sketch_prior_targets(spec)
    values = sketch_prior_values(spec)
    env = spec.sketch
    inspiration = bool(env is not None and env.treatment == "inspiration")
    hard_scale = env.hard_scale if inspiration else 1.0
    rows: dict[str, dict[str, Any]] = {}
    for key, (target, tol) in targets.items():
        value = values[key]
        normalized = abs(value - target) / tol
        excess = max(normalized - 1.0, 0.0)
        rows[key] = {
            "got": value,
            "target": target,
            "tol": tol,
            "hard_tol": tol * hard_scale,
            "normalized_deviation": normalized,
            "excess_tolerance": excess,
            "within_tolerance": normalized <= 1.0 + 1e-9,
            "within_hard_bound": normalized <= hard_scale + 1e-9,
        }
    return rows


def shape_fidelity_report(
    spec: VehicleSpec,
    sketch_departures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recompute shape bounds and require reasons for soft-prior departures."""
    inspiration = bool(
        spec.sketch is not None and spec.sketch.treatment == "inspiration"
    )
    documented = {
        str(item.get("parameter")): item
        for item in (sketch_departures or [])
        if isinstance(item, dict) and item.get("reason")
    }
    rows: dict[str, Any] = {}
    for key, prior in sketch_prior_rows(spec).items():
        needs_departure = inspiration and not prior["within_tolerance"]
        departure = documented.get(key)
        row = {
            **prior,
            "treatment": "inspiration" if inspiration else "requirement",
            "departure_required": needs_departure,
            "departure_documented": bool(departure),
            "departure_reason": departure.get("reason") if departure else None,
        }
        row["ok"] = bool(
            prior["within_hard_bound"]
            and (not needs_departure or row["departure_documented"])
        )
        rows[key] = row
    rows["departure_count"] = sum(
        1
        for row in rows.values()
        if isinstance(row, dict) and row["departure_required"]
    )
    rows["ok"] = all(row["ok"] for row in rows.values() if isinstance(row, dict))
    return rows


def fidelity_penalty(spec: VehicleSpec) -> float:
    """Mean squared excess beyond the one-tolerance visual prior."""
    env = spec.sketch
    if env is None or env.treatment != "inspiration":
        return 0.0
    rows = sketch_prior_rows(spec)
    if not rows:
        return 0.0
    return sum(float(row["excess_tolerance"]) ** 2 for row in rows.values()) / len(rows)


def fin_trailing_edge_overhang_m(spec: VehicleSpec) -> float:
    """Return fin attachment overhang beyond its supporting airframe surface.

    Center/body-mounted fins are bounded by the fuselage tail. Outboard fins
    are instead bounded by the local wing trailing edge at their root; their
    free tip is not expected to remain inside the fuselage planform.
    """
    fin = spec.vtail
    root_te = fin.x_le_m + fin.root_chord_m
    half_span = 0.5 * spec.wing.span_m
    if abs(fin.y_root_m) > 0.5 * spec.fuselage.max_width_m:
        eta = min(abs(fin.y_root_m) / max(half_span, 1e-9), 1.0)
        wing_le = spec.wing.x_le_at(eta)
        wing_chord = spec.wing.chord_at(eta)
        return root_te - (wing_le + wing_chord)

    tip_te = (
        fin.x_le_m
        + fin.span_m * math.tan(math.radians(fin.le_sweep_deg))
        + fin.root_chord_m * fin.taper
    )
    # Differentiable approximation to max(root_te, tip_te).
    delta = root_te - tip_te
    aft_te = 0.5 * (root_te + tip_te + math.sqrt(delta * delta + 1e-12))
    return aft_te - spec.fuselage.length_m
