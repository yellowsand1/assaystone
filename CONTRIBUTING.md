# Contributing

The fastest way to help is to bring a real failure case.

## Bring a failure case

If an agent produced output that looked acceptable but was not, open an issue with the
`failure case` template. Redact secrets, attach the trace JSON if you can, and state
the human verdict and which check should have caught it. Accepted cases go into the
[Failure Zoo](failure_zoo/README.md) and become regression tests.

## Add a verifier

A verifier is a small class with a declared layer, cost, and independence.

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

Requirements:

- Return `(ok, reasons, evidence)`. `ok=None` means "cannot decide" and escalates.
- Prefer deterministic evidence from artifacts, tool results, or the environment.
- Declare an honest `cost_usd`; the runner uses it to order checks.
- Add a test that proves the verifier kills a known defect and passes a clean run.
- Do not use an LLM judge as an oracle.

To ship a verifier as a third-party pack, expose a module that imports your
`@register` classes and add an entry point:

```toml
[project.entry-points."assaystone.verifiers"]
mypack = "mypack.verifiers"
```

Assaystone loads installed packs at import time; a broken pack is ignored.

## Good first issues

Concrete starting points, roughly smallest first:

- Add a trace JSON schema and an `assaystone schema` command.
- Add a Cursor or Windsurf transcript adapter with a redacted fixture.
- Add an intent-aware `tests.weakened` verifier that compares removed test functions
  and assertions against the pre-image.
- Add a redacted failure case to the [Failure Zoo](failure_zoo/README.md) corpus.
- Add a PR comment summary mode for the GitHub Action.
- Add a chart that tracks verifier recall across releases.

Open an issue with the proposal before starting; if an issue already exists, comment
on it. Small PRs with a test and a fixture are easiest to review.

## Add an adapter

Adapters live in `assaystone/adapters/`. They must be duck-typed and must not import
the framework. Add a test with recorded messages, not a live API call.

## Development

```bash
make test       # Python 3.10+ is selected automatically when available
make pytest     # pytest entry point, including plugin collection
make lint
make demo
make benchmark  # Failure Zoo scorecard; fails on a recall regression
```

No runtime dependencies. Python 3.10+.

## Pull request checklist

- [ ] Tests pass (`make test`, `make pytest`).
- [ ] Lint passes (`make lint`).
- [ ] The demo still runs (`make demo`).
- [ ] New verifiers have a layered test (clean + defective).
- [ ] Docs updated if the contract or trace format changed.
- [ ] No secrets or customer data in fixtures.

Security reports: [SECURITY.md](SECURITY.md). Do not open a public issue for a
suspected vulnerability.

## Code of conduct

Be direct, be kind, assume good faith. Harassment is not welcome.
