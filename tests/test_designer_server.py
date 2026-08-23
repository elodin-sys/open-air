from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest
import yaml

import openair.designer.__main__ as designer_cli
from openair.designer.server import (
    ConceptWorkspace,
    WorkspaceConflict,
    WorkspaceError,
    concept_name,
    make_server,
)
from openair.schemas import VehicleSpec

PNG_1X1 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"open-air-test-image").decode(
    "ascii"
)


@contextmanager
def running_server(workspace: ConceptWorkspace) -> Iterator[str]:
    server = make_server(workspace, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def post_save(
    base_url: str,
    workspace: ConceptWorkspace,
    payload: dict,
    *,
    token: str | None = None,
) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base_url}/api/save",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Openair-Token": token or workspace.save_token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def valid_payload(workspace: ConceptWorkspace) -> dict:
    design_yaml = yaml.safe_dump(
        workspace.spec.model_dump(mode="json", exclude_computed_fields=True),
        sort_keys=False,
    )
    return {
        "design_yaml": design_yaml,
        "brief_md": (
            "# Server test\n\n"
            "<!-- OPENAIR_SKETCH_WORKSHEET_START -->\n"
            "## Sketch measurement worksheet\n"
            "<!-- OPENAIR_SKETCH_WORKSHEET_END -->\n"
        ),
        "sketches": [
            {
                "name": "sketch-top.png",
                "png_base64": PNG_1X1,
            },
            {
                "name": "sketch-top-rectified.png",
                "png_base64": PNG_1X1,
            },
        ],
    }


def test_new_workspace_has_complete_geometry_envelope(tmp_path: Path):
    workspace = ConceptWorkspace.new(
        "ready-default",
        designs_dir=tmp_path / "designs",
    )
    spec = workspace.spec

    assert spec.name == "ready-default"
    assert spec.sketch is not None
    assert spec.sketch.span_over_length == pytest.approx(
        spec.wing.span_m / spec.fuselage.length_m,
        abs=1e-6,
    )
    assert spec.sketch.root_over_length == pytest.approx(
        spec.wing.root_chord_m / spec.fuselage.length_m,
        abs=1e-6,
    )
    assert spec.sketch.x_le_root_over_length == pytest.approx(
        spec.wing.x_le_root_m / spec.fuselage.length_m,
        abs=1e-6,
    )
    for field in (
        "payload_bay_x_lo_m",
        "payload_bay_x_hi_m",
        "fuel_tank_x_lo_m",
        "fuel_tank_x_hi_m",
        "twist_tip_lo_deg",
        "twist_tip_hi_deg",
    ):
        assert getattr(spec.sketch, field) is not None
    assert spec.fuselage.stations is not None
    assert len(spec.fuselage.stations) >= 6
    assert all(
        station.side_power == station.top_power == station.bottom_power == 2.0
        for station in spec.fuselage.stations
    )


def test_new_server_saves_validated_workspace_bundle(tmp_path: Path):
    designs = tmp_path / "designs"
    workspace = ConceptWorkspace.new("server-test", designs_dir=designs)
    assert not workspace.target.exists()

    with running_server(workspace) as url:
        with urllib.request.urlopen(f"{url}/", timeout=3) as response:
            document = response.read().decode("utf-8")
        assert '"mode":"new"' in document
        assert workspace.save_token in document

        status, result = post_save(url, workspace, valid_payload(workspace))

    assert status == 200
    assert result["next"] == "/create-aero designs/server-test"
    assert result["written"] == [
        "design.yaml",
        "brief.md",
        "sketch-top-rectified.png",
        "sketch-top.png",
    ]
    spec = VehicleSpec.model_validate(
        yaml.safe_load((workspace.target / "design.yaml").read_text(encoding="utf-8"))
    )
    assert spec.name == "server-test"
    assert "## Sketch measurement worksheet" in (
        workspace.target / "brief.md"
    ).read_text(encoding="utf-8")
    assert (
        (workspace.target / "sketch-top.png")
        .read_bytes()
        .startswith(b"\x89PNG\r\n\x1a\n")
    )
    assert (workspace.target / "sketch-top-rectified.png").is_file()

    edited = ConceptWorkspace.edit("designs/server-test", designs_dir=designs)
    assert edited.mode == "edit"
    assert edited.spec.name == "server-test"
    (edited.target / "keep-me.txt").write_text("preserved", encoding="utf-8")
    update = valid_payload(edited)
    update["brief_md"] = "# Updated brief\n"
    update["sketches"] = []
    edit_result = edited.save(update)
    assert edit_result["written"] == ["design.yaml", "brief.md"]
    assert (edited.target / "brief.md").read_text(
        encoding="utf-8"
    ) == "# Updated brief\n"
    assert (edited.target / "keep-me.txt").read_text(encoding="utf-8") == "preserved"
    assert (edited.target / "sketch-top.png").is_file()


def test_invalid_yaml_writes_nothing(tmp_path: Path):
    workspace = ConceptWorkspace.new(
        "invalid-yaml",
        designs_dir=tmp_path / "designs",
    )
    payload = valid_payload(workspace)
    payload["design_yaml"] = "fuselage:\n  length_m: -4\n"

    with running_server(workspace) as url:
        status, result = post_save(url, workspace, payload)

    assert status == 400
    assert "validation failed" in result["error"]
    assert not workspace.target.exists()


