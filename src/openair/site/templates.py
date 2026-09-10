"""HTML templates for the published design-review index."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

from openair.theme import REPORT_CSS


SITE_CSS = """
.brand a { color:inherit; text-decoration:none; }
.hero-showcase { display:block; position:relative; border:1px solid rgba(255,255,255,.18); border-radius:18px; background:#071f29; overflow:hidden; box-shadow:0 28px 70px rgba(0,0,0,.35); }
.hero-showcase img { display:block; width:100%; aspect-ratio:1.935; object-fit:contain; background:white; }
.hero-caption { display:flex; justify-content:space-between; gap:16px; color:#d6e7ec; font-size:.75rem; background:#071f29; padding:9px 12px; }
.design-card { display:flex; flex-direction:column; min-width:0; padding:0; overflow:hidden; transition:transform .18s ease,box-shadow .18s ease; }
.design-card:hover { transform:translateY(-3px); box-shadow:0 13px 30px rgba(17,48,59,.10); }
.design-card-media { display:block; border-bottom:1px solid var(--line); background:#e9eeeb; }
.design-card-media img { display:block; width:100%; aspect-ratio:1.935; object-fit:contain; }
.design-card-body { display:flex; flex:1; flex-direction:column; padding:21px; }
.design-card h3 { margin:.6em 0 .38em; font-size:1.32rem; line-height:1.15; letter-spacing:-.025em; }
.design-card h3 a { color:var(--ink); text-decoration:none; }
.design-card p { margin:0 0 1em; color:var(--muted); }
.fact-list { display:flex; flex-wrap:wrap; gap:6px 12px; margin-top:auto; padding-top:7px; color:var(--muted); font-size:.76rem; }
.fact-list span { white-space:nowrap; }
.card-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:18px; }
.button { display:inline-flex; align-items:center; min-height:38px; border-radius:8px; padding:8px 12px; color:white; background:var(--teal); font-size:.78rem; font-weight:800; text-decoration:none; }
.button.secondary { color:var(--ink); background:#e8eeec; }
.button.text { color:var(--teal); background:transparent; padding-inline:3px; }
.evidence-callout { border-left:6px solid var(--orange); }
.evidence-callout p:last-child { margin-bottom:0; }
.site-footer-grid { display:flex; justify-content:space-between; align-items:flex-start; gap:28px; }
.site-footer-grid a { color:#d6e7ec; }
.site-footer-meta { color:#7fa1aa; font-size:.78rem; text-align:right; }
@media (max-width:900px) { .cards { grid-template-columns:repeat(2,1fr); } }
@media (max-width:560px) { .cards { grid-template-columns:1fr; } .hero-caption,.site-footer-grid { display:block; } .site-footer-meta { margin-top:15px; text-align:left; } }
"""


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _fact_items(design: Mapping[str, Any]) -> str:
    facts: list[str] = []
    span_m = design.get("span_m")
    length_m = design.get("length_m")
    if isinstance(span_m, (int, float)):
        facts.append(f"optimized {span_m:.2f} m span")
    if isinstance(length_m, (int, float)):
        facts.append(f"optimized {length_m:.2f} m length")
    if design.get("credibility"):
        facts.append(
            "optimized package: "
            + str(design["credibility"]).replace("-", " ")
        )
    if design.get("run_date"):
        facts.append(f"package {design['run_date']}")
    return "".join(f"<span>{_text(fact)}</span>" for fact in facts)


def _design_card(
    design: Mapping[str, Any],
    *,
    repo_url: str,
    commit: str,
) -> str:
    slug = _text(design["slug"])
    title = _text(design["title"])
    package_link = ""
    if design.get("has_package"):
        package_link = (
            '<a class="button text" href="'
            f"{_text(repo_url)}/tree/{_text(commit)}/results/{slug}/optimized/"
            'elodin_package/">Elodin package ↗</a>'
        )
    return f"""<article class="card design-card">
  <a class="design-card-media" href="designs/{slug}/" aria-label="Open {title} design review">
    <img src="designs/{slug}/baseline_vs_optimized.png" alt="{title} baseline and optimized comparison" loading="lazy">
  </a>
  <div class="design-card-body">
    <div><span class="pill">{_text(design["kind"])}</span></div>
    <h3><a href="designs/{slug}/">{title}</a></h3>
    <p>{_text(design["summary"])}</p>
    <div class="fact-list">{_fact_items(design)}</div>
    <div class="card-actions">
      <a class="button" href="designs/{slug}/">Open design review</a>
      <a class="button secondary" href="designs/{slug}/executive_brief.pdf">Executive brief</a>
      {package_link}
    </div>
  </div>
</article>"""


def render_index(
    designs: Sequence[Mapping[str, Any]],
    *,
    repo_url: str,
    commit: str,
    generated_at: str,
) -> str:
    """Render the public landing page."""
    featured = next(design for design in designs if design["featured"])
    cards = "\n".join(
        _design_card(design, repo_url=repo_url, commit=commit)
        for design in designs
    )
    featured_slug = _text(featured["slug"])
    featured_title = _text(featured["title"])
    short_commit = _text(commit[:8])
    guidebook_url = (
        f"{_text(repo_url)}/blob/{_text(commit)}/docs/guidebook/00-qa-workflow.md"
    )
    validation_url = (
        f"{_text(repo_url)}/blob/{_text(commit)}/docs/validation-envelope.md"
    )
    architecture_url = (
        f"{_text(repo_url)}/blob/{_text(commit)}/ARCHITECTURE.md"
    )
    return (
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Open, evidence-first aerostructures design reviews built with OpenVSP, OpenAeroStruct, and OpenMDAO.">
<title>open-air · Aircraft design in the open</title>
<style>
"""
        + REPORT_CSS
        + SITE_CSS
        + f"""
</style>
</head>
<body>
<header class="topbar"><div class="wrap"><div class="brand"><a href="./">open-air</a></div><nav><a href="#designs">Designs</a><a href="#workflow">How it works</a><a href="#evidence">Evidence</a><a href="{_text(repo_url)}">GitHub ↗</a></nav></div></header>
<main>
<section class="hero"><div class="wrap hero-grid">
  <div>
    <div class="eyebrow">Open aerostructures design suite</div>
    <h1>Aircraft concepts, engineered in the open.</h1>
    <p class="deck">One inspectable design source becomes OpenVSP geometry, OpenAeroStruct aerostructures, OpenMDAO optimization, and an evidence-rich design review you can challenge down to the exported mesh.</p>
    <div class="verdict"><span class="dot"></span>Public engineering artifacts, not a black-box score</div>
    <div class="stat-row">
      <div class="stat"><strong>{len(designs)}</strong><span>published designs</span></div>
      <div class="stat"><strong>12</strong><span>review gates</span></div>
      <div class="stat"><strong>3 + 3</strong><span>core + optional tools</span></div>
      <div class="stat"><strong>2</strong><span>analyzed phases</span></div>
    </div>
  </div>
  <a class="hero-showcase" href="designs/{featured_slug}/" aria-label="Open featured design {featured_title}">
    <img src="designs/{featured_slug}/baseline_vs_optimized.png" alt="{featured_title} baseline and optimized comparison">
    <span class="hero-caption"><b>Featured · {featured_title}</b><span>Open the full interactive review →</span></span>
  </a>
</div></section>

<section id="designs"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">01 · Published work</div><h2>Design reviews</h2></div><p>Each review binds a baseline aircraft and its optimized descendant to phase-local geometry, aerodynamic, structural, balance, and provenance evidence. Open a card to orbit the delivered mesh and inspect every gate.</p></div>
  <div class="cards">{cards}</div>
</div></section>

<section id="workflow" class="alt"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">02 · How it works</div><h2>From intent to inspectable evidence</h2></div><p>Python is the control plane; established geometry, aerodynamics, structures, optimization, and stretch-solver kernels stay intact. The source YAML remains authoritative throughout.</p></div>
  <div class="timeline">
    <div class="phase"><h3>Define</h3><p>Requirements, sketches, or a reference mesh become one schema-checked <code>design.yaml</code>.</p></div>
    <div class="phase"><h3>Analyze</h3><p>Sizing, OpenVSP geometry, aerodynamics, flight dynamics, and structures evaluate the baseline aircraft.</p></div>
    <div class="phase"><h3>Optimize</h3><p>OpenMDAO searches bounded design variables, then the delivered aircraft is independently re-evaluated.</p></div>
    <div class="phase"><h3>Challenge</h3><p>Twelve gates and optional TACS, VSPAERO, and SU2 cross-checks expose assumptions, failures, and model limits.</p></div>
  </div>
  <p style="margin-top:28px"><a class="button secondary" href="{architecture_url}">Read the architecture ↗</a></p>
</div></section>

<section id="evidence"><div class="wrap">
  <div class="section-head"><div><div class="eyebrow">03 · Engineering honesty</div><h2>Evidence, not claims</h2></div><p>A green pipeline is the beginning of review, not the end. Every headline value must trace to the same aircraft phase and every validation statement stays inside its recorded evidence class and intended use.</p></div>
  <div class="card evidence-callout">
    <h3>Read the verdict in context</h3>
    <p><code>ok: true</code> is a stage claim, not a verdict. Baseline and optimized results describe different aircraft and are never mixed in one claim. TACS and SU2 remain calibration cross-checks, not pass/fail evidence.</p>
    <p><a href="{guidebook_url}">AERO QA workflow ↗</a> · <a href="{validation_url}">Validation envelope ↗</a></p>
  </div>
</div></section>
</main>
<footer><div class="wrap site-footer-grid"><div><div class="brand">open-air</div><div>Agent-friendly aerostructures design, with the evidence left visible.</div></div><div class="site-footer-meta">Built from <a href="{_text(repo_url)}/commit/{_text(commit)}">{short_commit}</a><br>{_text(generated_at)}</div></div></footer>
</body>
</html>
"""
    )


def render_404(*, repo_url: str) -> str:
    """Render a small fallback page with the same visual language."""
    project_path = "/" + repo_url.rstrip("/").rsplit("/", 1)[-1] + "/"
    project_path_json = (
        json.dumps(project_path)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found · open-air</title>
<style>
"""
        + REPORT_CSS
        + SITE_CSS
        + f"""
</style>
</head>
<body>
<header class="topbar"><div class="wrap"><div class="brand"><a id="site-home-brand" href="./">open-air</a></div></div></header>
<main><section class="hero"><div class="wrap"><div class="eyebrow">404 · Not found</div><h1>This flight path ends here.</h1><p class="deck">The design review or artifact at this address is not published.</p><p><a class="button" id="site-home-button" href="./">Return to the design index</a> <a class="button secondary" href="{_text(repo_url)}">Open the repository ↗</a></p></div></section></main>
<script>
const siteHome = location.hostname.endsWith(".github.io") ? {project_path_json} : "/";
document.getElementById("site-home-brand").href = siteHome;
document.getElementById("site-home-button").href = siteHome;
</script>
</body>
</html>
"""
    )
