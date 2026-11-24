# Roadmap

Assaystone's outcome target is 1,000 GitHub stars, but stars are a lagging indicator.
The product goal is a trusted, vendor-neutral acceptance layer that developers actually
run against real agent work.

## Now — make the first run useful

- [x] Audit Claude Code and Codex CLI transcripts
- [x] One-command discovery with `assaystone audit --latest`
- [x] Deterministic audit rules, contracts, CI reports, and runtime gates
- [x] Claude Code plugin marketplace and fail-open Stop hook
- [x] GitHub Action outputs and a hosted landing page
- [ ] Publish the Action to GitHub Marketplace
- [ ] Enable GitHub Discussions and seed the first community threads

## Next — increase proof and contribution surface

- [x] Public Failure Zoo benchmark runner and release scorecard
      (`assaystone benchmark failure-zoo`, `docs/failure-zoo.md`)
- [ ] Intent-aware test weakening detection with clean and defective fixtures
- [ ] Cursor or Windsurf transcript adapter
- [ ] PR comment summary mode for the GitHub Action
- [ ] Chart verifier recall across releases
- [ ] Five external, redacted failure cases from real users
- [ ] Integration guides for Claude Code, Codex, OpenAI Agents SDK, and LangGraph

## Later — make verification portable

- [ ] Data reconciliation and report citation packs
- [ ] Verifier registry with reproducible benchmark metadata
- [ ] TypeScript port or a language-neutral trace CLI
- [ ] A public benchmark with per-domain verifier recall and false-alarm rates

## Growth guardrails

- No purchased or coordinated stars
- No invented adoption or customer claims
- No “agents are cheating everywhere” framing
- Every launch asset should include a runnable command, a concrete failure, and the
  known limitations
