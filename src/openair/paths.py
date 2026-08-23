"""Repository locations and runtime library path setup."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
DESIGNS_DIR = REPO_ROOT / "designs"
RESULTS_DIR = REPO_ROOT / "results"
DOCS_DIR = REPO_ROOT / "docs"
TRUTH_DIR = REPO_ROOT / "truth"
TOOLS_DIR = REPO_ROOT / "tools"
OPENVSP_DIR = TOOLS_DIR / "openvsp" / "opt" / "OpenVSP"
LIB_DIR = TOOLS_DIR / "libs" / "usr" / "lib" / "x86_64-linux-gnu"


def truth_results_dir(case_id: str) -> Path:
    """Return the isolated prediction/score directory for one truth case."""
    return RESULTS_DIR / "truth" / case_id


def configure_runtime() -> None:
    """Put extracted OpenVSP binaries and .deb libraries on the process path."""
    lib = str(LIB_DIR)
    current = os.environ.get("LD_LIBRARY_PATH", "")
    parts = [p for p in current.split(":") if p]
    if lib not in parts and LIB_DIR.is_dir():
        os.environ["LD_LIBRARY_PATH"] = lib + ((":" + current) if current else "")
    bindir = str(OPENVSP_DIR)
    su2bin = str(TOOLS_DIR / "su2" / "bin")
    path_parts = os.environ.get("PATH", "").split(":")
    extras = [p for p in (bindir, su2bin) if p not in path_parts and Path(p).is_dir()]
    if extras:
        os.environ["PATH"] = ":".join(extras) + ":" + os.environ.get("PATH", "")
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    os.environ.setdefault("OPENMDAO_REPORTS", "0")


def _candidate_design(path: str | Path) -> Path:
    """Resolve a CLI design argument to a YAML path.

    A bare concept name is shorthand for ``designs/<name>``. Existing
    directories are expected to contain ``design.yaml``.
    """
    raw = Path(path).expanduser()
    if (
        not raw.exists()
        and len(raw.parts) == 1
        and raw.suffix.lower() not in {".yaml", ".yml"}
    ):
        raw = DESIGNS_DIR / raw
    if raw.is_dir():
        raw = raw / "design.yaml"
    if not raw.exists():
        raise FileNotFoundError(
            f"Design not found: {path}. Expected a concept directory or design YAML."
        )
    if raw.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError(f"Design must be a YAML file: {raw}")
    return raw.resolve()


def resolve_design(path: str | Path) -> tuple[str, Path, Path]:
    """Return ``(concept_name, design_yaml, results_root)`` for a design.

    Source concepts under ``designs/`` publish into ``results/<concept>``.
    Generated designs already under ``results/<concept>/<phase>/`` remain
    attached to that concept and write beside their YAML.
    """
    design_yaml = _candidate_design(path)
    try:
        rel = design_yaml.relative_to(RESULTS_DIR.resolve())
    except ValueError:
        rel = None

    if rel is not None and len(rel.parts) >= 3:
        concept_name = rel.parts[0]
    else:
        try:
            design_rel = design_yaml.relative_to(DESIGNS_DIR.resolve())
        except ValueError:
            design_rel = None
        if design_rel is not None and len(design_rel.parts) >= 2:
            concept_name = design_rel.parts[0]
        elif design_yaml.name in {"design.yaml", "design.yml"}:
            concept_name = design_yaml.parent.name
        else:
            concept_name = design_yaml.stem

    return concept_name, design_yaml, RESULTS_DIR / concept_name


def case_stem(case_path: str | Path) -> str:
    """Compatibility name for callers that still describe a design as a case."""
    return resolve_design(case_path)[0]


def results_root_for(design_path: str | Path) -> Path:
    return resolve_design(design_path)[2]


def results_dir_for(design_path: str | Path) -> Path:
    """Return the phase directory for a source or generated design."""
    _, design_yaml, results_root = resolve_design(design_path)
    try:
        rel = design_yaml.relative_to(results_root.resolve())
    except ValueError:
        rel = None
    if (
        rel is not None
        and len(rel.parts) >= 2
        and rel.parts[0] in {"baseline", "optimized"}
    ):
        out = design_yaml.parent
    else:
        out = results_root / "baseline"
    out.mkdir(parents=True, exist_ok=True)
    return out


def optimized_design_for(design_path: str | Path) -> Path:
    """Canonical path where MDO publishes the child design."""
    return results_root_for(design_path) / "optimized" / "design.yaml"
