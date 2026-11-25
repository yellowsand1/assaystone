# Changelog

## Unreleased

No changes yet.

## 0.9.0 — 2026-11-25

- **`capability brief`.** Render the manifest as a task brief for an agent: the
  criteria, the oracle bindings, the stage requirements, the exact gate command,
  and the rules against weakening tests, CI, or the manifest and against
  overriding a criterion. In the case study, the same task failed the API oracle
  without the brief and was reverted by the agent with it. The brief is a view of
  the manifest, not a second source of truth.
- **`transcript` oracle `ignore`.** Paths or globs excluded from the session
  artifacts, so the gate's own `.assaystone/` tooling is not counted as agent
  output. The real-agent run in the case study found this: an untracked
  `api_diff.py` produced a false `no_debug_prints` finding.
- **Lifecycle case study.** A real Maven module was taken through shadow, a
  public-API defect that compilation and an empty test suite cannot see, an
  escalation for a missing approval, a chained canary → production promotion,
  and a verified `git revert`. A second SQL/shadow domain ran on the same core.
  The write-up, with what it does and does not prove, is
  [docs/case-study-lifecycle.md](docs/case-study-lifecycle.md). A real Claude
  Code agent then made the same class of change in a fresh clone: it reported a
  verified build, and the gate still failed at the API oracle.
- **Java public-API oracle example.** `examples/capability/java_api_diff.py`
  compares `javap -public` against a git baseline in a temporary worktree. It is
  a command payload, not a new primitive.

## 0.8.0 — 2026-11-25

- **The GitHub Action gates a capability.** Pass `manifest` + `stage` (and
  optionally `root`, `audit`, `actor`, `strict`) instead of `contract` +
  `traces`. The action writes the oracle table to the job summary, sets
  `verdict` and `findings`, and exits non-zero on `fail` or `escalate`. A CI job
  now exercises the action against the pricing fixture.

## 0.7.0 — 2026-11-25

- **Chained lifecycle stages.** A policy can require a recorded pass of an
  earlier stage: `"production": {"after": "canary"}`. The gate reads the trail,
  takes the most recent entry for the same capability and stage, and escalates
  when that entry is missing, did not pass, or was decided under a different
  manifest digest. The trail records the chained entry (`prior`). CI must carry
  the same trail artifact between stages.

## 0.6.0 — 2026-11-25

### Acceptance plane: bind verifier checks and service metrics

- **`verifier` oracle.** A manifest can bind any check from the verifier ABI —
  `tests.integrity`, `diff.forbidden_paths`, `quality.no_debug_prints` — against
  the working-tree diff, using a temporary worktree of `HEAD`. Checks that trust
  agent testimony escalate (bind `transcript` instead); `tests.pass` needs
  `run_tests`. The verifier's claim, blind spots, and independence travel with
  the gate result.
- **Static assurance gap.** `capability validate` reports criteria that no
  stage gates at all, and `--strict` fails when one is critical. This is the
  manifest-level version of the per-stage gap the gate already reports.
- **Numeric HTTP thresholds.** `lte`, `gte`, `lt`, and `gt` compare a JSON path
  against a bound, so a canary policy can require an error rate or a latency
  directly. A boolean is rejected as a metric rather than compared as 1.

### Acceptance plane: the agent's session becomes gate evidence

- **`transcript` oracle.** The eighth primitive audits what the agent actually
  did: it runs the session audit over a transcript, trace, or directory and
  fails when a finding meets `fail_on`. Findings inherit the kernel's
  provenance rules, so a failure that rests on agent-written testimony arrives
  as an escalation. `git_preimage` and `workspace` cover pre- and post-session
  working trees; `run_tests` is opt-in. A session with no artifacts escalates
  instead of passing: there is nothing to diff, and a read-only session is not
  a clean change. Transcripts must stay inside the gate root. Validated on a
  real local Maven session: 12 artifacts, one unsupported-language finding,
  escalation in 0.05s.
