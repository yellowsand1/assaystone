# Assaystone — Goals

> **Status:** canonical. Read this before changing code, docs, or scope.
> **Last updated:** 2026-11-27
> **Supersedes:** the 2026-11 direction draft (now archived in git history),
> the narrative in `ROADMAP.md`, and any roadmap implied by the CHANGELOG.

---

## 0. The sentence we must be able to defend

**Assaystone turns one unit of agent work into a certificate: pass, fail, or a
human must look — with the evidence, the check that decided it, the check that
could not, and the cost of deciding.**

If a change does not make that sentence more true, it is not our work.

---

## 0.5 The one thing only we do

Every verifier on the market tells you a verdict. Almost none tells you what
the verdict is worth. Assaystone attaches the measurement to the decision:

- each check carries recall on the defect classes it **claims**, false-alarm
  rate on clean cases, adversarial recall, and the sample size behind the number;
- the certificate cites the digest of the profile it used, so a reviewer sees
  the instrument's calibration, not only its output;
- a check with no measurement says `unmeasured`; it does not get a number;
- the registry is public and neutral. A vendor will not publish an unfavorable
  number about its own checker; a neutral registry can. That is the durable
  position: the referee's referee, made portable.

The corpus and the measurements compound. A competitor can copy the code; it
cannot copy the evidence without doing the work.

---

## 1. Why this exists

Agents have converged. The loop is commodity: messages, tool calls, context
compaction, subagents. ShellBench (arXiv 2611.32946) ran 53,100 rollouts across
12 models and 5 harnesses and found harness choice moves pass@1 by ~2 points
while model choice moves it far more. A 100-line agent loop is competitive.
**Differentiation is no longer the loop. It is the environment, the evidence,
and the decision.**

What has not converged is the answer to: *is this work acceptable?* The evidence
says this is the actual bottleneck:

- **Outcome pass is not process pass.** CXBench (arXiv 2610.25954): 80.1% of
  runs that reached the right outcome failed process checks; only 13.8% passed
  both.
- **Capability is not reliability.** FIRE (arXiv 2609.26048): converting
  reachable solutions into repeatable delivery (pass²) is worth ~9 points where
  best-of-two moves ~1. Generic "check it again" interventions scored 39–43%,
  statistically indistinguishable from a sham; state-specific policies scored
  61%.
- **Verification does not survive abstraction.** A verifier judging compacted,
  delegated, tool-composed executions disagrees with the native view ~31% of the
  time; restoring provenance recovers 85.5% of those failures (arXiv 2611.18471).
- **Some things cannot be decided offline at all.** Post-Audit Mirage
  (arXiv 2610.31130) constructs matched lifecycles with identical
  verifier-visible evidence and opposite deployment truth. "Cannot determine" is
  a required verdict, not a failure.
- **Instruments fail silently.** Silent Instrument Errors (arXiv 2611.04399)
  found four grader bugs across two public leaderboards, one of which moved
  scores 59–82 points without printing an error. Evaluation infrastructure is
  part of the measurement.
- **There is no free checker.** No Free Checker (arXiv 2609.09250) surveys ~150
  verifiers: availability and credibility are monotonically opposed. Every
  verifier is a point on that curve, and must say where it sits.
- **Verifiers are an attack surface.** Verifier hardening (arXiv 2610.15924)
  shows programmatic verifiers can be driven to award full credit to cheating
  agents; a hacker–fixer loop is now used to audit Terminal-Bench environments.
- **Verifiers are widely built and rarely adopted.** Pure eval vendors have been
  absorbed into gateways (LiteLLM, Portkey), observability (Langfuse → ClickHouse,
  Braintrust), model labs (Humanloop → Anthropic), or forced into security
  (Promptfoo). Verification survives as a **feature of the layer that owns the
  traffic, the artifact, or the data** — not as a standalone score.

The conclusion is not "build a better judge". It is: **build the evidence that
makes a decision defensible, in the place where the work already happens.**

---

## 2. Who we serve, and the one job

**Primary user:** the engineer who reviews an agent's pull request and has to
put their name on it.

**Their job:** *"Before I merge this, tell me what the agent actually did, what
it did not do, and what you could not check."*

**Secondary user:** the platform engineer who has to let an agent touch a
staging or production system, and needs a decision they can defend afterwards.

We do **not** serve: ML researchers comparing models, compliance teams buying a
GRC suite, or teams who want a dashboard. Those are different products with
different buyers, and we lose to them on their turf.

---

## 3. The kernel

One pipeline, one artifact:

```
contract        what must be true, in a language a domain expert can review
  criteria      obligations: id, kind, statement, defect tag, severity, on_unknown
  checks        declared: claim / catches / blind_spots / trusts / cost / independence
      ↓
evidence        pointers into the diff, the transcript, command output, a source span
      ↓
decision        pass | fail | escalate   (+ first_failure, + unconfirmed flags)
      ↓
certificate     a hash-addressed object any third party can re-check
```

