"""Mesh-truth checks (QA audit F14/F15): pure-numpy, no OpenVSP needed."""

import math

import numpy as np

from conftest import BASELINE_DESIGN
from openair.cli import load_spec
from openair.geometry.mesh_checks import (
    check_fin_mesh,
    check_wing_mesh,
    root_section_inside_fuselage,
)


def _spec():
    return load_spec(BASELINE_DESIGN)


def _fin_verts_correct(spec) -> np.ndarray:
    """A properly built fin: vertical span (canted), streamwise chord."""
    v = spec.vtail
    cant = math.radians(v.cant_deg)
    sweep = math.tan(math.radians(v.le_sweep_deg))
    pts = []
    for s in np.linspace(0, v.span_m, 12):
        chord = v.root_chord_m * (1 - (1 - v.taper) * s / v.span_m)
        for c in np.linspace(0, chord, 8):
            pts.append(
                [
                    1.94 + s * sweep + c,
                    0.04 + s * math.sin(cant),
                    0.035 + s * math.cos(cant),
                ]
            )
    return np.asarray(pts)


def _fin_verts_f14_bug(spec) -> np.ndarray:
    """The old Y_Rel_Rotation=90 build: horizontal span, chord pointing down."""
    v = spec.vtail
    pts = []
    for s in np.linspace(0, v.span_m, 12):
        chord = v.root_chord_m * (1 - (1 - v.taper) * s / v.span_m)
        for c in np.linspace(0, chord, 8):
            pts.append([1.94, 0.14 + s, 0.08 - c])
    return np.asarray(pts)


def test_correct_fin_passes():
    spec = _spec()
    checks = check_fin_mesh(_fin_verts_correct(spec), spec, "r")
    assert all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]


def test_f14_bug_fin_fails():
    """Regression: the shipped horizontal-plate fins must fail these checks."""
    spec = _spec()
    checks = check_fin_mesh(_fin_verts_f14_bug(spec), spec, "r")
    assert any(not c["ok"] for c in checks), checks


def test_vertical_wing_fails_flatness():
    spec = _spec()
    # a wing accidentally built vertical (span in z)
    pts = np.array(
        [
            [1.0 + c, 0.0, s]
            for s in np.linspace(0, spec.wing.span_m, 20)
            for c in (0.0, 1.0)
        ]
    )
    checks = check_wing_mesh(pts, spec)
    assert any(not c["ok"] for c in checks)


def test_highly_twisted_horizontal_wing_passes_flatness():
    spec = _spec()
    spec.wing.twist_root_deg = -3.0
    spec.wing.twist_tip_deg = -14.5
    points = []
    half_span = spec.wing.span_m / 2.0
    for y in np.linspace(-half_span, half_span, 31):
        fraction = abs(y) / half_span
        chord = spec.wing.root_chord_m + fraction * (
            spec.wing.tip_chord_m - spec.wing.root_chord_m
        )
        twist = math.radians(
            spec.wing.twist_root_deg
            + fraction * (spec.wing.twist_tip_deg - spec.wing.twist_root_deg)
        )
        dihedral_z = abs(y) * math.tan(math.radians(spec.wing.dihedral_deg))
        for chord_fraction in (-0.25, 0.75):
            for thickness_sign in (-0.5, 0.5):
                points.append(
                    [
                        1.0 + chord_fraction * chord * math.cos(twist),
                        y,
                        dihedral_z
                        + chord_fraction * chord * math.sin(twist)
                        + thickness_sign * spec.wing.t_over_c * chord,
                    ]
                )

    checks = check_wing_mesh(np.asarray(points), spec)

    assert all(c["ok"] for c in checks), checks


def _fuselage_cloud() -> np.ndarray:
    pts = []
    for x in np.linspace(0, 2.45, 40):
        scale = 1.0 - abs(x / 2.45 - 0.5)
        for th in np.linspace(0, 2 * math.pi, 24, endpoint=False):
            pts.append([x, 0.16 * scale * math.cos(th), 0.14 * scale * math.sin(th)])
    return np.asarray(pts)


def test_attachment_detects_floating_component():
    fuse = _fuselage_cloud()
    # attached: root centroid deep inside the section
    attached = np.array(
        [[1.2 + c, 0.02, 0.02 + s] for s in np.linspace(0, 0.3, 10) for c in (0.0, 0.3)]
    )
    ok = root_section_inside_fuselage(attached, fuse, 2, "fin_test")
    assert ok["ok"], ok
    # floating: root hangs well outside the local section (the F14 class)
    floating = attached + np.array([0.0, 0.5, 0.0])
    bad = root_section_inside_fuselage(floating, fuse, 2, "fin_test")
    assert not bad["ok"], bad


def test_attachment_section_slice_scales_for_transport_mesh():
    spec = _spec()
    spec.fuselage.length_m = 37.5
    fuse = np.asarray(
        [
            [x, 2.0 * math.cos(theta), 2.0 * math.sin(theta)]
            for x in (12.32, 13.68)
            for theta in np.linspace(0, 2 * math.pi, 24, endpoint=False)
        ]
    )
    # The root lies midway between exported fuselage rings: farther than the
    # historical fixed 0.12 m and 1%-length slices, but within 2% of length.
    root = np.asarray(
        [
            [13.0 + chord, 0.0, span]
            for span in np.linspace(0.0, 1.0, 20)
            for chord in (0.0, 0.1)
        ]
    )

    result = root_section_inside_fuselage(root, fuse, 2, "fin_test", spec)

    assert result["ok"], result