- **Manifest digest and signed approvals.** A gate records the digest of its
  acceptance rules; a changed manifest escalates against an existing trail until
  `--accept-manifest-change`. A `human` oracle with `hmac_env` verifies an
  HMAC-SHA256 signature over the approval list.

### Acceptance plane: two more primitive families, a registry, and a trail

- **`http`, `sql`, and `shadow` oracles.** The plane now has seven generic
  primitives. `http` reads a status, a JSON path, or a matcher, resolves
  credentials from the environment, refuses to follow redirects, requires
  `allow_write` for mutating methods, and bypasses environment proxies for
  loopback hosts. `sql` accepts one read-only `SELECT`/`WITH` statement, opens
  SQLite with `mode=ro` and `query_only`, uses a read-only MySQL session when
  `pymysql` is installed, caps results, and escalates on an absent driver.
  `shadow` runs an old and a new implementation on the same input and compares
  text, JSON (ignored paths, numeric tolerance), or exit outcomes; divergence
  fails, a broken baseline escalates.
- **Oracle registry.** Shared oracle definitions live in a versioned
  `oracles.json`. Manifests reference them with a version pin; a ref cannot
  override `type` or `payload`, so a capability cannot quietly weaken a shared
  oracle. Every oracle carries a fingerprint, and the manifest records the
  registry fingerprint. `examples/capability/java.json` now resolves its Maven,
  artifact, and branch oracles from `examples/capability/oracles.json`.
- **Audit trail.** `gate --audit PATH --actor NAME` appends a hash-chained JSONL
  entry naming the capability, stage, actor, outcome, per-oracle evidence
  digests, missing oracles, and the assurance gap. `assaystone trail verify`
  recomputes the chain and reports where it broke; `--expect HASH` detects
  truncation when the head is anchored externally. The documentation states
  what a local chain cannot prove.
- **Assurance gap at the gate.** Every gate reports declared criteria the stage
  does not gate. `--strict` escalates when a critical criterion is ungated; a
  failure still outranks the gap.
- **MySQL validated on a live server.** The `sql` adapter ran against MySQL
  8.0.31: the session reports `transaction_read_only = 1`, scalar, row, and CTE
  expectations pass, and a write is rejected before a connection opens. MySQL
  returns `DECIMAL` for arithmetic; scalar and row comparisons now treat it as
  numeric with `tolerance` instead of comparing its string form. Optional tests
  run when `ASSAYSTONE_TEST_MYSQL_DSN` is set and skip otherwise.
- **A changed manifest is visible.** Every gate result and trail entry carries
  a `manifest_digest`: the acceptance rules with registry payloads, excluding
  the registry path. On a trail with a previous entry, a changed digest
  escalates until someone re-runs with `--accept-manifest-change`. An agent can
  still edit its manifest; it cannot do so silently.
- **Signed approval records.** A `human` oracle with `hmac_env` verifies an
  HMAC-SHA256 signature over the approval list. A missing key escalates, an
  unsigned or altered record fails. Without it, the record is a file and is
  documented as testimony, not evidence.
- **`capability init`.** Onboarding for the plane: inspect a repository for
  Maven, Gradle, npm, Python, Go, or Cargo, follow the branch convention it
  already uses, and write a draft `.assaystone/capability.json`. The draft
  declares no approvals and no rollback claim, because inventing either would
  be the unchecked assertion this project argues against. Detection lives in
  `scaffold.py`, outside the plane.
- **`assaystone demo plane`.** One screen for the plane: a pricing change
  passes `shadow` with a declared gap, a wire-format change that keeps the unit
  tests green fails at `parity`, `canary` escalates without approval and passes
  with it, and the trail detects an edited outcome. The demo copies its fixture
  to a temporary directory and leaves only the trail behind.
