# Verifiers

A verifier returns `(ok, reasons, evidence)`:

- `ok=True` — the check passed.
- `ok=False` — the check failed.
- `ok=None` — the check cannot decide; the run escalates to a human.

Every verifier declares `layer`, `cost_usd`, `independence`, `claim`, `catches`,
and `blind_spots`. The runner sorts by cost and stops at the first required
failure. A failure from a `low`-independence verifier is not decisive: the runner
looks for independent confirmation and escalates if none arrives. See
[the protocol](protocol.md) for the full ABI.

## Built-in pack

| Verifier | Layer | Cost | Params | Catches |
|---|---|---|---|---|
| `budget.steps` | L0 | 0.000001 | `max_steps` | runaway loops |
| `diff.syntax` | L1 | 0.000010 | — | broken Python |
| `diff.forbidden_paths` | L1 | 0.000010 | `forbidden` | CI/config edits on the declared list |
| `diff.ci_surface` | L1 | 0.000020 | `protected` | CI/build edits anywhere (`.github/`, `ci/`, `tox.ini`, …) |
| `tests.integrity` | L1 | 0.000020 | `protected_prefixes`, `allow_test_changes` | test edits anywhere (`tests/`, `server/tests/`) |
| `tests.harness_integrity` | L1 | 0.000020 | `extra_names`, `extra_suffixes` | startup hooks, module shadowing, `.pth` files |
| `tests.support_integrity` | L1 | 0.000020 | `protected_prefixes`, `allow_support_changes` | test support code changes (`helpers/`, `testing/`, …) |
| `diff.max_lines` | L0 | 0.000020 | `max_changed_lines` | oversized patches |
| `diff.public_api` | L2 | 0.000030 | — | removed/changed public API |
| `quality.no_debug_prints` | L2 | 0.000030 | — | `print()` / `breakpoint()` |
| `evidence.claims` | L3 | 0.000050 | — | success claims without evidence |
| `tests.pass` | L1 | 0.002000 | — | failing test suite |

Costs are illustrative USD-equivalent estimates. Override them per contract only if
you have a better model for your environment.

## Ops pack

Importing `assaystone` registers the ops pack. It reads `orders.json` and
`policy.json` from the workspace.

| Verifier | Layer | Cost | Params | Catches |
|---|---|---|---|---|
| `ops.json_valid` | L0 | 0.000001 | — | missing/invalid state files |
| `ops.amount_conserved` | L0 | 0.000010 | — | refund above the order amount |
| `ops.no_double_refund` | L1 | 0.000020 | — | duplicate refund ids, ledger mismatch |
| `ops.refund_limit` | L1 | 0.000020 | `limit_cents` | new refund above policy |
| `ops.status_consistent` | L1 | 0.000020 | — | status not matching refunded amount |
| `ops.refund_lineage` | L1 | 0.000025 | — | a refund row with no matching `refund.create` step |
| `ops.approval_recorded` | L2 | 0.000030 | `require_approval_for` | irreversible action without an approval record |
| `ops.approval_lineage` | L2 | 0.000025 | `require_approval_for` | an approval absent from the trace or granted for different arguments |

See `examples/ops_agent/` for the contracts, traces, and runtime demo.

## External pack

These adapters reuse installed tools without making them a runtime dependency. If
the tool is missing, the verifier escalates: the absence of a check is not evidence
that the work is acceptable.

| Verifier | Layer | Cost | Params | Catches | Independence |
|---|---|---|---|---|---|
| `external.pytest` | L1 | 0.003000 | `args`, `timeout` | `regression` | medium |
| `external.ruff_debug_print` | L2 | 0.000500 | `timeout` | `debug-print` | high |

`external.pytest` is only `medium` independence because it executes Python in the
same workspace as the agent and can be shadowed by a local module or a startup
hook. `external.ruff_debug_print` is static analysis, so it stays `high`.

## Contract params

```json
{"name": "diff.forbidden_paths", "params": {"forbidden": ["ci/", ".github/"]}}
```

`tests.integrity` protects `["tests/"]` by default. Prefixes match path segments, so
`server/tests/` and `demo2/server/tests/` are protected too. Set `allow_test_changes`
when the task is explicitly to modify tests.

## Write your own

```python
from assaystone import Verifier, register

@register
class NoMigrationEdits(Verifier):
    name = "policy.no_migrations"
    layer = "L1"
    cost_usd = 0.00001
    independence = "high"
    description = "Agents must not edit migrations."

    def check(self, ctx, params):
        bad = [path for path, _ in ctx.changed() if path.startswith("migrations/")]
        return (not bad, [f"migration touched: {path}" for path in bad], [])
```

Guidelines:

- Read artifacts, tool results, exit codes, or external state. Do not trust the
  agent's self-report.
- Be deterministic. An LLM judge belongs at L4 and must never be the sole oracle.
- Fail closed: if the verifier cannot decide, return `ok=None`.
- Add a clean-run test and a defective-run test.
- Keep the cost honest; the ladder depends on it.

## Third-party packs

A package can register verifiers with an entry point:

```toml
[project.entry-points."assaystone.verifiers"]
mypack = "mypack.verifiers"
```

`mypack.verifiers` should import modules that call `@register`. Assaystone loads
installed `assaystone.verifiers` entry points at import time; a broken pack is ignored.

## Verify the verifier

```bash
assaystone mutate --contract .assaystone/contract.json \
  --trace traces/t01-correct.json
```

Mutation testing injects known defects and reports what survived. Survivors are
either equivalent mutants or gaps in your oracle.
