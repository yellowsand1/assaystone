# Field note: `check` on a real repository

**Date:** 2026-11-27
**Subject:** `pallets/flask` at `main` (`49943b5a9441`, 2026-10-30), 236 files, 4.1 MB. Snapshot downloaded
from codeload, committed locally as a baseline, then three changes were applied
one at a time.
**Contract:** five deterministic checks — `diff.syntax`, `tests.integrity`,
`diff.forbidden_paths`, `diff.max_lines`, `quality.no_debug_prints`. No
`tests.pass`, no judge, no network.

This is not an external user. It is a real repository, a real git base, and
reproducible commands. It answers one narrow question: does the deterministic
layer meet its budget, and does it catch the two attacks it claims?

## Results

| change | decision | first failure | check time | process time |
|---|---|---|---|---|
| delete one test function from `tests/test_basic.py` | **fail** | `tests.integrity`: removed 1 test | 98 ms | 0.37 s |
| append a comment to `src/flask/app.py` | **pass** | — | 75 ms | 0.31 s |
| append a line to `.github/workflows/tests.yaml` | **fail** | `diff.forbidden_paths` | 68 ms | — |

The certificate records the base commit, the changed artifact digests, the
per-check evidence, and `source="runtime"` — the checker read the filesystem, it
did not trust a transcript.

## What this supports

- The deterministic layer runs in well under one second on a real repository,
  including the temporary worktree and the workspace copy.
- The two cheapest attack classes — deleted tests and edited CI — are caught
  without running the suite.
- A benign one-line change passes; the false-alarm rate on this sample is zero.

## What this does not support

- It is not adoption. No external team ran it, and the sample is three changes.
- It says nothing about semantic test weakening. `tests.integrity` is
  path-and-structure based; it reports activity, not intent.
- It does not run Flask's test suite. A contract with `tests.pass` will be
  dominated by the suite's runtime, not by Assaystone.
- One repository, one snapshot, no confidence interval. Treat it as a floor.

## Reproduce

```bash
curl -sSL -o flask.tgz https://codeload.github.com/pallets/flask/tar.gz/refs/heads/main
mkdir flask-check && tar xzf flask.tgz --strip-components=1 -C flask-check
cd flask-check && git init -q && git add -A && git commit -qm snapshot
# add .assaystone/contract.json with the five checks above, commit it
assaystone check --repo . --base HEAD --certificate ./certs
```
