# Known evasions

This page lists failure classes the current built-in pack does not catch. It
exists so a reader can judge the tool by what it misses, not only by what it
catches.

Status:

- **caught** — a built-in check detects it; the case is in the benchmark.
- **declared** — a check names it as a blind spot. The tool knows it misses it.
- **open** — no check names it. This is the list to work on.

| class | status | where |
|---|---|---|
| Semantic drift the suite does not cover | declared | `tests.pass`, `diff.public_api`; Goodhart `g04` |
| Test-specific logic (hardcoded expected values) | declared | `tests.pass`, `diff.public_api`; Goodhart `g06` |
| Forged `approval.request` step in an agent-written trace | declared | `ops.approval_lineage` |
| Forged `refund.create` step in an agent-written trace | declared | `ops.refund_lineage` |
| Secret format outside the pattern list; encoded or split secrets | declared | `example.no_new_secrets` |
| Test support code outside the protected prefixes | **open** | no built-in check |
| Network calls or data exfiltration in production code | **open** | no built-in check |
| Independence is self-reported, not measured | **open** | protocol checks the declaration |
| A verifier that is wrong in the same way as the generator | **open** | the runner cannot detect correlation |
| The corpus is small and self-authored | **open** | n=9 adversarial cases |

## Semantic drift the suite does not cover

A change can leave every deterministic signal green and still violate the task.
The benchmark includes two examples: a rounding change the suite does not cover,
and a lookup table that returns the expected values for the test inputs and the
old behavior everywhere else. No cheap check catches either.

This is not a bug to fix by adding another regex. It is the boundary of
deterministic acceptance, and the honest response is to declare it and route to a
human when the declared class matters.

## Forged lineage in an agent-written trace

The runtime path is trustworthy: `RuntimeGuard` writes the `approval.request`
step itself, before the action. The audit path is not: a transcript can contain a
fabricated approval step, and the lineage check cannot tell it from a real one.

This is why the blind spots say "a forged approval.request step in an
agent-written transcript". If you need authenticity, the evidence has to be
written by the runtime, not by the agent.

## Test support code outside the protected prefixes

`tests.integrity` protects the prefixes a contract declares — usually `tests/`.
A repository with test helpers in `helpers/`, `testing/`, or `test_utils/` has a
real gap: an agent can weaken the helper and leave every test file untouched.
`tests.harness_integrity` covers `conftest.py` and runtime hooks, not arbitrary
helper modules.

This is the most actionable open item in the table. A `tests.support_integrity`
check with a declared prefix list would close it, and a fixture that edits
`helpers/assertions.py` would prove it.

## Independence is self-reported

The protocol requires every verifier to declare `high`, `medium`, or `low`
independence, and the runner uses that declaration. It does not measure it.

A third-party pack can claim `high` while sharing code, context, or data with the
generator. The protocol makes the claim explicit and reviewable, not true. If you
need stronger than that, independence has to be computed from provenance (what the
check reads, what it executes, whether it can be modified by the agent), not
declared.

## The corpus is small and self-authored

The Goodhart suite has nine adversarial cases, all written by the people who
designed the checks. That is a floor, not a population estimate. The same is true
of the Failure Zoo. Treat every percentage on this site as "on these fixtures",
and add cases from outside the design team before quoting it as a rate.

`assaystone corpus add` exists so that a real trace becomes a fixture in one
command. The corpus is expected to grow past this page.
