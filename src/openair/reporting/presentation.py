"""Self-contained interactive HTML presentation and PDF executive brief."""

from __future__ import annotations

import argparse
import base64
import html
import importlib.metadata
import json
import platform
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from markdown_it import MarkdownIt

from openair.io import dump_json, load_yaml
from openair.paths import optimized_design_for, resolve_design, results_dir_for
from openair.reporting.gates import build_gate_feedback
from openair.reporting.plots import (
    cg_np_diagram,
    comparison_bars,
    mass_bar,
)
from openair.schemas import VehicleSpec
from openair.theme import REPORT_CSS


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    return data if isinstance(data, dict) else {}


def _spec(path: Path) -> VehicleSpec:
    return VehicleSpec.model_validate(load_yaml(path))


def _topology_label(spec: VehicleSpec) -> str:
    return (
        "UAV with conventional horizontal tail"
        if spec.htail.span_m > 0.05
        else "tailless UAV"
    )


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if abs(float(value)) >= 100:
            return f"{float(value):,.1f}"
        return f"{float(value):.{digits}f}"
    if isinstance(value, (list, dict)):
        text = json.dumps(value, separators=(",", ":"))
        return text if len(text) <= 100 else text[:97] + "…"
    return str(value)


def _image_uri(path: Path) -> str | None:
    if not path.exists():
        return None
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _load_triangles(path: Path) -> np.ndarray:
    """Read binary or ASCII STL into an ``(n, 3, 3)`` triangle array."""
    raw = path.read_bytes()
    if len(raw) >= 84:
        count = struct.unpack_from("<I", raw, 80)[0]
        if count > 0 and 84 + count * 50 == len(raw):
            triangles = np.empty((count, 3, 3), dtype=np.float64)
            offset = 84
            for idx in range(count):
                record = struct.unpack_from("<12fH", raw, offset)
                triangles[idx] = np.asarray(record[3:12]).reshape(3, 3)
                offset += 50
            return triangles

    vertices: list[list[float]] = []
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        fields = line.strip().split()
        if len(fields) == 4 and fields[0].lower() == "vertex":
            vertices.append([float(fields[1]), float(fields[2]), float(fields[3])])
    if not vertices or len(vertices) % 3:
        raise ValueError(f"STL has no complete triangles: {path}")
    return np.asarray(vertices, dtype=np.float64).reshape(-1, 3, 3)


def _mesh_payload(path: Path) -> dict[str, Any]:
    triangles = _load_triangles(path)
    mins = triangles.reshape(-1, 3).min(axis=0)
    maxs = triangles.reshape(-1, 3).max(axis=0)
    center = 0.5 * (mins + maxs)
    scale = max(float(np.max(maxs - mins)), 1e-9)

    # WebGL axes: X = aircraft span, Y = vertical, Z = nose-to-tail depth.
    normalized = (triangles - center) * (2.0 / scale)
    positions = normalized[:, :, [1, 2, 0]]
    positions[:, :, 2] *= -1.0

    edges_a = positions[:, 1] - positions[:, 0]
    edges_b = positions[:, 2] - positions[:, 0]
    face_normals = np.cross(edges_a, edges_b)
    lengths = np.linalg.norm(face_normals, axis=1)
    face_normals /= np.maximum(lengths[:, None], 1e-12)
    normals = np.repeat(face_normals[:, None, :], 3, axis=1)

    position_bytes = np.asarray(positions, dtype="<f4").reshape(-1).tobytes()
    normal_bytes = np.asarray(normals, dtype="<f4").reshape(-1).tobytes()
    return {
        "triangles": int(len(triangles)),
        "positions": base64.b64encode(position_bytes).decode("ascii"),
        "normals": base64.b64encode(normal_bytes).decode("ascii"),
        "bbox_min_m": [float(v) for v in mins],
        "bbox_max_m": [float(v) for v in maxs],
        "size_m": [float(v) for v in maxs - mins],
        "source": path.name,
    }


def _performance(
    baseline_sizing: dict[str, Any],
    baseline_mdo: dict[str, Any],
    optimized_aero: dict[str, Any],
    optimized_report: dict[str, Any],
    optimized_spec: VehicleSpec,
) -> tuple[dict[str, float], dict[str, float]]:
    base_dash = (baseline_sizing.get("dash") or {}).get("tas_mps", 0.0)
    base = {
        "dash_kmh": float(base_dash) * 3.6,
        "endurance_hr": float(baseline_sizing.get("endurance_s", 0.0)) / 3600.0,
        "mtow_kg": float(baseline_sizing.get("mtow_kg", 0.0)),
        "fuel_kg": float(baseline_sizing.get("fuel_kg", 0.0)),
        "span_m": float(baseline_sizing.get("span_m", optimized_spec.wing.span_m)),
        "lod": float((baseline_sizing.get("cruise") or {}).get("lod", 0.0)),
    }
    best = baseline_mdo.get("best") or {}
    desires = optimized_report.get("desires") or {}
    aero_dash = optimized_aero.get("dash") or {}
    dash_mps = float(
        desires.get("dash_mps")
        or best.get("dash_mps")
        or aero_dash.get("tas_mps")
        or 0.0
    )
    opt = {
        "dash_kmh": dash_mps * 3.6,
        "endurance_hr": float(
            desires.get("endurance_hr_pred")
            or (float(best.get("endurance_s", 0.0)) / 3600.0)
        ),
        "mtow_kg": float(
            desires.get("mtow_kg")
            or optimized_aero.get("mtow_kg")
            or best.get("mtow_kg")
            or 0.0
        ),
        "fuel_kg": float(
            desires.get("fuel_kg")
            or optimized_spec.mass.fuel_mass_kg
            or (best.get("dvs") or {}).get("fuel")
        ),
        "span_m": float(
            (best.get("dvs") or {}).get("span") or optimized_spec.wing.span_m
        ),
        "lod": float(
            desires.get("cruise_lod")
            or (optimized_aero.get("cruise") or {}).get("lod")
            or best.get("lod")
            or 0.0
        ),
    }
    return base, opt


def _trim_setting(aero: dict[str, Any]) -> tuple[str, float | None]:
    trim = aero.get("trim") or {}
    control = str(trim.get("control") or "none")
    if control == "tail_incidence":
        value = trim.get("tail_incidence_trim_deg")
    elif control == "elevon":
        value = trim.get("elevon_trim_deg")
    else:
        value = trim.get("twist_tip_trim_deg")
    return control, (float(value) if value is not None else None)