def test_sketch_filename_whitelist_is_enforced_before_writing(tmp_path: Path):
    workspace = ConceptWorkspace.new(
        "bad-sketch-name",
        designs_dir=tmp_path / "designs",
    )
    payload = valid_payload(workspace)
    payload["sketches"][0]["name"] = "../escape.png"

    with running_server(workspace) as url:
        status, result = post_save(url, workspace, payload)

    assert status == 400
    assert "not allowed" in result["error"]
    assert not workspace.target.exists()
    assert not (tmp_path / "escape.png").exists()


def test_save_requires_session_token(tmp_path: Path):
    workspace = ConceptWorkspace.new(
        "token-test",
        designs_dir=tmp_path / "designs",
    )
    with running_server(workspace) as url:
        status, result = post_save(
            url,
            workspace,
            valid_payload(workspace),
            token="wrong-token",
        )

    assert status == 403
    assert result["error"] == "invalid save token"
    assert not workspace.target.exists()


def test_new_refuses_existing_and_edit_requires_existing(tmp_path: Path):
    designs = tmp_path / "designs"
    existing = designs / "already-there"
    existing.mkdir(parents=True)

    with pytest.raises(WorkspaceConflict, match="already exists"):
        ConceptWorkspace.new("already-there", designs_dir=designs)
    with pytest.raises(FileNotFoundError, match="Concept not found"):
        ConceptWorkspace.edit("missing", designs_dir=designs)


@pytest.mark.parametrize(
    "value",
    [
        "../escape",
        "/absolute",
        "designs/nested/name",
        "other/name",
        "_reserved",
        "bad name",
    ],
)
def test_concept_name_rejects_paths_outside_canonical_workspace(value: str):
    with pytest.raises(WorkspaceError):
        concept_name(value)


def test_new_session_refuses_racing_folder_creation(tmp_path: Path):
    workspace = ConceptWorkspace.new(
        "racing-concept",
        designs_dir=tmp_path / "designs",
    )
    workspace.target.mkdir(parents=True)

    with pytest.raises(WorkspaceConflict, match="appeared while editing"):
        workspace.save(valid_payload(workspace))


@pytest.mark.parametrize("action", ["new", "edit"])
def test_cli_dispatches_workspace_subcommands(monkeypatch, action: str):
    workspace = object()
    monkeypatch.setattr(
        designer_cli.ConceptWorkspace,
        action,
        lambda value: workspace,
    )
    called: dict = {}
    monkeypatch.setattr(
        designer_cli,
        "serve_workspace",
        lambda selected, **options: called.update(
            workspace=selected,
            **options,
        ),
    )

    designer_cli.main([action, "cli-concept", "--port", "4321", "--open"])

    assert called == {
        "workspace": workspace,
        "port": 4321,
        "open_browser": True,
    }


def test_cli_open_existing_concept_dispatches_edit_workspace(monkeypatch):
    workspace = object()
    monkeypatch.setattr(
        designer_cli.ConceptWorkspace,
        "edit",
        lambda value: workspace,
    )
    monkeypatch.setattr(
        designer_cli,
        "generate_design_studio",
        lambda *args, **kwargs: pytest.fail("static Studio should not be generated"),
    )
    called: dict = {}
    monkeypatch.setattr(
        designer_cli,
        "serve_workspace",
        lambda selected, **options: called.update(
            workspace=selected,
            **options,
        ),
    )

    designer_cli.main(["cli-concept", "--open"])

    assert called == {
        "workspace": workspace,
        "port": 0,
        "open_browser": True,
    }


@pytest.mark.parametrize(
    ("argv", "expected_concept", "expected_output", "opens_browser"),
    [
        (["cli-concept"], "cli-concept", None, False),
        (
            ["cli-concept", "--open", "-o", "custom-studio.html"],
            "cli-concept",
            Path("custom-studio.html"),
            True,
        ),
        (
            ["designs/cli-concept/design.yaml", "--open"],
            "designs/cli-concept/design.yaml",
            None,
            True,
        ),
    ],
)
def test_cli_shortcut_preserves_static_generation_modes(
    tmp_path: Path,
    monkeypatch,
    argv: list[str],
    expected_concept: str,
    expected_output: Path | None,
    opens_browser: bool,
):
    target = tmp_path / "static-studio.html"
    generated: dict = {}

    def reject_edit(value: str) -> None:
        raise WorkspaceError(f"{value}: not a workspace path")

    monkeypatch.setattr(
        designer_cli.ConceptWorkspace,
        "edit",
        reject_edit,
    )
    monkeypatch.setattr(
        designer_cli,
        "generate_design_studio",
        lambda concept, *, output=None: (
            generated.update(concept=concept, output=output) or target
        ),
    )
    monkeypatch.setattr(
        designer_cli,
        "serve_workspace",
        lambda *args, **kwargs: pytest.fail("workspace server should not start"),
    )
    opened: list[str] = []
    monkeypatch.setattr(designer_cli.webbrowser, "open", opened.append)

    designer_cli.main(argv)

    assert generated == {
        "concept": expected_concept,
        "output": expected_output,
    }
    assert bool(opened) is opens_browser
