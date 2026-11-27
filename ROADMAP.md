# Roadmap

The roadmap is a sequence of **proofs**, not a list of features. The direction,
the laws, and the non-goals live in [GOALS.md](GOALS.md). This file is the
current bet and the conditions under which we abandon it.

The outcome target is adoption: a certificate produced on a real agent PR by
someone outside this repository, and a decision someone else can re-check.
Stars, releases, and the number of checks are lagging or vanity indicators.

## P0 — Spine (now)

Make the product one legible thing.

- [x] `GOALS.md` as the canonical direction; `CLAUDE.md` as the operating rules
- [x] Certificate v1: hash-addressed, provenance-bound, versioned
- [x] `verify --certificate` and `certificate verify` (re-check offline)
- [x] `check`: live git worktree → episode → certificate, with no trace
- [x] Five-command surface; everything else under `lab`
- [x] README leads with one workflow, not the whole surface
- [x] Changelog and release tooling stop lying
- [x] Lifecycle surface frozen: no new features in `plane` / `gate` / `trail` /
      `receipt` / `waiver` / `canary` / `drill` / `portfolio` / `prepare` /
      `nextstep` / `brief` / `diff` / `propose` / `leaderboard`
- [x] One documented path from `uvx` to a certificate in under five minutes
      (shipped in v0.33.0: `uvx assaystone demo audit` writes and verifies one)

## P1 — Proof (next)

The only thing that matters now: someone else uses it.

- [ ] 3 external repositories run `check` in CI on real agent PRs
- [ ] 1 public write-up: a defect the tests missed, caught by a certificate
- [ ] False-alarm rate measured on real PRs, not only on the corpus
- [ ] 1 contract authored outside this repository
- [ ] Escalation rate on real runs, with human agreement tracked

**Kill criterion.** If P1 produces no external repository in six weeks, cut the
lifecycle plane and every lab command. Ship `audit` + `check` as a pytest plugin
and a GitHub Action only. A smaller honest product is allowed to win.

## P2 — Harness-native (after P1)

Move the gate to the point of action, with evidence the agent cannot write.

- [ ] Pre-tool / post-tool / pre-final gates
- [ ] Runtime-written evidence outranks agent testimony by construction
- [ ] Spec coverage as a first-class obligation at pre-final
- [ ] Provenance survives compaction, delegation, and subagents; the certificate
      records which view the verifier actually saw
- [ ] Sub-second deterministic path on a real repository

## P3 — Lifecycle (only after P2)

Earn the plane; do not assert it.

- [ ] Gates consume certificates; a receipt binds a certificate id
- [ ] Shadow / canary only when an external user asks for them
- [ ] A third party verifies the trail end to end

## Deletion schedule

Pre-registered, so the decision is not made by attrition:

- Any command with zero recorded external use after 90 days.
- Any check without a measured false-alarm rate after one release.
- The lifecycle plane, if P1's kill criterion fires.
- The leaderboard, portfolio, and capability registry, if still demo-only after
  P1.
- Any domain pack that requires a change to the core.

## Growth guardrails

- No purchased or coordinated stars.
- No invented adoption, customer, or effect claims.
- No "agents cheat everywhere" framing.
- Every public asset includes a runnable command, a concrete failure, and the
  known limitations.
- No release from a red branch. PyPI versions are immutable: verify the wheel,
  then tag.
