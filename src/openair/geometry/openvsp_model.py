"""OpenVSP parametric geometry. Falls back to mesh-only if the API is missing."""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any

from openair.geometry.fuselage import (
    LEGACY_XSEC_SCALES,
    LEGACY_XSEC_STATIONS,
)
from openair.geometry.fin_attachment import fin_attachment
from openair.geometry.mesh import (
    generate_oas_rect_mesh,
    save_mesh,
    wing_planform_points,
)
from openair.geometry.packing import external_nacelle_y_positions, packing_report
from openair.paths import configure_runtime
from openair.schemas import VehicleSpec

VSP_LOCK = threading.RLock()


def _try_import_vsp():
    configure_runtime()
    try:
        import openvsp as vsp

        return vsp
    except Exception:
        return None


def _set(vsp, gid: str, name: str, group: str, value: float) -> bool:
    try:
        vsp.SetParmVal(gid, name, group, float(value))
        return True
    except Exception:
        return False


def _subsurface_parm_value(vsp, subsurface_id: str, name: str) -> float:
    """Read a SubSurf parm by ID; serialized group names gain numeric suffixes."""
    matches = [
        parm_id
        for parm_id in vsp.GetSubSurfParmIDs(subsurface_id)
        if str(vsp.GetParmName(parm_id)) == name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"subsurface {subsurface_id} has {len(matches)} parms named {name!r}"
        )
    return float(vsp.GetParmVal(matches[0]))


# Fuselage XSec scale table used by the builder: stations (fraction of
# length) and width/height scale factors applied to max_width/max_height.
FUSE_XSEC_STATIONS = LEGACY_XSEC_STATIONS
FUSE_XSEC_SCALES = LEGACY_XSEC_SCALES


def _station_uses_superellipse(station) -> bool:
    return any(
        abs(power - 2.0) > 1e-12
        for power in (
            station.side_power,
            station.top_power,
            station.bottom_power,
        )
    )


def _drain_vsp_errors(vsp) -> list[str]:
    """Drain OpenVSP's process-global error queue."""
    errors: list[str] = []
    try:
        mgr = vsp.ErrorMgrSingleton.getInstance()
        while mgr.GetNumTotalErrors() > 0:
            errors.append(str(mgr.PopLastError().GetErrorString()).strip())
    except Exception:
        pass
    return errors


def _set_wing_driver_group(vsp, geom_id: str, section_index: int = 1) -> None:
    try:
        vsp.SetDriverGroup(
            geom_id,
            section_index,
            vsp.SPAN_WSECT_DRIVER,
            vsp.ROOTC_WSECT_DRIVER,
            vsp.TIPC_WSECT_DRIVER,
        )
    except Exception:
        try:
            vsp.SetDriverGroup(
                geom_id,
                section_index,
                vsp.AREA_WSECT_DRIVER,
                vsp.ROOTC_WSECT_DRIVER,
                vsp.TIPC_WSECT_DRIVER,
            )
        except Exception:
            pass


def _wing_twist_at(spec: VehicleSpec, eta: float) -> float:
    return spec.wing.twist_root_deg + float(eta) * (
        spec.wing.twist_tip_deg - spec.wing.twist_root_deg
    )


def _configure_wing(vsp, wing_id: str, spec: VehicleSpec) -> None:
    """Write either the scalar trapezoid or the measured section loft."""
    wing = spec.wing
    _set(vsp, wing_id, "X_Rel_Location", "XForm", wing.x_le_root_m)
    _set(vsp, wing_id, "Z_Rel_Location", "XForm", wing.z_root_m)
    code = wing.airfoil
    camber = int(code[0]) / 100.0
    camber_loc = int(code[1]) / 10.0

    if wing.sections is None:
        _set_wing_driver_group(vsp, wing_id)
        _set(vsp, wing_id, "Span", "XSec_1", 0.5 * wing.span_m)
        _set(vsp, wing_id, "TotalSpan", "WingGeom", wing.span_m)
        _set(vsp, wing_id, "Root_Chord", "XSec_1", wing.root_chord_m)
        _set(vsp, wing_id, "Tip_Chord", "XSec_1", wing.tip_chord_m)
        _set(vsp, wing_id, "Sweep", "XSec_1", wing.le_sweep_deg)
        _set(vsp, wing_id, "Sweep_Location", "XSec_1", 0.0)
        _set(vsp, wing_id, "Dihedral", "XSec_1", wing.dihedral_deg)
        _set(vsp, wing_id, "Twist", "XSec_0", wing.twist_root_deg)
        _set(vsp, wing_id, "Twist", "XSec_1", wing.twist_tip_deg)
        for index in range(2):
            group = f"XSecCurve_{index}"
            _set(vsp, wing_id, "Camber", group, camber)
            _set(vsp, wing_id, "CamberLoc", group, camber_loc)
            _set(vsp, wing_id, "ThickChord", group, wing.t_over_c)
        vsp.Update()
        return

    xsec_surf = vsp.GetXSecSurf(wing_id, 0)
    while int(vsp.GetNumXSec(xsec_surf)) < len(wing.sections):
        last_index = int(vsp.GetNumXSec(xsec_surf)) - 1
        vsp.InsertXSec(wing_id, last_index, vsp.XS_FOUR_SERIES)
        vsp.Update()
    if int(vsp.GetNumXSec(xsec_surf)) != len(wing.sections):
        raise RuntimeError(
            "OpenVSP wing section count does not match wing.sections: "
            f"{vsp.GetNumXSec(xsec_surf)} != {len(wing.sections)}"
        )

    for index in range(1, len(wing.sections)):
        _set_wing_driver_group(vsp, wing_id, index)
    for index, section in enumerate(wing.sections):
        curve_group = f"XSecCurve_{index}"
        _set(vsp, wing_id, "Camber", curve_group, camber)
        _set(vsp, wing_id, "CamberLoc", curve_group, camber_loc)
        _set(
            vsp,
            wing_id,
            "ThickChord",
            curve_group,
            wing.t_over_c if section.t_over_c is None else section.t_over_c,
        )
        _set(
            vsp,
            wing_id,
            "Twist",
            f"XSec_{index}",
            _wing_twist_at(spec, section.eta),
        )
        if index == 0:
            continue
        inner = wing.sections[index - 1]
        dy = (section.eta - inner.eta) * 0.5 * wing.span_m
        dz = section.z_le_m - inner.z_le_m
        panel_group = f"XSec_{index}"
        _set(vsp, wing_id, "Span", panel_group, math.hypot(dy, dz))
        _set(vsp, wing_id, "Root_Chord", panel_group, inner.chord_m)
        _set(vsp, wing_id, "Tip_Chord", panel_group, section.chord_m)
        _set(
            vsp,
            wing_id,
            "Sweep",
            panel_group,
            math.degrees(math.atan2(section.x_le_m - inner.x_le_m, dy)),
        )
        _set(vsp, wing_id, "Sweep_Location", panel_group, 0.0)
        _set(
            vsp,
            wing_id,
            "Dihedral",
            panel_group,
            math.degrees(math.atan2(dz, dy)),
        )
    vsp.Update()
    # OpenVSP 3.51 leaves XSec_1.Area and WingGeom.TotalArea at their
    # pre-insertion defaults even though all section parms read back correctly.
    # Nudging and restoring the aggregate span forces those derived values to
    # recompute and, critically, makes the written VSP3 reopen with the same
    # panel chords instead of rescaling the wing to the stale total area.
    total_span = 2.0 * sum(
        math.hypot(
            (outer.eta - inner.eta) * 0.5 * wing.span_m,
            outer.z_le_m - inner.z_le_m,
        )
        for inner, outer in zip(wing.sections, wing.sections[1:])
    )
    _set(vsp, wing_id, "TotalSpan", "WingGeom", total_span * 1.001)
    vsp.Update()
    _set(vsp, wing_id, "TotalSpan", "WingGeom", total_span)
    vsp.Update()


def _mirrored_control_gains(mode: str) -> tuple[float, float]:
    """OpenVSP mirrored WING copies use opposite local hinge orientation."""
    if mode == "collective":
        return (1.0, -1.0)
    if mode == "differential":
        return (1.0, 1.0)
    raise ValueError(f"unsupported mirrored control mode: {mode}")


