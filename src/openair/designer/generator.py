"""Generate the self-contained open-air Design Studio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openair.designer.template import STUDIO_TEMPLATE
from openair.io import load_yaml
from openair.paths import DESIGNS_DIR, resolve_design
from openair.schemas import VehicleSpec


def _dereference(node: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in node:
        return schema["$defs"][node["$ref"].rsplit("/", 1)[-1]]
    for option in node.get("anyOf", []):
        if option.get("type") != "null":
            return _dereference(option, schema)
    return node


def schema_field_paths(schema: dict[str, Any] | None = None) -> list[str]:
    """Return every model field as a stable dotted editor contract path."""
    root = schema or VehicleSpec.model_json_schema()
    paths: list[str] = []

    def visit(node: dict[str, Any], prefix: str) -> None:
        resolved = _dereference(node, root)
        for name, child in resolved.get("properties", {}).items():
            path = f"{prefix}.{name}" if prefix else name
            paths.append(path)
            child_resolved = _dereference(child, root)
            if child_resolved.get("type") == "array":
                item = _dereference(child_resolved.get("items", {}), root)
                visit(item, f"{path}[]")
            else:
                visit(child_resolved, path)

    visit(root, "")
    return paths


def build_design_studio(
    spec: VehicleSpec,
    *,
    concept: str = "new-concept",
    source_name: str = "design.yaml",
    mode: str = "file",
    brief_md: str = "",
    save_token: str | None = None,
) -> str:
    """Render one offline HTML document containing schema, data, CSS, and JS."""
    if mode not in {"file", "new", "edit"}:
        raise ValueError(f"unsupported Design Studio mode: {mode}")
    schema = VehicleSpec.model_json_schema()
    payload = {
        "schema": schema,
        "initial": spec.model_dump(mode="json", exclude_computed_fields=True),
        "fieldPaths": schema_field_paths(schema),
        "concept": concept,
        "sourceName": source_name,
        "mode": mode,
        "briefMd": brief_md,
        "saveToken": save_token,
        "version": 1,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Script elements use HTML raw-text parsing even for application/json.
    # Escaping every "<" as JSON keeps comment/script delimiters invisible to
    # the HTML parser without introducing invalid escapes such as "\!".
    encoded = encoded.replace("<", "\\u003c")
    return STUDIO_TEMPLATE.replace("__OPENAIR_STUDIO_PAYLOAD__", encoded)


def generate_design_studio(
    design: str | Path | None = None,
    *,
    output: str | Path | None = None,
) -> Path:
    """Generate ``design-studio.html`` for a concept or the repository template."""
    if design is None:
        concept = "new-concept"
        design_yaml = DESIGNS_DIR / "_template" / "design.yaml"
    else:
        concept, design_yaml, _ = resolve_design(design)
    spec = VehicleSpec.model_validate(load_yaml(design_yaml))
    brief_path = design_yaml.parent / "brief.md"
    brief_md = (
        brief_path.read_text(encoding="utf-8")
        if brief_path.is_file()
        else "# Concept brief\n"
    )
    target = (
        Path(output).expanduser()
        if output is not None
        else (
            Path.cwd() / "design-studio.html"
            if design is None
            else design_yaml.parent / "design-studio.html"
        )
    )
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        build_design_studio(
            spec,
            concept=concept,
            source_name=design_yaml.name,
            mode="file",
            brief_md=brief_md,
        ),
        encoding="utf-8",
    )
    return target
