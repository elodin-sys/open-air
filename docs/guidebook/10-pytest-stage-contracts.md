# 10 — pytest and the stage-JSON contracts

## What it is

pytest (this venv runs **9.1.1**; the 8.x line ended at 8.4.2) is the
gatekeeper: fast contract tests on every push, slower physics smoke tests,
and optional `stretch` tests that only run where TACS/SU2 exist.
The pipeline's inter-stage contract is JSON:
`python -m openair.<stage> run <concept-or-yaml>` →
`results/<concept>/{baseline,optimized}/<stage>.json`
via [`src/openair/io.py`](../../src/openair/io.py) (`dump_stage`/`load_stage`).

## Source and docs

- pytest: [docs.pytest.org](https://docs.pytest.org/en/stable/) ·
  [github.com/pytest-dev/pytest](https://github.com/pytest-dev/pytest)
  - [markers](https://docs.pytest.org/en/stable/how-to/mark.html) ·
    [skipif](https://docs.pytest.org/en/stable/how-to/skipping.html) ·
    [tmp_path](https://docs.pytest.org/en/stable/how-to/tmp_path.html) ·
    [parametrize](https://docs.pytest.org/en/stable/how-to/parametrize.html)
- Extended notes: [`_research/pydantic-pytest.md`](_research/pydantic-pytest.md)

## Conventions in this repo

- Markers registered in [`pyproject.toml`](../../pyproject.toml): `slow`
  (heavier OAS/MDO runs), `stretch` (needs `SU2_CFD` on PATH or the micromamba
  `tacs` env; auto-skip otherwise).
- Contract tests assert **keys and gates**, not exact floats; physics tests
  assert **tolerance bands with documented rationale** (e.g. CDi within 25%
  of elliptic).
- Solver smoke tests shrink the mesh (`n_spanwise = 7`) to stay under a few
  seconds.
- Stage tests write into `tmp_path`, never into `results/` — the pipeline
  owns `results/`.
- Tests import stable design paths from `tests/conftest.py`; their YAML inputs
  live under `tests/fixtures/`, never under mutable `designs/` or generated
  `results/`.
- Warnings config lives in `pyproject.toml` (`filterwarnings`); OAS wingbox
  ComplexWarning noise is benign (chapter 03).

## The test map

| File | What it proves |
|---|---|
| `tests/test_env.py` | imports + tiny OAS VLM produces finite CL/CD |
| `tests/test_schema.py` | case invariants, computed fields, TSFC/ISA/Breguet identities |
| `tests/test_sizing.py` | endurance closure, packing, dash > cruise |
| `tests/test_balance.py` | thin-airfoil values, SM in band both fuel states, CG travel, stall |
| `tests/test_geometry.py` | mesh shape, packing, OpenVSP read-back match |
| `tests/test_aero.py` | positive lift, elliptic CDi band, pitch-trim solve |
| `tests/test_structures.py` | cantilever identity, wingbox failure ≤ 0 at +4g |
| `tests/test_mdo.py` | smoke run, optimized YAML re-validates and re-evaluates |
| `tests/test_io.py` | dump/load round-trip, stage JSON contract keys |
| `tests/test_validation_stage.py` | validation runner core checks structure |
| `tests/test_reporting.py` | report writes, honest dash Mach, gate rows |
| `tests/test_paths.py` | concept-dir, YAML, and generated optimized path resolution |
| `tests/test_presentation.py` | self-contained HTML mesh payload + PDF smoke |
| `tests/test_prototype_desires.py` | delivered prototype meets desires + gates |
| `tests/test_vspaero_polar.py` | polar parser on a recorded header |
| `tests/test_stretch.py` (`-m stretch`) | TACS/SU2 honesty when installed |

## Check your work

1. `pytest` green before and after your change; `pytest -m stretch` on this
   machine (tools are installed here).
2. A new stage output key used by QA gets a contract assertion the same day.
3. Regression bands: when a physics fix legitimately moves a number, update
   the band **and the rationale comment**, not just the number.
4. Never assert against `results/` contents in unit tests — run the stage
   into `tmp_path` and assert on its return + files there.

## Known lies

- A green suite that never runs the failing path (stretch tests silently
  skipping everywhere — check the skip report line).
- Float-equality tests that pass only on one BLAS.
- Tests that read stale `results/` artifacts and "pass" against an old design
  (the F13 class).
