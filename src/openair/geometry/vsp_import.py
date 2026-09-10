"""Restricted OpenVSP GUI round-trip into ``VehicleSpec`` geometry fields."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from openair.geometry.fuselage import (
    LEGACY_XSEC_SCALES,
    LEGACY_XSEC_STATIONS,
)
from openair.geometry.fin_attachment import fin_attachment
from openair.geometry.openvsp_model import (
    VSP_LOCK,
    _drain_vsp_errors,
    _try_import_vsp,
)
from openair.schemas import VehicleSpec

GEOMETRY_KEYS = ("wing", "fuselage", "vtail", "htail")
VALUE_TOL = 1e-5


class ImportRejected(ValueError):
    """The GUI model cannot be represented safely by ``VehicleSpec``."""

    def __init__(self, reasons: list[str] | str):
        self.reasons = [reasons] if isinstance(reasons, str) else reasons
        super().__init__("; ".join(self.reasons))


def _parm(vsp, geom_id: str, name: str, group: str) -> float:
    return float(vsp.GetParmVal(geom_id, name, group))


def _reject_nonzero_transform(
    vsp,
    geom_id: str,
    label: str,
    *,
    allow_location: set[str] | None = None,
    allow_rotation: set[str] | None = None,
) -> list[str]:
    allow_location = allow_location or set()
    allow_rotation = allow_rotation or set()
    reasons: list[str] = []
    for axis in "XYZ":
        location = f"{axis}_Rel_Location"
        if location not in allow_location:
            value = _parm(vsp, geom_id, location, "XForm")
            if abs(value) > VALUE_TOL:
                reasons.append(f"{label}: {location}={value:.6g} is not representable")
        rotation = f"{axis}_Rel_Rotation"
        if rotation not in allow_rotation:
            value = _parm(vsp, geom_id, rotation, "XForm")
            if abs(value) > VALUE_TOL:
                reasons.append(f"{label}: {rotation}={value:.6g} is not representable")
    scale = _parm(vsp, geom_id, "Scale", "XForm")
    if abs(scale - 1.0) > VALUE_TOL:
        reasons.append(f"{label}: XForm Scale={scale:.6g} is not representable")
    return reasons


def _require_two_section_wing(vsp, geom_id: str, label: str) -> list[str]:
    xsurf = vsp.GetXSecSurf(geom_id, 0)
    count = int(vsp.GetNumXSec(xsurf))
    reasons = []
    if count != 2:
        reasons.append(
            f"{label}: expected exactly 2 wing sections, found {count}; "
            "multi-section wings are not representable yet"
        )
        return reasons
    for index in range(count):
        shape = int(vsp.GetXSecShape(vsp.GetXSec(xsurf, index)))
        if shape != int(vsp.XS_FOUR_SERIES):
            reasons.append(
                f"{label}: section {index} must use a NACA four-series airfoil"
            )
    return reasons


def _require_wing_sections(
    vsp,
    geom_id: str,
    label: str,
    *,
    minimum: int = 2,
    maximum: int = 12,
) -> tuple[int, list[str]]:
    xsurf = vsp.GetXSecSurf(geom_id, 0)
    count = int(vsp.GetNumXSec(xsurf))
    reasons = []
    if not minimum <= count <= maximum:
        reasons.append(
            f"{label}: expected {minimum}–{maximum} wing sections, found {count}"
        )
        return count, reasons
    for index in range(count):
        shape = int(vsp.GetXSecShape(vsp.GetXSec(xsurf, index)))
        if shape != int(vsp.XS_FOUR_SERIES):
            reasons.append(
                f"{label}: section {index} must use a NACA four-series airfoil"
            )
    return count, reasons


def _naca_code(
    vsp,
    geom_id: str,
    label: str,
    *,
    count: int = 2,
    thickness_digits: str | None = None,
    allow_variable_thickness: bool = False,
) -> tuple[str | None, list[str]]:
    reasons: list[str] = []
    sections: list[tuple[float, float, float]] = []
    for index in range(count):
        group = f"XSecCurve_{index}"
        sections.append(
            (
                _parm(vsp, geom_id, "Camber", group),
                _parm(vsp, geom_id, "CamberLoc", group),
                _parm(vsp, geom_id, "ThickChord", group),
            )
        )
    if any(
        abs(section[0] - sections[0][0]) > 1e-4
        or abs(section[1] - sections[0][1]) > 1e-4
        for section in sections[1:]
    ):
        reasons.append(
            f"{label}: root and tip airfoils differ; mixed camber lines are not "
            "representable yet"
        )
        return None, reasons
    if not allow_variable_thickness and any(
        abs(section[2] - sections[0][2]) > 1e-4 for section in sections[1:]
    ):
        reasons.append(
            f"{label}: root and tip airfoils differ; variable thickness is not "
            "representable for a two-section wing"
        )
        return None, reasons
    camber, camber_loc, thickness = sections[0]
    first = round(camber * 100.0)
    second = 0 if first == 0 else round(camber_loc * 10.0)
    last = (
        int(thickness_digits)
        if thickness_digits is not None
        else round(thickness * 100.0)
    )
    reconstructed = (first / 100.0, second / 10.0)
    if (
        abs(camber - reconstructed[0]) > 5e-4
        or (first != 0 and abs(camber_loc - reconstructed[1]) > 5e-4)
        or (thickness_digits is None and abs(thickness - last / 100.0) > 5e-4)
        or not 0 <= first <= 9
        or not 0 <= second <= 9
        or not 0 <= last <= 99
    ):
        reasons.append(
            f"{label}: airfoil parameters do not describe a four-digit NACA code"
        )
        return None, reasons
    return f"{first:d}{second:d}{last:02d}", reasons


def _import_wing(
    vsp,
    geom_id: str,
    seed_spec: VehicleSpec,
) -> tuple[dict[str, Any], list[str]]:
    reasons = _reject_nonzero_transform(
        vsp,
        geom_id,
        "wing",
        allow_location={"X_Rel_Location", "Z_Rel_Location"},
    )
    count, section_reasons = _require_wing_sections(vsp, geom_id, "wing")
    reasons.extend(section_reasons)
    for index in range(1, count):
        sweep_location = _parm(vsp, geom_id, "Sweep_Location", f"XSec_{index}")
        if abs(sweep_location) > VALUE_TOL:
            reasons.append(
                f"wing: XSec_{index}.Sweep_Location must remain 0 so section "
                "sweep means LE sweep"
            )
    sectioned = count >= 3
    if seed_spec.wing.sections is not None and not sectioned:
        reasons.append("wing: a sectioned source must retain at least 3 sections")
    if sectioned and not (
        seed_spec.sketch is not None and seed_spec.sketch.treatment == "reproduction"
    ):
        reasons.append(
            "wing: multi-section geometry requires sketch.treatment='reproduction'"
        )
    airfoil, airfoil_reasons = _naca_code(
        vsp,
        geom_id,
        "wing",
        count=count,
        thickness_digits=seed_spec.wing.airfoil[2:],
        allow_variable_thickness=sectioned,
    )
    reasons.extend(airfoil_reasons)
    root = _parm(vsp, geom_id, "Root_Chord", "XSec_1")
    thickness = _parm(vsp, geom_id, "ThickChord", "XSecCurve_0")
    if not sectioned:
        tip = _parm(vsp, geom_id, "Tip_Chord", "XSec_1")
        return {
            "span_m": _parm(vsp, geom_id, "TotalSpan", "WingGeom"),
            "root_chord_m": root,
            "taper": tip / root if root > 0.0 else 0.0,
            "le_sweep_deg": _parm(vsp, geom_id, "Sweep", "XSec_1"),
            "dihedral_deg": _parm(vsp, geom_id, "Dihedral", "XSec_1"),
            "twist_root_deg": _parm(vsp, geom_id, "Twist", "XSec_0"),
            "twist_tip_deg": _parm(vsp, geom_id, "Twist", "XSec_1"),
            "t_over_c": thickness,
            "airfoil": airfoil or "0000",
            "x_le_root_m": _parm(vsp, geom_id, "X_Rel_Location", "XForm"),
            "z_root_m": _parm(vsp, geom_id, "Z_Rel_Location", "XForm"),
            "sections": None,
        }, reasons

    span = _parm(vsp, geom_id, "TotalProjectedSpan", "WingGeom")
    semispan = 0.5 * span
    x_le = _parm(vsp, geom_id, "X_Rel_Location", "XForm")
    z_le = _parm(vsp, geom_id, "Z_Rel_Location", "XForm")
    y = 0.0
    root_twist = _parm(vsp, geom_id, "Twist", "XSec_0")
    section_values: list[dict[str, Any]] = [
        {
            "eta": 0.0,
            "chord_m": root,
            "x_le_m": x_le,
            "z_le_m": z_le,
            "t_over_c": (
                None
                if seed_spec.wing.sections
                and seed_spec.wing.sections[0].t_over_c is None
                and abs(thickness - seed_spec.wing.t_over_c) <= 1e-4
                else thickness
            ),
        }
    ]
    twists = [root_twist]
    for index in range(1, count):
        group = f"XSec_{index}"
        projected_span = _parm(vsp, geom_id, "ProjectedSpan", group)
        panel_span = _parm(vsp, geom_id, "Span", group)
        sweep = _parm(vsp, geom_id, "Sweep", group)
        dihedral = _parm(vsp, geom_id, "Dihedral", group)
        y += projected_span
        x_le += projected_span * math.tan(math.radians(sweep))
        z_le += panel_span * math.sin(math.radians(dihedral))
        t_over_c = _parm(vsp, geom_id, "ThickChord", f"XSecCurve_{index}")
        seed_section = (
            seed_spec.wing.sections[index]
            if seed_spec.wing.sections is not None
            and index < len(seed_spec.wing.sections)
            else None
        )
        section_values.append(
            {
                "eta": y / max(semispan, 1e-12),
                "chord_m": _parm(vsp, geom_id, "Tip_Chord", group),
                "x_le_m": x_le,
                "z_le_m": z_le,
                "t_over_c": (
                    None
                    if seed_section is not None
                    and seed_section.t_over_c is None
                    and abs(t_over_c - seed_spec.wing.t_over_c) <= 1e-4
                    else t_over_c
                ),
            }
        )
        twists.append(_parm(vsp, geom_id, "Twist", group))
    tip_twist = twists[-1]
    for index, (section, twist) in enumerate(
        zip(section_values[1:-1], twists[1:-1], strict=True),
        start=1,
    ):
        expected = root_twist + section["eta"] * (tip_twist - root_twist)
        if abs(twist - expected) > 1e-4:
            reasons.append(
                f"wing: XSec_{index}.Twist={twist:.6g} is not on the "
                f"representable root-to-tip linear law ({expected:.6g})"
            )
    try:
        equivalent = seed_spec.wing.equivalent_trapezoid(section_values, span)
    except ValueError as exc:
        reasons.append(f"wing: cannot derive section equivalents: {exc}")
        equivalent = {
            "root_chord_m": root,
            "taper": seed_spec.wing.taper,
            "le_sweep_deg": seed_spec.wing.le_sweep_deg,
            "dihedral_deg": seed_spec.wing.dihedral_deg,
            "x_le_root_m": section_values[0]["x_le_m"],
            "z_root_m": section_values[0]["z_le_m"],
        }
    return {
        "span_m": span,
        "root_chord_m": equivalent["root_chord_m"],
        "taper": equivalent["taper"],
        "le_sweep_deg": equivalent["le_sweep_deg"],
        "dihedral_deg": equivalent["dihedral_deg"],
        "twist_root_deg": root_twist,
        "twist_tip_deg": tip_twist,
        "t_over_c": seed_spec.wing.t_over_c,
        "airfoil": airfoil or seed_spec.wing.airfoil,
        "x_le_root_m": equivalent["x_le_root_m"],
        "z_root_m": equivalent["z_root_m"],
        "sections": section_values,
    }, reasons


def _is_legacy_body(
    stations: list[dict[str, float]],
    seed: VehicleSpec,
) -> bool:
    if seed.fuselage.stations is not None or len(stations) != len(LEGACY_XSEC_STATIONS):
        return False
    for index, (station, x_fraction, scale) in enumerate(
        zip(stations, LEGACY_XSEC_STATIONS, LEGACY_XSEC_SCALES)
    ):
        endpoint = index in {0, len(stations) - 1}
        expected_width = 0.0 if endpoint else seed.fuselage.max_width_m * scale
        expected_height = 0.0 if endpoint else seed.fuselage.max_height_m * scale
        if (
            abs(station["x_over_length"] - x_fraction) > 1e-5
            or abs(station["width_m"] - expected_width) > 1e-4
            or abs(station["height_m"] - expected_height) > 1e-4
            or abs(station["z_offset_m"]) > 1e-5
        ):
            return False
    return True


def _import_fuselage(
    vsp,
    geom_id: str,
    seed: VehicleSpec,
) -> tuple[dict[str, Any], list[str]]:
    reasons = _reject_nonzero_transform(vsp, geom_id, "fuselage")
    length = _parm(vsp, geom_id, "Length", "Design")
    xsurf = vsp.GetXSecSurf(geom_id, 0)
    count = int(vsp.GetNumXSec(xsurf))
    if not 4 <= count <= 8:
        reasons.append(f"fuselage: expected 4–8 sections, found {count}")
    stations: list[dict[str, float]] = []
    for index in range(count):
        xs = vsp.GetXSec(xsurf, index)
        shape = int(vsp.GetXSecShape(xs))
        supported = {
            int(vsp.XS_POINT),
            int(vsp.XS_ELLIPSE),
            int(vsp.XS_SUPER_ELLIPSE),
        }
        if shape not in supported:
            if shape in {
                int(vsp.XS_ROUNDED_RECTANGLE),
                int(vsp.XS_GENERAL_FUSE),
            }:
                detail = "rounded-rectangle/general sections are not representable"
            else:
                detail = f"cross-section type {shape} is not representable"
            reasons.append(f"fuselage: section {index}: {detail}")
        width = 0.0 if shape == int(vsp.XS_POINT) else float(vsp.GetXSecWidth(xs))
        height = 0.0 if shape == int(vsp.XS_POINT) else float(vsp.GetXSecHeight(xs))
        side_power = 2.0
        top_power = 2.0
        bottom_power = 2.0
        if shape == int(vsp.XS_SUPER_ELLIPSE):
            side_power = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_M")))
            top_power = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_N")))
            bottom_side_power = float(
                vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_M_bot"))
            )
            bottom_power = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_N_bot")))
            max_width_location = float(
                vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_MaxWidthLoc"))
            )
            if abs(bottom_side_power - side_power) > VALUE_TOL:
                reasons.append(
                    f"fuselage: section {index}: Super_M_bot must equal "
                    "Super_M because side_power is shared by both halves"
                )
            if abs(max_width_location) > VALUE_TOL:
                reasons.append(
                    f"fuselage: section {index}: Super_MaxWidthLoc must remain "
                    "0; vertical width bias is not representable yet"
                )
        stations.append(
            {
                "x_over_length": float(
                    vsp.GetParmVal(vsp.GetXSecParm(xs, "XLocPercent"))
                ),
                "width_m": width,
                "height_m": height,
                "z_offset_m": float(vsp.GetParmVal(vsp.GetXSecParm(xs, "ZLocPercent")))
                * length,
                "side_power": side_power,
                "top_power": top_power,
                "bottom_power": bottom_power,
            }
        )
    if not stations:
        reasons.append("fuselage: no sections found")
        max_width = seed.fuselage.max_width_m
        max_height = seed.fuselage.max_height_m
    else:
        max_width = max(station["width_m"] for station in stations)
        max_height = max(station["height_m"] for station in stations)
    return {
        "length_m": length,
        "max_width_m": max_width,
        "max_height_m": max_height,
        "stations": None if _is_legacy_body(stations, seed) else stations,
    }, reasons


def _read_tail_planform(
    vsp, geom_id: str, label: str
) -> tuple[dict[str, float], list[str]]:
    reasons = _require_two_section_wing(vsp, geom_id, label)
    sweep_location = _parm(vsp, geom_id, "Sweep_Location", "XSec_1")
    if abs(sweep_location) > VALUE_TOL:
        reasons.append(f"{label}: Sweep_Location must remain 0 so sweep is LE sweep")
    root = _parm(vsp, geom_id, "Root_Chord", "XSec_1")
    tip = _parm(vsp, geom_id, "Tip_Chord", "XSec_1")
    t_root = _parm(vsp, geom_id, "ThickChord", "XSecCurve_0")
    t_tip = _parm(vsp, geom_id, "ThickChord", "XSecCurve_1")
    if abs(t_root - t_tip) > 1e-4:
        reasons.append(f"{label}: root and tip thickness ratios must match")
    for group in ("XSecCurve_0", "XSecCurve_1"):
        if abs(_parm(vsp, geom_id, "Camber", group)) > VALUE_TOL:
            reasons.append(
                f"{label}: tail airfoils must remain symmetric; camber is "
                "not represented"
            )
    for name, group in (
        ("Dihedral", "XSec_1"),
        ("Twist", "XSec_0"),
        ("Twist", "XSec_1"),
    ):
        value = _parm(vsp, geom_id, name, group)
        if abs(value) > VALUE_TOL:
            reasons.append(f"{label}: {group}.{name}={value:.6g} is not represented")
    span = _parm(vsp, geom_id, "Span", "XSec_1")
    taper = tip / root if root > 0.0 else 0.0
    sweep = _parm(vsp, geom_id, "Sweep", "XSec_1")
    if (
        span <= 0.0
        or root <= 0.0
        or not 0.03 < taper <= 1.0
        or not -45.0 <= sweep <= 60.0
        or not 0.04 < t_root < 0.30
    ):
        reasons.append(f"{label}: planform values are outside supported bounds")
    return {
        "span_m": span,
        "root_chord_m": root,
        "taper": taper,
        "le_sweep_deg": sweep,
        "t_over_c": t_root,
        "x_le_m": _parm(vsp, geom_id, "X_Rel_Location", "XForm"),
    }, reasons


def _import_vtail(
    vsp,
    right_id: str,
    left_id: str,
    seed_spec: VehicleSpec,
) -> tuple[dict[str, Any], list[str]]:
    reasons = []
    right, right_reasons = _read_tail_planform(vsp, right_id, "vtailr")
    left, left_reasons = _read_tail_planform(vsp, left_id, "vtaill")
    reasons.extend(right_reasons)
    reasons.extend(left_reasons)
    reasons.extend(
        _reject_nonzero_transform(
            vsp,
            right_id,
            "vtailr",
            allow_location={
                "X_Rel_Location",
                "Y_Rel_Location",
                "Z_Rel_Location",
            },
            allow_rotation={"X_Rel_Rotation"},
        )
    )
    reasons.extend(
        _reject_nonzero_transform(
            vsp,
            left_id,
            "vtaill",
            allow_location={
                "X_Rel_Location",
                "Y_Rel_Location",
                "Z_Rel_Location",
            },
            allow_rotation={"X_Rel_Rotation"},
        )
    )
    for key in right:
        if abs(right[key] - left[key]) > 1e-4:
            reasons.append(f"vtail pair: {key} differs between right and left fins")
    right_rotation = _parm(vsp, right_id, "X_Rel_Rotation", "XForm")
    left_rotation = _parm(vsp, left_id, "X_Rel_Rotation", "XForm")
    cant = 90.0 - right_rotation
    if not 0.0 <= cant <= 75.0:
        reasons.append(f"vtail pair: cant {cant:.6g} deg is outside 0–75 deg")
    if abs(left_rotation - (90.0 + cant)) > 1e-4:
        reasons.append(
            "vtail pair: left/right X rotations do not describe a symmetric canted pair"
        )

    attachment = fin_attachment(seed_spec)
    actual = {
        "right_y": _parm(vsp, right_id, "Y_Rel_Location", "XForm"),
        "left_y": _parm(vsp, left_id, "Y_Rel_Location", "XForm"),
        "right_z": _parm(vsp, right_id, "Z_Rel_Location", "XForm"),
        "left_z": _parm(vsp, left_id, "Z_Rel_Location", "XForm"),
    }
    if seed_spec.vtail.root_attachment == "measured":
        if (
            actual["right_y"] <= 0.0
            or abs(actual["left_y"] + actual["right_y"]) > 1e-4
            or abs(actual["left_z"] - actual["right_z"]) > 1e-4
        ):
            reasons.append(
                "vtail pair: measured root positions must be a mirrored +/-y "
                "pair at one shared z"
            )
        y_root_m = actual["right_y"]
        z_root_m = 0.5 * (actual["right_z"] + actual["left_z"])
    else:
        expected_y = float(attachment["y_m"])
        expected_z = float(attachment["z_m"])
        if (
            abs(actual["right_y"] - expected_y) > 1e-4
            or abs(actual["left_y"] + expected_y) > 1e-4
            or abs(actual["right_z"] - expected_z) > 1e-4
            or abs(actual["left_z"] - expected_z) > 1e-4
        ):
            reasons.append(
                "vtail pair: root y/z positions are derived from the local "
                "fuselage and cannot be edited directly"
            )
        y_root_m = seed_spec.vtail.y_root_m
        z_root_m = seed_spec.vtail.z_root_m
    return {
        **right,
        "count": 2,
        "cant_deg": cant,
        "root_attachment": seed_spec.vtail.root_attachment,
        "y_root_m": y_root_m,
        "z_root_m": z_root_m,
    }, reasons


def _import_single_vtail(
    vsp,
    center_id: str,
    seed_spec: VehicleSpec,
) -> tuple[dict[str, Any], list[str]]:
    center, reasons = _read_tail_planform(vsp, center_id, "vtailc")
    reasons.extend(
        _reject_nonzero_transform(
            vsp,
            center_id,
            "vtailc",
            allow_location={
                "X_Rel_Location",
                "Y_Rel_Location",
                "Z_Rel_Location",
            },
            allow_rotation={"X_Rel_Rotation"},
        )
    )
    rotation = _parm(vsp, center_id, "X_Rel_Rotation", "XForm")
    cant = 90.0 - rotation
    if not 0.0 <= cant <= 75.0:
        reasons.append(f"vtail center: cant {cant:.6g} deg is outside 0–75 deg")

    attachment = fin_attachment(seed_spec)
    actual_y = _parm(vsp, center_id, "Y_Rel_Location", "XForm")
    actual_z = _parm(vsp, center_id, "Z_Rel_Location", "XForm")
    if seed_spec.vtail.root_attachment == "measured":
        if abs(actual_y) > 1e-4:
            reasons.append("vtail center: measured root must remain at y=0")
        y_root_m = 0.0
        z_root_m = actual_z
    else:
        expected_z = float(attachment["z_m"])
        if abs(actual_y) > 1e-4 or abs(actual_z - expected_z) > 1e-4:
            reasons.append(
                "vtail center: root y/z position is derived from the local "
                "fuselage and cannot be edited directly"
            )
        y_root_m = seed_spec.vtail.y_root_m
        z_root_m = seed_spec.vtail.z_root_m
    return {
        **center,
        "count": 1,
        "cant_deg": cant,
        "root_attachment": seed_spec.vtail.root_attachment,
        "y_root_m": y_root_m,
        "z_root_m": z_root_m,
    }, reasons


def _import_htail(vsp, geom_id: str) -> tuple[dict[str, Any], list[str]]:
    reasons = _reject_nonzero_transform(
        vsp,
        geom_id,
        "htail",
        allow_location={"X_Rel_Location", "Z_Rel_Location"},
        allow_rotation={"Y_Rel_Rotation"},
    )
    planform, planform_reasons = _read_tail_planform(vsp, geom_id, "htail")
    reasons.extend(planform_reasons)
    root = planform["root_chord_m"]
    tip = _parm(vsp, geom_id, "Tip_Chord", "XSec_1")
    total_span = _parm(vsp, geom_id, "TotalSpan", "WingGeom")
    if total_span <= 0.05:
        reasons.append("htail: total span must remain above 0.05 m")
    return {
        "span_m": total_span,
        "root_chord_m": root,
        "taper": tip / root if root > 0.0 else 0.0,
        "le_sweep_deg": planform["le_sweep_deg"],
        "t_over_c": planform["t_over_c"],
        "x_le_m": planform["x_le_m"],
        "z_m": _parm(vsp, geom_id, "Z_Rel_Location", "XForm"),
        "incidence_deg": _parm(vsp, geom_id, "Y_Rel_Rotation", "XForm"),
    }, reasons


def _model_geoms(vsp) -> tuple[dict[str, str], list[str]]:
    by_name: dict[str, str] = {}
    reasons = []
    for geom_id in vsp.FindGeoms():
        name = str(vsp.GetGeomName(geom_id))
        if name in by_name:
            reasons.append(f"duplicate OpenVSP geom name: {name}")
        by_name[name] = geom_id
    return by_name, reasons


def import_vsp3(
    path: str | Path,
    seed_spec: VehicleSpec,
    *,
    attachment_spec: VehicleSpec | None = None,
) -> dict[str, Any]:
    """Import only geometry fields from a restricted OpenVSP session model."""
    vsp = _try_import_vsp()
    if vsp is None:
        raise ImportRejected("OpenVSP Python API is unavailable")
    source = Path(path).resolve()
    if not source.is_file():
        raise ImportRejected(f"OpenVSP session file is missing: {source}")

    with VSP_LOCK:
        _drain_vsp_errors(vsp)
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(source))
        vsp.Update()
        by_name, reasons = _model_geoms(vsp)
        fin_names = {"vtailc"} if seed_spec.vtail.count == 1 else {"vtailr", "vtaill"}
        expected = {"fuselage", "wing", *fin_names}
        if seed_spec.htail.span_m > 0.05:
            expected.add("htail")
        missing = sorted(expected - set(by_name))
        added = sorted(set(by_name) - expected)
        if missing:
            reasons.append(f"required geoms missing: {', '.join(missing)}")
        if added:
            reasons.append(
                f"unsupported geoms added: {', '.join(added)}; edit existing "
                "components only"
            )
        expected_types = {
            "fuselage": "Fuselage",
            "wing": "Wing",
            "vtailc": "Wing",
            "vtailr": "Wing",
            "vtaill": "Wing",
            "htail": "Wing",
        }
        type_mismatch = False
        for name in sorted(expected & set(by_name)):
            got_type = str(vsp.GetGeomTypeName(by_name[name]))
            if got_type != expected_types[name]:
                type_mismatch = True
                reasons.append(
                    f"{name}: expected {expected_types[name]} geom, found {got_type}"
                )
        if missing or type_mismatch:
            raise ImportRejected(reasons)

        fuselage, fuselage_reasons = _import_fuselage(
            vsp, by_name["fuselage"], seed_spec
        )
        wing, wing_reasons = _import_wing(vsp, by_name["wing"], seed_spec)
        reasons.extend(fuselage_reasons)
        reasons.extend(wing_reasons)

        seed_data = seed_spec.model_dump(mode="python", exclude_computed_fields=True)
        seed_data["wing"].update(wing)
        seed_data["fuselage"].update(fuselage)
        try:
            VehicleSpec.model_validate(seed_data)
        except ValidationError as exc:
            reasons.append(f"wing/fuselage validation failed: {exc}")
            raise ImportRejected(reasons) from exc

        if seed_spec.vtail.count == 1:
            vtail, vtail_reasons = _import_single_vtail(
                vsp,
                by_name["vtailc"],
                attachment_spec or seed_spec,
            )
        else:
            vtail, vtail_reasons = _import_vtail(
                vsp,
                by_name["vtailr"],
                by_name["vtaill"],
                attachment_spec or seed_spec,
            )
        reasons.extend(vtail_reasons)
        htail = None
        if "htail" in expected:
            htail, htail_reasons = _import_htail(vsp, by_name["htail"])
            reasons.extend(htail_reasons)

        errors = _drain_vsp_errors(vsp)
        if errors:
            reasons.extend(f"OpenVSP: {error}" for error in errors)

    geometry: dict[str, Any] = {
        "wing": wing,
        "fuselage": fuselage,
        "vtail": vtail,
    }
    if htail is not None:
        geometry["htail"] = htail
    merged = seed_spec.model_dump(mode="python", exclude_computed_fields=True)
    for key, value in geometry.items():
        merged[key].update(value)
    try:
        VehicleSpec.model_validate(merged)
    except ValidationError as exc:
        reasons.append(f"VehicleSpec validation failed: {exc}")
    if reasons:
        raise ImportRejected(reasons)
    return geometry


def geometry_changes(
    seed_spec: VehicleSpec,
    geometry: dict[str, Any],
) -> list[str]:
    """Return compact human-readable imported field changes."""
    before = seed_spec.model_dump(mode="python", exclude_computed_fields=True)
    changes: list[str] = []

    def visit(path: str, old: Any, new: Any) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in new:
                visit(f"{path}.{key}" if path else key, old.get(key), new[key])
            return
        if isinstance(old, list) and isinstance(new, list):
            if len(old) != len(new):
                changes.append(f"{path}: {len(old)} → {len(new)} stations")
            elif all(
                isinstance(old_item, dict) and isinstance(new_item, dict)
                for old_item, new_item in zip(old, new)
            ):

                def item_value_changed(old_value: Any, new_value: Any) -> bool:
                    if isinstance(old_value, (int, float)) and isinstance(
                        new_value, (int, float)
                    ):
                        return abs(float(old_value) - float(new_value)) > 1e-5
                    return old_value != new_value

                changed = any(
                    any(
                        item_value_changed(old_item.get(key), value)
                        for key, value in new_item.items()
                    )
                    for old_item, new_item in zip(old, new)
                )
                if changed:
                    changes.append(f"{path}: station loft updated")
            elif old != new:
                changes.append(f"{path}: values updated")
            return
        if isinstance(new, list):
            changes.append(f"{path}: {old!r} → {len(new)} stations")
            return
        if isinstance(old, list):
            changes.append(f"{path}: {len(old)} stations → {new!r}")
            return
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            if abs(float(old) - float(new)) > 1e-6:
                changes.append(f"{path}: {float(old):.6g} → {float(new):.6g}")
            return
        if old != new:
            changes.append(f"{path}: {old!r} → {new!r}")

    for key in GEOMETRY_KEYS:
        if key in geometry:
            visit(key, before[key], geometry[key])
    return changes
