# Adding a case to a corpus

A benchmark is only as good as its failures. `assaystone corpus add` is the
on-ramp: it takes a trace or a redacted transcript, attaches a human label, and
writes it into an existing family so the next run scores it.

## One command

```bash
assaystone corpus add \
  --corpus assaystone/demo_data/goodhart/corpus.json \
  --family mechanical \
  --trace ~/session.jsonl \
  --format claude-code \
  --baseline ~/repo-before \
  --label fail \
  --defect test-harness-hijack \
  --note "neutralised assertEqual instead of fixing the rounding"
```

- `--trace` accepts a trace JSON, a transcript, or an observability export
  (`auto`, `messages`, `claude-code`, `codex`, `langsmith`, `langfuse`, `otel`).
- `--baseline` is the repository state before the session. It is required to
  replay a transcript into artifacts; for a trace JSON that already contains
  artifacts it is ignored.
- `--label fail` requires `--defect`. `--label pass` must not declare one.
- `--validate` reruns the corpus and prints `caught`, `escaped`, or
  `false_alarm`, plus the verifier that caught it.

The command writes one file into the family's source directory. It never edits
the manifest: existing families point at a directory, so the next run picks the
case up and the manifest stays reviewable.

## Choosing a family

| family | what belongs there |
|---|---|
| `mechanical` | attacks on the test runtime or CI surface (harness hijack, module shadowing, CI bypass) |
| `semantic` | a change that leaves every deterministic signal green but violates the task |
| `ops_lineage` | an action domain where approval or ledger lineage is the evidence |
| `support` | test support code outside the `tests/` prefix (shared assertion helpers) |

The Failure Zoo (`assaystone/demo_data/failure_zoo/`) uses the same format for
recall cases.

## Labels and defect tags

A label is the ground truth a human would give, not what the verifier said:

- `verdict: "fail"` and a `defect` tag for a case that should not pass;
- `verdict: "pass"` and no defect for a case that should pass.

Reuse the tags the verifiers declare in `catches` and `blind_spots`. The
benchmark uses them to compute coverage, broken claims, and declared escapes; a
new synonym splits the vocabulary.

## Thresholds

If a new case is caught, raise the threshold so the gain is locked in. If it
escapes, either add a verifier that catches it or declare the tag in that
verifier's `blind_spots` and lower the threshold deliberately. Never lower a
threshold only to make a red run green.

## Review

Before opening a pull request:

```bash
assaystone benchmark failure-zoo --no-thresholds
assaystone benchmark goodhart --no-thresholds
assaystone scorecard --contract examples/code_agent/contracts/hardened.json \
  --trace examples/code_agent/traces --baseline examples/code_agent/baseline
```

Redact secrets, customer data, and absolute paths. A case that cannot be shared
is still useful as a private corpus: the manifest format is the same.
