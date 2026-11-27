# Task specs

A contract says what "acceptable" means for a task type. A spec says what **this
task** asked for. `check --spec spec.json` compiles the spec's obligations into
criteria, evaluates them with deterministic evidence rules, and reports coverage
in the certificate.

The spec is an artifact, not a prompt. It is written by the person (or planning
agent) who knows what the task requires, versioned with the code, and readable
without a model.

## Format

```json
{
  "schema": "assaystone.spec/1",
  "task": "add the schema command",
  "obligations": [
    {
      "id": "schema-command",
      "statement": "The CLI exposes the schema command.",
      "severity": "high",
      "evidence": [
        {"kind": "path", "glob": "assaystone/schema.py", "change": "added"},
        {"kind": "contains", "glob": "assaystone/cli.py", "text": "schema"}
      ]
    },
    {
      "id": "tests",
      "statement": "New behaviour has a test.",
      "evidence": [{"kind": "path", "glob": "tests/test_schema.py", "min_changed_lines": 5}]
    },
    {
      "id": "ci",
      "statement": "CI was not disabled.",
      "evidence": [{"kind": "absent", "glob": ".github/workflows/*"}]
    }
  ]
}
```

## Evidence rules

| kind | decides | fields |
|---|---|---|
| `path` | a changed path matches the glob, optionally with a change status or a minimum number of changed lines | `glob`, `change`, `min_changed_lines` |
| `contains` | a changed or baseline file matching the glob contains the text | `glob`, `text`, `regex` |
| `absent` | no changed path matches the glob | `glob` |
| `exists` | a file matching the glob exists after the change | `glob` |

- **`mode`** on an obligation is `all` (default) or `any`.
- **`on_unknown`** is `escalate` (default) or `fail`; an unknown obligation that
  is high or critical gates the run the same way a criterion does.
- **`severity`** defaults to `high`.

## What the certificate gets

Each obligation becomes a criterion with `defect: spec:<id>` and
`source: "evidence"`. The certificate's `assurance.spec` block reports:

```json
{
  "task": "add the schema command",
  "digest": "sha256:...",
  "total": 3,
  "satisfied": ["schema-command", "tests"],
  "violated": ["ci"],
  "unknown": [],
  "coverage": 0.6667
}
```

`certificate show` prints one line: `spec 2/3 obligations met; violated: ci`.

## Limits

- This does not parse natural language. A free-form ticket becomes checkable only
  when a person (or a planning agent) writes the obligations down.
- Globs use `fnmatch`; `*` crosses `/`. Be explicit.
- `path` and `absent` look at changed paths; `contains` and `exists` also read the
  baseline when nothing changed.
- It can check that a migration file exists. It cannot check that the migration
  is correct. That is what a contract check is for.
- An obligation with no evidence rule is not allowed; an untestable requirement
  should say so in the contract's `open_obligations` instead.

## Try it

```bash
assaystone check --base origin/main --spec .assaystone/spec.json --certificate ./certs
```