def _baseline_findings(
    spec: VehicleSpec,
    sizing: dict[str, Any],
    aero: dict[str, Any],
    structures: dict[str, Any],
) -> list[str]:
    """Summarize what the as-drawn aircraft did, from baseline artifacts only."""
    findings: list[str] = []
    stability = aero.get("stability") or {}
    sm = stability.get("sm_full")
    band = stability.get("band") or []
    if sm is not None and len(band) == 2:
        position = (
            "inside"
            if band[0] <= float(sm) <= band[1]
            else ("above" if float(sm) > band[1] else "below")
        )
        neutral_point = stability.get("x_np_measured_m") or stability.get("x_np_m")
        findings.append(
            f"Static margin {float(sm):.3f} MAC sits {position} the "
            f"{band[0]:.2f}–{band[1]:.2f} design band"
            + (
                f" (measured NP {float(neutral_point):.3f} m)"
                if neutral_point is not None
                else ""
            )
            + "."
        )
    control, trim_value = _trim_setting(aero)
    trim = aero.get("trim") or {}
    if trim_value is not None:
        spec_value = trim.get(f"{control}_spec_deg")
        findings.append(
            f"Pitch trim closes with {control.replace('_', ' ')} at "
            f"{trim_value:+.2f}°"
            + (" (trailing edge up positive, twist frozen)" if control == "elevon" else "")
            + (
                f" against a {float(spec_value):+.2f}° spec setting"
                if spec_value is not None
                else ""
            )
            + (
                f" within the {trim['elevon_travel_deg'][0]:+.0f}…"
                f"{trim['elevon_travel_deg'][1]:+.0f}° travel"
                if control == "elevon" and trim.get("elevon_travel_deg")
                else ""
            )
            + ("." if trim.get("converged") else " (not converged).")
        )
    balance = aero.get("balance") or sizing.get("balance") or {}
    vstall = balance.get("vstall_mps")
    if vstall is not None:
        findings.append(
            f"Stall {float(vstall):.1f} m/s against the "
            f"{spec.mission.stall_speed_max_mps:.0f} m/s requirement, from "
            f"effective CLmax {float(balance.get('cl_max_effective') or spec.mission.cl_max):.2f}."
        )
    dash = sizing.get("dash") or aero.get("dash") or {}
    if dash.get("tas_mps") is not None:
        mach = dash.get("mach")
        findings.append(
            f"Thrust-limited dash {float(dash['tas_mps']):.1f} m/s"
            + (f" (M {float(mach):.2f}" if mach is not None else "(")
            + f" vs cap {spec.mission.dash_mach_cap:.2f})."
        )
    if spec.mission.endurance_required and sizing.get("endurance_s") is not None:
        achieved = float(sizing["endurance_s"])
        target = float(spec.mission.endurance_s)
        findings.append(
            f"Endurance {achieved:.0f} s against the {target:.0f} s target "
            f"({'met' if achieved >= target else 'short'})."
        )
    positive = structures.get("positive_g") or {}
    negative = structures.get("negative_g") or {}
    if positive.get("failure") is not None and negative.get("failure") is not None:
        findings.append(
            f"Wingbox at ±limit load: +g KS {float(positive['failure']):.2f}, "
            f"−g KS {float(negative['failure']):.2f} "
            "(negative values are margin)."
        )
    return findings


def _evolution_rows(
    baseline_spec: VehicleSpec,
    optimized_spec: VehicleSpec,
    base_metrics: dict[str, float],
    opt_metrics: dict[str, float],
    baseline_aero: dict[str, Any],
    optimized_aero: dict[str, Any],
    endurance_applicable: bool,
) -> list[list[str]]:
    rows: list[list[str]] = []

    def numeric(
        label: str,
        base: Any,
        opt: Any,
        unit: str = "",
        digits: int = 3,
        percent: bool = True,
    ) -> None:
        if base is None or opt is None:
            return
        base_f, opt_f = float(base), float(opt)
        suffix = f" {unit}" if unit else ""
        delta = opt_f - base_f
        change = f"{delta:+.{digits}f}{suffix}"
        if percent and abs(base_f) > 1e-9:
            change += f" ({delta / base_f * 100.0:+.1f}%)"
        rows.append(
            [
                label,
                f"{base_f:.{digits}f}{suffix}",
                f"{opt_f:.{digits}f}{suffix}",
                change if abs(delta) > 10.0 ** (-digits) / 2 else "unchanged",
            ]
        )

    numeric("Wing span", baseline_spec.wing.span_m, optimized_spec.wing.span_m, "m")
    numeric("Wing area", baseline_spec.wing.area_m2, optimized_spec.wing.area_m2, "m²")
    numeric(
        "Aspect ratio",
        baseline_spec.wing.aspect_ratio,
        optimized_spec.wing.aspect_ratio,
        digits=2,
    )
    numeric(
        "Taper",
        baseline_spec.wing.taper,
        optimized_spec.wing.taper,
        digits=3,
        percent=False,
    )
    numeric(
        "LE sweep",
        baseline_spec.wing.le_sweep_deg,
        optimized_spec.wing.le_sweep_deg,
        "deg",
        digits=1,
        percent=False,
    )
    rows.append(
        [
            "Airfoil",
            f"NACA {baseline_spec.wing.airfoil}",
            f"NACA {optimized_spec.wing.airfoil}",
            (
                "changed"
                if baseline_spec.wing.airfoil != optimized_spec.wing.airfoil
                else "unchanged"
            ),
        ]
    )
    numeric(
        "Thickness t/c",
        baseline_spec.wing.t_over_c,
        optimized_spec.wing.t_over_c,
        digits=3,
        percent=False,
    )
    numeric(
        "Tip twist",
        baseline_spec.wing.twist_tip_deg,
        optimized_spec.wing.twist_tip_deg,
        "deg",
        digits=2,
        percent=False,
    )
    numeric("MTOW", base_metrics.get("mtow_kg"), opt_metrics.get("mtow_kg"), "kg", 2)
    numeric("Fuel", base_metrics.get("fuel_kg"), opt_metrics.get("fuel_kg"), "kg", 2)
    numeric(
        "Dash speed",
        base_metrics.get("dash_kmh"),
        opt_metrics.get("dash_kmh"),
        "km/h",
        0,
    )
    if endurance_applicable:
        numeric(
            "Endurance",
            base_metrics.get("endurance_hr"),
            opt_metrics.get("endurance_hr"),
            "h",
            2,
        )
    numeric("Cruise L/D", base_metrics.get("lod"), opt_metrics.get("lod"), digits=2)
    numeric(
        "Stall speed",
        (baseline_aero.get("balance") or {}).get("vstall_mps"),
        (optimized_aero.get("balance") or {}).get("vstall_mps"),
        "m/s",
        1,
    )
    numeric(
        "Static margin (full)",
        (baseline_aero.get("stability") or {}).get("sm_full"),
        (optimized_aero.get("stability") or {}).get("sm_full"),
        "MAC",
        3,
        percent=False,
    )
    base_control, base_trim = _trim_setting(baseline_aero)
    opt_control, opt_trim = _trim_setting(optimized_aero)
    if base_control == opt_control and base_control != "none":
        numeric(
            f"Trim {base_control.replace('_', ' ')}",
            base_trim,
            opt_trim,
            "deg",
            2,
            percent=False,
        )
    return rows


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BRIEF_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def _brief_html(text: str) -> str:
    """Render a concept ``brief.md`` (or spec notes) to HTML."""
    cleaned = _HTML_COMMENT.sub("", text).strip()
    if not cleaned:
        return ""
    rendered = _BRIEF_MARKDOWN.render(cleaned)
    rendered = rendered.replace("<table>", '<div class="table-wrap"><table>')
    rendered = rendered.replace("</table>", "</table></div>")
    return f'<div class="brief">{rendered}</div>'


def _table_rows(rows: list[list[str]], statuses: list[bool] | None = None) -> str:
    body: list[str] = []
    for index, cells in enumerate(rows):
        status_class = ""
        if statuses is not None:
            status_class = " pass-row" if statuses[index] else " fail-row"
        body.append(
            f'<tr class="{status_class.strip()}">'
            + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells)
            + "</tr>"
        )
    return "".join(body)


def _chart_cards(paths: list[tuple[str, str, Path, str]]) -> str:
    cards: list[str] = []
    for title, kicker, path, caption in paths:
        uri = _image_uri(path)
        if not uri:
            continue
        cards.append(
            '<figure class="chart-card">'
            f'<div class="eyebrow">{html.escape(kicker)}</div>'
            f"<h3>{html.escape(title)}</h3>"
            f'<img src="{uri}" alt="{html.escape(title)}">'
            f"<figcaption>{html.escape(caption)}</figcaption>"
            "</figure>"
        )
    return "".join(cards)


