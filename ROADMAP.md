# Roadmap

Assaystone's outcome target is adoption: external verifier packs scored by the same
benchmark, and contracts running in CI. Stars are a lagging indicator.

## Now — the protocol and the two benchmarks

- [x] Verifier ABI: `claim`, `catches`, `blind_spots`, `cost`, `independence`
- [x] Independence-aware verdicts: a low-independence failure escalates unless an
      independent check confirms it
- [x] Protocol v1 JSON Schemas, catalog, contract check, and manifest check
- [x] Failure Zoo recall benchmark and the Goodhart resistance suite
      (`mechanical`, `ops_lineage`, and `semantic` families)
- [x] Contract coverage and a one-page report card with a single exit code
- [x] External `pytest` and `ruff` adapters; a third-party pack example
- [x] Approval lineage recorded by the runtime and checked by `ops.approval_lineage`
- [ ] Five external verifier packs scored by the benchmark
- [ ] Five external, redacted adversarial cases from real users
- [ ] Publish the Action to GitHub Marketplace

## Next — proof and contribution surface

- [x] Public Failure Zoo benchmark runner and release scorecard
      (`assaystone benchmark failure-zoo`, `docs/failure-zoo.md`)
- [ ] Intent-aware test weakening detection with clean and defective fixtures
- [ ] Cursor or Windsurf transcript adapter
- [ ] PR comment summary mode for the GitHub Action
- [ ] Chart verifier recall and resistance across releases
- [ ] Integration guides for Claude Code, Codex, OpenAI Agents SDK, and LangGraph

## Later — make verification portable

- [ ] Data reconciliation and report citation packs
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
