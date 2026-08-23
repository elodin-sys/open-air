from pathlib import Path

import openair.paths as paths


def test_resolve_design_directory_and_yaml(tmp_path: Path, monkeypatch):
    designs = tmp_path / "designs"
    results = tmp_path / "results"
    design_yaml = designs / "demo" / "design.yaml"
    design_yaml.parent.mkdir(parents=True)
    design_yaml.write_text("{}\n")
    monkeypatch.setattr(paths, "DESIGNS_DIR", designs)
    monkeypatch.setattr(paths, "RESULTS_DIR", results)

    for argument in (design_yaml.parent, design_yaml):
        concept, resolved, root = paths.resolve_design(argument)
        assert concept == "demo"
        assert resolved == design_yaml.resolve()
        assert root == results / "demo"
        assert paths.results_dir_for(argument) == results / "demo" / "baseline"


def test_resolve_design_generated_optimized_yaml(tmp_path: Path, monkeypatch):
    designs = tmp_path / "designs"
    results = tmp_path / "results"
    optimized = results / "demo" / "optimized" / "design.yaml"
    optimized.parent.mkdir(parents=True)
    optimized.write_text("{}\n")
    monkeypatch.setattr(paths, "DESIGNS_DIR", designs)
    monkeypatch.setattr(paths, "RESULTS_DIR", results)

    concept, resolved, root = paths.resolve_design(optimized)
    assert concept == "demo"
    assert resolved == optimized.resolve()
    assert root == results / "demo"
    assert paths.results_dir_for(optimized) == optimized.parent
