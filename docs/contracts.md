# Contracts

A contract is the acceptance criteria for one task type. It is versioned with the
agent that produces the traces.

```json
{
  "name": "fix_bug",
  "test_command": ["{python}", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
  "fail_fast": true,
  "human_review_cost_usd": 6.0,
  "max_verification_cost_usd": 0.05,
  "require_measured": false,
  "verifiers": [
    {"name": "budget.steps", "params": {"max_steps": 40}},
    {"name": "diff.forbidden_paths", "params": {"forbidden": ["ci/", ".github/workflows/"]}},
    {"name": "tests.integrity", "params": {"protected_prefixes": ["tests/"]}},
    {"name": "tests.pass"}
  ]
}
```

## Fields

- `name` — shown in reports and annotations.
- `test_command` — used by `tests.pass`. `{python}` is replaced with the current
  interpreter. Run from the baseline root.
- `fail_fast` — stop at the first required failure. Default `true`.
- `human_review_cost_usd` — used to report verification cost as a percentage of a
  human review. Default `6.0`. Costs are an illustrative model; override it with your
  own numbers before quoting a ratio.
- `max_verification_cost_usd` — escalate if the next verifier would exceed the budget.
  Default `0.05`.
- `require_measured` — when true, a pass must rest on at least one measured,
  independent check; otherwise the run escalates. Default `false`. See
  [reliability.md](reliability.md).
- `verifiers` — ordered specs. The runner reorders by `cost_usd`.
  - `name` — a registered verifier.
  - `required` — default `true`. A failed optional verifier is advisory.
  - `params` — verifier-specific.

## Packs

Importing `assaystone` registers the built-in packs. The code/test pack uses the
`diff.*`, `tests.*`, `quality.*`, `evidence.*`, and `budget.*` verifiers; the ops pack
adds `ops.*` (see `examples/ops_agent/contracts/hardened.json`).

`test_command` is only used by `tests.pass`. Leave it out (or use a no-op) in contracts
that do not run a test suite.

## Exit codes

`assaystone verify` returns:

- `0` — every trace passed.
- `1` — at least one trace failed.
- `2` — no failures, but at least one trace needs a human (escalate).

## Scaffold

```bash
assaystone init --ci
```

The generated contract is a starting point. Adjust `test_command`, protected paths,
and the step/diff budgets to match your repository.

If you already have traces, audit first and let the findings produce the contract:

```bash
assaystone audit session.jsonl --baseline . \
  --write-contract .assaystone/contract.json
```

The audit contract runs with `fail_fast: false` so it reports every finding; adjust it
to `true` before using it as a gate.

## Versioning

Commit the contract next to the agent. When the acceptance criteria change, change the
contract in the same pull request as the agent change that requires it. Backtest the
new contract against historical traces before enforcing it.
