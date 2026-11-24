# Changelog

## Unreleased

- `assaystone schema list|trace|contract` prints bundled draft 2020-12 JSON
  Schemas; the schemas ship in the wheel and sdist, and the test suite validates
  every bundled demo trace and contract against them
- `assaystone benchmark failure-zoo` runs every built-in verifier independently
  against the labelled corpus (code/test, ops/refund, and an audit transcript),
  reports caught / escaped / false-alarm counts per verifier, and emits deterministic
  Markdown, JSON, and CSV
- committed regression thresholds fail the run when verifier recall drops or a
  verifier disappears from the corpus; `make benchmark` refreshes
  `docs/failure-zoo.md`
- CI runs the benchmark and fails when the committed scorecard is stale

## 0.5.0 — 2026-11-24

- Codex CLI transcript import, including `apply_patch` replay and `exec_command`
  test-evidence inference
- `assaystone audit --latest claude-code` and `--latest codex` discover the newest
  local session for the current workspace
- root `pytest` collection fixed by scoping tests to `tests/`; CI now runs both the
  unittest suite and pytest entry point
- Python 3.13 added to the CI matrix; lint and coverage gates added
- wheel and sdist no longer include `__pycache__` or `.pyc` files; PEP 639 license
  metadata and an explicit development dependency set added
- GitHub Action outputs: `verdict`, `findings`, and `traces`
- Claude Code plugin marketplace with `/assaystone:audit`, `/assaystone:setup`, and a
  fail-open Stop hook, validated with `claude plugin validate --strict`
- GitHub Pages landing page and social preview
- Makefile supports newer local Python interpreters and adds `pytest`, `lint`, and
  `package` targets

## 0.4.1 — 2026-11-23

- Packaging fix: generated GitHub workflows now pin `v0.4.1`, and the README/Action
  metadata reflect the 0.4.x release. No verifier behavior changes.

## 0.4.0 — 2026-11-23

- LangGraph (`LangGraphGuard`) and OpenAI Agents SDK (`run_with_verification`)
  runtime wrappers
- strict, newline-only JSONL parsing; invalid lines are skipped with a warning instead
  of corrupting a record on U+0085/U+2028
- SARIF locations now point at the artifact named in the finding
- test evidence is inferred only from explicit runner commands and structured outcomes
- workspace copies skip heavy directories and refuse the home directory or filesystem
  root
- forbidden defaults narrowed to `.github/workflows/` and `.github/actions/`; debug
  prints in CLI/example/script paths are ignored
- unreadable files in a trace directory are skipped with a warning; invalid trace
  shapes are rejected before `Trace.from_dict`
- field-note manual triage: 0 confirmed test tampering in the five strongest
  candidates; the path-based rule surfaces activity, not intent
- generated GitHub workflows pin the released action tag instead of `@main`

## 0.3.1

- Claude Code hook merges git working-tree changes, capturing Bash-made edits
- audit step budget raised from 200 to 5,000 based on a 162-session field audit
- `scripts/corpus_audit.py` for read-only aggregate corpus audits
- real-session field note and release notes

## 0.3.0

- `assaystone audit`: Claude Code transcripts, message exports, trace JSON
- LangSmith, Langfuse, and OpenTelemetry GenAI importers (`--format`, auto-detect)
- Claude Code Stop hook (`assaystone hook install claude-code`), warn/block, dedupe,
  and `.assaystone/hook.json` ignore rules
- SARIF 2.1.0 and JUnit output for `audit` and `verify`
- shared tool-call replay and test-evidence inference
- `--workspace` / post-session fallback: current files when replay cannot cover edits
- `--git-preimage`: HEAD-based baseline for post-session diff checks; the hook uses it
  when available
- `tests.integrity` matches nested test dirs (`server/tests/`, `demo2/server/tests/`)
- default audit rules, severity levels, JSON output, `--fail-on`, suggested contract
- `Contract.from_dict` / `to_dict`; `fail_fast=False` aggregates all verdicts
- `record` accepts Claude Code transcripts, importers, and trace JSON
- packaged `demo_data` so `pip install assaystone && assaystone demo` works
- `--no-evidence` to keep raw evidence out of machine reports
- third-party verifier packs via `assaystone.verifiers` entry points
- CI matrix 3.10–3.12 plus a wheel build/install demo job
- GitHub Action install input; project metadata and license files

## 0.2.0

- runtime gate: irreversible-tool policies, approval callbacks, contract enforcement,
  shadow mode
- ops/refund verifier pack and `assaystone demo ops`
- LangGraph adapter
- runtime, adapter, verifier, and contract reference docs

## 0.1.0

- acceptance contracts and a cost-ordered verifier ladder
- `pass / fail / escalate` verdicts with reasons and evidence refs
- mutation testing and backtesting over recorded traces
- Claude Agent SDK / OpenAI-style / LangGraph message adapters and `artifacts_from_git`
- `assaystone init --ci`, `assaystone record`, `verify --json`, `verify --github`
- pytest plugin (one item per trace) and a composite GitHub Action
- scorecard, Failure Zoo seed, and launch docs

## 0.0.1

- initial code/test verifier pack and demo
