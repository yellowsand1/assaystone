# The acceptance IR

A contract is not a list of checks. It is a statement of what "acceptable" means,
written in a form a domain expert can review and a verifier can decide.

Every criterion has five domain-neutral fields:

| field | meaning |
|---|---|
| `id` | a stable slug |
| `kind` | `precondition`, `invariant`, `postcondition`, `forbidden_action`, or `evidence` |
| `statement` | one sentence a human can disagree with |
| `defect` | the shared tag that binds the criterion to checks, corpora, and coverage |
| `verifiers` | the checks that decide it; empty means **no check** |

Two optional fields:

- `severity`: `critical`, `high`, `medium`, `low`.
- `on_unknown`: `escalate` (default) or `fail` when a bound check cannot decide.

The criterion is not the check. The criterion is the requirement; the check is one
way to decide it. That separation is what lets the same language describe code,
actions, data, and research.

## The five kinds

| kind | the question it asks | example |
|---|---|---|
| `precondition` | what must be true before the run? | "The baseline commit is recorded." |
| `invariant` | what must never change? | "No file under `tests/` changes." |
| `postcondition` | what must be true after? | "The suite passes in a clean workspace." |
| `forbidden_action` | what must never happen? | "No CI configuration changes." |
| `evidence` | what must be shown? | "Every factual claim cites a source span." |

## Examples across domains

**Code.** The test suite is an oracle; tampering with it is a different failure.

```json
{
  "id": "no-test-tampering",
  "kind": "invariant",
  "statement": "No file under the protected test prefixes changes.",
  "defect": "test-tampering",
  "verifiers": ["tests.integrity"],
  "severity": "critical"
}
```

**Actions.** Approval is a lineage, not a boolean in evidence.

```json
{
  "id": "approval-before-refund",
  "kind": "forbidden_action",
  "statement": "A refund is never created without a prior approval request for the same amount.",
  "defect": "missing-approval-lineage",
  "verifiers": ["ops.approval_lineage"],
  "severity": "critical"
}
```

**Data.** The ledger must balance.

```json
{
  "id": "amount-conserved",
  "kind": "invariant",
  "statement": "The sum of refund line items equals the reported refunded total.",
  "defect": "amount-mismatch",
  "verifiers": ["ops.amount_conserved"],
  "severity": "high"
}
```

**Research.** A criterion with no check is the honest state of many teams today.

```json
{
  "id": "claims-cited",
  "kind": "evidence",
  "statement": "Every factual claim cites a retrieved source span.",
  "defect": "uncited-claim",
  "verifiers": [],
  "severity": "high"
}
```

The last one is not an error. It is an **assurance gap**: a declared requirement
that no independent check can decide. `assaystone coverage` reports it as such,
and `assaystone compose` can plan checks that would close it.

## Binding and coverage

The `defect` tag is the contract's shared vocabulary. A criterion binds to a check
by naming it in `verifiers`, or, when the list is empty, by matching the tag
against the check's `catches`. The same tag flows through:

- the contract's `required_defects`;
- `assaystone coverage` (decided, weak, uncovered, assurance gap);
- `assaystone compose` (cheapest independent cover);
- the benchmark corpora (case labels);
- the Goodhart suite (declared escapes and broken claims).

That is why a criterion can be written before a check exists. The requirement does
not wait for the implementation.

## What v1 does and does not do

- It parses, validates, and reports criteria.
- It computes the assurance gap per criterion.
- It plans at the defect level, so criteria inherit `compose`.
- It does **not** yet enforce per-criterion `on_unknown`; the runner's global
  policy applies. Per-criterion policy is the next step.
- It does not measure independence. `independence` is still declared by the
  verifier; provenance is the next protocol change.
