"""Shared visual theme for generated open-air HTML."""

from __future__ import annotations


REPORT_CSS = """:root { --ink:#102a34; --muted:#58707a; --paper:#f4f1ea; --card:#fffdf8; --navy:#082631; --teal:#1f7184; --orange:#e96f3d; --green:#287a52; --red:#b34235; --line:#d4ddd9; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; color:var(--ink); background:var(--paper); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.55; }
a { color:var(--teal); }
.wrap { width:min(1180px,calc(100% - 40px)); margin:auto; }
.topbar { position:sticky; top:0; z-index:10; background:rgba(8,38,49,.94); backdrop-filter:blur(12px); color:white; border-bottom:1px solid rgba(255,255,255,.12); }
.topbar .wrap { display:flex; align-items:center; justify-content:space-between; gap:22px; min-height:58px; }
.brand { font-weight:800; letter-spacing:.08em; text-transform:uppercase; font-size:.82rem; }
nav { display:flex; flex-wrap:wrap; gap:18px; }
nav a { color:#d6e7ec; text-decoration:none; font-size:.84rem; }
.hero { color:white; background:radial-gradient(circle at 80% 10%,#185c6f 0,#0b3542 35%,#061f29 72%); padding:66px 0 58px; overflow:hidden; }
.hero-grid { display:grid; grid-template-columns:minmax(0,.82fr) minmax(480px,1.18fr); gap:42px; align-items:center; }
.eyebrow { color:var(--orange); text-transform:uppercase; letter-spacing:.14em; font-weight:800; font-size:.73rem; }
h1 { margin:.2em 0 .22em; font-size:clamp(2.5rem,5vw,5.2rem); line-height:.96; letter-spacing:-.045em; }
.deck { color:#c9dce1; font-size:1.12rem; max-width:670px; }
.verdict { display:inline-flex; gap:9px; align-items:center; margin-top:16px; padding:8px 12px; border:1px solid rgba(255,255,255,.18); border-radius:999px; font-weight:750; }
.dot { width:9px; height:9px; border-radius:50%; background:#56d28a; box-shadow:0 0 0 5px rgba(86,210,138,.12); }
.verdict.fail .dot { background:#ff7d6f; }
.stat-row { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:27px; }
.stat { padding:14px 8px 10px; border-top:2px solid rgba(255,255,255,.24); }
.stat strong { display:block; font-size:1.55rem; letter-spacing:-.03em; }
.stat span { color:#a9c5cc; font-size:.76rem; text-transform:uppercase; letter-spacing:.08em; }
.viewer-shell { position:relative; border:1px solid rgba(255,255,255,.18); border-radius:18px; background:#071f29; overflow:hidden; box-shadow:0 28px 70px rgba(0,0,0,.35); }
#mesh-canvas { display:block; width:100%; aspect-ratio:1.35; touch-action:none; cursor:grab; }
#mesh-canvas:active { cursor:grabbing; }
.viewer-tools { position:absolute; top:12px; right:12px; display:flex; gap:7px; }
.viewer-tools button { color:white; background:rgba(6,27,35,.78); border:1px solid rgba(255,255,255,.22); border-radius:8px; padding:7px 10px; cursor:pointer; }
#viewer-notice { position:absolute; left:14px; bottom:12px; color:#bcd2d9; font-size:.73rem; background:rgba(4,20,27,.70); border-radius:6px; padding:5px 8px; }
section { padding:76px 0; }
section.alt { background:#e9eeeb; }
.section-head { display:grid; grid-template-columns:.55fr 1fr; gap:40px; margin-bottom:34px; align-items:end; }
.section-head h2 { margin:0; font-size:clamp(2rem,3.4vw,3.35rem); line-height:1; letter-spacing:-.04em; }
.section-head p { color:var(--muted); margin:0; max-width:720px; }
.cards { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
.card,.chart-card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:21px; box-shadow:0 6px 18px rgba(17,48,59,.04); }
.card h3,.chart-card h3 { margin:.25em 0 .5em; }
.score { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.score th { text-align:left; color:white; background:var(--navy); padding:11px 14px; font-size:.78rem; text-transform:uppercase; letter-spacing:.06em; }
.score td { border-top:1px solid var(--line); padding:11px 14px; vertical-align:top; }
.pass-row td:last-child { color:var(--green); font-weight:800; }
.fail-row td:last-child { color:var(--red); font-weight:800; }
.gates { display:grid; grid-template-columns:repeat(3,1fr); gap:13px; margin-top:28px; }
.gate { border-radius:12px; padding:16px; color:white; min-height:126px; }
.gate.pass { background:linear-gradient(145deg,#1d6747,#2d875c); }
.gate.fail { background:linear-gradient(145deg,#8c3028,#bc493d); }
.gate b { display:block; font-size:1rem; margin-bottom:8px; }
.gate p { margin:0; font-size:.82rem; color:rgba(255,255,255,.86); }
.gate small { display:block; margin-top:8px; color:rgba(255,255,255,.66); }
.charts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }
.chart-card { margin:0; padding:18px; }
.chart-card img { width:100%; display:block; margin-top:12px; border-radius:8px; background:white; }
.chart-card figcaption { color:var(--muted); font-size:.79rem; margin-top:10px; }
.table-scroll { max-height:432px; overflow-y:auto; border:1px solid var(--line); border-radius:12px; }
.table-scroll .score { border:0; border-radius:0; }
.table-scroll th { position:sticky; top:0; z-index:1; }
.timeline { display:grid; grid-template-columns:repeat(4,1fr); gap:0; counter-reset:phase; }
.phase { position:relative; padding:20px 19px 18px; border-top:3px solid var(--teal); background:var(--card); }
.phase + .phase { border-left:1px solid var(--line); }
.phase:before { counter-increment:phase; content:counter(phase); position:absolute; top:-17px; left:17px; width:30px; height:30px; display:grid; place-items:center; border-radius:50%; color:white; background:var(--teal); font-weight:800; }
.phase h3 { margin:12px 0 5px; }
.phase p { color:var(--muted); font-size:.86rem; }
.split { display:grid; grid-template-columns:1.2fr .8fr; gap:22px; align-items:start; }
.outcome-banner { display:grid; grid-template-columns:minmax(240px,auto) 1fr; gap:6px 34px; align-items:center; background:var(--card); border:1px solid var(--line); border-left:6px solid var(--green); border-radius:14px; padding:16px 22px; margin-bottom:30px; }
.outcome-banner.fail { border-left-color:var(--red); }
.outcome-status { display:flex; align-items:center; gap:11px; font-weight:800; font-size:1.06rem; letter-spacing:-.01em; }
.outcome-banner .dot { background:var(--green); box-shadow:0 0 0 5px rgba(40,122,82,.12); }
.outcome-banner.fail .dot { background:var(--red); box-shadow:0 0 0 5px rgba(179,66,53,.12); }
.outcome-text { margin:0; color:var(--muted); font-size:.92rem; }
.outcome-meta { grid-column:1 / -1; margin:0; padding-top:10px; border-top:1px solid var(--line); color:var(--muted); font-size:.78rem; }
.brief-col { min-width:0; }
.brief p,.brief ul,.brief ol { max-width:58rem; }
.brief > :first-child { margin-top:0; }
.brief h1,.brief h2,.brief h3,.brief h4 { color:var(--ink); letter-spacing:-.02em; line-height:1.25; }
.brief h1 { font-size:1.28rem; margin:0 0 .55em; }
.brief h2 { font-size:1.08rem; margin:1.35em 0 .45em; }
.brief h3,.brief h4 { font-size:1rem; margin:1.1em 0 .4em; }
.brief p,.brief ul,.brief ol { margin:0 0 .85em; }
.brief ul,.brief ol { padding-left:1.2em; }
.brief li { margin-bottom:.35em; }
.brief li > ul,.brief li > ol { margin:.35em 0 0; }
.brief code { font:.86em/1.45 ui-monospace,SFMono-Regular,Consolas,monospace; background:#e8eeec; border-radius:4px; padding:.08em .35em; }
.brief pre { color:var(--ink); background:#e8eeec; max-height:none; }
.brief .table-wrap { overflow-x:auto; margin:0 0 1em; border:1px solid var(--line); border-radius:12px; background:var(--card); }
.brief table { width:100%; border-collapse:collapse; font-size:.78rem; }
.brief th { text-align:left; color:white; background:var(--navy); padding:8px 10px; font-size:.72rem; text-transform:uppercase; letter-spacing:.04em; }
.brief td { border-top:1px solid var(--line); padding:8px 10px; vertical-align:top; }
.brief tr:nth-child(even) td { background:#f7f6f1; }
pre { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; color:#d8e5e8; background:#092a35; border-radius:12px; padding:20px; max-height:650px; overflow:auto; }
.assumptions li { margin-bottom:10px; }
.pill { display:inline-block; border-radius:999px; padding:3px 8px; font-size:.7rem; font-weight:800; text-transform:uppercase; letter-spacing:.06em; background:#d9e6e2; }
.pill.stretch { background:#f2dfc4; color:#744a16; }
.meta { color:var(--muted); font-size:.8rem; }
footer { color:#a9c5cc; background:var(--navy); padding:35px 0; }
details summary { cursor:pointer; font-weight:800; margin-bottom:14px; }
@media (max-width:900px) { .hero-grid,.section-head,.split,.outcome-banner { grid-template-columns:1fr; } .hero-grid { gap:24px; } .stat-row,.cards,.gates,.timeline { grid-template-columns:repeat(2,1fr); } .charts { grid-template-columns:1fr; } }
@media (max-width:560px) { .wrap { width:min(100% - 24px,1180px); } nav { display:none; } .hero { padding-top:42px; } .stat-row,.cards,.gates,.timeline { grid-template-columns:1fr; } .viewer-shell { margin-inline:-6px; } section { padding:54px 0; } }
@media print { .topbar,.viewer-tools { display:none; } .hero { color:var(--ink); background:white; } .deck { color:var(--muted); } section { break-inside:avoid; } }"""
