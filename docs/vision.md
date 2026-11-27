# Product model

> This page replaced the four-layer "acceptance plane" narrative in November
> 2026. The direction is [GOALS.md](../GOALS.md); the design is
> [ARCHITECTURE.md](../ARCHITECTURE.md).

The short version:

- **One artifact.** A unit of agent work becomes a certificate: pass, fail, or a
  human must look — with evidence, the check that decided it, the check that
  could not, the assurance gap, and the cost.
- **One pipeline.** episode → contract → checks → evidence → decision →
  certificate.
- **Two surfaces.** The episode surface is active: `audit` (cold start) and
  `check` (a worktree or a recorded trace becomes a certificate). The lifecycle
  surface — capability manifests, stages, gates, trails, receipts — is frozen
  under `assaystone lab` until the episode surface has external users.
- **One measurement.** `prove` answers whether the checks themselves can be
  trusted: recall on labelled defects, resistance to a contract-aware agent,
  false alarms, and cost.

The acceptance plane's oracles and gates remain in the code and keep their
tests. They are not the product until someone outside this repository uses the
episode surface first.
