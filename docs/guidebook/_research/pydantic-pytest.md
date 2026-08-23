# Research notes: Pydantic v2 + pytest for the open-air QA guidebook

Scope: schema-first YAML cases (`cases/*.yaml` -> `VehicleSpec`) and stage-JSON contract
testing (`results/<case>/<stage>.json`). Facts below were verified against the live docs
on 2026-08-19 and against this repo (`src/openair/schemas.py`, `src/openair/io.py`,
`src/openair/cli.py`, `src/openair/mission/sizing.py`, `src/openair/mdo/problem.py`,
`tests/`, `pyproject.toml`).

Version reality check (this repo's venv, 2026-08-19): **pydantic 2.13.4** and
**pytest 9.1.1** are installed. `pyproject.toml` pins `pydantic>=2` and an unpinned
`pytest` dev extra. The pytest 8 line ended at **8.4.2 (2025-09-03)**; 9.x is current, so
`docs.pytest.org/en/stable/` now documents 9.x. Everything cited here (markers, skipif,
tmp_path, parametrize, filterwarnings) is behaviorally identical between 8.4 and 9.1 for
our purposes; if the guidebook must target pytest 8 exactly, pin `pytest>=8,<9` and cite
the version-pinned docs at `docs.pytest.org/en/8.4.x/`.

---

## 1. Links

Top-level:

- Pydantic v2 docs: <https://docs.pydantic.dev/latest/>
- Pydantic source: <https://github.com/pydantic/pydantic>
- pytest docs (stable): <https://docs.pytest.org/en/stable/> (pytest-8-pinned: <https://docs.pytest.org/en/8.4.x/>)
- pytest source: <https://github.com/pytest-dev/pytest>

Pydantic deep links (all verified live):

- `computed_field` concept: <https://docs.pydantic.dev/latest/concepts/fields/#the-computed_field-decorator>
- `computed_field` API: <https://docs.pydantic.dev/latest/api/fields/#pydantic.fields.computed_field>
- Validating data (`model_validate`, `model_validate_json`, `model_validate_strings`): <https://docs.pydantic.dev/latest/concepts/models/#validating-data>
- `model_validate` API: <https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_validate>
- Serialization (`model_dump`, `model_dump_json`, include/exclude): <https://docs.pydantic.dev/latest/concepts/serialization/>
- `model_dump` API: <https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_dump>
- `model_copy`: <https://docs.pydantic.dev/latest/concepts/models/#model-copy>
- Validators (field/model, before/after/plain/wrap): <https://docs.pydantic.dev/latest/concepts/validators/>
- Field constraints (`Field(gt=..., le=...)`): <https://docs.pydantic.dev/latest/concepts/fields/#field-constraints>
- Extra data (`extra='ignore'|'forbid'|'allow'`): <https://docs.pydantic.dev/latest/concepts/models/#extra-data>
- v1 -> v2 migration guide (`parse_obj` -> `model_validate`, `.dict()` -> `model_dump`, `.copy()` -> `model_copy`): <https://docs.pydantic.dev/latest/migration/>

pytest deep links (all verified live):

- Markers: <https://docs.pytest.org/en/stable/how-to/mark.html>
- skip / skipif / xfail: <https://docs.pytest.org/en/stable/how-to/skipping.html>
- `tmp_path`: <https://docs.pytest.org/en/stable/how-to/tmp_path.html>
- Parametrize: <https://docs.pytest.org/en/stable/how-to/parametrize.html>
- Warnings capture and `filterwarnings`: <https://docs.pytest.org/en/stable/how-to/capture-warnings.html>
- `pytest.approx` and config reference (`confval-filterwarnings`, `confval-markers`): <https://docs.pytest.org/en/stable/reference/reference.html>

---

## 2. Intended use in this pipeline

- **`VehicleSpec` is the single source of truth.** `src/openair/schemas.py` defines a
  nested model tree (`EngineSpec`, `WingSpec`, `FuselageSpec`, `VerticalTailSpec`,
  `HorizontalTailSpec`, `MissionSpec`, `StructureSpec`/`MaterialSpec`, `MassGuessSpec`,
  `SolverSpec`). Every field has a default, so `VehicleSpec()` is a complete, runnable
  vehicle; case YAML only overrides deltas.
- **Concept YAML in, validated spec out.** `openair.cli.load_spec` resolves a
  concept folder or YAML, then calls `VehicleSpec.model_validate(load_yaml(design_path))`;
  `load_yaml` (`src/openair/io.py`)
  rejects non-mapping YAML with `ValueError` before Pydantic ever sees it. Anything the
  schema does not catch here reaches the solvers.
- **Every stage writes into its concept phase.** `io.dump_stage` resolves
  `results/<concept>/{baseline,optimized}/<stage>.json` and `dump_json` serializes with a custom
  `_json_default` that converts numpy arrays/scalars and calls `model_dump()` on any
  Pydantic object. `load_stage` returns `None` for missing stages. These JSON files are
  the natural contract surface for QA: downstream stages and the report consume them.
- **Specs also round-trip through YAML mid-pipeline.** Sizing writes
  `baseline/target_sized.yaml` and the MDO stage writes
  `optimized/design.yaml`, both via
  `yaml.safe_dump(spec.model_dump(mode="python"))`, and both are later re-read with
  `VehicleSpec.model_validate(yaml.safe_load(...))`. So the schema is not only the input
  gate; it is a wire format between stages, and round-trip fidelity is a testable
  invariant.

---

## 3. Pydantic v2 best practices for this codebase

**`model_validate`, not `parse_obj`.** v1's `parse_obj`/`parse_raw`/`.dict()`/`.copy()`
are deprecated shims in v2; the v2 names are `model_validate` / `model_validate_json` /
`model_dump` / `model_copy` (migration guide). The repo is already consistently on the
v2 API. Two useful extras on `model_validate`: `strict=` per call, and (pydantic >= 2.12)
a per-call `extra=` override of the model's extra-data config — handy for validating
hand-authored case YAML strictly without changing model config globally. For JSON input
prefer `model_validate_json(raw)` over `model_validate(json.loads(raw))` (faster, and
JSON-mode validation semantics).

**`model_copy(deep=True)` for optimizer perturbation.** `model_copy()` is **shallow by
default**: the copy shares nested sub-models, so `copy.wing.span_m = ...` on a shallow
copy would mutate the base spec's `WingSpec` too. The repo does this correctly in all
three places that perturb specs (`mdo/problem.py::_apply_dvs`,
`mission/sizing.py::size_vehicle`, `structures/oas_wingbox.py`,
`validation/runner.py`). Caveat: `model_copy` performs **no validation**, and neither
does plain attribute assignment (see gotchas) — a perturbed spec is only as valid as the
code that perturbed it. `_apply_dvs` casting every optimizer value through `float()`
before assignment is load-bearing, not cosmetic.

**Computed fields ARE included in `model_dump`.** Confirmed in docs (the `Box.volume`
example appears in `model_dump()` output). Implications here:

- `WingSpec` dumps `tip_chord_m`, `area_m2`, `aspect_ratio`, `mac_m`, `y_mac_m`,
  `x_le_mac_m`, `x_ac_m`; tails dump `area_m2`; `MaterialSpec` dumps `G_pa`;
  `VehicleSpec` dumps `n_ult`. So `target_sized.yaml` / `optimized/design.yaml`
  contain derived geometry alongside the driving fields.
- Re-validating such a dump works **because `extra='ignore'` is the v2 default**: the
  computed keys are silently dropped on input and recomputed from the driving fields.
  This is the mechanism that makes the current pipeline round-trip safe.
- `extra='ignore'` vs `'forbid'`: flipping the models to `extra='forbid'` (tempting for
  catching typos like `tapper: 0.32` in case YAML) would instantly break re-validation
  of every machine-dumped YAML, because the computed keys become forbidden extras.
  Options if stricter input checking is wanted: (a) keep `ignore` on the models and
  validate hand-authored cases via `model_validate(data, extra='forbid')` on a path that
  never sees machine dumps; (b) strip computed fields at dump time — pydantic 2.13 added
  `@computed_field(exclude_if=...)` for conditional exclusion, or build the dump from
  `type(m).model_fields` keys only; (c) a standalone QA lint that recursively diffs YAML
  keys against `model_fields`. Do not naively set `extra='forbid'` in `model_config`.
- Note `@computed_field` wraps a plain `@property`: no caching, no invalidation, no
  validation of the computed value. `x_ac_m` chains four other computed properties —
  cheap here, but recomputed on every access and every dump.

**Field validators for physical bounds.** The schema currently has **no validators**;
nonsense inputs validate cleanly and then poison solvers or crash computed fields
(`taper=-1.0` -> `ZeroDivisionError` inside `mac_m`; `span_m=0` -> `ZeroDivisionError`
in `aspect_ratio`; negative chords -> negative areas fed to OAS). Recommended layers:

- Simple bounds via constrained fields, which also self-document in JSON schema:
  `span_m: float = Field(default=3.80, gt=0)`, `taper: float = Field(default=0.32, gt=0, le=1)`
  (the requested `0 < taper <= 1`), `t_over_c: float = Field(default=0.12, gt=0, lt=0.5)`,
  `payload_kg: float = Field(default=22.7, ge=0)`. Annotated aliases (`PositiveFloat`)
  are equivalent.
- `@field_validator(..., mode='after')` for checks needing logic, and
  `@model_validator(mode='after')` for cross-field physics
  (`static_margin_min < static_margin_max`, `dash_altitude_m <= cruise_altitude_m`,
  payload bay fits inside fuselage).
- Literal types already guard categorical fields (`fem_model_type: Literal["tube", "wingbox"]`)
  — but only at validation time, not on attribute assignment (see gotchas).

**Unit conventions in field names.** The schema consistently encodes SI units as
suffixes: `_m`, `_m2`, `_kg`, `_kg_s`, `_kg_m3`, `_deg`, `_pa`, `_n`, and dimensionless
names bare (`taper`, `t_over_c`, `nu`). This is the cheapest unit-safety system
available: it makes unit errors visible at every call site and in every dumped JSON/YAML
key. Guidebook rule: any new field carries a unit suffix or is explicitly dimensionless;
degrees stay `_deg` at the schema boundary and convert to radians only inside
computations (as `x_le_mac_m` does with `math.radians`).

---

## 4. pytest best practices for a solver pipeline

**Register markers in `pyproject.toml`.** No markers are registered today. Unknown
marks only warn by default, so a typo like `@pytest.mark.slwo` silently always-runs.
Register and enforce:

```toml
[tool.pytest.ini_options]
addopts = "-q --durations=20 --strict-markers"
markers = [
    "slow: full-resolution solver runs (> ~30 s); deselect with -m 'not slow'",
    "stretch: aspirational/known-failing physics targets, not CI-gating",
    "solver: needs an external solver binary (SU2, VSPAERO) on PATH",
]
```

Then `pytest -m "not slow"` is the default CI lane and the nightly lane runs everything.
`--strict-markers` turns unregistered marks into collection errors.

**`skipif` on missing binaries.** Standard pattern for optional external solvers:

```python
import shutil, pytest

requires_su2 = pytest.mark.skipif(
    shutil.which("SU2_CFD") is None, reason="SU2_CFD not on PATH"
)
```

Reusable module-level marks keep the reason string in one place. For optional Python
modules use `openvsp = pytest.importorskip("openvsp")` at module top. The skip reason
shows up in the summary, which is the difference between "CFD is red" and "CFD did not
run on this machine" — important for a pipeline where OpenVSP/SU2/gmsh availability
varies by machine.

**`tmp_path` for stage outputs.** `tmp_path` is a per-test, uniquely named
`pathlib.Path`; pytest keeps the last 3 test-run roots and prunes older ones. The
existing tests already use the right pattern — `run_geometry_stage(spec, tmp_path)`,
`run_mdo_stage(spec, tmp_path, None)` — passing `tmp_path` as the stage `outdir` instead
of letting anything resolve the real `results/` tree. Guidebook rule: tests never call
`dump_stage`/`load_stage` against a real case path; they pass `tmp_path` explicitly (or
monkeypatch `openair.paths.results_dir_for`).

**Contract tests: keys and types, not exact floats.** Each stage's JSON is a contract.
Assert its shape, not its physics:

```python
def test_sizing_contract(tmp_path):
    out = run_sizing_stage(load_spec(CASE), tmp_path)
    assert {"ok", "endurance_s", "masses", "sized_spec"} <= out.keys()
    assert isinstance(out["endurance_s"], float)
    payload = json.loads((tmp_path / "mass_breakdown.json").read_text())  # JSON-serializable proof
```

Round-tripping through `json.dumps`/`json.loads` in the test also proves
`_json_default` handled every numpy object. Exact-float assertions on solver outputs are
what break on BLAS/OS/library upgrades; key/type assertions are what catch real contract
regressions (renamed keys, numpy types leaking through).

**Tolerance-band regression tests with documented bands.** The repo already does this
well in `tests/test_schema.py`: TSFC hand-calc within +/-0.02, ISA sea-level `rho` within
+/-0.002, Breguet identity within 5 s. Guidebook rule: every band gets a comment saying
where the reference number comes from (spec sheet, hand calc, textbook) and why the
width was chosen (discretization error, iteration tolerance). Use
`pytest.approx(expected, rel=..., abs=...)` — spell the tolerances out; the default
`rel=1e-6` is far too tight for VLM/FEA outputs. Physics-reference checks like
`validation/runner.py`'s OAS-vs-elliptic induced drag comparison belong in this bucket
with an explicit band (e.g. within 10% of `CL^2 / (pi * AR * e)`).

**Keep solver smoke tests fast by shrinking the problem, not skipping it.** Existing
good examples: `test_env.py::test_tiny_oas_vlm` runs a full OAS VLM at `num_y=7,
num_x=3`; `test_mdo.py::test_mdo_smoke` sets `optimize_maxiter=3, optimize_tol=1e-3`.
The knobs are already in the schema (`SolverSpec.optimize_maxiter`,
`StructureSpec.n_spanwise/n_chordwise`, `SolverSpec.gmsh_lc_m`), so smoke tests just
override spec fields — no special test hooks needed. Target: smoke lane a few seconds
per solver; anything needing full resolution gets `@pytest.mark.slow`. `--durations=20`
(already in `addopts`) is the watchdog for creep.

**`parametrize` for case sweeps.** Natural uses here: one test body over many invalid
YAML fragments (rejection table, section 6), geometry invariants over a `taper`/`sweep`
grid (analytic `area_m2` vs meshed area), and running the same contract test over every
YAML in `cases/`. Use `ids=` so failures read `test_reject[taper-negative]` rather than
`test_reject[2]`.

---

## 5. Common gotchas

1. **Computed fields dumped into YAML, then re-validated.** Harmless *today*: with
   default `extra='ignore'`, `model_validate` drops `tip_chord_m`, `area_m2`, `n_ult`,
   etc. and recomputes them. It stops being harmless when: (a) anyone sets
   `extra='forbid'` — every previously dumped YAML becomes invalid input; (b) a human
   edits a dumped YAML (`root_chord_m`) without touching stale computed keys
   (`tip_chord_m`) — the stale values are silently ignored, so the file lies to human
   readers while the code recomputes correctly. QA countermeasure: a check that
   re-validates a dumped YAML and diffs stored computed values against recomputed ones.
2. **Attribute assignment bypasses all validation.** `validate_assignment` defaults to
   `False`, so `spec.wing.taper = 1.7` or `spec_i.structures.fem_model_type = "beam"`
   would stick — the `# type: ignore[assignment]` in `oas_wingbox.py` is the visible
   symptom. Bounds validators added per section 3 will NOT fire on optimizer
   perturbations unless `model_config = ConfigDict(validate_assignment=True)` is set (or
   perturbed specs are re-validated via `model_validate(spec.model_dump())`). Related
   footgun: an un-validated `np.float64` assigned into a field survives to
   `yaml.safe_dump`, which raises `RepresenterError` on numpy scalars — the `float()`
   casts in `_apply_dvs` are what currently prevent this.
3. **Float equality.** `test_schema.py::test_default_spec_computed_fields` compares
   computed fields with `==` — it passes only because both sides execute the identical
   expression. Any refactor of the formula (e.g. `mac_m` algebra) breaks it spuriously.
   Use `pytest.approx` with explicit tolerances, or `math.isclose`. Never `==` on
   anything that crossed a solver, a file format, or an architecture boundary. (JSON
   round-trip of Python floats is exact — `json.loads(json.dumps(x)) == x` — so contract
   tests may compare stage-JSON floats exactly *to the in-memory value that wrote them*,
   but never to constants.)
4. **Warnings-as-errors vs numpy/OpenMDAO.** Promoting warnings with
   `filterwarnings = ["error", ...]` is valuable for catching deprecations, but this
   stack is noisy: OpenMDAO emits its own warning taxonomy (`OpenMDAOWarning`,
   `OMDeprecationWarning`, setup/derivative warnings) and numpy emits floating-point
   `RuntimeWarning`s from solver internals (the existing `pyproject.toml` already
   ignores `divide by zero` and an `np.core` deprecation). Semantics to remember: in the
   config list, **later entries take precedence** (same as `warnings.filterwarnings`),
   so `"error"` goes first with targeted `ignore:...` lines after it;
   `@pytest.mark.filterwarnings` beats the config; stacked mark decorators apply in
   reverse order. Also note numpy FP warnings are gated by `np.errstate`/`np.seterr`
   upstream of the warnings system — library code that sets `errstate` locally will not
   be affected by pytest filters at all.
5. **Test order dependence via `results/` and CWD.** Two leak paths exist: (a) stage
   runners default to the repo-level `results/<concept>/<phase>/` tree (`results_dir_for`), and
   `load_sized_spec` reads `results/<concept>/baseline/target_sized.yaml` over the passed-in
   spec — a test (or a manual pipeline run) that populates real `results/` changes the
   behavior of later tests; (b) duplicated relative source paths assume CWD == repo root.
   Countermeasures: always pass `tmp_path` as `outdir` where possible, never assert
   against stale stage files, and import the absolute `BASELINE_DESIGN` /
   `OPTIMIZED_DESIGN` constants from `conftest.py`; periodically run with
   `pytest-randomly` (or `-p no:cacheprovider` plus shuffling) to smoke out hidden
   ordering assumptions. Fixtures that must touch shared state get explicit
   setup/teardown or `monkeypatch`-ed `results_dir_for`.

---

## 6. How a QA engineer validates the schema layer

**Round-trip: case YAML -> spec -> dump -> spec, equal on non-computed fields.**

```python
def test_yaml_round_trip():
    spec = load_spec(BASELINE_DESIGN)
    dumped = yaml.safe_dump(spec.model_dump(mode="python"), sort_keys=False)
    again = VehicleSpec.model_validate(yaml.safe_load(dumped))
    assert again == spec          # (1)
    assert again.model_dump() == spec.model_dump()  # (2) includes computed fields
```

(1) Pydantic `__eq__` compares declared (stored) field values recursively — computed
fields are properties, not stored state — so instance equality *is* "equality on
non-computed fields". (2) extends the check to computed outputs. For a per-field
diff on failure, iterate `type(spec).model_fields` and compare sub-models
individually. Also assert the dump is `yaml.safe_dump`-able and `json.dumps`-able —
that is the wire-format guarantee the other stages rely on.

**Rejection tests for invalid inputs.** Parametrize a table of bad fragments and assert
`ValidationError` (and that the error points at the right place):

```python
@pytest.mark.parametrize("patch, loc", [
    ({"wing": {"span_m": "wide"}}, ("wing", "span_m")),          # wrong type
    ({"structures": {"fem_model_type": "beam"}}, ("structures", "fem_model_type")),  # bad Literal
    ({"mission": {"payload_kg": -5}}, ("mission", "payload_kg")),  # bounds (once validators exist)
], ids=["type", "literal", "bounds"])
def test_rejects(patch, loc):
    with pytest.raises(ValidationError) as ei:
        VehicleSpec.model_validate(patch)
    assert any(e["loc"][: len(loc)] == loc for e in ei.value.errors())
```

Also cover the pre-Pydantic gate: `load_yaml` raising `ValueError` on non-mapping YAML,
and (if adopted) the strict lane `model_validate(data, extra='forbid')` rejecting a
misspelled key like `tapper`. Checking `errors()[i]["loc"]`/`["type"]` rather than just
"it raised" is what catches validators that fire on the wrong field.

**Checking bounds validators fire.** For every constrained field, test one value just
inside and one just outside each bound (`taper=1.0` passes, `taper=0.0` and `1.0001`
fail for `gt=0, le=1`); assert error `type` is the constraint kind (`greater_than`,
`less_than_equal`). Two extra checks worth automating: (a) construct-time defaults are
themselves valid — `VehicleSpec()` must not raise after adding validators; (b) if
`validate_assignment=True` is adopted, assert assignment fires the same validators
(`with pytest.raises(ValidationError): spec.wing.taper = 1.7`) — otherwise document
loudly that mutation is unvalidated and optimizer code must re-validate perturbed specs.

**Placement.** These are millisecond-scale tests: no marker, always-on, first lane in
CI. They gate everything downstream, because every solver stage trusts `VehicleSpec`
blindly.