Rules that are not negotiable:

- **The criterion is the requirement. The check is one way to decide it.** A
  criterion with no check is an **assurance gap** — an output, not a bug.
- **Three-valued.** `pass`, `fail`, `escalate`. A check that cannot see says so.
- **Independence is computed from provenance.** Anything the agent wrote is
  testimony. Testimony from an agent trace is downgraded, regardless of what the
  check declares. Runtime-written evidence outranks it.
- **Cascade by cost.** Deterministic invariants → tests → structural/evidence
  checks → judge. A judge never decides alone.
- **The certificate is the product surface.** JSON on stdout is an implementation
  detail.

---

## 4. Two surfaces, one currency

| surface | question | entry points | status |
|---|---|---|---|
| **Episode** | Is *this* unit of work acceptable? | `audit`, `verify` | **active** |
| **Lifecycle** | May *this capability* move to the next stage? | `capability`, `gate`, `trail`, `receipt` | **frozen** |

The certificate is the currency between them. A gate consumes certificates; it
must not re-invent evidence or grow a parallel verdict language.

**Freeze rule:** no new work on the lifecycle surface until the episode surface
has external users and a measured false-alarm rate. The code stays, the tests
stay green, the narrative stops leading with it.

---

## 5. The nine gaps — we attack them one at a time

Agents fail to land in nine places. A check covers one of them. We do not pretend
otherwise; we say which one we are attacking now.

| # | gap | what exists | our status |
|---|---|---|---|
| 1 | acceptance criteria live in someone's head | contracts, criteria, `propose` | **attacking** |
| 2 | the world is not observable | trace importers, session record | partial |
| 3 | no cheap, authoritative oracle | verifier ladder, transcript/diff oracles | **attacking (code only)** |
| 4 | actions are irreversible | dry-run, compensation | later — frozen |
| 5 | self-report is not evidence | provenance, independence downgrade | **attacking** |
| 6 | no owner, escalation, or audit | plane, waivers, receipts | later — frozen |
| 7 | verification costs more than it saves | cost model, triage, escalation | **attacking** |
| 8 | long-horizon error compounds | — | later |
| 9 | it does not fit existing tools | pytest, CI, hooks, Action | **attacking** |

**Domain wedge: coding agents.** Not because code is the end state, but because
code has the cheapest oracles in existence — compilers, tests, diffs, exit codes
— and therefore the shortest path from a verdict to a person who will act on it.
Every abstraction must be earned here before it is generalized.

---

## 6. The ten laws

1. **Evidence or it did not happen.** A verdict carries pointers a third party
   can re-open: artifact digest, command output, source span, trace event. No
   pointer, no verdict.
2. **Three values, never two.** `pass` / `fail` / `escalate`. Silent guessing is
   the failure mode we exist to remove.
3. **Cascade, and never judge alone.** Cheap deterministic checks first. A
   low-independence check raises a flag; it does not decide.
4. **Independence is provenance, not a claim.** We downgrade checks that trust
   agent-written testimony, even when they declare themselves independent.
5. **The contract is the product.** Checks are replaceable. Criteria, defect
   tags, and `on_unknown` are the durable artifact.
6. **Verify the verifier, and carry the measurement.** Every check ships with a
   clean case, a defective case, a declared blind spot, a measured cost, and a
   reliability profile. The profile travels with every certificate the check
   decides. If we cannot measure it, it is not shipped.
7. **Cheap in the loop.** The deterministic layer runs in under a second on a
   normal PR. If it cannot, it is CI-only and must say so.
8. **No new category.** We live in pytest, CI, the agent hook, and the PR
   comment. If adoption requires a new dashboard, we have failed.
9. **Every feature buys evidence or removes cost.** Otherwise it is deleted,
   not deferred.
10. **One external user beats ten features.** No new surface until the previous
    one has a named user outside this repository.

---

## 7. Non-goals

- **Not an eval platform.** No datasets, dashboards, or leaderboard product. The
  Failure Zoo is a credibility asset and a regression corpus, not a destination.
- **Not a general LLM judge.** Judges are a filter on the last rung; the default
  path is offline, deterministic, and key-free.
- **Not an agent framework.** We do not run agents, choose models, or manage
  context. We judge what they produced.
- **Not a hosted service.** The certificate is portable precisely because the
  decision is local.
- **Not a GRC or compliance suite.** The plane is frozen until earned.
- **Not a reward model or training pipeline.** We borrow the vocabulary; we do
  not train weights.
- **Not "agents cheat everywhere" marketing.** We publish measured, scoped
  failures and their sample size.

---

## 8. How we measure success

Adoption and honesty, not activity:

