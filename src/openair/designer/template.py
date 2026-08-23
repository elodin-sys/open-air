"""Assemble the self-contained Design Studio from packaged assets."""

from __future__ import annotations

from pathlib import Path

_ASSETS = Path(__file__).with_name("assets")


def _asset(relative: str) -> str:
    return (_ASSETS / relative).read_text(encoding="utf-8")


def _build_template() -> str:
    replacements = {
        "__OPENAIR_STUDIO_CSS__": _asset("studio.css"),
        "__OPENAIR_THREE_VENDOR__": _asset("vendor/three.classic.min.js"),
        "__OPENAIR_STUDIO_HANDLES__": _asset("handles.js"),
        "__OPENAIR_STUDIO_PREVIEW_MESH__": _asset("preview_mesh.js"),
        "__OPENAIR_STUDIO_VIEWPORT3D__": _asset("viewport3d.js"),
        "__OPENAIR_STUDIO_CORE__": _asset("core.js"),
    }
    template = _asset("studio.html")
    for marker, contents in replacements.items():
        template = template.replace(marker, contents)
    return template


STUDIO_TEMPLATE = _build_template()
