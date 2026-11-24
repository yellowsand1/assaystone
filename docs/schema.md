# JSON Schemas

Assaystone ships [JSON Schema](https://json-schema.org/) (draft 2020-12) definitions
for the two file formats it reads and writes: traces and contracts. They describe the
shape of the JSON, so editors can autocomplete and CI can reject malformed files
before a run.

## Commands

```bash
assaystone schema list       # contract, trace
assaystone schema trace      # print the trace schema as JSON
assaystone schema contract   # print the contract schema as JSON
```

`assaystone schema` with no name prints the trace schema. The output is plain JSON on
stdout, so you can redirect it into an editor configuration or a repository:

```bash
assaystone schema contract > schema/contract.schema.json
```

## Files

The schemas live in the installed package:

- `assaystone/schemas/trace.schema.json`
- `assaystone/schemas/contract.schema.json`

They are pure data with no runtime dependency: `assaystone` itself does not import a
JSON Schema validator. The test suite uses the test-only `jsonschema` package (declared
in the `pytest` and `dev` extras) to check the bundled demo traces and contracts.

## What is validated

- Trace files produced by `record`, the framework adapters, or by hand.
- Contract files loaded by `verify`, `backtest`, and `mutate`.

The schemas describe structure only. They do not decide whether a verifier name is
registered, whether verifier params are meaningful, or whether the work described by a
trace is correct. Those checks belong to the runner and the verifier packs; see
[docs/contracts.md](contracts.md) and [docs/verifiers.md](verifiers.md).

Unknown properties are rejected (`additionalProperties: false`) so typos surface at
validation time instead of being silently ignored. Every field the Python models
serialize is declared in the matching schema, and the test suite asserts that parity.

## Versioning

`assaystone.schema.SCHEMA_VERSION` tracks the schema revision. The schema `$id`
(`https://assaystone.dev/schema/...`) is stable, so editor references do not change
between releases. A change to the accepted JSON shape is a schema-version bump and
should be called out in `CHANGELOG.md`.

## Packaging check

The schema files are package data. A built wheel and sdist contain them:

```bash
python3 -m build
python3 -c "import zipfile,glob; print([n for n in zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist() if '/schemas/' in n])"
tar -tf dist/*.tar.gz | grep '/schemas/'
```

The packaging CI job runs the same check.
