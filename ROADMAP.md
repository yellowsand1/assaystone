# Roadmap

Assaystone's outcome target is adoption: a capability gated by a manifest someone
else wrote, external verifier packs scored by the same benchmark, and decisions a
third party can re-check. Stars are a lagging indicator.

The center moved from "a verifier library" to the deployment layer above it. The
protocol and the two benchmarks are now the measurement layer for that plane.

## Now — the acceptance plane, and external proof

- [x] Acceptance IR: typed criteria, per-criterion verdicts, assurance gap
- [x] Verifier ABI and independence-aware verdicts: a low-independence failure
      escalates unless an independent check confirms it
- [x] Nine generic oracles: `command`, `file`, `git`, `human`, `http`, `sql`,
      `shadow`, `transcript`, `verifier`
- [x] Capability manifests and `shadow` / `canary` / `production` gates
- [x] Chained stages: a later stage requires a recorded earlier pass under the
      same manifest digest, and the chain verifies the trail before trusting it
- [x] Versioned oracle registry with pins, fingerprints, and no payload override
- [x] Hash-chained gate trail, manifest-digest continuity, signed approvals
- [x] Checked rollback evidence; `capability validate --strict` reports a
      criterion no stage gates
- [x] Failure Zoo recall benchmark, Goodhart resistance suite, report card
- [x] External `pytest` and `ruff` adapters; a third-party pack example
- [x] Data reconciliation and report citation packs
- [ ] One external capability gated end to end (shadow → canary → production)
- [ ] Five external verifier packs scored by the benchmark
- [ ] Five external, redacted adversarial cases from real users
- [ ] Publish the Action to GitHub Marketplace

## Next — proof and contribution surface

- [x] Public Failure Zoo benchmark runner and release scorecard
- [ ] Intent-aware test weakening detection with clean and defective fixtures
- [ ] Reversibility: dry-run and compensation as executable oracles
- [ ] Canary metrics guide with a real staging endpoint (error rate, latency)
- [ ] Cursor or Windsurf transcript adapter
- [ ] PR comment summary mode for the GitHub Action
- [ ] Chart verifier recall and resistance across releases
- [ ] Integration guides for Claude Code, Codex, OpenAI Agents SDK, and LangGraph

## Later — make verification portable

- [ ] A registry of conformant verifier manifests, with reproducible benchmark
      metadata per pack
- [ ] TypeScript port or a language-neutral trace CLI
- [ ] Per-domain leaderboards with recall, resistance, coverage, and cost

## Growth guardrails

- No purchased or coordinated stars
- No invented adoption or customer claims
- No “agents are cheating everywhere” framing
- Every launch asset should include a runnable command, a concrete failure, and the
  known limitations
- No release from a red branch. PyPI versions are immutable: verify the wheel,
  then tag.
