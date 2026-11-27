# What we are building

Assaystone is not a better test runner, a linter, or an eval platform. It is an
**acceptance layer**: a way to say what "acceptable" means for an agent's work,
decide it with evidence, and measure whether the decision itself can be trusted.

## The measured problem

The problem is no longer hypothetical:

- **CXBench** (arXiv 2610.25954) ran 840 executions across seven models. **80.1%
  of the runs that reached the right outcome still failed process checks**; only
  **13.8%** passed both. A green result is not an acceptable process.
- **TestMu AI's Agent Assurance** (GA October 2026) ships the same three-valued
  verdict — Pass, Fail, **Unable to Verify** — and reports the share of
  unverifiable criteria as an **assurance gap**. The category is forming.
- **VerifierBench** (arXiv 2610.28679) found that verifiers reject invalid
  solutions more reliably than they accept valid ones; the dominant failure is
  over-restriction, not leniency.
- The verification literature is converging on a second finding: **correlated
  verifiers are an echo.** Judges shown the agent's own report lose recall;
  stacking checks that read the same source adds confidence without adding
  evidence.

So the bottleneck is not generation. It is deciding whether the work is
acceptable, and knowing how much of that decision is real.

## The four layers

```
Acceptance IR  ->  verifier algebra  ->  adversarial scoreboard  ->  runtime
(what must be)     (who decides, at      (can the decision be      (lineage,
                    what cost and          gamed?)                   reversibility)
                    independence)
```

### 1. Acceptance IR

A contract is a set of typed criteria: `precondition`, `invariant`,
`postcondition`, `forbidden_action`, `evidence`. Each has a human statement, a
shared defect tag, an optional verifier binding, severity, and an `on_unknown`
policy.

The criterion is the requirement. The verifier is one way to decide it. A
criterion with no check is an **assurance gap**, not a bug.

### 2. Verifier algebra

Every verifier declares what it claims, what it catches, what it cannot see, what
it costs, and how independent it is. From those declarations the system computes:

- the cheapest independent cover of the declared criteria (`assaystone compose`);
- the residual risk and the assurance gap (`assaystone coverage`);
- the per-criterion verdict (`assaystone verify`).

### 3. Adversarial scoreboard

Recall asks whether a check catches a known defect. **Resistance** asks whether an
agent that knows the contract can pass without doing the work. The Goodhart suite
measures both, by family, and separates a **declared escape** (the check knew it
was blind) from a **surprise**.

No vendor will publish an unfavorable comparison of its own verifier. A neutral
scoreboard can. That is the durable position: the referee's referee.

### 4. Runtime

The same contract runs at the point of action. Irreversible calls require an
approval lineage, not a boolean in evidence; the runtime records the request
itself, so the trace can be walked. Shadow mode and escalation are first-class.

### 5. Acceptance plane

The four layers decide one artifact. A deployment asks more: which capability,
at which lifecycle stage, with which approvals, recorded where, and what happens
after a pass. The acceptance plane is that layer: capability manifests, eight
generic oracles (including a `transcript` oracle that audits the agent's actual
session), a versioned oracle registry, lifecycle gates that report their
assurance gap, checked rollback evidence, and a hash-chained trail. The
criterion language is unchanged; the plane is where it meets an owner, a stage,
and an audit. Reference: [plane.md](plane.md).

## Domain packs

The core is domain-neutral. A domain pack supplies what changes:

| the core needs | the pack provides |
|---|---|
| artifacts and traces | adapters for the domain's artifact types |
| criteria | invariants expressed in the domain's terms |
| decision | oracles: tests, differential replay, policies, human labels |
| reversibility | which actions can be undone, and how |

Code, ops, data, and research ship today. The acceptance IR has the kinds each
domain needs: `invariant` for arithmetic and ledgers, `evidence` for citations
and quotes, `forbidden_action` for leaks and unauthorised actions.

The plane applies the same boundary at deployment level: Java, refunds, and
pricing are manifests, not code paths. Adapting a domain that requires changing
the core is treated as a design failure, not a feature request.

## What makes this different

- **Neutral.** It scores verifier stacks, including commercial ones, not only the
  built-in checks.
- **Open.** A protocol with schemas, a manifest check, and an entry-point SDK. A
  verifier written in another language can be scored by the same benchmark.
- **Measured.** Blind spots and resistance are first-class, not hidden behind a
  pass rate.
- **Honest.** The assurance gap and declared escapes are outputs, not footnotes.

## What it is not

- Not an eval platform with datasets and dashboards. Those are crowded and
  vendor-controlled.
- Not a linter or a type-checker. Those are useful inputs, not acceptance.
- Not a model-cheating benchmark. Those measure the model; this measures the
  verifier.
- Not a hosted service. It runs locally, offline, with no runtime dependencies.

## Roadmap

1. **Measured independence.** The first provenance rule ships: a check that
   trusts agent-written `trace` or `evidence` is downgraded to low. The next step
   is the full source declaration: what a check reads and executes.
2. **Public scoreboard.** External verifier packs scored on the same corpus, with
   their declared blind spots and false-alarm rates.
3. **The domain packs ship.** Code, ops, data, and research use the same IR. The
   next proof is external: real stacks and real cases on the scoreboard.
4. **Statistical honesty.** More controls and confidence intervals; the current
   corpus is a floor, not a population estimate.
5. **Deployment proof.** The plane runs on a real capability, at a real stage,
   with a real approval and a trail someone else can verify. The local validation
   is a start; external use is the test.
