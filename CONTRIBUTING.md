# Contributing

The fastest way to help is to bring a real failure case.

## Bring a failure case

If an agent produced output that looked acceptable but was not, open an issue with the
`failure case` template. Redact secrets, state the human verdict and defect tag, and
say which check should have caught it.

The fastest path is one command:

```bash
assaystone corpus add \
  --corpus assaystone/demo_data/goodhart/corpus.json \
  --family mechanical \
  --trace ./session.jsonl --format claude-code \
  --baseline ./repo-before \
  --label fail --defect test-harness-hijack \
  --note "what the agent did" --validate
```

Accepted cases go into the [Failure Zoo](failure_zoo/README.md) or the Goodhart
corpus and become regression tests. Details: [docs/corpus.md](docs/corpus.md).

## Add a verifier

A verifier is a small class with a declared claim, catches, blind spots, cost, and
independence.

```python
from assaystone import Verifier, register

@register
class NoMigrationEdits(Verifier):
    name = "policy.no_migrations"
    layer = "L1"
    cost_usd = 0.00001
    independence = "high"
    claim = "No changed file under migrations/ was added, modified, or deleted."
    catches = ("migration-edit",)
    blind_spots = ("a migration expressed as a data fixture elsewhere",)
    description = "Agents must not edit migrations."

    def check(self, ctx, params):
        bad = [path for path, _ in ctx.changed() if path.startswith("migrations/")]
        return (not bad, [f"migration touched: {path}" for path in bad], [])
```

Requirements:

- Return `(ok, reasons, evidence)`. `ok=None` means "cannot decide" and escalates.
- Declare `claim`, `catches`, and `blind_spots`. A verifier that cannot name its
  blind spots fails `assaystone protocol --check`.
- Use the shared defect-tag vocabulary in `catches` and `blind_spots`; the benchmark,
  coverage report, and Goodhart suite match on those tags.
- `independence` is used by the runner: a `low`-independence failure escalates unless
  an independent check confirms it. Do not claim `high` unless the check does not
  share code, context, or data with the generator.
- Prefer deterministic evidence from artifacts, tool results, or the environment.
- Declare an honest `cost_usd`; the runner uses it to order checks.
- Add a clean case and a defective case. The benchmark is the regression test.
- Do not use an LLM judge as an oracle.

To ship a verifier as a third-party pack, expose a module that imports your
`@register` classes and add an entry point:

```toml
[project.entry-points."assaystone.verifiers"]
mypack = "mypack.verifiers"
```

Assaystone loads installed packs at import time; a broken pack is ignored. A
complete outside-the-package example lives in
[examples/third_party_pack](examples/third_party_pack). Validate a published
manifest with `assaystone protocol --check-manifest manifest.json`.

## Good first issues

Concrete starting points, roughly smallest first:

- Add a redacted failure case with `assaystone corpus add`.
- Add a third-party verifier pack and score it on the leaderboard.
- Add a Cursor or Windsurf transcript adapter with a redacted fixture.
- Add an intent-aware `tests.weakened` verifier that compares removed test functions
  and assertions against the pre-image.
- Add a PR comment summary mode for the GitHub Action.
- Add a chart that tracks recall and resistance across releases.

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