def _configure_control_groups(
    vsp, controls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Create all overlapping logical VSPAERO groups in one model."""
    if not controls:
        return []
    vsp.AutoGroupVSPAEROControlSurfaces()
    for index in reversed(range(int(vsp.GetNumControlSurfaceGroups()))):
        vsp.DeleteVSPAEROControlSurfaceGroup(index)

    logical: dict[str, dict[str, Any]] = {}
    for control in controls:
        for mix in control["mixing"]:
            entry = logical.setdefault(
                mix["id"],
                {
                    "id": mix["id"],
                    "mode": mix["mode"],
                    "axis": mix["axis"],
                    "members": [],
                },
            )
            entry["members"].append(
                {
                    "surface_id": control["id"],
                    "gain": float(mix["gain"]),
                }
            )

    settings = vsp.FindContainer("VSPAEROSettings", 0)
    groups: list[dict[str, Any]] = []
    for group_index, group in enumerate(logical.values()):
        created_index = int(vsp.CreateVSPAEROControlSurfaceGroup())
        if created_index != group_index:
            raise RuntimeError(
                f"unexpected VSPAERO control group index {created_index}; "
                f"expected {group_index}"
            )
        vsp.AddAllToVSPAEROControlSurfaceGroup(group_index)
        vsp.SetVSPAEROControlGroupName(group["id"], group_index)
        expected_gains: dict[str, list[float]] = {}
        member_gain = {
            item["surface_id"]: float(item["gain"]) for item in group["members"]
        }
        for control in controls:
            physical_gain = member_gain.get(control["id"], 0.0)
            for subsurface in control["subsurfaces"]:
                if subsurface["mirrored"] and physical_gain:
                    gains = tuple(
                        physical_gain * value
                        for value in _mirrored_control_gains(group["mode"])
                    )
                elif subsurface["mirrored"]:
                    gains = (0.0, 0.0)
                else:
                    if group["mode"] != "single" and physical_gain:
                        raise ValueError(
                            f"unmirrored surface {control['id']} requires single mixing"
                        )
                    gains = (physical_gain,)
                expected_gains[subsurface["subsurface_id"]] = list(gains)
                for copy_index, gain in enumerate(gains):
                    gain_id = vsp.FindParm(
                        settings,
                        f"Surf_{subsurface['subsurface_id']}_{copy_index}_Gain",
                        f"ControlSurfaceGroup_{group_index}",
                    )
                    if not gain_id:
                        raise RuntimeError(
                            "missing VSPAERO gain for "
                            f"{control['id']} copy {copy_index} in {group['id']}"
                        )
                    vsp.SetParmVal(gain_id, gain)
        groups.append({**group, "expected_gains": expected_gains})
    vsp.Update()
    return groups


def _construct_model(
    vsp,
    spec: VehicleSpec,
    *,
    filename: Path | None = None,
) -> dict[str, Any]:
    """Build the representable OpenVSP geometry without analyses or exports."""
    _drain_vsp_errors(vsp)
    vsp.ClearVSPModel()
    if filename is not None:
        vsp.SetVSP3FileName(str(filename))
    errors: list[str] = []

    fid = vsp.AddGeom("FUSELAGE", "")
    vsp.SetGeomName(fid, "fuselage")
    _set(vsp, fid, "Length", "Design", spec.fuselage.length_m)
    xsurf = vsp.GetXSecSurf(fid, 0)
    if spec.fuselage.stations is None:
        try:
            nxs = vsp.GetNumXSec(xsurf)
            scales = list(FUSE_XSEC_SCALES)
            for index in range(nxs):
                xs = vsp.GetXSec(xsurf, index)
                scale = scales[min(index, len(scales) - 1)]
                vsp.SetXSecWidthHeight(
                    xs,
                    spec.fuselage.max_width_m * scale,
                    spec.fuselage.max_height_m * scale,
                )
        except Exception as exc:
            errors.append(f"fuselage_legacy: {exc}")
    else:
        stations = spec.fuselage.stations
        try:
            while vsp.GetNumXSec(xsurf) < len(stations):
                vsp.InsertXSec(fid, vsp.GetNumXSec(xsurf) - 2, vsp.XS_ELLIPSE)
            while vsp.GetNumXSec(xsurf) > len(stations):
                vsp.CutXSec(fid, vsp.GetNumXSec(xsurf) - 2)
            for index, station in enumerate(stations):
                shape = (
                    vsp.XS_POINT
                    if station.width_m == 0.0 and station.height_m == 0.0
                    else (
                        vsp.XS_SUPER_ELLIPSE
                        if _station_uses_superellipse(station)
                        else vsp.XS_ELLIPSE
                    )
                )
                vsp.ChangeXSecShape(xsurf, index, shape)
            vsp.Update()
            for index, station in enumerate(stations):
                xs = vsp.GetXSec(xsurf, index)
                vsp.SetParmVal(
                    vsp.GetXSecParm(xs, "XLocPercent"), station.x_over_length
                )
                vsp.SetParmVal(
                    vsp.GetXSecParm(xs, "ZLocPercent"),
                    station.z_offset_m / spec.fuselage.length_m,
                )
                if station.width_m > 0.0 and station.height_m > 0.0:
                    vsp.SetXSecWidthHeight(xs, station.width_m, station.height_m)
                    if _station_uses_superellipse(station):
                        for name, value in (
                            ("Super_TopBotSym", 0.0),
                            ("Super_M", station.side_power),
                            ("Super_N", station.top_power),
                            ("Super_M_bot", station.side_power),
                            ("Super_N_bot", station.bottom_power),
                            ("Super_MaxWidthLoc", 0.0),
                        ):
                            vsp.SetParmVal(vsp.GetXSecParm(xs, name), value)
        except Exception as exc:
            errors.append(f"fuselage_stations: {exc}")
    vsp.Update()

    wid = vsp.AddGeom("WING", "")
    vsp.SetGeomName(wid, "wing")
    try:
        _configure_wing(vsp, wid, spec)
    except Exception as exc:
        errors.append(f"wing_sections: {exc}")

    # A WING geom spans +y. One X-axis roll makes a vertical fin while
    # preserving streamwise chord: right 90-cant, left 90+cant. The shared
    # attachment policy either preserves the historical body-derived root or
    # honours a measured y/z junction exactly; exported-mesh QA verifies that
    # the selected point remains attached (QA audit F14/F15/F34).
    fin_attach = {
        **fin_attachment(spec),
        "x_rotation_center_deg": 90.0 - spec.vtail.cant_deg,
        "x_rotation_right_deg": 90.0 - spec.vtail.cant_deg,
        "x_rotation_left_deg": 90.0 + spec.vtail.cant_deg,
    }
    root_y = fin_attach["y_m"]
    z_attach = fin_attach["z_m"]
    vtails = []
    fin_defs = (
        ((1.0, "vtailc", 0.0),)
        if spec.vtail.count == 1
        else ((1.0, "vtailr", root_y), (-1.0, "vtaill", -root_y))
    )
    for sign, name, y_root in fin_defs:
        vid = vsp.AddGeom("WING", "")
        vsp.SetGeomName(vid, name)
        _set(vsp, vid, "Sym_Planar_Flag", "Sym", 0.0)
        _set(vsp, vid, "Sym_Ancestor_Origin_Flag", "Sym", 0.0)
        _set_wing_driver_group(vsp, vid)
        _set(vsp, vid, "X_Rel_Location", "XForm", spec.vtail.x_le_m)
        _set(vsp, vid, "Y_Rel_Location", "XForm", y_root)
        _set(vsp, vid, "Z_Rel_Location", "XForm", z_attach)
        _set(
            vsp,
            vid,
            "X_Rel_Rotation",
            "XForm",
            90.0 - sign * spec.vtail.cant_deg,
        )
        _set(vsp, vid, "Y_Rel_Rotation", "XForm", 0.0)
        _set(vsp, vid, "Span", "XSec_1", spec.vtail.span_m)
        _set(vsp, vid, "Root_Chord", "XSec_1", spec.vtail.root_chord_m)
        _set(
            vsp,
            vid,
            "Tip_Chord",
            "XSec_1",
            spec.vtail.root_chord_m * spec.vtail.taper,
        )
        _set(vsp, vid, "Sweep", "XSec_1", spec.vtail.le_sweep_deg)
        _set(vsp, vid, "Sweep_Location", "XSec_1", 0.0)
        _set(vsp, vid, "ThickChord", "XSecCurve_0", spec.vtail.t_over_c)
        _set(vsp, vid, "ThickChord", "XSecCurve_1", spec.vtail.t_over_c)
        vsp.Update()
        vtails.append(vid)

    hid = None
    if spec.htail.span_m > 0.05:
        hid = vsp.AddGeom("WING", "")
        vsp.SetGeomName(hid, "htail")
        _set_wing_driver_group(vsp, hid)
        _set(vsp, hid, "X_Rel_Location", "XForm", spec.htail.x_le_m)
        _set(vsp, hid, "Z_Rel_Location", "XForm", spec.htail.z_m)
        _set(vsp, hid, "Y_Rel_Rotation", "XForm", spec.htail.incidence_deg)
        _set(vsp, hid, "Span", "XSec_1", 0.5 * spec.htail.span_m)
        _set(vsp, hid, "TotalSpan", "WingGeom", spec.htail.span_m)
        _set(vsp, hid, "Root_Chord", "XSec_1", spec.htail.root_chord_m)
        _set(
            vsp,
            hid,
            "Tip_Chord",
            "XSec_1",
            spec.htail.root_chord_m * spec.htail.taper,
        )
        _set(vsp, hid, "Sweep", "XSec_1", spec.htail.le_sweep_deg)
        _set(vsp, hid, "Sweep_Location", "XSec_1", 0.0)
        _set(vsp, hid, "ThickChord", "XSecCurve_0", spec.htail.t_over_c)
        _set(vsp, hid, "ThickChord", "XSecCurve_1", spec.htail.t_over_c)
        vsp.Update()

    controls: list[dict[str, Any]] = []
    logical_groups: list[dict[str, Any]] = []
    # Declared control surfaces are serialized whenever they exist, not only
    # when the flight-dynamics stage is enabled: the validation stage uses the
    # VSPAERO control groups to cross-check the OAS elevon pitch derivative.
    if spec.flight_dynamics.control_surfaces:
        host_geometries = {
            "wing": [wid],
            "htail": [hid] if hid is not None else [],
            "vtail": list(vtails),
        }
        try:
            for surface in spec.flight_dynamics.control_surfaces:
                host_ids = host_geometries[surface.host]
                if not host_ids:
                    raise ValueError(
                        f"control surface {surface.id} has unavailable host {surface.host}"
                    )
                subsurfaces = []
                for host_id in host_ids:
                    subsurface_id = vsp.AddSubSurf(host_id, vsp.SS_CONTROL, 0)
                    vsp.SetSubSurfName(host_id, subsurface_id, surface.id)
                    _set(vsp, subsurface_id, "EtaFlag", "SS_Control", 1.0)
                    _set(
                        vsp,
                        subsurface_id,
                        "EtaStart",
                        "SS_Control",
                        surface.span_start_fraction,
                    )
                    _set(
                        vsp,
                        subsurface_id,
                        "EtaEnd",
                        "SS_Control",
                        surface.span_end_fraction,
                    )
                    _set(
                        vsp,
                        subsurface_id,
                        "Length_C_Start",
                        "SS_Control",
                        surface.chord_fraction,
                    )
                    _set(
                        vsp,
                        subsurface_id,
                        "Length_C_End",
                        "SS_Control",
                        surface.chord_fraction,
                    )
                    _set(vsp, subsurface_id, "LE_Flag", "SS_Control", 0.0)
                    subsurfaces.append(
                        {
                            "geom_id": host_id,
                            "geom_name": str(vsp.GetGeomName(host_id)),
                            "subsurface_id": subsurface_id,
                            "mirrored": surface.host in {"wing", "htail"},
                        }
                    )
                controls.append(
                    {
                        "id": surface.id,
                        "host": surface.host,
                        "span_start_fraction": surface.span_start_fraction,
                        "span_end_fraction": surface.span_end_fraction,
                        "chord_fraction": surface.chord_fraction,
                        "mixing": [
                            {
                                "id": mix.id,
                                "mode": mix.mode,
                                "axis": mix.axis,
                                "gain": mix.gain,
                            }
                            for mix in surface.mixing
                        ],
                        "subsurfaces": subsurfaces,
                    }
                )
            logical_groups = _configure_control_groups(vsp, controls)
        except Exception as exc:
            errors.append(f"control_surfaces: {exc}")

    engine_pods = []
    pod_positions: list[tuple[float, str]] = []
    if spec.engine.installation == "external":
        positions = external_nacelle_y_positions(spec)
        names = (
            ["engine_pod_c"]
            if len(positions) == 1
            else (
                ["engine_pod_l", "engine_pod_r"]
                if len(positions) == 2
                else [f"engine_pod_{index + 1}" for index in range(len(positions))]
            )
        )
        pod_positions = list(zip(positions, names, strict=True))
        x_nose = float(spec.engine.x_m) - 0.5 * spec.engine.length_m
        for y_m, name in pod_positions:
            pod = vsp.AddGeom("POD", "")
            vsp.SetGeomName(pod, name)
            _set(vsp, pod, "X_Rel_Location", "XForm", x_nose)
            _set(vsp, pod, "Y_Rel_Location", "XForm", y_m)
            _set(vsp, pod, "Z_Rel_Location", "XForm", spec.engine.z_m)
            _set(vsp, pod, "Length", "Design", spec.engine.length_m)
            _set(
                vsp,
                pod,
                "FineRatio",
                "Design",
                2.0 * spec.engine.length_m / spec.engine.diameter_m,
            )
            _set(vsp, pod, "Tess_U", "Shape", 24)
            vsp.Update()
            engine_pods.append(pod)

    errors.extend(_drain_vsp_errors(vsp))
    return {
        "fuselage": fid,
        "fuselage_xsurf": xsurf,
        "wing": wid,
        "control_surfaces": controls,
        "control_groups": logical_groups,
        "vtails": vtails,
        "htail": hid,
        "engine_pods": engine_pods,
        "engine_pod_positions": pod_positions,
        "fin_attach": fin_attach,
        "errors": errors,
    }


def _rebind_serialized_model_ids(vsp, built: dict[str, Any]) -> dict[str, Any]:
    """Rebind IDs that OpenVSP regenerates while reopening a VSP3.

    Geom IDs are normally serialized, but SubSurf IDs are not stable. Read-back
    and component exports must therefore use IDs discovered from the reopened
    artifact, not handles retained from the in-memory construction.
    """
    by_name = {str(vsp.GetGeomName(gid)): gid for gid in vsp.FindGeoms()}
    required = {"fuselage", "wing"}
    fin_names = ["vtailc"] if len(built["vtails"]) == 1 else ["vtailr", "vtaill"]
    required.update(fin_names)
    if built["htail"] is not None:
        required.add("htail")
    missing = required - by_name.keys()
    if missing:
        raise RuntimeError(
            f"reopened VSP3 is missing geometry names: {sorted(missing)}"
        )

    old_to_new_subsurf: dict[str, str] = {}
    controls: list[dict[str, Any]] = []
    for control in built["control_surfaces"]:
        subsurfaces = []
        for old in control["subsurfaces"]:
            geom_name = str(old["geom_name"])
            geom_id = by_name[geom_name]
            candidates = [
                str(subsurf_id)
                for subsurf_id in vsp.GetSubSurfIDVec(geom_id)
                if str(vsp.GetSubSurfName(geom_id, subsurf_id)) == control["id"]
            ]
            if len(candidates) != 1:
                raise RuntimeError(
                    f"reopened {geom_name} has {len(candidates)} subsurfaces "
                    f"named {control['id']!r}, expected one"
                )
            subsurface_id = candidates[0]
            old_to_new_subsurf[str(old["subsurface_id"])] = subsurface_id
            subsurfaces.append(
                {
                    **old,
                    "geom_id": geom_id,
                    "subsurface_id": subsurface_id,
                }
            )
        controls.append({**control, "subsurfaces": subsurfaces})

    control_groups = []
    for group in built["control_groups"]:
        control_groups.append(
            {
                **group,
                "expected_gains": {
                    old_to_new_subsurf.get(
                        str(subsurface_id), str(subsurface_id)
                    ): gains
                    for subsurface_id, gains in group["expected_gains"].items()
                },
            }
        )
    engine_pods = [
        by_name[name] for _, name in built["engine_pod_positions"] if name in by_name
    ]
    return {
        **built,
        "fuselage": by_name["fuselage"],
        "fuselage_xsurf": vsp.GetXSecSurf(by_name["fuselage"], 0),
        "wing": by_name["wing"],
        "control_surfaces": controls,
        "control_groups": control_groups,
        "vtails": [by_name[name] for name in fin_names],
        "htail": by_name.get("htail"),
        "engine_pods": engine_pods,
    }


def _sectioned_wing_readback(
    vsp,
    spec: VehicleSpec,
    wing_id: str,
) -> tuple[dict[str, Any], bool]:
    """Read every OpenVSP panel and reconstruct its outer planform station."""
    wing = spec.wing
    assert wing.sections is not None
    xsec_surf = vsp.GetXSecSurf(wing_id, 0)
    count = int(vsp.GetNumXSec(xsec_surf))
    count_ok = count == len(wing.sections)
    root_chord = float(vsp.GetParmVal(wing_id, "Root_Chord", "XSec_1"))
    x_le = float(vsp.GetParmVal(wing_id, "X_Rel_Location", "XForm"))
    z_le = float(vsp.GetParmVal(wing_id, "Z_Rel_Location", "XForm"))
    y = 0.0
    section_rows = [
        {
            "index": 0,
            "eta": 0.0,
            "chord_m": root_chord,
            "x_le_m": x_le,
            "z_le_m": z_le,
            "twist_deg": float(vsp.GetParmVal(wing_id, "Twist", "XSec_0")),
            "t_over_c": float(vsp.GetParmVal(wing_id, "ThickChord", "XSecCurve_0")),
        }
    ]
    panel_rows: list[dict[str, Any]] = []
    projected_area = 0.0
    sections_ok = count_ok
    if not count_ok:
        return {
            "count": count,
            "expected_count": len(wing.sections),
            "sections": section_rows,
            "panels": panel_rows,
            "matches": False,
        }, False

    root_want = wing.sections[0]
    sections_ok = sections_ok and (
        abs(root_chord - root_want.chord_m) <= 1e-4
        and abs(x_le - root_want.x_le_m) <= 1e-4
        and abs(z_le - root_want.z_le_m) <= 1e-4
        and abs(section_rows[0]["twist_deg"] - _wing_twist_at(spec, 0.0)) <= 0.1
        and abs(
            section_rows[0]["t_over_c"]
            - (wing.t_over_c if root_want.t_over_c is None else root_want.t_over_c)
        )
        <= 1e-4
    )
    semispan = 0.5 * wing.span_m
    for index in range(1, count):
        group = f"XSec_{index}"
        curve_group = f"XSecCurve_{index}"
        span = float(vsp.GetParmVal(wing_id, "Span", group))
        projected_span = float(vsp.GetParmVal(wing_id, "ProjectedSpan", group))
        root = float(vsp.GetParmVal(wing_id, "Root_Chord", group))
        tip = float(vsp.GetParmVal(wing_id, "Tip_Chord", group))
        sweep = float(vsp.GetParmVal(wing_id, "Sweep", group))
        sweep_location = float(vsp.GetParmVal(wing_id, "Sweep_Location", group))
        dihedral = float(vsp.GetParmVal(wing_id, "Dihedral", group))
        twist = float(vsp.GetParmVal(wing_id, "Twist", group))
        t_over_c = float(vsp.GetParmVal(wing_id, "ThickChord", curve_group))
        y += projected_span
        x_le += projected_span * math.tan(math.radians(sweep))
        z_le += span * math.sin(math.radians(dihedral))
        projected_area += (root + tip) * projected_span
        inner_want = wing.sections[index - 1]
        outer_want = wing.sections[index]
        want_dy = (outer_want.eta - inner_want.eta) * semispan
        want_dz = outer_want.z_le_m - inner_want.z_le_m
        want_span = math.hypot(want_dy, want_dz)
        want_sweep = math.degrees(
            math.atan2(outer_want.x_le_m - inner_want.x_le_m, want_dy)
        )
        want_dihedral = math.degrees(math.atan2(want_dz, want_dy))
        want_t_over_c = (
            wing.t_over_c if outer_want.t_over_c is None else outer_want.t_over_c
        )
        panel_ok = (
            abs(span - want_span) <= max(1e-4, 0.002 * want_span)
            and abs(projected_span - want_dy) <= max(1e-4, 0.002 * want_dy)
            and abs(root - inner_want.chord_m) <= 1e-4
            and abs(tip - outer_want.chord_m) <= 1e-4
            and abs(sweep - want_sweep) <= 0.1
            and abs(sweep_location) <= 1e-6
            and abs(dihedral - want_dihedral) <= 0.1
            and abs(twist - _wing_twist_at(spec, outer_want.eta)) <= 0.1
            and abs(t_over_c - want_t_over_c) <= 1e-4
            and abs(x_le - outer_want.x_le_m) <= 5e-4
            and abs(z_le - outer_want.z_le_m) <= 5e-4
        )
        sections_ok = sections_ok and panel_ok
        panel_rows.append(
            {
                "index": index,
                "span_m": span,
                "projected_span_m": projected_span,
                "root_chord_m": root,
                "tip_chord_m": tip,
                "sweep_deg": sweep,
                "sweep_location": sweep_location,
                "dihedral_deg": dihedral,
                "matches": panel_ok,
            }
        )
        section_rows.append(
            {
                "index": index,
                "eta": y / max(semispan, 1e-12),
                "chord_m": tip,
                "x_le_m": x_le,
                "z_le_m": z_le,
                "twist_deg": twist,
                "t_over_c": t_over_c,
            }
        )
    return {
        "count": count,
        "expected_count": len(wing.sections),
        "projected_area_m2": projected_area,
        "sections": section_rows,
        "panels": panel_rows,
        "matches": sections_ok,
    }, sections_ok


def _construction_readback(
    vsp,
    spec: VehicleSpec,
    built: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Verify the values set by :func:`_construct_model`."""
    wid = built["wing"]
    xsurf = built["fuselage_xsurf"]
    errors: list[str] = []
    try:
        got_area = float(vsp.GetParmVal(wid, "TotalArea", "WingGeom"))
        got_root = float(vsp.GetParmVal(wid, "Root_Chord", "XSec_1"))
        got_twist_root = float(vsp.GetParmVal(wid, "Twist", "XSec_0"))

        def _rel(got: float, want: float) -> float:
            return abs(got - want) / max(abs(want), 1e-9)

        if spec.wing.sections is None:
            got_span = float(vsp.GetParmVal(wid, "TotalSpan", "WingGeom"))
            got_tip = float(vsp.GetParmVal(wid, "Tip_Chord", "XSec_1"))
            got_sweep = float(vsp.GetParmVal(wid, "Sweep", "XSec_1"))
            got_twist_tip = float(vsp.GetParmVal(wid, "Twist", "XSec_1"))
            readback: dict[str, Any] = {
                "planform_mode": "trapezoid",
                "span_m": got_span,
                "area_m2": got_area,
                "root_chord_m": got_root,
                "tip_chord_m": got_tip,
                "le_sweep_deg": got_sweep,
                "twist_root_deg": got_twist_root,
                "twist_tip_deg": got_twist_tip,
                "rel_err": {
                    "span": _rel(got_span, spec.wing.span_m),
                    "area": _rel(got_area, spec.wing.area_m2),
                    "root_chord": _rel(got_root, spec.wing.root_chord_m),
                    "tip_chord": _rel(got_tip, spec.wing.tip_chord_m),
                },
            }
            twist_ok = (
                abs(got_twist_root - spec.wing.twist_root_deg) <= 0.1
                and abs(got_twist_tip - spec.wing.twist_tip_deg) <= 0.1
            )
            sections_ok = True
        else:
            section_readback, sections_ok = _sectioned_wing_readback(vsp, spec, wid)
            got_span = float(vsp.GetParmVal(wid, "TotalProjectedSpan", "WingGeom"))
            got_tip = float(section_readback["sections"][-1]["chord_m"])
            got_twist_tip = float(section_readback["sections"][-1]["twist_deg"])
            projected_area = float(section_readback.get("projected_area_m2", 0.0))
            readback = {
                "planform_mode": "sections",
                "span_m": got_span,
                "area_m2": got_area,
                "projected_area_m2": projected_area,
                "root_chord_m": got_root,
                "actual_tip_chord_m": got_tip,
                "equivalent_tip_chord_m": spec.wing.tip_chord_m,
                "le_sweep_deg": spec.wing.le_sweep_deg,
                "twist_root_deg": got_twist_root,
                "twist_tip_deg": got_twist_tip,
                "wing_sections": section_readback,
                "rel_err": {
                    "span": _rel(got_span, spec.wing.span_m),
                    "area": _rel(projected_area, spec.wing.area_m2),
                    "root_chord": _rel(got_root, spec.wing.root_chord_m),
                    "tip_chord": _rel(got_tip, spec.wing.chord_at(1.0)),
                },
            }
            twist_ok = (
                abs(got_twist_root - spec.wing.twist_root_deg) <= 0.1
                and abs(got_twist_tip - spec.wing.twist_tip_deg) <= 0.1
            )
        readback["wing_sections_match"] = sections_ok
        readback["twist_matches"] = twist_ok
        controls_ok = len(built["control_surfaces"]) == len(
            spec.flight_dynamics.control_surfaces
        )
        control_values = []
        wanted_by_id = {
            surface.id: surface for surface in spec.flight_dynamics.control_surfaces
        }
        for control in built["control_surfaces"]:
            wanted = wanted_by_id[control["id"]]
            surface_values = []
            for subsurface in control["subsurfaces"]:
                subsurface_id = subsurface["subsurface_id"]
                values = {
                    "geom_name": subsurface["geom_name"],
                    "subsurface_id": subsurface_id,
                    "name": str(
                        vsp.GetSubSurfName(subsurface["geom_id"], subsurface_id)
                    ),
                    "eta_flag": _subsurface_parm_value(vsp, subsurface_id, "EtaFlag"),
                    "span_start_fraction": _subsurface_parm_value(
                        vsp, subsurface_id, "EtaStart"
                    ),
                    "span_end_fraction": _subsurface_parm_value(
                        vsp, subsurface_id, "EtaEnd"
                    ),
                    "chord_fraction_start": _subsurface_parm_value(
                        vsp, subsurface_id, "Length_C_Start"
                    ),
                    "chord_fraction_end": _subsurface_parm_value(
                        vsp, subsurface_id, "Length_C_End"
                    ),
                }
                surface_values.append(values)
                controls_ok = controls_ok and (
                    values["name"] == control["id"]
                    and abs(values["eta_flag"] - 1.0) <= 1e-8
                    and abs(values["span_start_fraction"] - wanted.span_start_fraction)
                    <= 1e-5
                    and abs(values["span_end_fraction"] - wanted.span_end_fraction)
                    <= 1e-5
                    and abs(values["chord_fraction_start"] - wanted.chord_fraction)
                    <= 1e-5
                    and abs(values["chord_fraction_end"] - wanted.chord_fraction)
                    <= 1e-5
                )
            control_values.append(
                {
                    "id": control["id"],
                    "host": control["host"],
                    "subsurfaces": surface_values,
                    "mixing": control["mixing"],
                }
            )

        group_names = [
            str(vsp.GetVSPAEROControlGroupName(index))
            for index in range(int(vsp.GetNumControlSurfaceGroups()))
        ]
        expected_group_names = [group["id"] for group in built["control_groups"]]
        controls_ok = controls_ok and group_names == expected_group_names
        settings = vsp.FindContainer("VSPAEROSettings", 0)
        group_readback = []
        for group_index, group in enumerate(built["control_groups"]):
            gains: dict[str, list[float]] = {}
            for subsurface_id, expected in group["expected_gains"].items():
                got = []
                for copy_index in range(len(expected)):
                    gain_id = vsp.FindParm(
                        settings,
                        f"Surf_{subsurface_id}_{copy_index}_Gain",
                        f"ControlSurfaceGroup_{group_index}",
                    )
                    got.append(float(vsp.GetParmVal(gain_id)) if gain_id else math.nan)
                gains[subsurface_id] = got
                controls_ok = controls_ok and all(
                    math.isfinite(value) and abs(value - target) <= 1e-8
                    for value, target in zip(got, expected, strict=True)
                )
            group_readback.append(
                {
                    "id": group["id"],
                    "axis": group["axis"],
                    "mode": group["mode"],
                    "gains": gains,
                }
            )
        tag_basenames = [
            f"{spec.name}{subsurface['geom_name']}_Surf{copy_index}_{control['id']}"
            for control in built["control_surfaces"]
            for subsurface in control["subsurfaces"]
            for copy_index in range(2 if subsurface["mirrored"] else 1)
        ]
        taglist_unique = len(tag_basenames) == len(set(tag_basenames))
        lifting_geom_names = [
            "wing",
            *(["htail"] if built["htail"] is not None else []),
            *(str(vsp.GetGeomName(vid)) for vid in built["vtails"]),
        ]
        delimiter_safe_names = all(name.isalnum() for name in lifting_geom_names)
        controls_ok = controls_ok and taglist_unique and delimiter_safe_names
        readback["control_surfaces"] = control_values
        readback["control_groups"] = group_readback
        readback["control_group_count"] = len(group_names)
        readback["control_group_names"] = group_names
        readback["tag_basenames"] = tag_basenames
        readback["taglist_unique"] = taglist_unique
        readback["delimiter_safe_lifting_names"] = delimiter_safe_names
        readback["control_surfaces_match"] = controls_ok
        station_ok = True
        if spec.fuselage.stations is not None:
            station_readback = []
            station_ok = vsp.GetNumXSec(xsurf) == len(spec.fuselage.stations)
            for index, wanted in enumerate(spec.fuselage.stations):
                xs = vsp.GetXSec(xsurf, index)
                shape = int(vsp.GetXSecShape(xs))
                expected_shape = (
                    int(vsp.XS_POINT)
                    if wanted.width_m == 0.0 and wanted.height_m == 0.0
                    else (
                        int(vsp.XS_SUPER_ELLIPSE)
                        if _station_uses_superellipse(wanted)
                        else int(vsp.XS_ELLIPSE)
                    )
                )
                if shape == int(vsp.XS_SUPER_ELLIPSE):
                    powers = {
                        "side_power": float(
                            vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_M"))
                        ),
                        "top_power": float(
                            vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_N"))
                        ),
                        "bottom_side_power": float(
                            vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_M_bot"))
                        ),
                        "bottom_power": float(
                            vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_N_bot"))
                        ),
                        "max_width_location": float(
                            vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_MaxWidthLoc"))
                        ),
                        "top_bottom_symmetric": float(
                            vsp.GetParmVal(vsp.GetXSecParm(xs, "Super_TopBotSym"))
                        ),
                    }
                else:
                    powers = {
                        "side_power": 2.0,
                        "top_power": 2.0,
                        "bottom_side_power": 2.0,
                        "bottom_power": 2.0,
                        "max_width_location": 0.0,
                        "top_bottom_symmetric": 0.0,
                    }
                got_station = {
                    "shape": shape,
                    "x_over_length": float(
                        vsp.GetParmVal(vsp.GetXSecParm(xs, "XLocPercent"))
                    ),
                    "width_m": float(vsp.GetXSecWidth(xs)),
                    "height_m": float(vsp.GetXSecHeight(xs)),
                    "z_offset_m": float(
                        vsp.GetParmVal(vsp.GetXSecParm(xs, "ZLocPercent"))
                    )
                    * spec.fuselage.length_m,
                    **powers,
                }
                station_readback.append(got_station)
                station_ok = station_ok and (
                    got_station["shape"] == expected_shape
                    and abs(got_station["x_over_length"] - wanted.x_over_length) <= 1e-5
                    and abs(got_station["width_m"] - wanted.width_m) <= 1e-4
                    and abs(got_station["height_m"] - wanted.height_m) <= 1e-4
                    and abs(got_station["z_offset_m"] - wanted.z_offset_m) <= 1e-4
                    and abs(got_station["side_power"] - wanted.side_power) <= 1e-5
                    and abs(got_station["top_power"] - wanted.top_power) <= 1e-5
                    and abs(got_station["bottom_side_power"] - wanted.side_power)
                    <= 1e-5
                    and abs(got_station["bottom_power"] - wanted.bottom_power) <= 1e-5
                    and abs(got_station["max_width_location"]) <= 1e-8
                    and abs(got_station["top_bottom_symmetric"]) <= 1e-8
                )
            readback["fuselage_stations"] = station_readback
            readback["fuselage_stations_match"] = station_ok

        expected_fin_names = (
            ["vtailc"] if spec.vtail.count == 1 else ["vtailr", "vtaill"]
        )
        expected_fin_y = (
            [0.0]
            if spec.vtail.count == 1
            else [built["fin_attach"]["y_m"], -built["fin_attach"]["y_m"]]
        )
        expected_fin_rotation = (
            [90.0 - spec.vtail.cant_deg]
            if spec.vtail.count == 1
            else [90.0 - spec.vtail.cant_deg, 90.0 + spec.vtail.cant_deg]
        )
        fin_readback = []
        fin_ok = len(built["vtails"]) == spec.vtail.count
        for index, vid in enumerate(built["vtails"]):
            values = {
                "name": str(vsp.GetGeomName(vid)),
                "span_m": float(vsp.GetParmVal(vid, "Span", "XSec_1")),
                "root_chord_m": float(vsp.GetParmVal(vid, "Root_Chord", "XSec_1")),
                "tip_chord_m": float(vsp.GetParmVal(vid, "Tip_Chord", "XSec_1")),
                "sweep_deg": float(vsp.GetParmVal(vid, "Sweep", "XSec_1")),
                "sweep_location": float(
                    vsp.GetParmVal(vid, "Sweep_Location", "XSec_1")
                ),
                "t_over_c_root": float(
                    vsp.GetParmVal(vid, "ThickChord", "XSecCurve_0")
                ),
                "t_over_c_tip": float(vsp.GetParmVal(vid, "ThickChord", "XSecCurve_1")),
                "x_le_m": float(vsp.GetParmVal(vid, "X_Rel_Location", "XForm")),
                "y_root_m": float(vsp.GetParmVal(vid, "Y_Rel_Location", "XForm")),
                "z_root_m": float(vsp.GetParmVal(vid, "Z_Rel_Location", "XForm")),
                "x_rotation_deg": float(vsp.GetParmVal(vid, "X_Rel_Rotation", "XForm")),
            }
            fin_readback.append(values)
            fin_ok = fin_ok and (
                index < len(expected_fin_names)
                and values["name"] == expected_fin_names[index]
                and _rel(values["span_m"], spec.vtail.span_m) <= 0.02
                and _rel(values["root_chord_m"], spec.vtail.root_chord_m) <= 0.02
                and _rel(
                    values["tip_chord_m"],
                    spec.vtail.root_chord_m * spec.vtail.taper,
                )
                <= 0.02
                and abs(values["sweep_deg"] - spec.vtail.le_sweep_deg) <= 0.1
                and abs(values["sweep_location"]) <= 1e-6
                and abs(values["t_over_c_root"] - spec.vtail.t_over_c) <= 1e-4
                and abs(values["t_over_c_tip"] - spec.vtail.t_over_c) <= 1e-4
                and abs(values["x_le_m"] - spec.vtail.x_le_m) <= 1e-4
                and abs(values["y_root_m"] - expected_fin_y[index]) <= 1e-4
                and abs(values["z_root_m"] - built["fin_attach"]["z_m"]) <= 1e-4
                and abs(values["x_rotation_deg"] - expected_fin_rotation[index]) <= 0.1
            )
        readback["vtail_count"] = len(fin_readback)
        readback["vtails"] = fin_readback
        readback["vtails_match"] = fin_ok

        auxiliary_ok = fin_ok and controls_ok
        if built["htail"] is not None:
            hid = built["htail"]
            htail_values = {
                "span_m": float(vsp.GetParmVal(hid, "TotalSpan", "WingGeom")),
                "root_chord_m": float(vsp.GetParmVal(hid, "Root_Chord", "XSec_1")),
                "tip_chord_m": float(vsp.GetParmVal(hid, "Tip_Chord", "XSec_1")),
                "sweep_deg": float(vsp.GetParmVal(hid, "Sweep", "XSec_1")),
                "sweep_location": float(
                    vsp.GetParmVal(hid, "Sweep_Location", "XSec_1")
                ),
                "t_over_c_root": float(
                    vsp.GetParmVal(hid, "ThickChord", "XSecCurve_0")
                ),
                "t_over_c_tip": float(vsp.GetParmVal(hid, "ThickChord", "XSecCurve_1")),
                "x_le_m": float(vsp.GetParmVal(hid, "X_Rel_Location", "XForm")),
                "z_m": float(vsp.GetParmVal(hid, "Z_Rel_Location", "XForm")),
                "incidence_deg": float(vsp.GetParmVal(hid, "Y_Rel_Rotation", "XForm")),
            }
            readback["htail"] = htail_values
            auxiliary_ok = auxiliary_ok and (
                _rel(htail_values["span_m"], spec.htail.span_m) <= 0.02
                and _rel(htail_values["root_chord_m"], spec.htail.root_chord_m) <= 0.02
                and _rel(
                    htail_values["tip_chord_m"],
                    spec.htail.root_chord_m * spec.htail.taper,
                )
                <= 0.02
                and abs(htail_values["sweep_deg"] - spec.htail.le_sweep_deg) <= 0.1
                and abs(htail_values["sweep_location"]) <= 1e-6
                and abs(htail_values["t_over_c_root"] - spec.htail.t_over_c) <= 1e-4
                and abs(htail_values["t_over_c_tip"] - spec.htail.t_over_c) <= 1e-4
                and abs(htail_values["x_le_m"] - spec.htail.x_le_m) <= 1e-4
                and abs(htail_values["z_m"] - spec.htail.z_m) <= 1e-4
                and abs(htail_values["incidence_deg"] - spec.htail.incidence_deg) <= 0.1
            )
        pod_readback = []
        expected_pod_count = (
            spec.engine.installation_count
            if spec.engine.installation == "external"
            else 0
        )
        pod_ok = len(built["engine_pods"]) == expected_pod_count
        for index, pod in enumerate(built["engine_pods"]):
            length = float(vsp.GetParmVal(pod, "Length", "Design"))
            fine_ratio = float(vsp.GetParmVal(pod, "FineRatio", "Design"))
            values = {
                "name": str(vsp.GetGeomName(pod)),
                "length_m": length,
                "diameter_m": 2.0 * length / max(fine_ratio, 1e-9),
                "x_center_m": float(vsp.GetParmVal(pod, "X_Rel_Location", "XForm"))
                + 0.5 * length,
                "y_m": float(vsp.GetParmVal(pod, "Y_Rel_Location", "XForm")),
                "z_m": float(vsp.GetParmVal(pod, "Z_Rel_Location", "XForm")),
            }
            pod_readback.append(values)
            pod_ok = pod_ok and (
                _rel(values["length_m"], spec.engine.length_m) <= 1e-4
                and _rel(values["diameter_m"], spec.engine.diameter_m) <= 1e-4
                and abs(values["x_center_m"] - float(spec.engine.x_m)) <= 1e-4
                and abs(values["y_m"] - built["engine_pod_positions"][index][0]) <= 1e-4
                and abs(values["z_m"] - spec.engine.z_m) <= 1e-4
            )
        readback["engine_pods"] = pod_readback
        readback["engine_pods_match"] = pod_ok
        auxiliary_ok = auxiliary_ok and pod_ok
        readback["auxiliary_matches"] = auxiliary_ok
        readback["matches_spec"] = (
            twist_ok
            and sections_ok
            and station_ok
            and auxiliary_ok
            and all(value <= 0.02 for value in readback["rel_err"].values())
        )
        if not readback["matches_spec"]:
            errors.append(f"geometry read-back mismatch: {readback}")
        return readback, errors
    except Exception as exc:
        return {"matches_spec": False, "error": str(exc)}, [f"readback: {exc}"]


def write_vsp3(spec: VehicleSpec, path: Path) -> dict[str, Any]:
    """Write a lightweight, read-back-verified OpenVSP session model."""
    vsp = _try_import_vsp()
    if vsp is None:
        return {"ok": False, "reason": "openvsp_import_failed"}
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    diagnostic = target.with_suffix(".vsp3.failed")
    if diagnostic.exists():
        diagnostic.unlink()
    with VSP_LOCK:
        built = _construct_model(vsp, spec, filename=target)
        prewrite_readback, prewrite_errors = _construction_readback(vsp, spec, built)
        vsp.Update()
        vsp.WriteVSPFile(str(target), vsp.SET_ALL)
        write_errors = _drain_vsp_errors(vsp)
        try:
            vsp.ClearVSPModel()
            vsp.ReadVSPFile(str(target))
            vsp.Update()
            built = _rebind_serialized_model_ids(vsp, built)
            readback, readback_errors = _construction_readback(vsp, spec, built)
        except Exception as exc:
            readback = {"matches_spec": False, "error": str(exc)}
            readback_errors = [f"reopen_readback: {exc}"]
        errors = [
            *built["errors"],
            *prewrite_errors,
            *write_errors,
            *readback_errors,
            *_drain_vsp_errors(vsp),
        ]
        verified = bool(
            target.is_file()
            and prewrite_readback.get("matches_spec")
            and readback.get("matches_spec")
            and not errors
        )
        diagnostic_path = None
        if not verified and target.exists():
            try:
                target.replace(diagnostic)
                diagnostic_path = str(diagnostic)
            except OSError as exc:
                errors.append(f"reopen_diagnostic_move: {exc}")
                try:
                    target.unlink(missing_ok=True)
                except OSError as unlink_exc:
                    errors.append(f"rejected_vsp3_remove: {unlink_exc}")
        return {
            "ok": verified,
            "vsp3": str(target) if verified else None,
            "diagnostic_vsp3": diagnostic_path,
            "geom_ids": {
                "fuselage": built["fuselage"],
                "wing": built["wing"],
                "control_surfaces": [
                    {
                        "id": control["id"],
                        "host": control["host"],
                        "subsurface_ids": [
                            item["subsurface_id"] for item in control["subsurfaces"]
                        ],
                    }
                    for control in built["control_surfaces"]
                ],
                "vtails": built["vtails"],
                "htail": built["htail"],
                "engine_pods": built["engine_pods"],
            },
            "prewrite_readback": prewrite_readback,
            "readback": readback,
            "errors": errors,
            "openvsp_version": vsp.GetVSPVersion(),
        }


def _failed_serialized_geometry_result(
    vsp,
    vsp3: Path,
    built: dict[str, Any],
    prewrite_readback: dict[str, Any],
    readback: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    """Fail closed without exposing a rejected VSP3 as a nominal artifact."""
    for stale in (
        vsp3.with_suffix(".stl"),
        vsp3.with_name(f"{vsp3.stem}_DegenGeom.csv"),
        *vsp3.parent.glob("component_*.stl"),
    ):
        try:
            stale.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"stale_geometry_remove: {stale}: {exc}")
    diagnostic = vsp3.with_suffix(".vsp3.failed")
    diagnostic_path = None
    try:
        if diagnostic.exists():
            diagnostic.unlink()
        if vsp3.exists():
            vsp3.replace(diagnostic)
            diagnostic_path = str(diagnostic)
    except OSError as exc:
        errors.append(f"reopen_diagnostic_move: {exc}")
        try:
            vsp3.unlink(missing_ok=True)
        except OSError as unlink_exc:
            errors.append(f"rejected_vsp3_remove: {unlink_exc}")
    return {
        "ok": False,
        "vsp3": None,
        "diagnostic_vsp3": diagnostic_path,
        "stl": None,
        "geom_ids": {
            "fuselage": None,
            "wing": None,
            "control_surfaces": [],
            "vtails": [],
            "htail": None,
            "engine_pods": [],
        },
        "fin_attach": built["fin_attach"],
        "prewrite_readback": prewrite_readback,
        "readback": readback,
        "stl_bbox": None,
        "mesh_checks": {
            "ok": False,
            "reason": "serialized VSP3 failed reopen/readback; no mesh exported",
        },
        "mass_props": {},
        "degen": None,
        "errors": errors,
        "openvsp_version": vsp.GetVSPVersion(),
    }


def _build_openvsp_model_locked(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    vsp = _try_import_vsp()
    if vsp is None:
        return {"ok": False, "reason": "openvsp_import_failed"}

    vsp3 = outdir / f"{spec.name}.vsp3"
    for stale in (
        vsp3,
        vsp3.with_suffix(".vsp3.failed"),
        vsp3.with_suffix(".stl"),
        vsp3.with_name(f"{vsp3.stem}_DegenGeom.csv"),
        *outdir.glob("component_*.stl"),
    ):
        stale.unlink(missing_ok=True)
    built = _construct_model(vsp, spec, filename=vsp3)
    errors = list(built["errors"])
    prewrite_readback, prewrite_errors = _construction_readback(vsp, spec, built)
    errors.extend(prewrite_errors)
    vsp.Update()
    vsp.WriteVSPFile(str(vsp3), vsp.SET_ALL)
    errors.extend(_drain_vsp_errors(vsp))
    try:
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(vsp3))
        vsp.Update()
        built = _rebind_serialized_model_ids(vsp, built)
        readback, readback_errors = _construction_readback(vsp, spec, built)
        errors.extend(readback_errors)
    except Exception as exc:
        errors.append(f"reopen_readback: {exc}")
        readback = {"matches_spec": False, "error": str(exc)}
        return _failed_serialized_geometry_result(
            vsp,
            vsp3,
            built,
            prewrite_readback,
            readback,
            errors,
        )
    if not (prewrite_readback.get("matches_spec") and readback.get("matches_spec")):
        return _failed_serialized_geometry_result(
            vsp,
            vsp3,
            built,
            prewrite_readback,
            readback,
            errors,
        )

    fid = built["fuselage"]
    wid = built["wing"]
    vtails = built["vtails"]
    hid = built["htail"]
    engine_pods = built["engine_pods"]
    fin_attach = built["fin_attach"]

    stl_path = outdir / f"{spec.name}.stl"
    try:
        vsp.ExportFile(str(stl_path), vsp.SET_ALL, vsp.EXPORT_STL)
    except Exception as exc:
        stl_path = None
        errors.append(f"stl_export: {exc}")

    mass_props = {}
    try:
        vsp.SetAnalysisInputDefaults("MassProp")
        rid = vsp.ExecAnalysis("MassProp")
        mass = vsp.GetDoubleResults(rid, "Total_Mass")
        cg = vsp.GetVec3dResults(rid, "Total_CG")
        mass_props = {
            "total_mass": float(mass[0]) if mass else None,
            "cg": [cg[0].x(), cg[0].y(), cg[0].z()] if cg else None,
        }
    except Exception as exc:
        try:
            vsp.ComputeMassProps(vsp.SET_ALL, 20, vsp.X_DIR)
            rid = vsp.FindLatestResultsID("MassProp")
            mass = vsp.GetDoubleResults(rid, "Total_Mass")
            mass_props = {"total_mass": float(mass[0]) if mass else None}
        except Exception as exc2:
            errors.append(f"massprops: {exc}; {exc2}")

    degen = None
    try:
        vsp.SetAnalysisInputDefaults("DegenGeom")
        vsp.ExecAnalysis("DegenGeom")
        # DegenGeom writes <vsp3-basename>_DegenGeom.csv next to the model.
        cand = outdir / f"{spec.name}_DegenGeom.csv"
        degen = str(cand) if cand.exists() else None
        if degen is None:
            errors.append("degen: expected _DegenGeom.csv not written")
    except Exception as exc:
        errors.append(f"degen: {exc}")

    stl_bbox = (
        _stl_bbox_check(stl_path, spec)
        if stl_path and Path(stl_path).exists()
        else None
    )

    # Mesh-truth verification: measure the exported tessellation against the
    # spec (per-component extents, fin verticality, attachment). Read-back
    # alone cannot catch a wrong rotation choice (QA audit F14/F15).
    from openair.geometry.mesh_checks import run_mesh_checks

    try:
        mesh_checks = run_mesh_checks(
            vsp,
            spec,
            {
                "fuselage": fid,
                "wing": wid,
                "vtails": vtails,
                "htail": hid,
                "engine_pods": engine_pods,
            },
            outdir,
            fin_z_attach_m=fin_attach["z_m"],
        )
    except Exception as exc:
        mesh_checks = {"ok": False, "error": str(exc)}

    return {
        "ok": vsp3.exists()
        and bool(readback.get("matches_spec"))
        and bool(stl_bbox and stl_bbox.get("ok"))
        and bool(mesh_checks.get("ok"))
        and not errors,
        "vsp3": str(vsp3) if vsp3.exists() else None,
        "stl": str(stl_path) if stl_path and Path(stl_path).exists() else None,
        "geom_ids": {
            "fuselage": fid,
            "wing": wid,
            "control_surfaces": [
                {
                    "id": control["id"],
                    "host": control["host"],
                    "subsurface_ids": [
                        item["subsurface_id"] for item in control["subsurfaces"]
                    ],
                }
                for control in built["control_surfaces"]
            ],
            "vtails": vtails,
            "htail": hid,
            "engine_pods": engine_pods,
        },
        "fin_attach": fin_attach,
        "prewrite_readback": prewrite_readback,
        "readback": readback,
        "stl_bbox": stl_bbox,
        "mesh_checks": mesh_checks,
        "mass_props": mass_props,
        "degen": degen,
        "errors": errors,
        "openvsp_version": vsp.GetVSPVersion(),
    }


def build_openvsp_model(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    """Build and verify the full OpenVSP geometry stage artifact."""
    with VSP_LOCK:
        return _build_openvsp_model_locked(spec, outdir)


def _expected_model_length_m(spec: VehicleSpec) -> float:
    """Axis-aligned x-extent of fuselage + wing planform."""
    w = spec.wing
    if w.sections is None:
        x_le = [w.x_le_root_m, w.x_le_at(1.0)]
        x_te = [w.x_le_root_m + w.root_chord_m, w.x_le_at(1.0) + w.tip_chord_m]
    else:
        x_le = [section.x_le_m for section in w.sections]
        x_te = [section.x_le_m + section.chord_m for section in w.sections]
    x_min = min(0.0, *x_le)
    x_max = max(spec.fuselage.length_m, *x_te)
    return x_max - x_min


def _stl_bbox_check(stl_path: Path | str, spec: VehicleSpec) -> dict[str, Any]:
    """Bounding box of the exported STL vs the spec envelope (±10%)."""
    import numpy as np

    mins = np.full(3, np.inf)
    maxs = np.full(3, -np.inf)
    try:
        with open(stl_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s.startswith("vertex"):
                    p = np.array([float(x) for x in s.split()[1:4]])
                    mins = np.minimum(mins, p)
                    maxs = np.maximum(maxs, p)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    size = maxs - mins
    want_len = spec.fuselage.length_m
    want_extent = _expected_model_length_m(spec)
    want_span = spec.wing.span_m
    ok = (
        abs(size[0] - want_extent) / max(want_extent, want_len) < 0.25
        and abs(size[1] - want_span) / want_span < 0.10
    )
    return {
        "ok": bool(ok),
        "size_xyz_m": [float(v) for v in size],
        "expected_length_m": want_len,
        "expected_x_extent_m": want_extent,
        "expected_span_m": want_span,
    }


def run_geometry_stage(spec: VehicleSpec, outdir: Path) -> dict[str, Any]:
    spec.assert_cross_model_invariants()
    outdir.mkdir(parents=True, exist_ok=True)
    mesh = generate_oas_rect_mesh(spec)
    mesh_path = save_mesh(outdir, mesh)
    planform = wing_planform_points(spec)
    pack = packing_report(spec, spec.mass.fuel_mass_kg)
    vsp_info = build_openvsp_model(spec, outdir)

    # Three-view rendered from the exported artifact (not the spec)
    threeview_path = None
    if vsp_info.get("stl"):
        from openair.reporting.plots import threeview_from_stl

        out_png = outdir / "threeview.png"
        if threeview_from_stl(
            Path(vsp_info["stl"]), out_png, title=f"{spec.name} — exported mesh"
        ):
            threeview_path = str(out_png)

    # Planform plot
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        pts = planform["planform_xy"]
        xs = [p[0] for p in pts] + [pts[0][0]]
        ys = [p[1] for p in pts] + [pts[0][1]]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(ys, xs, "k-")  # nose-up, y as horizontal
        ax.set_aspect("equal")
        ax.set_xlabel("y [m]")
        ax.set_ylabel("x [m] (aft)")
        ax.set_title(
            f"{spec.name} planform  S={spec.wing.area_m2:.2f} m²  AR={spec.wing.aspect_ratio:.2f}"
        )
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(outdir / "planform.png", dpi=120)
        plt.close(fig)
    except Exception:
        pass

    # Reference-model fidelity: when the concept carries a measured reference
    # mesh (designs/<concept>/reference/), score the exported artifact against
    # it. The check is evidence for the geometry-truth gate; for a
    # source-locked reproduction it also decides this stage's ``ok``.
    reference_fidelity: dict[str, Any] | None = None
    if vsp_info.get("stl"):
        try:
            from openair.reference.compare import (
                compare_reference,
                reference_dir_for_outdir,
            )

            reference_dir = reference_dir_for_outdir(outdir)
            if reference_dir is not None:
                reference_fidelity = compare_reference(
                    spec,
                    outdir,
                    stl_path=vsp_info["stl"],
                    component_stls=(vsp_info.get("mesh_checks") or {}).get(
                        "component_stls"
                    )
                    or {},
                    reference_dir=reference_dir,
                )
        except Exception as exc:  # pragma: no cover - depends on artifacts
            reference_fidelity = {"ok": False, "available": True, "error": str(exc)}

    # If OpenVSP ran, the model must match the spec; mesh-only mode is
    # acceptable only when the API is unavailable, not when it disagrees.
    vsp_attempted = vsp_info.get("reason") != "openvsp_import_failed"
    geometry_ok = pack["ok"] and (not vsp_attempted or bool(vsp_info.get("ok")))
    reproduction = bool(
        spec.sketch is not None and spec.sketch.treatment == "reproduction"
    )
    if (
        reproduction
        and reference_fidelity is not None
        and reference_fidelity.get("available")
    ):
        geometry_ok = geometry_ok and bool(reference_fidelity.get("ok"))
    result = {
        "ok": geometry_ok,
        "mesh_shape": list(mesh.shape),
        "mesh_path": str(mesh_path),
        "wing_area_m2": spec.wing.area_m2,
        "aspect_ratio": spec.wing.aspect_ratio,
        "mac_m": spec.wing.mac_m,
        "x_ac_m": spec.wing.x_ac_m,
        "wing": {
            "planform_mode": planform["planform_mode"],
            "sections": planform["sections"],
            "equivalent_trapezoid": {
                "root_chord_m": spec.wing.root_chord_m,
                "taper": spec.wing.taper,
                "le_sweep_deg": spec.wing.le_sweep_deg,
                "dihedral_deg": spec.wing.dihedral_deg,
                "x_le_root_m": spec.wing.x_le_root_m,
                "z_root_m": spec.wing.z_root_m,
            },
        },
        "planform": planform,
        "packing": pack,
        "openvsp": vsp_info,
        "threeview": threeview_path,
        "backend": "openvsp" if vsp_info.get("ok") else "mesh_only",
    }
    if reference_fidelity is not None:
        reference_fidelity["gates_stage_ok"] = reproduction
        result["reference_fidelity"] = reference_fidelity
    return result
