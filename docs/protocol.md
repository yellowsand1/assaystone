# The Assaystone verifier protocol, v1

A verifier is a partial oracle. The protocol exists to make that limitation
explicit, machine-readable, and comparable across implementations.

It defines three artifacts:

| artifact | question it answers | schema |
|---|---|---|
| **contract** | what must be accepted, and which defect classes matter? | `contract.schema.json` |
| **verifier manifest** | what does this check claim, and what can it not see? | `verifier.schema.json` |
| **verdict** | what did the check decide, with what evidence and cost? | `verdict.schema.json` |

Generate the schemas with:

```bash
assaystone protocol --schemas ./schemas
```

Print the catalog of every registered verifier, including its declared blind
spots, with `assaystone protocol`. Check a contract against the protocol with
`assaystone protocol --check path/to/contract.json`.

## The verifier manifest

Every verifier must declare six things. A verifier that leaves any of them empty
fails conformance.

```yaml
name: tests.harness_integrity
version: "1"
layer: L1
independence: high
claim: "No changed file can rewrite the test runtime before the suite runs."
catches:
  - test-harness-hijack
  - module-shadow
blind_spots:
  - environment variables set outside the repository
  - globally installed test plugins
  - a hijack hidden in an already-listed dependency
cost:
  usd: 0.00002
```

### `claim`

One sentence a human can disagree with. "Tests pass" is not a claim; "the suite
passes in a clean workspace" is. The claim is what the benchmark holds the
verifier to.

### `catches`

The defect tags this verifier claims to detect. Tags are the shared vocabulary
between a contract, a corpus, and a coverage report. A verifier that claims a tag
and misses it in the Goodhart suite produces a **broken claim**.

### `blind_spots`

The defect tags this verifier knows it cannot detect. This is mandatory. A
verifier that cannot name its blind spots is claiming to be an oracle.

Blind spots are used twice:

- the coverage report distinguishes *decided*, *weakly covered*, and *uncovered*
  defect classes;
- the Goodhart suite distinguishes a **declared escape** (honest) from a
  **surprise** (false confidence).

### `independence`

`high`, `medium`, or `low`. This is not a label; the runner uses it.

- A `high` or `medium` failure is decisive: the contract fails.
- A `low` failure cannot decide alone. The runner keeps looking for an
  independent confirmation. If none arrives, the verdict is `escalate`.
- An unknown level is treated as `low`, so a verifier that cannot describe
  itself routes to a human.

The reason is structural: a check that shares code, context, or data with the
generator is correlated with the failure it is supposed to catch. Its failure is
evidence, not a verdict.

### `cost`

Cost per check in USD, and optionally milliseconds. The runner orders checks by
cost and stops when the contract's `max_verification_cost_usd` is exhausted,
escalating the remainder.

## The contract

```json
{
  "name": "hardened",
  "test_command": ["{python}", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
  "required_defects": ["regression", "test-tampering", "ci-bypass"],
  "max_verification_cost_usd": 0.05,
  "human_review_cost_usd": 6.0,
  "verifiers": [
    {"name": "tests.integrity", "required": true},
    {"name": "tests.pass", "required": true}
  ]
}
```

`required_defects` is the claim the contract makes about itself. `assaystone
coverage` measures it. Without it, coverage has nothing to measure.

`domain` is optional. A benchmark only applies a contract's verifiers to corpus
families in the same domain, so a `code` contract is not scored against an `ops`
corpus. When a contract omits the domain, its verifiers are applied to every
family it is run against.

## The verdict

A verdict is three-valued: `pass`, `fail`, or `escalate`. It carries the verifier
name, its layer and independence, the reasons, the evidence references, and its
cost. A crashing verifier produces `escalate`, never `pass` (fail closed).

## Publishing a verifier

Any Python package can register a verifier through an entry point:

```toml
[project.entry-points."assaystone.verifiers"]
mypack = "mypack.verifiers"
```

The module must call `register` on a subclass of `Verifier` and declare the six
ABI fields. The verifier then appears in `assaystone protocol`, can be used in a
contract, and is scored by both benchmarks.

Verifiers written in another language can publish a manifest that validates
against `verifier.schema.json`; the scorecard consumes the manifest, not the
implementation language.

## Versioning

The protocol version is `1`. Additive changes keep the major version; a change
that removes a field or changes an outcome requires a new major version. The
schemas are the source of truth.