- **Fail closed under bad payloads.** A malformed timeout, an invalid regex, a
  non-UTF-8 artifact, or any other primitive error becomes `escalate` with the
  exception name; the gate never crashes. `trail append` refuses to extend a
  chain that does not verify.
- **Rollback is checked, not claimed.** A policy with `rollback_required`
  must name a `rollback` oracle; without one the manifest is invalid. The gate
  runs it as a required check, so a production decision carries the evidence
  and its digest. The three example capabilities bind human or command
  rollback oracles.
- **Third domain, manifest only.** `pricing.json` checks a fee refactor with a
  `shadow` parity oracle, a `sql` ledger oracle, a `command` test oracle, and a
  human publish approval. `pricing_project` is deterministic and needs no
  network, JVM, or database server. `plane.py` gained no domain-specific code.
- **Proxy fix.** A loopback `http` oracle no longer routes through
  `http_proxy`; a refused local connection used to arrive as a proxy error page
  and read as a failure instead of an escalation.
- **Coverage of the new surface.** 59 new tests, 350 total.

### Verifier protocol and adversarial measurement

- **Verifier protocol v1.** Every verifier now declares `claim`, `catches`,
  `blind_spots`, `cost`, and `independence`. `assaystone protocol` prints the
  catalog, `--schemas DIR` exports contract/verifier/verdict JSON Schemas, and
  `--check` validates a contract without a third-party dependency. A verifier that
  cannot name its blind spots fails conformance.
- **Independence-aware verdicts.** A low-independence failure can no longer decide
  alone. The runner seeks independent confirmation and escalates when none arrives;
  unknown independence levels are treated as low. `Verdict` and `RunResult` carry
  the independence level and the unconfirmed failures.
- **Contract coverage.** `assaystone coverage` separates declared defect classes
  that are decided by an independent check, weakly covered by a low-independence
  check, and not covered at all. `--strict` exits non-zero on residual risk.
  Contracts gain `required_defects`.
- **Goodhart suite.** `assaystone benchmark goodhart` measures whether an agent
  that knows the contract can obtain a clean pass without doing the work. The
  bundled adversary is split into `mechanical` attacks (startup-hook hijack,
  stdlib module shadow, CI bypass), `semantic` attacks (an untested behavior
  change and hardcoded test inputs), and an `ops_lineage` attack (an approval
  recorded in evidence but absent from the trace). Mechanical and ops resistance
  are 100%; semantic resistance is 0%; the overall 67% is reported with both
  escapes declared as blind spots rather than surprises.
- **Approval lineage.** The runtime now records an `approval.request` step before
  an irreversible action, and `ops.approval_lineage` walks the trace instead of
  trusting a boolean in evidence. An approval that exists only as a claim is
  caught even when `ops.approval_recorded` is satisfied. The check matches the
  approved arguments, so an approval for 4000 cents does not cover an 8000-cent
  refund.
- **Refund lineage.** `ops.refund_lineage` requires one `refund.create` step per
  new refund row. Two identical refunds recorded from a single step are caught,
  even when the ledger balances and every id is unique.
- **Corpus on-ramp.** `assaystone corpus add` turns a trace or a redacted
  transcript into a labelled fixture in an existing family, replays a transcript
  against a baseline, and optionally validates the new case against the current
  pack. See [docs/corpus.md](docs/corpus.md).
- **Leaderboard.** `assaystone leaderboard --manifest benchmarks/leaderboard.json`
  compares several contracts on coverage, recall, resistance, false alarms, cost,
  and a single result. The committed table is
  [docs/leaderboard.md](docs/leaderboard.md).
- **Default-stack result.** `benchmark goodhart --contract` now scores an
  arbitrary contract on the adversarial corpus. The bundled pytest+ruff contract
  covers its two declared classes and resists 0/3 mechanical attacks; one escape
  (CI bypass) is a surprise because neither tool declares that blind spot.
- **Adoption script.** [docs/adoption.md](docs/adoption.md) is the 45-minute
  design-partner script: who to ask, the invitation, the agenda, and what to
  collect.