| metric | target | why |
|---|---|---|
| Time to first verdict (own repo) | < 5 minutes | the cold start is the product |
| `uvx assaystone demo audit` | < 60 seconds, no setup | the first screen must land |
| Certificate determinism | same inputs + versions → same id | a decision must be reproducible |
| Deterministic layer p95 | < 1 s on a 50-file diff | law 7 |
| False-alarm rate per shipped check | measured, ≤ 5% on the labelled corpus | an alarm nobody trusts gets switched off |
| Failure Zoo recall | no regression across releases | the checks must keep working |
| External repos with a passing gate | 3 by end of P1 | the only real proof |
| Real defects caught that tests missed | ≥ 1, published with permission | the value claim |
| External contracts authored by someone else | ≥ 1 | the protocol must be usable without us |

Vanity metrics we do not report as success: stars, releases, number of
verifiers, number of domain packs, lines of code.

---

## 9. Roadmap and kill criteria

### P0 — Spine (now)

- [x] This document
- [x] **Certificate v1**: hash-addressed, provenance-bound, versioned
- [x] **Measured reliability travels with the decision**: per-check recall,
      false-alarm rate, sample size, and a corpus digest in every certificate
- [x] `verify --certificate`; `certificate verify` to re-check a third-party file
- [x] `check`: a live git worktree becomes an episode and a certificate, with no
      trace and no instrumentation
- [x] Five-command surface (`audit`, `check`, `certificate`, `prove`, `hook`);
      everything else moved under `lab` and frozen
- [x] README leads with one workflow: audit → check → certificate → CI
- [x] Changelog and release tooling stop lying
- [x] One documented path from `uvx` to a certificate in under five minutes
      (shipped in v0.33.0: `uvx assaystone demo audit` writes and verifies one)

### P1 — Proof (next)

- [ ] 3 external repositories run `check` in CI on real agent PRs
- [ ] 1 public write-up: a defect the tests missed, caught by a certificate
- [ ] False-alarm rate measured on real PRs, not just the corpus
- [ ] 1 contract authored outside this repository

**Kill criterion:** if P1 produces no external repository in 6 weeks, cut the
plane and every lab command. Ship `audit` + `check` as a pytest plugin and a
GitHub Action only. That is a smaller, honest product, and it is allowed to win.

### P2 — Harness-native (starts after P1, unless the owner orders otherwise)

> P1 remains the top metric. The owner authorized the pre-tool gate early because
> no external repository was available; it adds no new user-facing surface beyond
> `hook`.

- [x] Pre-tool gate with runtime-written evidence (`.assaystone/session.jsonl`)
- [x] Post-tool and pre-final gates with runtime evidence
- [x] Spec coverage as a first-class obligation (v1: deterministic
      evidence rules; pre-final runs the same contract)
- [ ] Provenance survives compaction and delegation (certificate says what view
      the verifier saw)
- [x] Sub-second deterministic path on a real repository (68–98 ms on Flask; see
      `docs/field-note-flask.md`)

### P3 — Lifecycle (only after P2)

- [ ] Gates consume certificates; receipts bind a certificate id
- [ ] Shadow / canary only when an external user asks for them

---

## 10. The change review

Every PR, issue, and idea answers five questions:

1. Does it increase evidence per decision, or decrease the cost of a decision?
2. Can a third party re-check the output without re-running the agent?
3. Does it work offline, with no key, on the default path?
4. Does it reduce time-to-first-verdict for the primary user?
5. Is it a new surface? If so, name the external user who asked for it.

If 1 is no, it is not our work. If 5 is yes and there is no name, it waits.

---

## 11. What we will delete if it fails

Pre-registered, so the decision is not made by attrition:

- Any command with zero recorded external use after 90 days.
- Any check without a measured false-alarm rate after one release.
- The lifecycle plane, if P1's kill criterion fires.
- The leaderboard, the portfolio, and the capability registry, if they remain
  demo-only after P1.
- Any domain pack that requires a change to the core.

Deletion is a success condition, not a failure: it means the kernel survived.

---

## Appendix — reading that shaped this

- Jason Wei, *Asymmetry of verification and verifier's rule* (2025)
- Snell et al., *Scaling LLM Test-Time Compute Optimally* (2024)
- Huang et al., *Large Language Models Cannot Self-Correct Reasoning Yet* (2023)
- CXBench (2026), VerifierBench (2026), No Free Checker (2026)
- FIRE (2026), Verification Transport (2026), Post-Audit Mirage (2026)
- Silent Instrument Errors (2026), Verifier Hardening (2026)
- Agent-as-a-Verifier (2026), LLM-as-a-Verifier (2026)
- Rubric Curriculum RL (2026), Specification Satisficing (2026)
- VFM (2026), Evidence Sufficiency (2026), Admitted Is Not Effective (2026)