def _versions(openvsp_version: str | None) -> list[tuple[str, str]]:
    packages = [
        ("Python", platform.python_version()),
        ("OpenVSP", openvsp_version or "not recorded"),
    ]
    for display, package in (
        ("OpenMDAO", "openmdao"),
        ("OpenAeroStruct", "openaerostruct"),
        ("Pydantic", "pydantic"),
        ("NumPy", "numpy"),
        ("Matplotlib", "matplotlib"),
    ):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = "not installed"
        packages.append((display, version))
    return packages


VIEWER_SCRIPT = r"""
<script>
const meshPayload = @@MESH_PAYLOAD@@;
(() => {
  const canvas = document.getElementById("mesh-canvas");
  const notice = document.getElementById("viewer-notice");
  const gl = canvas.getContext("webgl", {antialias:true, alpha:false});
  if (!gl) {
    notice.textContent = "WebGL is unavailable. Use the artifact-derived three-view below.";
    return;
  }
  const decodeFloats = (encoded) => {
    const raw = atob(encoded);
    const bytes = new Uint8Array(raw.length);
    for (let i=0; i<raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return new Float32Array(bytes.buffer);
  };
  const positions = decodeFloats(meshPayload.positions);
  const normals = decodeFloats(meshPayload.normals);
  const edges = new Float32Array(meshPayload.triangles * 18);
  for (let tri=0; tri<meshPayload.triangles; tri++) {
    const p = tri * 9, e = tri * 18;
    const pairs = [[0,3],[3,6],[6,0]];
    for (let k=0; k<3; k++) {
      edges.set(positions.subarray(p+pairs[k][0], p+pairs[k][0]+3), e+k*6);
      edges.set(positions.subarray(p+pairs[k][1], p+pairs[k][1]+3), e+k*6+3);
    }
  }
  const compile = (kind, source) => {
    const shader = gl.createShader(kind);
    gl.shaderSource(shader, source); gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
    return shader;
  };
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl.VERTEX_SHADER, `
    attribute vec3 aPosition;
    attribute vec3 aNormal;
    uniform mat4 uMVP;
    uniform mat4 uModel;
    varying vec3 vNormal;
    void main() {
      vNormal = normalize(mat3(uModel) * aNormal);
      gl_Position = uMVP * vec4(aPosition, 1.0);
    }`));
  gl.attachShader(program, compile(gl.FRAGMENT_SHADER, `
    precision mediump float;
    varying vec3 vNormal;
    uniform bool uWire;
    void main() {
      if (uWire) { gl_FragColor = vec4(0.78, 0.90, 0.94, 0.94); return; }
      vec3 n = normalize(vNormal);
      vec3 light = normalize(vec3(-0.35, 0.75, 0.65));
      float diffuse = max(dot(n, light), 0.0);
      float rim = pow(1.0 - abs(n.z), 2.0);
      vec3 base = vec3(0.20, 0.64, 0.76);
      gl_FragColor = vec4(base * (0.42 + 0.58*diffuse) + 0.15*rim, 1.0);
    }`));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
  gl.useProgram(program);

  const buffer = (values) => {
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, values, gl.STATIC_DRAW); return b;
  };
  const posBuffer = buffer(positions), normalBuffer = buffer(normals), edgeBuffer = buffer(edges);
  const aPosition = gl.getAttribLocation(program, "aPosition");
  const aNormal = gl.getAttribLocation(program, "aNormal");
  const uMVP = gl.getUniformLocation(program, "uMVP");
  const uModel = gl.getUniformLocation(program, "uModel");
  const uWire = gl.getUniformLocation(program, "uWire");

  const multiply = (a,b) => {
    const out = new Float32Array(16);
    for (let col=0; col<4; col++) for (let row=0; row<4; row++) {
      let value=0;
      for (let k=0; k<4; k++) value += a[k*4+row] * b[col*4+k];
      out[col*4+row]=value;
    }
    return out;
  };
  const perspective = (fov, aspect, near, far) => {
    const f=1/Math.tan(fov/2), nf=1/(near-far);
    return new Float32Array([f/aspect,0,0,0, 0,f,0,0, 0,0,(far+near)*nf,-1, 0,0,2*far*near*nf,0]);
  };
  const translate = (z) => new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,z,1]);
  const rotateX = (a) => {
    const c=Math.cos(a),s=Math.sin(a);
    return new Float32Array([1,0,0,0, 0,c,s,0, 0,-s,c,0, 0,0,0,1]);
  };
  const rotateY = (a) => {
    const c=Math.cos(a),s=Math.sin(a);
    return new Float32Array([c,0,-s,0, 0,1,0,0, s,0,c,0, 0,0,0,1]);
  };
  let yaw=-0.65, pitch=-0.30, distance=2.75, wire=false, dragging=false, px=0, py=0;
  const resize = () => {
    const dpr=Math.min(window.devicePixelRatio || 1, 2);
    const width=Math.max(1, Math.floor(canvas.clientWidth*dpr));
    const height=Math.max(1, Math.floor(canvas.clientHeight*dpr));
    if (canvas.width!==width || canvas.height!==height) {canvas.width=width;canvas.height=height;}
    gl.viewport(0,0,width,height);
  };
  const render = () => {
    resize();
    gl.enable(gl.DEPTH_TEST);
    gl.clearColor(0.025,0.055,0.070,1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const model=multiply(rotateY(yaw),rotateX(pitch));
    const view=translate(-distance);
    const projection=perspective(Math.PI/4,canvas.width/canvas.height,0.1,100);
    gl.uniformMatrix4fv(uModel,false,model);
    gl.uniformMatrix4fv(uMVP,false,multiply(projection,multiply(view,model)));
    gl.uniform1i(uWire,wire ? 1 : 0);
    gl.bindBuffer(gl.ARRAY_BUFFER,wire ? edgeBuffer : posBuffer);
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition,3,gl.FLOAT,false,0,0);
    if (wire) {
      gl.disableVertexAttribArray(aNormal); gl.vertexAttrib3f(aNormal,0,0,1);
      gl.drawArrays(gl.LINES,0,edges.length/3);
    } else {
      gl.bindBuffer(gl.ARRAY_BUFFER,normalBuffer);
      gl.enableVertexAttribArray(aNormal);
      gl.vertexAttribPointer(aNormal,3,gl.FLOAT,false,0,0);
      gl.drawArrays(gl.TRIANGLES,0,positions.length/3);
    }
    requestAnimationFrame(render);
  };
  canvas.addEventListener("pointerdown",(event)=>{dragging=true;px=event.clientX;py=event.clientY;canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener("pointermove",(event)=>{if(!dragging)return;yaw+=(event.clientX-px)*0.008;pitch+=(event.clientY-py)*0.008;pitch=Math.max(-1.45,Math.min(1.45,pitch));px=event.clientX;py=event.clientY;});
  canvas.addEventListener("pointerup",()=>dragging=false);
  canvas.addEventListener("pointercancel",()=>dragging=false);
  canvas.addEventListener("wheel",(event)=>{event.preventDefault();distance=Math.max(2.15,Math.min(7,distance+event.deltaY*0.003));},{passive:false});
  document.getElementById("wire-toggle").addEventListener("click",()=>{wire=!wire;document.getElementById("wire-toggle").textContent=wire?"Shaded":"Wireframe";});
  document.getElementById("view-reset").addEventListener("click",()=>{yaw=-0.65;pitch=-0.30;distance=2.75;});
  const size=meshPayload.size_m;
  notice.textContent=`${meshPayload.triangles.toLocaleString()} triangles · ${size[0].toFixed(2)} × ${size[1].toFixed(2)} × ${size[2].toFixed(2)} m · drag to orbit · wheel to zoom`;
  render();
})();
</script>
"""