- **Two-domain adaptation.** The plane runs a synthetic Java change (compile,
  class artifact, feature branch) and a support refund (ledger JSON, policy
  limit, manager approval) from manifests only; `plane.py` is unchanged.
  `java_local.json` uses `javac` so the gate runs without a Maven download.
- **Acceptance plane (preview).** Capability manifests bind criteria to four
  generic oracle primitives (`command`, `file`, `git`, `human`) and lifecycle
  policies. `assaystone capability validate` and `assaystone gate` evaluate a
  capability at `shadow`, `canary`, or `production`; `shadow` cannot merge and
  `production` requires approvals. The core is domain-blind;
  `examples/capability/java.json` is the first template.
- **Language coverage.** `diff.language_coverage` escalates when a changed
  source file is in a language the contract does not support. Real Java sessions
  no longer audit as "clean"; they become "needs a human" until a Java pack
  exists. `init` includes the check, and the hardened code contract declares
  `unverified-language`.
- **Real-session false positive fixed.** A 477-edit real session produced one
  medium finding: a `print()` in a reproduction script.
  `quality.no_debug_prints` now also excludes `repro/`, `tools/`, `benchmarks/`,
  and `docs/`. The same session now audits clean. The test also exposed two
  structural gaps now recorded in
  [docs/known-evasions.md](docs/known-evasions.md): non-Python source edits are
  invisible to the syntax/API/debug checks, and Bash-only sessions have no
  artifacts to diff offline.
- **Confidence intervals.** Goodhart resistance, catch rate, and false-alarm
  rate now report a 95% Wilson interval and the sample size. A 17-case corpus
  no longer reads as a precise population estimate.
- **Research pack.** The fourth domain ships: `research.citations`,
  `research.sources_exist`, and `research.quotes_verbatim`, with criteria for
  cited claims, existing sources, and verbatim quotes. The Goodhart `research`
  family adds an uncited claim, a fabricated quote, and a clean control.
  The acceptance language is now exercised by code, ops, data, and research.
- **Data pack.** A third domain ships: `data.schema`, `data.totals`, and
  `data.no_pii`, with a contract whose criteria are schema validity, conserved
  totals, and no PII. The Goodhart `data` family adds a totals mismatch, a PII
  leak, and a clean control. The leaderboard gains a data entry. The acceptance
  language is unchanged across code, ops, and data.
- **Provenance.** Traces declare `source: agent|runtime`; verifiers declare
  `trusts`. A check that trusts agent-written `trace` or `evidence` is downgraded
  to low independence, so a failure found only in testimony escalates instead of
  deciding. `RuntimeGuard` writes runtime traces; the ops fixtures are runtime
  traces. `Verdict` records both the effective and declared independence.
- **Product spec.** [docs/vision.md](docs/vision.md) states the four layers
  (acceptance IR, verifier algebra, adversarial scoreboard, runtime), the
  domain-pack boundary, and what the product is not.
- **Acceptance IR.** Contracts can carry typed `criteria` (precondition,
  invariant, postcondition, forbidden_action, evidence) with a statement, a
  defect tag, an optional verifier binding, severity, and `on_unknown`. Coverage
  reports the **assurance gap**: declared criteria that no independent check can
  decide. The runner decides each criterion: a bound failure fails it, an
  unresolved check escalates unless `on_unknown: fail`, and a criterion with no
  bound check escalates. Critical/high criteria gate the run. The IR is backward
  compatible; `required_defects` is derived from the criteria when omitted.
  `examples/ops_agent/contracts/declared_only.json` declares six criteria, has
  no checks for them, and escalates a clean run instead of passing it. Spec:
  [docs/acceptance-ir.md](docs/acceptance-ir.md).
