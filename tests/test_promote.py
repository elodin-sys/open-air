from pathlib import Path

import pytest
import yaml

import openair.cli as cli
import openair.paths as paths
from openair.schemas import VehicleSpec


def _write_spec(path: Path, spec: VehicleSpec) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(spec.model_dump(mode="python"), sort_keys=False),
        encoding="utf-8",
    )


def test_promote_copies_optimized_yaml_provenance_and_sketches(
    tmp_path,
    monkeypatch,
):
    designs = tmp_path / "designs"
    results = tmp_path / "results"
    designs.mkdir()
    results.mkdir()
    monkeypatch.setattr(paths, "DESIGNS_DIR", designs)
    monkeypatch.setattr(paths, "RESULTS_DIR", results)
    monkeypatch.setattr(cli, "DESIGNS_DIR", designs)

    source = VehicleSpec(name="source-concept")
    _write_spec(designs / "source-concept" / "design.yaml", source)
    (designs / "source-concept" / "brief.md").write_text(
        "# Original brief\n",
        encoding="utf-8",
    )
    (designs / "source-concept" / "sketch-top.png").write_bytes(
        b"\x89PNG\r\n\x1a\nfixture"
    )
    reference = designs / "source-concept" / "reference"
    reference.mkdir()
    (reference / "reference.json").write_text('{"schema": "openair.reference/1"}', encoding="utf-8")
    (reference / "reference.ply").write_bytes(b"ply fixture")
    optimized = source.model_copy(deep=True)
    optimized.wing.span_m = 4.2
    _write_spec(results / "source-concept" / "optimized" / "design.yaml", optimized)

    destination = cli.promote_design("source-concept", "promoted-v2")
    promoted = cli.load_spec(destination)

    assert destination == designs / "promoted-v2"
    assert promoted.name == "promoted-v2"
    assert promoted.wing.span_m == 4.2
    assert "Promoted from source-concept" in promoted.notes
    assert (destination / "sketch-top.png").exists()
    # The measured reference model travels with the promoted concept.
    assert (destination / "reference" / "reference.json").exists()
    assert (destination / "reference" / "reference.ply").exists()
    brief = (destination / "brief.md").read_text(encoding="utf-8")
    assert "Promotion provenance" in brief
    assert "Original brief" in brief
    assert "reference/" in brief

    with pytest.raises(FileExistsError):
        cli.promote_design("source-concept", "promoted-v2")
