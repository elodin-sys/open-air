"""Reference-model ingest, measurement, and compare contracts.

A synthetic aircraft with known geometry is exported as a triangle mesh in a
scrambled (Y-up, centimetre, translated, pitched) frame; the ingest must
recover the open-air frame and the schema-ready values within the tolerances
it declares, and the compare step must score the same mesh as a near-perfect
match.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from openair.geometry.mesh import naca4_thickness
from openair.reference import measure as M
from openair.reference.compare import compare_reference
from openair.reference.ingest import (
    ReferenceInputError,
    classify_input,
    ingest_reference,
    load_reference_mesh,
    parse_axes,
    refusal_message,
    suggest_spec_values,
    suggest_wing_sections,
)
from openair.schemas import VehicleSpec

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Synthetic aircraft (open-air frame, metres).
LENGTH = 0.70
BODY_HALF_WIDTH = 0.06
BODY_HALF_HEIGHT = 0.05
SPAN = 0.80
ROOT_CHORD = 0.20
TAPER = 0.5
SWEEP_DEG = 10.0
X_LE_ROOT = 0.30
FIN_CANT_DEG = 30.0
FIN_SPAN = 0.12
FIN_ROOT_CHORD = 0.10
FIN_X_LE = 0.55
FIN_Y_ROOT = 0.03
FIN_Z_ROOT = 0.03


def _airfoil_outline(chord: float, n: int = 40) -> np.ndarray:
    beta = np.linspace(0.0, math.pi, n)
    x = 0.5 * (1.0 - np.cos(beta))
    yt = naca4_thickness(x, 0.12)
    upper = np.column_stack([x[::-1], yt[::-1]])
    lower = np.column_stack([x[1:-1], -yt[1:-1]])
    return np.vstack([upper, lower]) * chord


def _wing_mesh() -> trimesh.Trimesh:
    ys = np.linspace(-0.5 * SPAN, 0.5 * SPAN, 41)
    sections = []
    for y in ys:
        eta = abs(y) / (0.5 * SPAN)
        chord = ROOT_CHORD * (1.0 - (1.0 - TAPER) * eta)
        x_le = X_LE_ROOT + abs(y) * math.tan(math.radians(SWEEP_DEG))
        outline = _airfoil_outline(chord)
        sections.append(
            np.column_stack(
                [outline[:, 0] + x_le, np.full(outline.shape[0], y), outline[:, 1]]
            )
        )
    n = sections[0].shape[0]
    vertices = np.vstack(sections)
    faces = []
    for k in range(len(sections) - 1):
        a = k * n
        b = (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            faces.append([a + i, b + i, b + j])
            faces.append([a + i, b + j, a + j])
    # Tip caps as fans.
    for base, flip in ((0, True), ((len(sections) - 1) * n, False)):
        centre = len(vertices)
        vertices = np.vstack([vertices, sections[0 if base == 0 else -1].mean(axis=0)])
        for i in range(n):
            j = (i + 1) % n
            faces.append(
                [centre, base + j, base + i] if flip else [centre, base + i, base + j]
            )
    return trimesh.Trimesh(vertices, np.array(faces), process=False)


def _fin_mesh(side: float) -> trimesh.Trimesh:
    cant = math.radians(FIN_CANT_DEG)
    span_dir = np.array([0.0, side * math.sin(cant), math.cos(cant)])
    root_le = np.array([FIN_X_LE, side * FIN_Y_ROOT, FIN_Z_ROOT])
    root_te = root_le + np.array([FIN_ROOT_CHORD, 0.0, 0.0])
    tip_le = (
        root_le
        + FIN_SPAN * span_dir
        + np.array([FIN_SPAN * math.tan(math.radians(20.0)), 0.0, 0.0])
    )
    tip_te = tip_le + np.array([0.6 * FIN_ROOT_CHORD, 0.0, 0.0])
    normal = np.cross(np.array([1.0, 0.0, 0.0]), span_dir)
    normal /= np.linalg.norm(normal)
    corners = np.array([root_le, root_te, tip_te, tip_le])
    pts = np.vstack([corners + 0.003 * normal, corners - 0.003 * normal])
    return trimesh.convex.convex_hull(pts)


def synthetic_aircraft() -> trimesh.Trimesh:
    body = trimesh.creation.icosphere(subdivisions=4)
    body.apply_scale([0.5 * LENGTH, BODY_HALF_WIDTH, BODY_HALF_HEIGHT])
    body.apply_translation([0.5 * LENGTH, 0.0, 0.0])
    parts = [body, _wing_mesh(), _fin_mesh(1.0), _fin_mesh(-1.0)]
    for offset in ([0.9, 0.3, 0.2], [-0.1, -0.4, -0.1], [0.4, 0.0, 0.3]):
        debris = trimesh.creation.icosphere(subdivisions=1, radius=0.004)
        debris.apply_translation(offset)
        parts.append(debris)
    return trimesh.util.concatenate(parts)


def scramble_to_source_frame(
    mesh: trimesh.Trimesh, *, pitch_deg: float = 2.0
) -> trimesh.Trimesh:
    """Pitch the aircraft, then express it Y-up with the nose at +Z in centimetres."""
    out = mesh.copy()
    pitch = math.radians(pitch_deg)
    rot_y = np.array(
        [
            [math.cos(pitch), 0, math.sin(pitch)],
            [0, 1, 0],
            [-math.sin(pitch), 0, math.cos(pitch)],
        ]
    )
    out.apply_transform(trimesh.transformations.rotation_matrix(0.0, [1, 0, 0]))
    vertices = np.asarray(out.vertices) @ rot_y.T
    # source X = -y, source Y = +z, source Z = -x  (so open-air x = -Z, y = -X, z = +Y)
    source = np.column_stack([-vertices[:, 1], vertices[:, 2], -vertices[:, 0]]) * 100.0
    source += np.array([10.0, 20.0, 30.0])
    return trimesh.Trimesh(source, out.faces, process=False)


@pytest.fixture(scope="module")
def scan_dir(tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("scan")
    mesh = scramble_to_source_frame(synthetic_aircraft())
    mesh.export(str(directory / "synthetic.stl"))
    (directory / "synthetic.reference.json").write_text(
        json.dumps(
            {
                "units": "cm",
                "measured_span_mm": SPAN * 1000.0,
                "export_tool": "synthetic fixture",
                "mirrored_half": False,
            }
        ),
        encoding="utf-8",
    )
    return directory


@pytest.fixture(scope="module")
def ingested(scan_dir: Path, tmp_path_factory):
    out = tmp_path_factory.mktemp("concept")
    summary = ingest_reference(
        scan_dir / "synthetic.stl",
        concept="synthetic-ref",
        out_dir=out / "reference",
        sketch_dir=out,
        axes="x:-z,y:-x,z:+y",
        target_faces=20000,
        mm_per_px=1.0,
    )
    return out, summary


def test_native_cad_files_are_refused_generically(tmp_path):
    fake = tmp_path / "model.f3d"
    fake.write_bytes(b"PK\x03\x04 not a mesh")
    assert classify_input(fake) == "native"
    assert "triangle mesh" in refusal_message(fake)
    with pytest.raises(
        ReferenceInputError, match="native CAD/scan project files are not accepted"
    ):
        load_reference_mesh(fake, units="mm")
    for suffix in (".step", ".sldprt", ".blend", ".e57"):
        assert classify_input(tmp_path / f"x{suffix}") == "native"


def test_units_must_be_declared(scan_dir: Path):
    with pytest.raises(ReferenceInputError, match="length unit not declared"):
        load_reference_mesh(scan_dir / "synthetic.stl")


def test_axes_mapping_rejects_reflections():
    with pytest.raises(ReferenceInputError, match="reflection"):
        parse_axes("x:+z,y:-x,z:+y")
    rotation = parse_axes("x:-z,y:-x,z:+y")
    assert abs(np.linalg.det(rotation) - 1.0) < 1e-9
    assert np.allclose(parse_axes(None), np.eye(3))


def test_span_anchor_mismatch_aborts(scan_dir: Path, tmp_path):
    with pytest.raises(ReferenceInputError, match="span cross-check failed"):
        ingest_reference(
            scan_dir / "synthetic.stl",
            concept="synthetic-bad-units",
            out_dir=tmp_path / "reference",
            sketch_dir=tmp_path,
            units="mm",  # wrong: the file is in centimetres
            expect_span_m=SPAN,
            axes="x:-z,y:-x,z:+y",
            dry_run=True,
        )


def test_ingest_recovers_known_geometry(ingested):
    out, summary = ingested
    cleaning = summary["cleaning"]
    assert cleaning["dropped_count"] == 3
    align = summary["alignment"]
    assert abs(align["datum_leveling"]["pitch_rotation_applied_deg"] - 2.0) < 0.6
    assert align["symmetry"]["residual_median_m"] < 0.002
    assert summary["anchor_check"]["ok"] is True

    wing = summary["suggested"]["wing"]
    tol = summary["tolerances"]["wing"]
    assert abs(wing["span_m"] - SPAN) <= max(tol["span_m"], 0.004)
    assert abs(wing["root_chord_m"] - ROOT_CHORD) <= max(tol["root_chord_m"], 0.01)
    assert abs(wing["le_sweep_deg"] - SWEEP_DEG) <= max(tol["le_sweep_deg"], 1.0)
    assert abs(wing["taper"] - TAPER) <= max(tol["taper"], 0.06)
    assert abs(wing["x_le_root_m"] - X_LE_ROOT) <= max(tol["x_le_root_m"], 0.01)
    assert abs(wing["twist_tip_deg"]) <= max(tol["twist_tip_deg"], 1.0)
    assert abs(wing["dihedral_deg"]) <= 1.0
    assert abs(wing["t_over_c"] - 0.12) <= 0.02
    assert wing["airfoil"].startswith("00")
    assert 3 <= len(wing["sections"]) <= 12
    assert wing["sections"][0]["eta"] == 0.0
    assert wing["sections"][-1]["eta"] == 1.0
    assert all(
        right["eta"] > left["eta"]
        for left, right in zip(wing["sections"], wing["sections"][1:])
    )
    assert summary["disclosures"]["wing_planform"]["section_count"] == len(
        wing["sections"]
    )

    fuselage = summary["suggested"]["fuselage"]
    assert abs(fuselage["length_m"] - LENGTH) <= 0.004
    assert abs(fuselage["max_width_m"] - 2.0 * BODY_HALF_WIDTH) <= 0.012
    assert abs(fuselage["max_height_m"] - 2.0 * BODY_HALF_HEIGHT) <= 0.008
    stations = fuselage["stations"]
    assert 4 <= len(stations) <= 8
    assert stations[0]["x_over_length"] == 0.0 and stations[-1]["x_over_length"] == 1.0
    assert all(
        b["x_over_length"] > a["x_over_length"] for a, b in zip(stations, stations[1:])
    )
    assert not summary["measurements"]["fairings"]["aft_shoulder"]["ok"]
    assert not fuselage.get("fairings")
    VehicleSpec.model_validate(
        {
            "name": "synthetic-ref",
            "sketch": {
                **summary["suggested"]["sketch"],
                "treatment": "reproduction",
                "hard_scale": 1.0,
            },
            "wing": {k: v for k, v in wing.items() if v is not None},
            "fuselage": {
                **fuselage,
                "max_width_m": max(fuselage["max_width_m"], 0.06),
                "max_height_m": max(fuselage["max_height_m"], 0.06),
            },
            "vtail": summary["suggested"]["vtail"],
        }
    )
    inspired = suggest_spec_values(
        summary["measurements"],
        summary["alignment"],
        treatment="inspiration",
    )
    assert inspired["suggested"]["sketch"]["treatment"] == "inspiration"
    assert inspired["suggested"]["wing"]["sections"] is None
    VehicleSpec.model_validate(
        {
            "name": "synthetic-inspired",
            "sketch": inspired["suggested"]["sketch"],
            "wing": {
                key: value
                for key, value in inspired["suggested"]["wing"].items()
                if value is not None
            },
            "fuselage": {
                **inspired["suggested"]["fuselage"],
                "max_width_m": max(
                    inspired["suggested"]["fuselage"]["max_width_m"], 0.06
                ),
                "max_height_m": max(
                    inspired["suggested"]["fuselage"]["max_height_m"], 0.06
                ),
            },
            "vtail": inspired["suggested"]["vtail"],
        }
    )

    fins = summary["suggested"]["vtail"]
    assert fins["count"] == 2
    assert abs(fins["cant_deg"] - FIN_CANT_DEG) <= 3.0
    assert abs(fins["span_m"] - FIN_SPAN) <= 0.02
    assert abs(fins["root_chord_m"] - FIN_ROOT_CHORD) <= 0.015
    assert abs(fins["x_le_m"] - FIN_X_LE) <= 0.012

    assert summary["measurements"]["control_surface"]["resolved"] is False
    assert summary["evidence_class"].startswith("measured design input")


def test_section_suggestion_excludes_body_and_keeps_rounded_tip():
    station_y = [0.05, 0.11, 0.30, 0.70, 0.90, 0.97]
    x_le = [0.15, 0.26, 0.29, 0.31, 0.34, 0.42]
    x_te = [0.55, 0.52, 0.50, 0.46, 0.44, 0.445]
    wing_stations = []
    for side in (-1.0, 1.0):
        for y, leading, trailing in zip(station_y, x_le, x_te, strict=True):
            wing_stations.append(
                {
                    "y_m": side * y,
                    "x_le_m": leading,
                    "x_te_m": trailing,
                    "x_te_undeflected_m": trailing,
                    "z_chord_mid_m": (
                        0.02
                        - 0.01 * y
                        + (0.03 if y == 0.70 else 0.0)
                        + (0.02 if side > 0.0 and y == 0.30 else 0.0)
                    ),
                    "incidence_deg": 0.0,
                }
            )
    record = {
        "overall": {"length_m": 1.2},
        "stations": [
            {"x_over_length": 0.0, "width_m": 0.0},
            {"x_over_length": 0.35, "width_m": 0.20},
            {"x_over_length": 0.55, "width_m": 0.18},
            {"x_over_length": 1.0, "width_m": 0.0},
        ],
        "body_half_width_at_wing_m": 0.10,
        "airfoil_summary": {"t_over_c_mean": 0.10},
        "wing": {
            "ok": True,
            "stations": wing_stations,
            "span_m": 2.0,
            "semispan_m": 1.0,
            "body_half_width_m": 0.06,
            "x_le_root_m": 0.28,
            "x_te_root_m": 0.53,
            "root_chord_m": 0.25,
            "z_root_le_m": 0.02,
            "le_sweep_deg": 3.0,
            "te_sweep_deg": -5.0,
            "straight_range_abs_y_m": [0.3, 0.9],
        },
    }

    result = suggest_wing_sections(record, resolution_m=0.0005)
    assert result is not None
    sections, disclosure = result
    assert sections[0]["eta"] == 0.0
    assert sections[-1]["eta"] == 1.0
    assert all(section["eta"] != pytest.approx(0.05) for section in sections)
    assert any(section["eta"] == pytest.approx(0.11) for section in sections)
    assert sections[-1]["chord_m"] < sections[-2]["chord_m"]
    assert disclosure["body_exclusion_half_width_m"] == pytest.approx(0.10)
    assert disclosure["section_count"] <= 12
    assert disclosure["z_asymmetry_excluded_count"] == 1
    assert disclosure["z_asymmetry_max_excluded_m"] == pytest.approx(0.02)
    assert (
        disclosure["simplification_max_residual_m"]["z_le_m"]
        <= disclosure["simplification_tolerance_m"] + 1e-12
    )
    assert disclosure["tip_method"].startswith("linear extrapolation")

    exact_tip_record = json.loads(json.dumps(record))
    for station in exact_tip_record["wing"]["stations"]:
        if abs(abs(station["y_m"]) - 0.97) < 1e-9:
            station["y_m"] = math.copysign(1.0, station["y_m"])
            station["x_te_m"] = station["x_le_m"] + 0.001
            station["x_te_undeflected_m"] = station["x_te_m"]
    exact_tip = suggest_wing_sections(exact_tip_record, resolution_m=0.0005)
    assert exact_tip is not None
    assert exact_tip[1]["tip_method"].startswith("nearest measured station")
    assert not exact_tip[1]["tip_chord_floor_applied"]
    assert exact_tip[0][-1]["chord_m"] == pytest.approx(0.001)


def test_section_suggestion_rejects_outline_beyond_section_budget():
    stations = []
    for side in (-1.0, 1.0):
        for index, y in enumerate(np.linspace(0.1, 0.98, 24)):
            x_le = 0.2 if index % 2 == 0 else 0.5
            stations.append(
                {
                    "y_m": side * y,
                    "x_le_m": x_le,
                    "x_te_m": x_le + 0.2,
                    "x_te_undeflected_m": x_le + 0.2,
                    "z_chord_mid_m": 0.0,
                    "incidence_deg": 0.0,
                }
            )
    record = {
        "overall": {"length_m": 1.2},
        "stations": [],
        "body_half_width_at_wing_m": 0.05,
        "airfoil_summary": {"t_over_c_mean": 0.1},
        "wing": {
            "ok": True,
            "stations": stations,
            "span_m": 2.0,
            "semispan_m": 1.0,
            "body_half_width_m": 0.05,
            "x_le_root_m": 0.3,
            "x_te_root_m": 0.5,
            "root_chord_m": 0.2,
            "z_root_le_m": 0.0,
            "le_sweep_deg": 0.0,
            "te_sweep_deg": 0.0,
            "straight_range_abs_y_m": [0.2, 0.8],
        },
    }

    with pytest.raises(ReferenceInputError, match="at most 12 sections"):
        suggest_wing_sections(record, resolution_m=0.0005)


def test_ingest_writes_reference_bundle_and_silhouettes(ingested):
    out, summary = ingested
    reference = out / "reference"
    assert (reference / "reference.json").is_file()
    assert (reference / "reference.ply").is_file()
    assert (reference / "reference-sections.png").is_file()
    decimated = trimesh.load(
        str(reference / "reference.ply"), force="mesh", process=False
    )
    assert len(decimated.faces) <= 22000
    assert abs(decimated.extents[1] - SPAN) < 0.01  # span preserved by decimation
    for view in ("top", "side", "front"):
        path = out / f"sketch-{view}.png"
        data = path.read_bytes()
        assert data.startswith(PNG_SIGNATURE)
        from PIL import Image

        with Image.open(path) as image:
            assert image.text["openair:view"] == view
            assert float(image.text["openair:mm_per_px"]) == 1.0
            assert "by construction" in image.text["openair:rectified"]
    written = json.loads((reference / "reference.json").read_text(encoding="utf-8"))
    assert written["provenance"]["declared_units"] == "cm"
    assert (
        written["provenance"]["source_sha256"] == summary["provenance"]["source_sha256"]
    )
    assert written["acceptance"]["p95_m"] == pytest.approx(0.015)


def test_existing_silhouettes_need_force(ingested, scan_dir: Path):
    out, _ = ingested
    with pytest.raises(ReferenceInputError, match="--force"):
        ingest_reference(
            scan_dir / "synthetic.stl",
            concept="synthetic-ref",
            out_dir=out / "reference",
            sketch_dir=out,
            axes="x:-z,y:-x,z:+y",
            target_faces=20000,
        )


def test_compare_scores_the_same_shape_as_a_match(ingested, tmp_path):
    out, _ = ingested
    aligned = trimesh.load(
        str(out / "reference" / "reference.ply"), force="mesh", process=False
    )
    model_path = tmp_path / "model.stl"
    aligned.export(str(model_path))
    spec = VehicleSpec(name="synthetic-ref")
    spec.fuselage.length_m = LENGTH
    result = compare_reference(
        spec,
        tmp_path,
        stl_path=model_path,
        component_stls={"wing": model_path},
        reference_dir=out / "reference",
    )
    assert result["available"] is True
    assert result["ok"] is True
    assert result["distance_model_to_reference"]["p95_m"] < 0.003
    assert result["silhouettes"]["top"]["iou"] > 0.97
    assert (
        result["disclosed"]["p95_model_to_reference_exposed_components_m"]["wing"]
        < 0.003
    )
    assert (tmp_path / "reference_fidelity.json").is_file()
    assert (tmp_path / "reference_overlay.png").read_bytes().startswith(PNG_SIGNATURE)


def test_compare_flags_a_different_shape(ingested, tmp_path):
    out, _ = ingested
    aligned = trimesh.load(
        str(out / "reference" / "reference.ply"), force="mesh", process=False
    )
    stretched = aligned.copy()
    stretched.apply_scale([1.0, 1.25, 1.0])  # 25% more span than the reference
    model_path = tmp_path / "stretched.stl"
    stretched.export(str(model_path))
    spec = VehicleSpec(name="synthetic-ref")
    result = compare_reference(
        spec,
        tmp_path,
        stl_path=model_path,
        reference_dir=out / "reference",
        write=False,
    )
    assert result["ok"] is False
    assert result["checks"]["iou_top"]["ok"] is False


def test_compare_gates_body_union_and_excludes_buried_root(ingested, tmp_path):
    out, _ = ingested
    aligned = trimesh.load(
        str(out / "reference" / "reference.ply"), force="mesh", process=False
    )
    model_path = tmp_path / "body-union.stl"
    aligned.export(str(model_path))
    spec = VehicleSpec(name="synthetic-ref")
    spec.fuselage.length_m = LENGTH

    result = compare_reference(
        spec,
        tmp_path,
        stl_path=model_path,
        component_stls={
            "fuselage": str(model_path),
            "fairing_aft_shoulder": str(model_path),
            "fin_r_root": str(model_path),
        },
        reference_dir=out / "reference",
        write=False,
    )

    assert result["ok"]
    assert result["checks"]["p95_body"]["basis"] == (
        "fuselage + measured fairing components"
    )
    assert result["disclosed"]["body_union_components"] == [
        "fuselage",
        "fairing_aft_shoulder",
    ]
    assert result["components"]["fin_r_root"]["excluded_from_fidelity"]
    assert "fin_r_root" not in result["disclosed"]["p95_components_m"]


def test_compare_without_reference_is_unavailable(tmp_path):
    spec = VehicleSpec(name="none")
    result = compare_reference(
        spec, tmp_path, stl_path=tmp_path / "missing.stl", reference_dir=None
    )
    assert result["available"] is False


def test_section_powers_recover_an_ellipse():
    y = np.linspace(-0.05, 0.05, 81)
    top = 0.03 * np.sqrt(np.clip(1.0 - (y / 0.05) ** 2, 0.0, 1.0)) + 0.01
    bot = -0.03 * np.sqrt(np.clip(1.0 - (y / 0.05) ** 2, 0.0, 1.0)) + 0.01
    fit = M.fit_section_powers(
        y, top, bot, half_width=0.05, height=0.06, z_center=0.01, scale=0.0005
    )
    assert abs(fit["side_power"] - 2.0) < 0.15
    assert abs(fit["top_power"] - 2.0) < 0.15
    assert abs(fit["bottom_power"] - 2.0) < 0.15


def test_shoulder_fairing_fit_recovers_synthetic_dome():
    points = []
    for x_m in np.linspace(0.005, 0.695, 139):
        scale = math.sin(math.pi * x_m / LENGTH)
        for theta in np.linspace(0.0, 2.0 * math.pi, 64, endpoint=False):
            points.append(
                [
                    x_m,
                    BODY_HALF_WIDTH * scale * math.cos(theta),
                    BODY_HALF_HEIGHT * scale * math.sin(theta),
                ]
            )
    for x_m in np.linspace(0.42, 0.69, 80):
        for y_m in np.linspace(-0.20, 0.20, 100):
            points.extend(([x_m, y_m, 0.006], [x_m, y_m, -0.006]))
    for x_m in np.linspace(0.48, 0.66, 50):
        fraction = (x_m - 0.48) / 0.18
        half_width = 0.085 - 0.010 * fraction
        base_z = 0.004
        top_z = 0.052 - 0.010 * fraction
        for y_m in np.linspace(-half_width, half_width, 80):
            dome_z = base_z + (top_z - base_z) * math.sqrt(
                max(0.0, 1.0 - (y_m / half_width) ** 2)
            )
            points.extend(([x_m, y_m, dome_z], [x_m, y_m, base_z]))
    profile = [
        {
            "x_m": x_m,
            "width_m": 2.0
            * BODY_HALF_WIDTH
            * math.sin(math.pi * x_m / LENGTH),
            "height_m": 2.0
            * BODY_HALF_HEIGHT
            * math.sin(math.pi * x_m / LENGTH),
        }
        for x_m in np.linspace(0.005, 0.695, 139)
    ]
    fin = {
        "span_m": FIN_SPAN,
        "root_chord_m": FIN_ROOT_CHORD,
        "tip_chord_m": 0.6 * FIN_ROOT_CHORD,
        "taper": 0.6,
        "le_sweep_deg": 25.0,
        "cant_deg": FIN_CANT_DEG,
        "toe_deg": 0.0,
        "x_le_m": FIN_X_LE,
        "y_root_m": FIN_Y_ROOT,
        "z_root_m": 0.05,
        "thickness_m": 0.008,
        "t_over_c": 0.10,
        "plane_normal": [0.0, 1.0, 0.0],
        "fit_rms_m": {"le": 0.0, "te": 0.0},
    }
    fins = {
        "count": 2,
        "fins": [{**fin, "y_root_m": -FIN_Y_ROOT}, fin],
        "mirrored_mean": fin,
    }

    result = M.measure_shoulder_fairing(
        M.PointField(np.asarray(points), 0.001),
        length_m=LENGTH,
        semispan_m=0.5 * SPAN,
        body_profile_records=profile,
        wing=None,
        fins=fins,
    )

    assert result["ok"], result
    assert result["station_count"] == 8
    assert result["stations"][0]["width_m"] == 0.0
    assert result["stations"][-1]["width_m"] == 0.0
    measured_width = max(station["width_m"] for station in result["stations"])
    assert 0.09 <= measured_width <= 0.18
    assert result["shoulder_excess_max_m"] >= 0.03
    assert result["base_burial_allowance_m"] == pytest.approx(0.008)


def test_choose_station_fractions_is_monotone_and_bounded():
    profile = [
        {
            "x_m": x,
            "width_m": 0.1 * math.sin(math.pi * x / 0.7),
            "height_m": 0.08 * math.sin(math.pi * x / 0.7),
        }
        for x in np.linspace(0.005, 0.695, 139)
    ]
    fractions = M.choose_station_fractions(
        profile, 0.7, anchors_m=[0.3, 0.5, 0.55, 0.65, 0.6]
    )
    assert fractions[0] == 0.0 and fractions[-1] == 1.0
    assert len(fractions) <= 8
    assert all(b > a for a, b in zip(fractions, fractions[1:]))