- **Test support integrity.** `tests.support_integrity` protects test support
  code outside the `tests/` prefix (`helpers/`, `testing/`, `test_utils/`,
  `spec/support/`). The Goodhart `support` family adds a fixture whose suite
  imports `helpers/assertions.py`: `g10` makes the helper a no-op and is caught;
  `g11` is a behavior-preserving refactor and passes. `init` includes the check.
- **Known evasions.** [docs/known-evasions.md](docs/known-evasions.md) lists every
  failure class the current pack does not catch, split into declared and open.
  Test support tampering moved from open to caught; the open list now names
  network/exfiltration checks and measured independence.
- **Adversarial demo.** `assaystone demo adversarial` shows the trap in one
  screen: a `sitecustomize.py` that neutralises `assertEqual`, the naive contract
  returning pass, and the hardened contract failing at `tests.harness_integrity`.
  [docs/evasions.md](docs/evasions.md) has the minimal reproductions for the
  module-shadow and `conftest.py` variants as well.
- **Contract composition.** `assaystone compose` solves the weighted set cover
  over declared defect classes: the cheapest independent checks, the classes no
  check decides, and the classes that rest on a single check. Exact for small
  declared sets, with a deterministic greedy fallback.
- **Onboarding fixes.** `assaystone init` now writes `domain` and a default
  `required_defects` list, and includes `diff.ci_surface` and
  `tests.harness_integrity`. A contract that declares no defect classes is no
  longer reported as 100% coverage: coverage is unmeasurable, and the report card
  says so.
- **Second third-party pack.** `examples/third_party_pack/secret_guard/` registers
  `example.no_new_secrets`, a deterministic added-credential check with declared
  blind spots.
- The Goodhart `ops_lineage` family grows to three attacks: forged approval,
  duplicate refund from one step, and an approval for a different amount.
- **Report card.** `assaystone scorecard` puts protocol conformance, declared
  coverage, recall on labelled traces, and resistance by family on one page, and
  exits non-zero when any of the four fails. A contract's card is scoped to its
  declared domain; the benchmark itself reports every family.
- **Verifier manifest check.** `assaystone protocol --check-manifest` validates a
  third-party verifier manifest without a JSON Schema dependency. The
  `examples/third_party_pack/` pack registers a verifier outside the package.
- **External pack.** `external.pytest` and `external.ruff_debug_print` run real
  third-party tools when installed and escalate when they are missing. The pytest
  adapter is declared `medium` independence because it shares the runtime hijack
  surface.
- New verifiers: `tests.harness_integrity` catches `sitecustomize.py`,
  `unittest.py`, `.pth`, and related runtime hijacks; `diff.ci_surface` protects
  the whole CI/build surface, not only `.github/workflows/`.
- SARIF and JUnit now surface unconfirmed low-independence failures so CI and
  reviewers can see a routed check instead of a silent one.
- Benchmark families gain `category` and `required_defects`, so an adversarial
  corpus and a recall corpus can share one runner.

### Failure Zoo

- `assaystone benchmark failure-zoo` runs every built-in verifier independently
  against the labelled corpus (code/test, ops/refund, and an audit transcript),
  reports caught / escaped / false-alarm counts per verifier, and emits deterministic
  Markdown, JSON, and CSV
- committed regression thresholds fail the run when verifier recall drops or a
  verifier disappears from the corpus; `make benchmark` refreshes
  `docs/failure-zoo.md`
- CI runs the benchmark and fails when the committed scorecard is stale

## 0.5.0 — 2026-11-24

- Codex CLI transcript import, including `apply_patch` replay and `exec_command`
  test-evidence inference
- `assaystone audit --latest claude-code` and `--latest codex` discover the newest
  local session for the current workspace
- root `pytest` collection fixed by scoping tests to `tests/`; CI now runs both the
  unittest suite and pytest entry point
- Python 3.13 added to the CI matrix; lint and coverage gates added
- wheel and sdist no longer include `__pycache__` or `.pyc` files; PEP 639 license
  metadata and an explicit development dependency set added
