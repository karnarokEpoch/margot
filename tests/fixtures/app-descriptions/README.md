# Application description fixtures

Standalone `app.yaml` documents for exercising `margot verify` (Schema A and Schema B)
and, going forward, `margot describe`. Each file is a complete, self-contained
`ApplicationDescription` — no accompanying `margo.yaml` is needed. Point a test or a
manual run at one directly:

```bash
margot verify --manifest tests/fixtures/app-descriptions/minimal.yaml --recommend
```

or, from Python, feed the path straight to the runner:

```python
from margot.schemas import SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS, SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS
from margot.validation.linkml_runner import run_validation

run_validation("tests/fixtures/app-descriptions/minimal.yaml", SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS)
run_validation("tests/fixtures/app-descriptions/minimal.yaml", SCHEMA_B_PATH, SCHEMA_B_TARGET_CLASS)
```

Every finding count below was produced by actually running the file through
`validation/linkml_runner.py::run_validation` against both vendored schemas — re-check
with the snippet above if either schema changes.

## Files

### `minimal.yaml`

Bare minimum: exactly the fields the spec marks required, nothing else. Clean on both
schemas.

- **Schema A:** 0 findings.
- **Schema B:** 3 warnings — `metadata.description`, `metadata.catalog.application`,
  `metadata.catalog.author` are all absent and all `recommended: true`. 0 errors.

### `complex.yaml`

Full-featured descriptor: helm *and* compose deployment profiles, `requiredResources`
(CPU, memory, storage, peripherals, interfaces), a `parameters` / `configuration` block
exercising every `Schema` subclass rule shape (`regexMatch`, `minValue`/`maxValue`,
`minPrecision`/`maxPrecision`, `options`), every recommended catalog field populated, and
an `x-placeholder-extensions` block. Represents a catalog-ready, spec-valid application.

- **Schema A:** 0 findings.
- **Schema B:** 0 findings — every recommended slot is present, so nothing to warn about
  either.

### `missing-recommended.yaml`

All spec-required fields present (clean on Schema A) but a partial, realistic gap in the
catalog metadata: `catalog.application` exists (with `site`/`tags` filled in) but its own
recommended sub-fields are empty, `metadata.description` and `catalog.author` are absent
entirely. Distinguishes "the block is missing" from "the block exists but is thin" —
compare its Schema B findings to `minimal.yaml`'s.

- **Schema A:** 0 findings.
- **Schema B:** 5 warnings, 0 errors:
  - `/metadata` — `description` recommended
  - `/metadata/catalog/application` — `descriptionFile`, `icon`, `releaseNotes`
    recommended (three separate findings, same path)
  - `/metadata/catalog` — `author` recommended

### `unlinked-parameters.yaml`

Structurally valid — clean on both schemas — but semantically inconsistent in ways
neither LinkML schema checks today, because these are cross-field relationships, not
shapes:

- `parameters.unusedApiKey` is declared but no `setting` references it (orphaned
  parameter).
- `configuration.sections[0].settings` includes a setting whose `parameter:
  greetingAddressee` does not exist under `parameters` (dangling parameter reference).
- Another setting's `schema: strictText` does not match any `configuration.schema[].name`
  (dangling schema reference).
- `configuration.schema` includes `unusedRule`, which no setting's `schema:` points at
  (dead schema rule).

Reserved for a future semantic/coherence validation pass, and useful today for
`margot describe`, which is specified to render exactly this kind of mess faithfully
rather than judge it (see `.kiro/sprints/sprint-7.md`).

- **Schema A:** 0 findings.
- **Schema B:** 2 warnings (`catalog.application`, `catalog.author` recommended), 0
  errors — none of the dangling references above are visible to either schema.

### `missing-required.yaml`

Deliberately missing several spec-required fields at once, and includes one case where
Schema A and Schema B disagree on purpose:

- Top-level `id` absent.
- `metadata.version` absent.
- `metadata.catalog.organization` absent (`catalog: {}`).
- `deploymentProfiles[0].components` is an empty list — the spec's `DeploymentProfile`
  requires the slot but accepts an empty list; Schema B additionally imposes
  `minimum_cardinality: 1`, so this line is an ERROR under Schema B only.

- **Schema A:** 3 errors (`id`, `metadata.version`, `metadata.catalog.organization`), 0
  warnings.
- **Schema B:** 4 errors (Schema A's 3, plus the empty-`components` cardinality error), 3
  warnings (the usual `description` / `application` / `author` recommendations).

## Adding a fixture

1. Write the smallest `app.yaml` that demonstrates the case.
2. Run it through `run_validation` against both `SCHEMA_A_PATH` and `SCHEMA_B_PATH` (see
   the snippet above) and paste the actual finding count/paths into this README — don't
   guess at what LinkML will report.
3. If the case is meant to stay clean on both schemas (a "good" fixture), assert that in
   a test, not just here.
