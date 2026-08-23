from pathlib import Path

from openair.paths import configure_runtime

configure_runtime()

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
# Shared test inputs must never depend on mutable user concepts or generated results.
BASELINE_DESIGN = FIXTURES_DIR / "reference-design.yaml"
FORWARD_SWEPT_DESIGN = FIXTURES_DIR / "forward-swept-design.yaml"
INSPIRATION_DESIGN = FIXTURES_DIR / "inspiration-design.yaml"
TRIM_INFEASIBLE_DESIGN = FIXTURES_DIR / "trim-infeasible-design.yaml"
