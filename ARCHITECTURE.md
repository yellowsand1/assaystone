# Architecture

The target design. [GOALS.md](GOALS.md) says why; this file says how.

## One pipeline

```
episode        one unit of agent work: a working tree, a recorded trace, or a runtime action
   ↓
contract       obligations (criteria) + checks + policy (on_unknown, budget)
   ↓
checks         declared: claim / catches / blind_spots / trusts / cost / independence
   ↓
evidence       a pointer into an artifact, a command result, or a trace event
   ↓
decision       pass | fail | escalate  (+ first_failure, + unconfirmed)
   ↓
certificate    hash-addressed, provenance-bound, re-checkable offline
```

Nothing in the product is outside this pipeline. A feature that does not feed
evidence into a decision is lab code.

## The five commands

| command | question | input | output |
|---|---|---|---|
| `audit` | what is wrong with what this agent already did? | transcript, export, repo | findings + a suggested contract |
| `check` | is this episode acceptable? | working tree + base ref, or a trace | certificate |
| `certificate show\|verify` | can I re-check this decision? | a certificate | summary / valid or tampered |
| `prove` | can I trust the checks themselves? | a labelled corpus | recall, false alarms, resistance, cost |
| `hook` | can I run the same contract in the harness? | agent hook payload | block / warn / record |

Everything else lives under `assaystone lab` and is frozen. Old top-level names
(`verify`, `scorecard`, `gate`, …) still resolve as aliases so CI does not break,
but they are not part of the surface and receive no new features.

## Data contracts

**Episode.** `Trace` in `model.py`: id, task, agent, steps, artifacts, evidence,
source. `source="runtime"` means the checker read the filesystem itself;
`source="agent"` means the content came from a transcript. The distinction is
load-bearing: testimony from an agent trace downgrades any check that trusts it.

`GitEpisode` (`episode.py`) builds a runtime-sourced episode from
`git diff <base>..worktree` plus untracked files, and materializes the base tree
as a temporary worktree so the contract can run tests against the real baseline.

**Contract.** `contract.py`: verifier specs, criteria, budgets, `on_unknown`.
Criteria are the human-readable requirements; a verifier spec is one way to
decide them. A criterion without a verifier is an open obligation, reported in
the certificate's `assurance.open_obligations`.

**Check.** `verifiers.py`: `claim`, `catches`, `blind_spots`, `trusts`,
`independence`, `cost_usd`, `layer`, and `check(ctx, params) -> (ok|None,
reasons, evidence)`. `None` is escalation, not failure.

**Certificate.** `certificate.py`, schema `assaystone.certificate/1`. The `id` is
the content address of the decision: `issued_at` and per-check `duration_ms` are
excluded, so the same decision keeps the same id across machines. `verify`
recomputes the id; it does not re-run the agent.

## The layers

```
core/        model, contract, checks, runner, workspace, certificate, episode
checks/      diff, tests, quality, claims, policy        (deterministic by default)
harness/     claude_code, codex, ci, pytest_plugin
measure/     corpus, prove, stats
cli/         main, audit, check, certificate, prove, hook
lab/         plane, gates, oracles, registry, waivers   (frozen)
```

The physical layout is being migrated as files are touched; the boundary is
enforced now:

- `core` may not import `lab`.
- `checks` may not import `cli`, `harness`, or `lab`.
- `certificate` may not import `oracles` or `plane`.
- The default path imports no network client, no API key, and no LLM judge.

## Invariants

1. A decision always carries evidence; `verify --no-evidence` refuses to write a
   certificate.
2. A low-independence failure never decides alone; it becomes an escalation
   unless an independent check confirms it.
3. A check that crashes fails closed: `ok=None`, never `True`.
4. The runner is ordered by declared cost and stops at the first decisive
   failure; skipped checks are recorded in `assurance.not_run`.
5. Same episode + same contract + same versions → same certificate id.
6. The deterministic layer makes no network calls.
7. A check ships only with a clean case, a defective case, and a declared blind
   spot.

## Migration status

| area | state |
|---|---|
| certificate v1 + offline verify | done |
| `check` on a live git worktree | done |
| five-command surface, lab frozen | done |
| `prove` (recall, resistance, false alarms, cost in one report) | next |
| harness gates (pre-tool / post-tool / pre-final) | pre-tool done; post-tool and pre-final next |
| spec coverage as a first-class obligation | next |
| provenance across compaction and delegation | workspace-root inference done; view metadata next |
| lifecycle gates consuming certificates | frozen until P2 |
