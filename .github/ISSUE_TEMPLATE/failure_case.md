---
name: Failure case
about: Submit a real agent failure to the Failure Zoo or the Goodhart suite
title: "[failure] "
labels: failure-zoo
---

## What was the agent asked to do?

## What did it produce?

## Human verdict

- [ ] fail — why:
- [ ] pass — why this looked suspicious but is acceptable

## Label

- **Defect tag** (for a failing case): e.g. `test-tampering`, `test-harness-hijack`,
  `under-tested-change`, `missing-approval-lineage`.
- **Family**: `mechanical`, `semantic`, `ops_lineage`, or propose a new one.

## Which check should have caught it?

(e.g. `tests.integrity`, `diff.ci_surface`, `ops.refund_lineage`, or a new verifier idea)

## Trace

Attach a trace JSON, or paste the key artifacts and tool results. **Redact secrets,
tokens, customer data, and internal URLs.**

If you can run it locally, the fastest path is:

```bash
assaystone corpus add \
  --corpus assaystone/demo_data/goodhart/corpus.json \
  --family mechanical \
  --trace ./session.jsonl --format claude-code \
  --baseline ./repo-before \
  --label fail --defect test-harness-hijack \
  --note "what the agent did" --validate
```

Paste the command output so maintainers can see whether the current pack caught it.

## Environment

Framework, model, date, and anything else needed to reproduce.
