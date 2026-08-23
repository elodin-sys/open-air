# 08 — Pydantic v2 concepts (schema-first YAML)

## What it is

Every source concept is `designs/<concept>/design.yaml`, validated into `VehicleSpec`
([`src/openair/schemas.py`](../../src/openair/schemas.py)) — the single
source of truth for geometry, engine, mission, structures, solver knobs, and
the balance stations. Stages never read raw YAML; they read the validated
model. Physical derived quantities (`area_m2`, `mac_m`, `x_ac_m`, …) are
`computed_field`s.

## Source and docs

- Pydantic: [docs.pydantic.dev](https://docs.pydantic.dev/latest/) ·
  [github.com/pydantic/pydantic](https://github.com/pydantic/pydantic)
  - [computed_field](https://docs.pydantic.dev/latest/concepts/fields/#the-computed_field-decorator)
  - [model_validate / model_dump](https://docs.pydantic.dev/latest/concepts/serialization/)
- Extended notes: [`_research/pydantic-pytest.md`](_research/pydantic-pytest.md)

## Best practices

- `VehicleSpec.model_validate(load_yaml(path))` at the boundary; everything
  after trusts the model.
- Optimizer perturbations use `model_copy(deep=True)` — never mutate a shared
  spec.
- **Computed fields ARE serialized** by `model_dump`, so dumped YAML
  (`optimized/design.yaml`, `target_sized.yaml`) contains `tip_chord_m`,
  `area_m2`, etc. Re-validation ignores them as extras — harmless on the way
  in, but do not hand-edit a computed value expecting it to stick.
- Unit conventions live in the field names (`_m`, `_kg`, `_deg`, `_pa`).
  A number without a suffix convention does not go in the schema.
- Physical models use `validate_assignment=True` with `Field` bounds, so
  optimizer/trim mutations of a `model_copy` are validated at the assignment
  site (a bare `BaseModel` would happily accept `taper = -1` and crash later
  inside `mac_m`). This venv runs pydantic **2.13**.
- Calibration constants that a chapter documents (e.g. `np_shift_mac`,
  `cm_washout_per_deg`, `tail_incidence_offset_deg`) belong in `SolverSpec`,
  serialized with the analyzed concept, and recorded in its calibration
  history; source priors remain version-controlled in `design.yaml`.

Generated specs never live in `designs/`. Sizing writes its overlay to
`results/<concept>/baseline/`; MDO publishes the child spec to
`results/<concept>/optimized/design.yaml`. Promoting that child into a new
source concept is an explicit copy into a new `designs/<new-concept>/`.
Use `python -m openair promote <concept> <new-concept>`: it validates and
renames the optimized spec, copies canonical sketch PNGs, writes promotion
provenance plus the prior brief, refuses to overwrite an existing source, and
does not copy generated results.

## The overlay rule (audit F13)

Sizing writes `results/<concept>/baseline/target_sized.yaml`. That overlay
used to be loaded back as a **whole spec**, silently shadowing later edits to the concept
file (you change the airfoil; the pipeline keeps flying the old one).
`load_sized_spec` now copies **only `mass.fuel_mass_kg`** from the overlay
onto the freshly-loaded design. If you add a second sizing-closed quantity,
extend that function deliberately — never go back to whole-file overlays.

## Check your work

1. Round-trip: load design → dump → re-validate → non-computed fields equal.
2. `pytest tests/test_schema.py` — target design invariants (payload 22.7,
   endurance 7200 s, n_ult 6).
3. After editing a concept, run the orchestrator, which clears stale phase
   artifacts and runs
   sizing first; confirm a changed field actually shows up downstream (the
   F13 regression test does this for the airfoil).
4. The optimized YAML must re-validate and re-evaluate to the recorded MDO
   metrics (`evaluate_design` reproducibility check, chapter 04).

## Known lies

- A stale overlay wearing the concept's name (F13).
- Hand-edited computed fields that vanish on re-validation.
- YAML `notes` describing an older design generation — update them with the
  design.