PAGE_TEMPLATE = (
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@ · Design review</title>
<style>
"""
    + REPORT_CSS
    + """
</style>
</head>
<body>
<header class="topbar"><div class="wrap"><div class="brand">open-air · concept review</div><nav><a href="#executive">Executive</a><a href="#evidence">Evidence</a><a href="#evolution">Evolution</a><a href="#verification">V&amp;V</a><a href="#engineering">Engineering</a></nav></div></header>
<main>
<section class="hero"><div class="wrap hero-grid">
  <div>
    <div class="eyebrow">Executive design review · @@DATE@@</div>
    <h1>@@TITLE@@</h1>
    <p class="deck">@@DECK@@</p>
    <div class="verdict @@VERDICT_CLASS@@"><span class="dot"></span>@@VERDICT@@</div>
    <div class="stat-row">@@STATS@@</div>
  </div>
  <div class="viewer-shell">
    <canvas id="mesh-canvas" aria-label="Interactive 3D view of exported optimized STL"></canvas>
    <div class="viewer-tools"><button id="wire-toggle">Wireframe</button><button id="view-reset">Reset view</button></div>
    <div id="viewer-notice">Loading embedded mesh…</div>
  </div>
</div></section>

<section id="executive"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">01 · Decision view</div><h2>Mission fit and flight-worthiness</h2></div><p>Headline values come from the optimized aircraft’s own artifacts. Every gate below carries one-line evidence and a source path; the green state is not inferred from a stage’s top-level flag alone.</p></div>
  <div class="outcome-banner @@VERDICT_CLASS@@">
    <div class="outcome-status"><span class="dot"></span>@@OUTCOME_TITLE@@</div>
    <p class="outcome-text">@@OUTCOME_TEXT@@</p>
    <p class="outcome-meta">Concept source: designs/@@CONCEPT@@/design.yaml · Optimized spec: results/@@CONCEPT@@/optimized/design.yaml</p>
  </div>
  <div class="brief-col">@@BRIEF@@</div>
  <h3 style="margin-top:34px">Requirements scorecard</h3>
  <table class="score"><thead><tr><th>Requirement</th><th>Target</th><th>Predicted</th><th>Verdict</th></tr></thead><tbody>@@SCORECARD@@</tbody></table>
  <div class="gates">@@GATES@@</div>
</div></section>

<section id="evidence" class="alt"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">02 · Visual evidence</div><h2>Artifact, performance, loads, and margins</h2></div><p>The first figure and interactive hero are rendered from the exported STL itself. The remaining figures expose the numerical story: what changed, where drag and mass live, and how close the design sits to its constraints.</p></div>
  <div class="charts">@@CHARTS@@</div>
</div></section>

<section id="evolution"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">03 · Design evolution</div><h2>From source or sketch to delivered design</h2></div><p>The baseline is the aircraft as drawn; the optimizer answers what it presented. Both columns below are read from their own phase artifacts — the two phases are different aircraft and are never mixed inside one number. The delivered configuration is checked by a separate OAS solve; stability evidence is labeled by method.</p></div>
  <div class="split">
    <div>@@BASELINE_FIG@@</div>
    <div class="card"><div class="eyebrow">Baseline phase evidence</div><h3>What the baseline presented</h3><ul class="assumptions">@@BASELINE_FINDINGS@@</ul><p class="meta">Evidence: results/@@CONCEPT@@/baseline/{aero,sizing,structures}.json</p></div>
  </div>
  <h3 style="margin-top:36px">What the optimizer changed, and the effect</h3>
  <table class="score"><thead><tr><th>Quantity</th><th>Baseline</th><th>Optimized</th><th>Change</th></tr></thead><tbody>@@DELTA_ROWS@@</tbody></table>
  <div class="timeline" style="margin-top:46px">@@TIMELINE@@</div>
  <div class="split" style="margin-top:24px"><div><h3>Delivery starts</h3><div class="table-scroll"><table class="score"><thead><tr><th>Start</th><th>Dash</th><th>Endurance</th><th>MTOW</th><th>Feasible</th></tr></thead><tbody>@@MDO_STARTS@@</tbody></table></div></div><div><h3>Static-margin closure</h3><table class="score"><thead><tr><th>Attempt</th><th>Internal band</th><th>Evaluated full / reserve</th><th>Verdict</th></tr></thead><tbody>@@SM_CAL@@</tbody></table></div></div>
</div></section>

<section id="verification" class="alt"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">04 · Verification &amp; validation</div><h2>Cross-tool evidence, with convergence honesty</h2></div><p>Analytical identities, OAS comparisons, VSPAERO, artifact-level geometry checks, and stretch solvers test different failure modes. TACS and SU2 are shown as calibration data—not promoted into certification evidence.</p></div>
  <table class="score"><thead><tr><th>Check</th><th>Class</th><th>Observed</th><th>Reference</th><th>Verdict</th></tr></thead><tbody>@@VV_ROWS@@</tbody></table>
  <div class="cards" style="margin-top:24px">@@VV_CARDS@@</div>
</div></section>

<section id="engineering"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">05 · Engineering appendix</div><h2>Configuration, stations, tools, and known limits</h2></div><p>This section preserves the details needed to challenge or reproduce the design. Values are generated from the delivered optimized YAML and same-directory stage outputs.</p></div>
  <div class="split"><div><h3>Configuration</h3><table class="score"><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>@@CONFIG_ROWS@@</tbody></table></div><div><h3>Balance stations at full fuel</h3><table class="score"><thead><tr><th>Item</th><th>Mass</th><th>x station</th></tr></thead><tbody>@@BALANCE_ROWS@@</tbody></table></div></div>
  <div class="split" style="margin-top:28px"><div class="card"><h3>Pinned execution stack</h3><table class="score"><tbody>@@VERSIONS@@</tbody></table><p class="meta">Methodology: <a href="../../docs/guidebook/00-qa-workflow.md">AERO QA workflow</a> · <a href="../../docs/guidebook/04-openmdao.md">MDO</a> · <a href="../../docs/guidebook/03-openaerostruct.md">OAS</a> · <a href="../../docs/guidebook/01-openvsp.md">OpenVSP</a></p></div><div class="card assumptions"><h3>Assumptions and limitations</h3><ul>@@LIMITS@@</ul></div></div>
  <details class="card" style="margin-top:24px"><summary>Full optimized VehicleSpec YAML</summary><pre>@@SPEC_YAML@@</pre></details>
</div></section>
</main>
<footer><div class="wrap">Generated by open-air from immutable concept input and phase-local evidence · @@GENERATED@@</div></footer>
@@VIEWER@@
</body></html>
"""
)


def _pdf_brief(
    path: Path,
    title: str,
    metrics: dict[str, float],
    gates: list[dict[str, Any]],
    validation: dict[str, Any],
    images: dict[str, Path],
    spec: VehicleSpec,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    def add_image(fig: Any, image_path: Path | None, box: list[float]) -> None:
        if not image_path or not image_path.exists():
            return
        ax = fig.add_axes(box)
        ax.imshow(mpimg.imread(image_path))
        ax.axis("off")

    with PdfPages(path) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27), facecolor="#082631")
        fig.text(
            0.06,
            0.90,
            "OPEN-AIR · EXECUTIVE DESIGN REVIEW",
            color="#e96f3d",
            fontsize=11,
            weight="bold",
        )
        fig.text(0.06, 0.79, title, color="white", fontsize=31, weight="bold")
        fig.text(
            0.06,
            0.72,
            "Verified delivered configuration · interactive mesh available in report.html",
            color="#c7dbe0",
            fontsize=13,
        )
        add_image(fig, images.get("threeview"), [0.40, 0.11, 0.56, 0.55])
        y = 0.56
        endurance_value = (
            f"{metrics['endurance_hr']:.2f} h"
            if spec.mission.endurance_required
            else "not claimed"
        )
        for label, value in (
            ("Dash speed", f"{metrics['dash_kmh']:.0f} km/h"),
            ("Endurance", endurance_value),
            ("Payload", f"{spec.mission.payload_kg:.1f} kg"),
            ("MTOW", f"{metrics['mtow_kg']:.1f} kg"),
        ):
            fig.text(0.07, y, value, color="white", fontsize=22, weight="bold")
            fig.text(0.07, y - 0.035, label.upper(), color="#8fb3bd", fontsize=8)
            y -= 0.105
        pdf.savefig(fig, facecolor=fig.get_facecolor())
        plt.close(fig)

        fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
        fig.text(
            0.055,
            0.92,
            "Flight-worthiness gate review",
            fontsize=23,
            weight="bold",
            color="#102a34",
        )
        for idx, gate in enumerate(gates):
            col, row = idx // 6, idx % 6
            x, y = 0.06 + col * 0.47, 0.82 - row * 0.12
            color = "#287a52" if gate["ok"] else "#b34235"
            fig.text(x, y, "●", color=color, fontsize=16)
            fig.text(
                x + 0.025,
                y + 0.002,
                gate["name"],
                fontsize=11,
                weight="bold",
                color="#102a34",
            )
            fig.text(
                x + 0.025,
                y - 0.032,
                gate["evidence"][:78],
                fontsize=7.5,
                color="#58707a",
                wrap=True,
            )
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
        fig.text(
            0.055,
            0.93,
            "Performance and aerodynamic evidence",
            fontsize=22,
            weight="bold",
            color="#102a34",
        )
        add_image(fig, images.get("comparison"), [0.04, 0.48, 0.92, 0.40])
        add_image(fig, images.get("polar"), [0.10, 0.06, 0.38, 0.36])
        add_image(fig, images.get("drag"), [0.54, 0.06, 0.38, 0.36])
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
        fig.text(
            0.055,
            0.93,
            "Balance and structural margins",
            fontsize=22,
            weight="bold",
            color="#102a34",
        )
        add_image(fig, images.get("balance"), [0.05, 0.52, 0.90, 0.34])
        add_image(fig, images.get("margins"), [0.08, 0.08, 0.40, 0.36])
        add_image(fig, images.get("mass"), [0.52, 0.08, 0.42, 0.36])
        pdf.savefig(fig)
        plt.close(fig)

        fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
        fig.text(
            0.055,
            0.92,
            "Verification summary and engineering limits",
            fontsize=22,
            weight="bold",
            color="#102a34",
        )
        fig.text(
            0.06,
            0.855,
            f"Validation core: {validation.get('core_passed', 0)}/{validation.get('core_total', 0)} · "
            f"all recorded checks: {validation.get('passed', 0)}/{validation.get('total', 0)}",
            fontsize=13,
            color="#287a52" if validation.get("ok") else "#b34235",
            weight="bold",
        )
        checks = validation.get("checks") or []
        for idx, check in enumerate(checks[:13]):
            y = 0.80 - idx * 0.041
            fig.text(
                0.065,
                y,
                "✓" if check.get("ok") else "✕",
                color="#287a52" if check.get("ok") else "#b34235",
                fontsize=10,
            )
            fig.text(
                0.087,
                y,
                str(check.get("name", "")).replace("_", " "),
                fontsize=8.5,
                color="#102a34",
            )
        limits = [
            "Engine thrust-lapse and part-throttle TSFC are assumptions anchored by one static vendor point.",
            f"Stall uses an assumed CLmax={spec.mission.cl_max:.2f}; no high-lift or nonlinear separation model is present.",
            "OAS/VSPAERO are lifting-surface models; fins are gated separately by Vv and exported-mesh truth.",
            "SU2 is a coarse 2-D Euler calibration and must report convergence separately from successful execution.",
            "TACS and OAS use different wingbox idealizations; their mass/stress ratio is calibration evidence only.",
        ]
        fig.text(
            0.54,
            0.80,
            "Documented limitations",
            fontsize=13,
            weight="bold",
            color="#102a34",
        )
        y = 0.75
        for item in limits:
            fig.text(0.55, y, "• " + item, fontsize=9, color="#58707a", wrap=True)
            y -= 0.105
        fig.text(
            0.06,
            0.08,
            "Full interactive evidence, exact stage values, and configuration: report.html",
            fontsize=10,
            color="#1f7184",
        )
        pdf.savefig(fig)
        plt.close(fig)


def build_presentation(design_path: str | Path) -> dict[str, Any]:
    concept, baseline_yaml, results_root = resolve_design(design_path)
    optimized_yaml = optimized_design_for(baseline_yaml)
    if not optimized_yaml.exists():
        raise FileNotFoundError(
            f"Optimized design is missing: {optimized_yaml}. Run the concept pipeline first."
        )
    baseline_dir = results_dir_for(baseline_yaml)
    optimized_dir = results_dir_for(optimized_yaml)
    baseline_spec = _spec(baseline_yaml)
    optimized_spec = _spec(optimized_yaml)

    baseline_sizing = _read_json(baseline_dir / "sizing.json")
    mdo = _read_json(baseline_dir / "mdo.json")
    data = {
        name: _read_json(optimized_dir / f"{name}.json")
        for name in (
            "geometry",
            "aero",
            "structures",
            "validation",
            "report",
            "tacs",
            "su2",
        )
    }
    data["mdo"] = mdo
    baseline_aero = _read_json(baseline_dir / "aero.json")
    baseline_structures = _read_json(baseline_dir / "structures.json")
    base_metrics, opt_metrics = _performance(
        baseline_sizing,
        mdo,
        data["aero"],
        data["report"],
        optimized_spec,
    )

    comparison_path = results_root / "baseline_vs_optimized.png"
    balance_path = results_root / "cg_np_balance.png"
    comparison_bars(base_metrics, opt_metrics, comparison_path)
    balance_for_plot = dict(data["aero"].get("balance") or {})
    stability_for_plot = data["aero"].get("stability") or {}
    balance_for_plot["x_np_m"] = (
        stability_for_plot.get("x_np_measured_m")
        or stability_for_plot.get("x_np_m")
        or balance_for_plot.get("x_np_m")
    )
    if stability_for_plot.get("band"):
        balance_for_plot["band"] = stability_for_plot["band"]
    cg_np_diagram(optimized_spec, balance_for_plot, balance_path)
    mass_path = optimized_dir / "mass_breakdown.png"
    if not mass_path.exists():
        masses = data["structures"].get("masses") or {}
        mass_bar(masses, mass_path)

    openvsp = data["geometry"].get("openvsp") or {}
    stl_value = openvsp.get("stl")
    stl_path = (
        Path(stl_value) if stl_value else optimized_dir / f"{optimized_spec.name}.stl"
    )
    if not stl_path.exists():
        whole_stls = [
            p
            for p in optimized_dir.glob("*.stl")
            if not p.name.startswith("component_")
        ]
        if not whole_stls:
            raise FileNotFoundError(
                f"No optimized whole-aircraft STL found in {optimized_dir}"
            )
        stl_path = whole_stls[0]
    mesh_payload = _mesh_payload(stl_path)

    existing_feedback = _read_json(results_root / "gate_feedback.json")
    gate_feedback = build_gate_feedback(
        design_path,
        auto_retries=existing_feedback.get("auto_retries") or [],
    )
    dump_json(results_root / "gate_feedback.json", gate_feedback)
    gates = gate_feedback["gates"]
    all_gates = all(gate["ok"] for gate in gates)
    title = concept.replace("-", " ").title().replace("Kingtech", "KingTech")
    generated = datetime.now().astimezone()
    brief_path = baseline_yaml.parent / "brief.md"
    brief_text = (
        brief_path.read_text(encoding="utf-8")
        if brief_path.exists()
        else baseline_spec.notes
    )
    brief_html = _brief_html(brief_text)

    desires = data["report"].get("desires") or {}
    endurance_applicable = bool(
        desires.get("endurance_applicable", optimized_spec.mission.endurance_required)
    )
    score_rows = [
        [
            "Engine",
            str(desires.get("engine_required") or optimized_spec.engine.name),
            str(desires.get("engine_predicted") or optimized_spec.engine.name),
            "MET" if desires.get("engine_met") else "SHORT",
        ],
        [
            "Payload",
            f"{float(desires.get('payload_kg_req', optimized_spec.mission.payload_kg)):.1f} kg",
            f"{float(desires.get('payload_kg_pred', optimized_spec.mission.payload_kg)):.1f} kg",
            "MET" if desires.get("payload_met") else "SHORT",
        ],
        [
            "Endurance",
            (
                f"{optimized_spec.mission.endurance_s / 3600:.2f} h"
                if endurance_applicable
                else "not claimed"
            ),
            f"{opt_metrics['endurance_hr']:.2f} h" if endurance_applicable else "n/a",
            (
                "MET"
                if endurance_applicable and desires.get("endurance_met")
                else "SHORT"
                if endurance_applicable
                else "N/A"
            ),
        ],
        [
            "Dash",
            f"maximize; M ≤ {optimized_spec.mission.dash_mach_cap:.2f}",
            f"{opt_metrics['dash_kmh']:.0f} km/h · M {_fmt(desires.get('dash_mach'), 2)}",
            "MET" if desires.get("mach_cap_ok") else "SHORT",
        ],
        [
            "Configuration",
            "sketch envelope",
            f"{optimized_spec.wing.span_m:.2f} m span · {optimized_spec.wing.le_sweep_deg:.1f}° sweep",
            "MET" if desires.get("shape_ok") else "SHORT",
        ],
    ]
    score_status = [row[-1] in {"MET", "N/A"} for row in score_rows]
    score_html = _table_rows(score_rows, score_status)

    gates_html = "".join(
        f'<article class="gate {"pass" if gate["ok"] else "fail"}">'
        f'<div class="eyebrow">Tier {html.escape(gate["tier"])} · {html.escape(gate["tier_name"])}</div>'
        f"<b>{'PASS' if gate['ok'] else 'FAIL'} · {html.escape(gate['name'])}</b>"
        f"<p>{html.escape(gate['meaning'])}</p>"
        f"<p>{html.escape(gate['evidence'])}</p>"
        f"<small>{html.escape(gate['source'])} · Upstream response: "
        f"{html.escape(gate['upstream_knob'])}</small></article>"
        for gate in gates
    )
    gates_html += "".join(
        f'<article class="gate {"pass" if (retry.get("after") or {}).get("trigger_cleared") else "fail"}">'
        '<div class="eyebrow">Automated response · one-shot retry</div>'
        f"<b>{html.escape(str(retry.get('trigger') or 'gate retry'))}</b>"
        f"<p>{html.escape(str(retry.get('action') or ''))}</p>"
        f"<small>Overlay: {html.escape(_fmt(retry.get('overlay')))} · "
        f"after: {html.escape(_fmt(retry.get('after')))}</small></article>"
        for retry in gate_feedback.get("auto_retries") or []
    )

    sketch_cards = [
        (
            f"Concept sketch · {path.stem.removeprefix('sketch-').replace('-', ' ')}",
            "Design intent",
            path,
            "Version-controlled source sketch shown beside the artifact-derived three-view for direct shape-fidelity review.",
        )
        for path in sorted(baseline_yaml.parent.glob("sketch-*.png"))
    ]
    reference_cards = []
    reference_fidelity = data["geometry"].get("reference_fidelity") or {}
    if reference_fidelity.get("available") and (optimized_dir / "reference_overlay.png").exists():
        distance = reference_fidelity.get("distance_model_to_reference") or {}
        views = reference_fidelity.get("silhouettes") or {}
        reference_cards.append(
            (
                "Reference model · exported mesh versus measured scan",
                "Artifact truth",
                optimized_dir / "reference_overlay.png",
                f"Point-sampled surface deviation p95 {1000.0 * float(distance.get('p95_m') or 0.0):.1f} mm whole aircraft "
                f"(body gate {1000.0 * float(((reference_fidelity.get('checks') or {}).get('p95_body') or {}).get('got') or 0.0):.1f} mm); "
                f"silhouette IoU top {float((views.get('top') or {}).get('iou') or 0.0):.3f}, "
                f"side {float((views.get('side') or {}).get('iou') or 0.0):.3f}. "
                "The reference model is measured design input, not validation truth.",
            )
        )
    charts = _chart_cards(
        [
            (
                "Exported-aircraft three-view",
                "Artifact truth",
                optimized_dir / "threeview.png",
                "Orthographic projections drawn from the optimized STL, not from design parameters.",
            ),
            *reference_cards,
            *sketch_cards,
            (
                "Baseline versus optimized",
                "Design evolution",
                comparison_path,
                "Same-unit comparisons expose the performance gain and its mass, fuel, and geometry trades.",
            ),
            (
                "CG travel and evaluated neutral point",
                "Balance",
                balance_path,
                "Full- and reserve-fuel CG stations are shown against the static-margin-derived allowable band.",
            ),
            (
                "OAS aerodynamic polar",
                "Aerodynamics",
                optimized_dir / "polar.png",
                "Lift and drag behavior from the optimized wing model over the analyzed angle-of-attack range.",
            ),
            (
                "Mass breakdown",
                "Mass properties",
                mass_path,
                "Delivered mass buildup, including payload, fuel, propulsion, airframe, systems, and contingency.",
            ),
            (
                "Parasite-drag buildup",
                "Aerodynamics",
                optimized_dir / "drag_breakdown.png",
                "Explicit component contributions prevent a single unexplained CD0 from hiding the performance budget.",
            ),
            (
                "Spanwise lift reference",
                "Loads",
                optimized_dir / "spanwise_loads.png",
                "Spanwise lift distribution with an elliptic reference for rapid shape and load sanity checking.",
            ),
            (
                "Constraint margins",
                "Optimization",
                optimized_dir / "margins.png",
                "Positive bars are feasible margins; bars near zero identify active design drivers.",
            ),
        ]
    )

    baseline_threeview_uri = _image_uri(baseline_dir / "threeview.png")
    if baseline_threeview_uri:
        baseline_fig = (
            '<figure class="chart-card">'
            '<div class="eyebrow">Artifact truth · baseline</div>'
            "<h3>Baseline aircraft three-view</h3>"
            f'<img src="{baseline_threeview_uri}" alt="Baseline three-view">'
            "<figcaption>Orthographic projections drawn from the baseline STL — "
            "the as-drawn aircraft before any optimization.</figcaption>"
            "</figure>"
        )
    else:
        baseline_fig = (
            '<div class="card"><div class="eyebrow">Artifact truth · baseline</div>'
            "<h3>Baseline three-view unavailable</h3>"
            "<p>results/"
            + html.escape(concept)
            + "/baseline/threeview.png was not found.</p></div>"
        )
    findings = _baseline_findings(
        baseline_spec,
        baseline_sizing,
        baseline_aero,
        baseline_structures,
    )
    findings_html = (
        "".join(f"<li>{html.escape(item)}</li>" for item in findings)
        or "<li>No baseline stage artifacts were found beside the source design.</li>"
    )
    delta_rows = _evolution_rows(
        baseline_spec,
        optimized_spec,
        base_metrics,
        opt_metrics,
        baseline_aero,
        data["aero"],
        endurance_applicable,
    )

    starts = mdo.get("starts") or []
    start_rows = [
        [
            str(start.get("start")),
            f"{float(start.get('dash_mps') or 0) * 3.6:.0f} km/h",
            (
                f"{float(start.get('endurance_s') or 0) / 3600:.2f} h"
                if endurance_applicable
                else "n/a"
            ),
            f"{float(start.get('mtow_kg') or 0):.1f} kg",
            "yes" if start.get("feasible") else "no",
        ]
        for start in starts
    ]
    cal_rows: list[list[str]] = []
    for item in mdo.get("sm_calibration") or []:
        np_calibration = item.get("lifting_surface_np_calibration") or {}
        if np_calibration:
            cal_rows.append(
                [
                    "same-run OAS NP",
                    "model error ≤ 0.05 MAC",
                    f"{_fmt(np_calibration.get('error_before_mac'))} / "
                    f"{_fmt(np_calibration.get('error_after_mac'))} MAC",
                    "PASS" if np_calibration.get("converged") else "RE-RUN",
                ]
            )
        elif "sm_measured_ok" in item:
            cal_rows.append(
                [
                    str(item.get("attempt")),
                    _fmt(item.get("sm_bounds_internal")),
                    f"{_fmt(item.get('sm_measured_full'))} / "
                    f"{_fmt(item.get('sm_measured_reserve'))}",
                    "PASS" if item.get("sm_measured_ok") else "RE-RUN",
                ]
            )
        else:
            cal_rows.append(
                [
                    str(item.get("kind") or "same-run calibration"),
                    "declared solver evidence",
                    _fmt(item.get("hybrid_evidence")),
                    "PASS" if item.get("ok") else "RE-RUN",
                ]
            )
    reproduction = bool(
        optimized_spec.sketch is not None
        and optimized_spec.sketch.treatment == "reproduction"
    )
    sized_text = (
        "Fuel and MTOW close without an endurance claim"
        if not endurance_applicable
        else f"Fuel and MTOW close at {base_metrics['endurance_hr']:.2f} h"
    )
    closure_title = (
        "Deterministic reproduction closure" if reproduction else "Multi-start MDO"
    )
    closure_text = (
        "Source coordinates remain frozen while same-run OAS closes model "
        "calibration and verifies trim, stability, and structures."
        if reproduction
        else f"{len(starts)} starts maximize dash inside shape, trim, balance, "
        "packing, stall, and structure constraints."
    )
    timeline = "".join(
        [
            '<article class="phase"><h3>Sketch envelope</h3><p>Mission, topology, and proportions become a validated, version-controlled concept specification.</p></article>',
            f'<article class="phase"><h3>Sized baseline</h3><p>{sized_text}; artifact geometry and OAS models establish the reference.</p></article>',
            f'<article class="phase"><h3>{closure_title}</h3><p>{closure_text}</p></article>',
            f'<article class="phase"><h3>{"Verified delivery" if reproduction else "Verified optimum"}</h3><p>Separate OAS and mesh-truth checks produce the {opt_metrics["dash_kmh"]:.0f} km/h delivered configuration.</p></article>',
        ]
    )

    checks = data["validation"].get("checks") or []
    vv_rows: list[list[str]] = []
    vv_status: list[bool] = []
    for check in checks:
        stretch = str(check.get("note") or "").startswith("stretch")
        vv_rows.append(
            [
                str(check.get("name", "")).replace("_", " "),
                "stretch calibration" if stretch else "core gate",
                _fmt(
                    check.get("got")
                    if "got" in check
                    else check.get("CL_ratio_vspaero_over_oas")
                    or check.get("backend")
                    or check.get("converged")
                ),
                _fmt(check.get("want") if "want" in check else check.get("note")),
                "PASS" if check.get("ok") else "FAIL",
            ]
        )
        vv_status.append(bool(check.get("ok")))
    mesh_checks = (openvsp.get("mesh_checks") or {}).get("checks") or []
    tacs_analysis = data["tacs"].get("analysis") or {}
    su2 = data["su2"]
    vspaero = next(
        (check for check in checks if check.get("name") == "vspaero_vs_oas_CL"), {}
    )
    vv_cards = "".join(
        [
            f'<article class="card"><div class="eyebrow">Mesh truth</div><h3>{sum(bool(c.get("ok")) for c in mesh_checks)}/{len(mesh_checks)} checks</h3><p>Component extents, fin verticality, whole-model envelope, and root attachment are measured on exported STL files.</p></article>',
            f'<article class="card"><div class="eyebrow">Independent VLM</div><h3>CLα ratio {_fmt(vspaero.get("CL_alpha_ratio_vspaero_over_oas", vspaero.get("CL_ratio_vspaero_over_oas")), 2)}</h3><p>VSPAERO versus OAS lift-curve slope across α={html.escape(str(vspaero.get("alpha_range_deg") or "n/a"))}° on the same lifting surfaces. Absolute CL has different camber fidelity; CD is intentionally not compared.</p></article>',
            f'<article class="card"><div class="eyebrow">Stretch calibration</div><h3>TACS {html.escape(str(tacs_analysis.get("backend") or "not run"))}</h3><p>Shell mass {_fmt(tacs_analysis.get("maneuver_mass"))} kg; SU2 cruise converged={_fmt((su2.get("cruise") or {}).get("converged"))}, rmsρ={_fmt((su2.get("cruise") or {}).get("rms_density"))}.</p></article>',
        ]
    )

    config_rows = [
        [
            "Fuselage",
            f"{optimized_spec.fuselage.length_m:.2f} × {optimized_spec.fuselage.max_width_m:.2f} × {optimized_spec.fuselage.max_height_m:.2f} m",
        ],
        [
            "Wing",
            f"{optimized_spec.wing.span_m:.2f} m span · {optimized_spec.wing.area_m2:.2f} m² · AR {optimized_spec.wing.aspect_ratio:.2f}",
        ],
        [
            "Planform",
            f"root {optimized_spec.wing.root_chord_m:.2f} m · taper {optimized_spec.wing.taper:.3f} · LE sweep {optimized_spec.wing.le_sweep_deg:.1f}°",
        ],
        [
            "Airfoil / thickness",
            f"NACA {optimized_spec.wing.airfoil} · t/c {optimized_spec.wing.t_over_c:.3f}",
        ],
        [
            "Twist",
            f"root {optimized_spec.wing.twist_root_deg:+.2f}° · tip {optimized_spec.wing.twist_tip_deg:+.2f}°",
        ],
        [
            "Single fin" if optimized_spec.vtail.count == 1 else "Twin fins",
            f"{optimized_spec.vtail.span_m:.2f} m span"
            + (" · " if optimized_spec.vtail.count == 1 else " each · ")
            + f"{optimized_spec.vtail.cant_deg:.1f}° cant",
        ],
        [
            "Propulsion",
            f"{optimized_spec.engine.name} · {optimized_spec.engine.max_thrust_sl_n:.1f} N SL",
        ],
        ["Fuel", f"{optimized_spec.mass.fuel_mass_kg:.2f} kg delivered spec"],
        [
            "Structure",
            f"{optimized_spec.structures.fem_model_type} · skin {optimized_spec.structures.skin_thickness_m * 1000:.2f} mm · spar {optimized_spec.structures.spar_thickness_m * 1000:.2f} mm",
        ],
        [
            "Material",
            f"{optimized_spec.structures.material.name} · yield {optimized_spec.structures.material.yield_pa / 1e6:.0f} MPa",
        ],
    ]
    balance_items = (data["aero"].get("balance") or {}).get("items_full") or []
    balance_rows = [
        [
            str(item.get("name")),
            f"{float(item.get('mass_kg') or 0):.2f} kg",
            f"{float(item.get('x_m') or 0):.3f} m",
        ]
        for item in balance_items
    ]
    version_rows = [
        [name, version] for name, version in _versions(openvsp.get("openvsp_version"))
    ]
    limits = [
        (
            "The electric deck supplies sourced steady thrust only. Battery "
            "energy, range, and endurance are outside this reproduction."
            if optimized_spec.engine.energy_source == "electric"
            else "The vendor engine deck supplies geometry, mass, static thrust, "
            "and maximum fuel flow. Flight thrust lapse and part-throttle TSFC "
            "remain documented assumptions."
        ),
        f"Stall speed uses CLmax = {optimized_spec.mission.cl_max:.2f}; nonlinear separation and high-lift devices are not modeled.",
        "OAS and VSPAERO are lifting-surface methods. The fins affect mass, drag, and Vv but do not enter the wing-only OAS stability solve.",
        "SU2 is a coarse 2-D Euler section calculation. A successful process return is not aerodynamic convergence.",
        "TACS and OAS use different structural idealizations; their discrepancy is calibration information, not interchangeable proof.",
        "No propulsion installation loss, inlet distortion, controls, flutter, thermal, landing, manufacturing, or certification analysis is claimed.",
    ]

    endurance_stat = (
        f'<div class="stat"><strong>{opt_metrics["endurance_hr"]:.2f}</strong>'
        "<span>hours endurance</span></div>"
        if endurance_applicable
        else '<div class="stat"><strong>—</strong><span>endurance not claimed</span></div>'
    )
    payload_kg = float(optimized_spec.mission.payload_kg)
    payload_stat = (
        f'<div class="stat"><strong>{payload_kg:.1f}</strong><span>kg payload</span></div>'
        if payload_kg > 0.05
        else f'<div class="stat"><strong>{optimized_spec.wing.span_m:.2f}</strong><span>m span</span></div>'
    )
    stats_html = "".join(
        [
            f'<div class="stat"><strong>{opt_metrics["dash_kmh"]:.0f}</strong><span>km/h dash</span></div>',
            endurance_stat,
            payload_stat,
            f'<div class="stat"><strong>{opt_metrics["mtow_kg"]:.1f}</strong><span>kg MTOW</span></div>',
        ]
    )
    topology = _topology_label(optimized_spec)
    substitutions = {
        "@@TITLE@@": html.escape(title),
        "@@DATE@@": generated.strftime("%d %B %Y"),
        "@@DECK@@": html.escape(
            f"{optimized_spec.engine.name} {topology} · "
            + (f"{payload_kg:.1f} kg payload · " if payload_kg > 0.05 else "")
            + "baseline-to-optimized evidence with an embedded model of the actual exported mesh."
        ),
        "@@VERDICT_CLASS@@": "" if all_gates else "fail",
        "@@VERDICT@@": f"{sum(g['ok'] for g in gates)}/{len(gates)} preliminary-design gates pass",
        "@@STATS@@": stats_html,
        "@@BRIEF@@": brief_html,
        "@@OUTCOME_TITLE@@": "Ready for wider review"
        if all_gates
        else "Engineering hold",
        "@@OUTCOME_TEXT@@": (
            "The concept meets the encoded mission and all current preliminary-design gates. "
            "This is a traceable conceptual design verdict—not an airworthiness certification."
            if all_gates
            else "One or more preliminary-design gates failed. Review the red evidence cards and fix the upstream model before presenting the concept as viable."
        ),
        "@@CONCEPT@@": html.escape(concept),
        "@@SCORECARD@@": score_html,
        "@@GATES@@": gates_html,
        "@@CHARTS@@": charts,
        "@@BASELINE_FIG@@": baseline_fig,
        "@@BASELINE_FINDINGS@@": findings_html,
        "@@DELTA_ROWS@@": _table_rows(delta_rows),
        "@@TIMELINE@@": timeline,
        "@@MDO_STARTS@@": _table_rows(
            start_rows, [row[-1] == "yes" for row in start_rows]
        ),
        "@@SM_CAL@@": _table_rows(cal_rows, [row[-1] == "PASS" for row in cal_rows]),
        "@@VV_ROWS@@": _table_rows(vv_rows, vv_status),
        "@@VV_CARDS@@": vv_cards,
        "@@CONFIG_ROWS@@": _table_rows(config_rows),
        "@@BALANCE_ROWS@@": _table_rows(balance_rows),
        "@@VERSIONS@@": _table_rows(version_rows),
        "@@LIMITS@@": "".join(f"<li>{html.escape(item)}</li>" for item in limits),
        "@@SPEC_YAML@@": html.escape(
            yaml.safe_dump(optimized_spec.model_dump(mode="python"), sort_keys=False)
        ),
        "@@GENERATED@@": generated.isoformat(timespec="seconds"),
        "@@VIEWER@@": VIEWER_SCRIPT.replace(
            "@@MESH_PAYLOAD@@", json.dumps(mesh_payload, separators=(",", ":"))
        ),
    }
    document = PAGE_TEMPLATE
    for marker, value in substitutions.items():
        document = document.replace(marker, value)
    html_path = results_root / "report.html"
    html_path.write_text(document, encoding="utf-8")

    images = {
        "threeview": optimized_dir / "threeview.png",
        "comparison": comparison_path,
        "polar": optimized_dir / "polar.png",
        "drag": optimized_dir / "drag_breakdown.png",
        "balance": balance_path,
        "margins": optimized_dir / "margins.png",
        "mass": mass_path,
    }
    pdf_path = results_root / "executive_brief.pdf"
    _pdf_brief(
        pdf_path, title, opt_metrics, gates, data["validation"], images, optimized_spec
    )
    return {
        "ok": all_gates,
        "html": str(html_path),
        "pdf": str(pdf_path),
        "triangle_count": mesh_payload["triangles"],
        "gates_passed": sum(gate["ok"] for gate in gates),
        "gates_total": len(gates),
        "concept": concept,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openair.reporting")
    parser.add_argument(
        "design", type=Path, help="concept folder or source design YAML"
    )
    args = parser.parse_args(argv)
    products = build_presentation(args.design)
    print(f"wrote {products['html']}")
    print(f"wrote {products['pdf']}")
    return 0
