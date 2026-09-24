"""Human-review report for the baseline-only multirotor workflow."""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any

import numpy as np

from openair.multirotor.geometry import render_threeview
from openair.multirotor.package import load_multirotor_package
from openair.multirotor.schema import MultirotorSpec


def _plot_directional_drag(aero: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tables = np.load(aero["table_asset"], allow_pickle=False)
    theta = tables["theta_deg"]
    phi = tables["phi_deg"]
    force = tables["force_area_body_m2"]
    fig, axis = plt.subplots(figsize=(8, 5))
    for requested in (0.0, 45.0, 90.0):
        index = int(np.argmin(np.abs(phi - requested)))
        directions = np.column_stack(
            (
                np.sin(np.radians(theta)) * np.cos(np.radians(phi[index])),
                np.sin(np.radians(theta)) * np.sin(np.radians(phi[index])),
                np.cos(np.radians(theta)),
            )
        )
        drag_area = -np.einsum("ij,ij->i", force[:, index], directions)
        axis.plot(theta, drag_area, label=f"phi={phi[index]:.0f} deg")
    axis.set_xlabel("theta from body +Z (deg)")
    axis.set_ylabel("effective drag area, CdA (m²)")
    axis.set_title("Passive-airframe directional drag table")
    axis.grid(True, alpha=0.3)
    axis.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _plot_mass(mass: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [item["name"] for item in mass["components"]]
    values = [float(item["mass_kg"]) for item in mass["components"]]
    fig, axis = plt.subplots(figsize=(8, 4.5))
    axis.bar(names, values, color="#376f86")
    axis.set_ylabel("mass (kg)")
    axis.set_title("Declared component mass budget (class D)")
    axis.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _image_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def _gate_rows(
    geometry: dict[str, Any],
    mass: dict[str, Any],
    propulsion: dict[str, Any],
    aero: dict[str, Any],
    package_ok: bool,
) -> list[dict[str, Any]]:
    return [
        {
            "gate": "Schema",
            "status": "pass",
            "evidence": "design.yaml validated through MultirotorSpec",
        },
        {
            "gate": "Reference segmentation",
            "status": "pass" if geometry["checks"]["finite"] else "fail",
            "evidence": "connected-shell classification; rotating hardware excluded",
        },
        {
            "gate": "Geometry artifact",
            "status": "pass" if geometry["ok"] else "fail",
            "evidence": "lossless STL round-trips, component hashes, Quad-X stations",
        },
        {
            "gate": "Mass properties",
            "status": "pass" if mass["ok"] else "fail",
            "evidence": "component closure and positive-definite inertia; class D",
        },
        {
            "gate": "Propulsion mapping",
            "status": "pass" if propulsion["ok"] else "fail",
            "evidence": "native motor order/spins, clearance, hover margin; class D",
        },
        {
            "gate": "Passive aero representation",
            "status": "pass" if aero["ok"] else "fail",
            "evidence": "finite/dissipative tables, projected-area bands, sign checks",
        },
        {
            "gate": "Hashed Elodin package",
            "status": "pass" if package_ok else "fail",
            "evidence": "GLB face/area/projection regression, schema, sizes, SHA-256",
        },
        {
            "gate": "Fixed-wing balance/trim/stall/structures/MDO",
            "status": "not_applicable",
            "evidence": "multirotor family has no wing or fixed-wing optimization phase",
        },
        {
            "gate": "Physical predictive accuracy",
            "status": "unvalidated",
            "evidence": "no vehicle-specific wind-tunnel or held-out flight evidence",
        },
    ]


def run_report_stage(
    spec: MultirotorSpec,
    outdir: Path,
    geometry: dict[str, Any],
    mass: dict[str, Any],
    propulsion: dict[str, Any],
    aero: dict[str, Any],
    package_result: dict[str, Any],
) -> dict[str, Any]:
    drag_plot = outdir / "directional_drag.png"
    mass_plot = outdir / "mass_breakdown.png"
    _plot_directional_drag(aero, drag_plot)
    _plot_mass(mass, mass_plot)
    package = load_multirotor_package(package_result["model"])
    import trimesh

    package_root = Path(package_result["package_dir"])
    glb_path = package_root / package.manifest["render_glb"].path
    glb_scene = trimesh.load(glb_path, force="scene", process=False)
    glb_mesh = glb_scene.to_geometry()
    threeview = outdir / "glb_threeview.png"
    if not render_threeview(
        glb_mesh,
        np.eye(3),
        threeview,
        f"{spec.name}: packaged GLB (propellers excluded, body FLU at CG)",
    ):
        raise RuntimeError("could not render packaged GLB three-view")
    gates = _gate_rows(geometry, mass, propulsion, aero, True)
    cardinal = aero["checks"]["cardinal_drag_area_m2"]
    markdown = f"""# {spec.name} — multirotor design report

**Verdict:** software/representation checks pass; physical aerodynamic accuracy
is unvalidated. Credibility is `{package.credibility}`.

## Headline values (baseline only)

- Mass: {mass['mass_kg']:.3f} kg (class {mass['evidence_class']})
- CG in body-origin coordinates: {[round(value, 5) for value in mass['cg_body_origin_m']]} m
- Elodin diagonal inertia: {[round(value, 6) for value in mass['elodin_diagonal_kg_m2']]} kg m²
- Thrust-to-weight: {propulsion['checks']['thrust_to_weight']:.2f}
- Hover command: {propulsion['checks']['hover_command']:.3f}
- Effective CdA: +X {cardinal['+x']:.4f}, +Y {cardinal['+y']:.4f},
  +Z {cardinal['+z']:.4f} m²
- Reference speed/domain: {aero['reference_speed_mps']:.1f} m/s;
  {aero['validity']['speed_mps']} m/s

## Geometry artifact

The reported dimensions, motor stations, and projected areas come from the
losslessly exported propeller-free reference mesh. The three-view is rendered
back from the packaged GLB. Rotating shells are not in either artifact.

## Gates

"""
    for row in gates:
        markdown += (
            f"- **{row['gate']}** — `{row['status']}`: {row['evidence']}\n"
        )
    markdown += """

## Capability boundary

The package represents 6-DOF mass properties, four independent motor stations,
first-order motor thrust, and direction-dependent passive-airframe force and
moment tables. Rotor inflow, propeller H-force/drag, rotor-body interactions,
electrical behavior, ground effect, and unsteady separated flow are absent.
Stretch/fixed-wing solvers are not pass/fail evidence for this model.
"""
    report_md = outdir / "design_report.md"
    report_md.write_text(markdown, encoding="utf-8")

    rows_html = "\n".join(
        "<tr>"
        f"<td>{html.escape(row['gate'])}</td>"
        f"<td><code>{html.escape(row['status'])}</code></td>"
        f"<td>{html.escape(row['evidence'])}</td>"
        "</tr>"
        for row in gates
    )
    capability = html.escape(
        json.dumps(package.capability_manifest, indent=2)
    )
    report_html = outdir.parent / "report.html"
    report_html.write_text(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(spec.name)} multirotor report</title>
<style>
body{{font:16px/1.45 system-ui;margin:0;background:#10161b;color:#e7edf2}}
main{{max-width:1100px;margin:auto;padding:2rem}}
.warning{{padding:1rem;border-left:4px solid #e9a23b;background:#252118}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}
img{{width:100%;background:white;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
td,th{{border-bottom:1px solid #3b4650;padding:.6rem;text-align:left;vertical-align:top}}
code,pre{{background:#1b242b;color:#d5e8f4}} pre{{padding:1rem;overflow:auto}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="brand">open-air · concept review</div>
<h1>{html.escape(spec.name)} — multirotor baseline</h1>
<p class="warning"><strong>Geometry-correlated only.</strong> Software and
representation checks pass; passive-airframe aerodynamic accuracy has no
vehicle-specific physical validation.</p>
<h2>Headline values</h2>
<ul><li>Mass: {mass['mass_kg']:.3f} kg</li>
<li>Thrust-to-weight: {propulsion['checks']['thrust_to_weight']:.2f}</li>
<li>CdA +X/+Y/+Z: {cardinal['+x']:.4f} / {cardinal['+y']:.4f} /
{cardinal['+z']:.4f} m²</li>
<li>Package: <code>baseline/elodin_package/elodin_model.json</code></li></ul>
<h3>Exported-aircraft three-view</h3>
<div class="grid"><figure><img src="{_image_uri(threeview)}"><figcaption>
Packaged-GLB propeller-free three-view</figcaption></figure>
<figure><img src="{_image_uri(drag_plot)}"><figcaption>Direction table</figcaption></figure></div>
<h2>QA gates</h2><table><thead><tr><th>Gate</th><th>Status</th><th>Evidence</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<h2>Capability manifest</h2><pre>{capability}</pre>
<h2>Integration</h2><p>Use
<code>baseline/elodin_package/integration_guide.md</code>. It maps package
mass/inertia/motors into <code>DroneConfig</code> and replaces the existing
aggregate drag system without double counting.</p>
</main></body></html>
""",
        encoding="utf-8",
    )
    return {
        "ok": all(row["status"] != "fail" for row in gates),
        "report_markdown": str(report_md),
        "report_html": str(report_html),
        "directional_drag_plot": str(drag_plot),
        "mass_plot": str(mass_plot),
        "glb_threeview": str(threeview),
        "gates": gates,
        "credibility": package.credibility,
        "physical_validation": "unvalidated",
        "headline": {
            "mass_kg": mass["mass_kg"],
            "thrust_to_weight": propulsion["checks"]["thrust_to_weight"],
            "cardinal_drag_area_m2": cardinal,
        },
    }