- GitHub Action outputs: `verdict`, `findings`, and `traces`
- Claude Code plugin marketplace with `/assaystone:audit`, `/assaystone:setup`, and a
  fail-open Stop hook, validated with `claude plugin validate --strict`
- GitHub Pages landing page and social preview
- Makefile supports newer local Python interpreters and adds `pytest`, `lint`, and
  `package` targets

## 0.4.1 — 2026-11-23

- Packaging fix: generated GitHub workflows now pin `v0.4.1`, and the README/Action
  metadata reflect the 0.4.x release. No verifier behavior changes.

## 0.4.0 — 2026-11-23

- LangGraph (`LangGraphGuard`) and OpenAI Agents SDK (`run_with_verification`)
  runtime wrappers
- strict, newline-only JSONL parsing; invalid lines are skipped with a warning instead
  of corrupting a record on U+0085/U+2028
- SARIF locations now point at the artifact named in the finding
- test evidence is inferred only from explicit runner commands and structured outcomes
- workspace copies skip heavy directories and refuse the home directory or filesystem
  root
- forbidden defaults narrowed to `.github/workflows/` and `.github/actions/`; debug
  prints in CLI/example/script paths are ignored
- unreadable files in a trace directory are skipped with a warning; invalid trace
  shapes are rejected before `Trace.from_dict`
- field-note manual triage: 0 confirmed test tampering in the five strongest
  candidates; the path-based rule surfaces activity, not intent
- generated GitHub workflows pin the released action tag instead of `@main`

## 0.3.1

- Claude Code hook merges git working-tree changes, capturing Bash-made edits
- audit step budget raised from 200 to 5,000 based on a 162-session field audit
- `scripts/corpus_audit.py` for read-only aggregate corpus audits
- real-session field note and release notes

## 0.3.0

- `assaystone audit`: Claude Code transcripts, message exports, trace JSON
- LangSmith, Langfuse, and OpenTelemetry GenAI importers (`--format`, auto-detect)
- Claude Code Stop hook (`assaystone hook install claude-code`), warn/block, dedupe,
  and `.assaystone/hook.json` ignore rules
- SARIF 2.1.0 and JUnit output for `audit` and `verify`
- shared tool-call replay and test-evidence inference
- `--workspace` / post-session fallback: current files when replay cannot cover edits
- `--git-preimage`: HEAD-based baseline for post-session diff checks; the hook uses it
  when available
- `tests.integrity` matches nested test dirs (`server/tests/`, `demo2/server/tests/`)
- default audit rules, severity levels, JSON output, `--fail-on`, suggested contract
- `Contract.from_dict` / `to_dict`; `fail_fast=False` aggregates all verdicts
- `record` accepts Claude Code transcripts, importers, and trace JSON
- packaged `demo_data` so `pip install assaystone && assaystone demo` works
- `--no-evidence` to keep raw evidence out of machine reports
- third-party verifier packs via `assaystone.verifiers` entry points
- CI matrix 3.10–3.12 plus a wheel build/install demo job
- GitHub Action install input; project metadata and license files

## 0.2.0

- runtime gate: irreversible-tool policies, approval callbacks, contract enforcement,
  shadow mode
- ops/refund verifier pack and `assaystone demo ops`
- LangGraph adapter
- runtime, adapter, verifier, and contract reference docs

## 0.1.0

- acceptance contracts and a cost-ordered verifier ladder
- `pass / fail / escalate` verdicts with reasons and evidence refs
- mutation testing and backtesting over recorded traces
- Claude Agent SDK / OpenAI-style / LangGraph message adapters and `artifacts_from_git`
- `assaystone init --ci`, `assaystone record`, `verify --json`, `verify --github`
- pytest plugin (one item per trace) and a composite GitHub Action
- scorecard, Failure Zoo seed, and launch docs

## 0.0.1

- initial code/test verifier pack and demo
