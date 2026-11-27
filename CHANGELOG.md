# Changelog

## Unreleased

No changes yet.

## 0.31.0 — 2026-11-27

- **`capability next --apply`.** Carries out every mechanical blocker: the
  approval oracle, the missing stage policy, the approval and `require` entries.
  It refuses to write a manifest that would not validate, and reports what it
  will not do — inventing a compensation command or an approval. Applying makes
  an owner approval stale, and the command says so. The trial ends with the
  blocker, the apply, and the stage declared.
No changes yet.

## 0.30.0 — 2026-11-27

- **`capability next`: what blocks the next stage, and the patch.** Reports a
  missing stage policy, a stage that permits nothing, a critical criterion the
  stage does not gate, and (with a trail) a required oracle without a passing
  decision — each with the JSON to add. The trial now ends with this instead of a
  residual-risk list, so the document ends with the next action.
No changes yet.

## 0.29.0 — 2026-11-26

- **`scripts/trial.py` and `docs/trial.md`: the loop as a runnable artifact.**
  The script builds a small service, has it inspected, then walks a change from
  "the agent says it is done" through a refusal (six of six mutants survived),
  a fix, a signed decision, and the card that says what is still unresolved.
  `make trial` regenerates the document and CI diffs it, so the evidence cannot
  drift from the code. Timestamps, hashes, and signatures are normalised.
- **`tests.integrity` is semantic.** It used to fail on any change under a test
  prefix, which made "the agent added a test" a defect. It now fails on a deleted
  test file, a removed test, or fewer assertions; a rewritten test body is
  `escalate` (counts cannot tell whether it still asserts the same thing); adding
  tests is fine.
- **`diff.ci_surface` allows the gate's own workflow to be added.** The draft
  writes `.github/workflows/assaystone.yml`; the next gate flagged its own file.
No changes yet.

## 0.28.0 — 2026-11-26

- **A team view without a service.** `capability list` accepts repeated `--root`
  and a `--index` file (`{"roots": ["api", "worker"]}`, resolved relative to the
  index). With several roots the table gains a `repo` column and critical risks
  are prefixed by repository; `--strict` aggregates across all of them. Still a
  local command over files, so the offline positioning is unchanged.
No changes yet.

## 0.27.0 — 2026-11-26

- **`canary` oracle (thirteenth primitive): compare distributions, not single
  measurements.** Samples the incumbent and the candidate, bootstraps an interval
  for the difference with a fixed seed, and fails only when the relative change
  exceeds the limit **and** the interval excludes zero. Fewer than five usable
  measurements escalates; noise does not fail.
No changes yet.

## 0.26.0 — 2026-11-26

- **`gate --sandbox`: do not judge a tree you have modified.** Workspace oracles
  run in a disposable copy, so a seed, a migration, or a build does not touch the
  repository being judged; only checks that reach outside the workspace (`git`,
  `http`, `human`, `sql` with `dsn_env`) use the real root. The result and the
  trail record `sandbox: true`.
No changes yet.

## 0.25.0 — 2026-11-26

- **Canary, documented and tested.** `shadow` already compares two HTTP
  endpoints, so a canary is `<incumbent>` vs `<candidate>` with `ignore` for
  version strings and timestamps and `tolerance` for numeric noise; an `http`
  oracle with a numeric threshold covers a metric that is already aggregated. A
  test now pins the pattern. No new primitive was needed.
- **`capability propose`: the standard grows with the repository.** Re-running
  the inference against an existing manifest lists criteria the repository now
  implies and the manifest lacks, with the evidence for each. `--apply` adds
  them, writes their helper scripts, refuses to produce an invalid manifest, and
  says the owner approval must be re-signed.
- **`mutation` oracle: do the tests cover the change?** It injects one plausible
  defect at a time into the **added** lines (`git diff -U0`), runs the suite, and
  requires most mutants to be killed. Test files are never mutated; a red baseline
  escalates; a surviving mutant is a behaviour nobody checks. This is the
  deterministic answer to "tests pass, so the behaviour must be fine", which was
  the largest remaining hole.
- **The draft proposes it** for a Python project with tests, priced at
  `cost_usd: 0.05` so it counts against the stage budget.
- **`capability init` proposes the checks the repository implies.** A Java
  module gets "the public API is unchanged" (`javap` against the baseline), a
  test tree gets `tests.integrity`, `.github/workflows` gets `diff.ci_surface`, a
  dependency manifest gets a dependency-set check, and a migration directory gets
  "every new migration declares a down path". Each proposal states why it
  applies, and the payload scripts it needs are written into
  `.assaystone/checks/`. The draft now checks what the repository has instead of
  three build commands.
- **`command` gains `unknown_exit`.** An exit code that means "the check could
  not decide" escalates instead of failing — the API check uses it when the
  baseline will not build.
No changes yet.

## 0.24.0 — 2026-11-26

- **The session and the decision point at each other.** A `runtime` payload can
  name a `trail`; the oracle then checks that the decision the record cites is
  really on it, for the same commit. Oracles publish `facts` (session, record
  digest, entry hash) which reach the trail entry and the signed receipt, and
  `receipt verify --runtime-record FILE` checks a receipt against the session
  file it cites. The hook's own gate skips `runtime` and `drill` and reports them
  as not evaluated here: the supervisor that writes the evidence cannot require
  it to exist already.
No changes yet.

## 0.23.0 — 2026-11-26

- **`capability utility`: which required checks have ever observed a failure.**
  Reads the trail and reports per-oracle runs, passes, failures, escalations, and
  the last outcome, plus the stage mix, checks required but never recorded,
  checks that have never failed, and oracles no policy uses. It states that
  "never failed" is a fact rather than a verdict: an oracle you have never seen
  reject anything is untested, not proven. This is the empirical half of "price
  the verification".
No changes yet.

## 0.22.0 — 2026-11-26

- **A policy may not permit what it cannot justify.** `validate` now refuses a
  stage that allows deploy without an approval and rollback evidence, or that
  allows merge without an approval when the manifest declares `merge`
  irreversible. The onboarding draft consequently starts with every stage
  locked: `capability init` used to emit a `production` policy that allowed
  deploy with no approval and no rollback, so a new user could get a green light
  from a manifest that checked almost nothing.
No changes yet.

## 0.21.0 — 2026-11-26

- **`capability drill` and the `drill` oracle: proof that the compensation
  works.** A manifest can declare `reversibility` (an action oracle, its
  compensation, and the state paths to compare). The drill hashes the state, runs
  the action, hashes again, runs the compensation, and requires the final hash to
  match the first — and requires the action to have changed something, or it
  fails as proving nothing. Directories are hashed by content. The record binds
  the manifest digest and the commit; the `drill` oracle fails a failed drill and
  escalates a missing, foreign, or stale one. This repository's own release now
  drills its build (`build` → `dist` → remove) before the production gate.
No changes yet.

## 0.20.0 — 2026-11-26

- **Ten primitives.** The README, the plane reference, and the demo count the
  `runtime` oracle, so the numbers match the code again.
- **The status card shows the runtime record.** A session record that is
  present but no longer describes the code is listed as residual risk, next to
  the trail, receipt, approval, and waivers. `capability status --runtime-record`
  overrides the default path.
- **`runtime` oracle: evidence the supervisor wrote.** The Stop hook records
  the commit, the session id, a content hash for every file it saw, the gate
  outcome, and the audit count. The new oracle decides against that record: a
  failed session is `fail`; a record for other code, older than the window, or
  naming a file that changed afterwards is `escalate`. The transcript oracle
  stays testimony; this is the other half of "runtime writes the evidence".
  `.assaystone/runtime/` is git-ignored and can be disabled with
  `record: false`.
- **`gate --dry-run`.** Executes only the oracles that do not declare
  `"mutates": true`. A dry run never returns `pass`, reports a read-only failure
  as `escalate` rather than `fail`, and refuses `--receipt`, so it cannot
  impersonate a decision or leave signed evidence.
- **A verification budget.** An oracle can declare `cost_usd` and a stage can
  declare `budget_usd`. The gate keeps the declared order (oracles often depend
  on each other), stops before an oracle it cannot afford, and **escalates** —
  an unchecked requirement is not a satisfied one. Cost reaches the result, the
  trail, and the receipt.
- **The manifest digest is stable across upgrades.** Adding `budget_usd` to the
  policy serialisation changed every digest and invalidated the owner's approval
  — the self-gate refused on CI and exposed it. The serialised shape is frozen:
  existing keys stay even when empty, and a later field appears only when set. A
  pinned-digest test guards it, and the self-capability's approval is asserted
  against the current manifest.
- **A stage chain now binds the commit.** `after` compared the capability and
  the manifest digest but not the code: a canary pass recorded on one commit
  would authorise a different one. The gate reads `HEAD` of `--root`, records it
  in the trail, and refuses to chain across commits — *re-run canary on this
  code*.
- **Stale evidence is visible.** `capability status` marks a stage decision
  recorded for a different commit as `[stale commit]` and lists it as residual
  risk; `capability list --strict` treats a stale decision for the current
  lifecycle as critical. `capability status` takes `--root` to say which code
  the decisions apply to.

## 0.19.0 — 2026-11-25

- **`capability diff`.** Compare two manifest versions the way a reviewer reads
  them: criteria added, removed, or changed, oracle fingerprints, per-stage
  requirements, approvals, rollback, and chain. A change that removes or lowers
  assurance is flagged; additions and tightening are shown but not flagged.
  `--json` returns the same structure. The diff decides nothing; it tells the
  owner what they are re-approving.

## 0.18.0 — 2026-11-25

- **Key revocation.** `capability.revocations.json` lists key ids that must no
  longer be trusted, with a reason. The gate checks owner approvals, waivers, and
  receipts against it and escalates when one was signed by a revoked key, naming
  the artifact and the reason. An unreadable list escalates; a list without
  reasons is rejected. The status card and registry report revoked artifacts as
  residual risk.
- **Branch protection on this repository.** `main` now requires a pull request
  and the seven CI checks, with administrators included and force pushes
  disabled. A direct push is rejected by the remote.
- **The changelog is now checked.** A release-prep test asserts that
  `CHANGELOG.md` has a section for `__version__` and `docs/releases/v<version>.md`
  exists, because this file silently drifted for eight releases.

## 0.17.1 — 2026-11-25

- **`receipt verify --commit` resolves refs.** An annotated tag resolves to its
  commit, so `--commit v0.17.0` means what a reviewer expects.
- **The receipt report names the scheme.** An ed25519 receipt shows its key id
  and says the public key verifies it.

## 0.17.0 — 2026-11-25

- **The product's own release is gated at production.** The self-manifest gains
  `manifest_approval: true`, a `production` policy, and a rollback oracle. The
  release workflow verifies the owner approval, runs tests/lint/benchmark and the
  rollback check, signs an Ed25519 release receipt with a key held in a GitHub
  secret, verifies it with the committed public key, and uploads the evidence.
  A failing gate stops the release before the build.
- **Lifecycle-aware status and registry.** A future stage without evidence is
  information, not a current defect.

## 0.16.0 — 2026-11-25

- **Key ids.** Ed25519 approvals, waivers, and receipts carry the SHA-256
  fingerprint of the signing public key inside the signed body. Verification
  rejects a substituted public key; `key fingerprint` prints the id.

## 0.15.0 — 2026-11-25

- **Ed25519 owner approvals and waivers.** `capability accept` and
  `capability waive` accept `--private-key-file`; the gate, status card, and
  registry verify with `--owner-public-key`. CI can verify the owner without
  holding the owner's key.

## 0.14.0 — 2026-11-25

- **Ed25519 receipts.** With the optional `cryptography` extra,
  `gate --receipt-key-file` signs with a private key and
  `receipt verify --public-key` verifies with only the public key. `key generate`
  writes a `0600` private key.

## 0.13.1 — 2026-11-25

- **Portfolio strictness fix.** A criterion gated only at a later stage is not
  a critical defect at the current lifecycle. Strict mode now requires every
  declared stage to have a passing decision and every critical criterion to be
  gated somewhere.
- **Incident trial.** The real Maven module went through canary → production →
  a caught API break → rollback → an incident gate requiring API parity, a clean
  worktree, a reverse-applicable commit, and two signed approvals.

## 0.13.0 — 2026-11-25

- **One-command onboarding.** `capability init --ci --hook` writes the draft
  manifest, a runnable GitHub Actions gate, and `.assaystone/hook.json`.
- **The capability registry.** `capability list --root .` scans nested
  `.assaystone/` directories and prints one row per capability; `--strict` exits
  `1` on any critical risk.

## 0.12.0 — 2026-11-25

- **Owner-signed waivers.** `waivers: true` plus `capability waive` records a
  time-boxed exception for one criterion, bound to the manifest digest. The gate
  applies it only when every criterion on the failing oracle is waived, the
  failure is `fail` rather than `escalate`, and the signature verifies. A waived
  oracle is residual risk in the trail, receipt, and card — never a clean pass.

## 0.11.0 — 2026-11-25

- **The Stop hook runs the capability gate.** `hook install claude-code
  --manifest ... --stage shadow` writes `.assaystone/hook.json`; at Stop the
  hook evaluates the manifest on the working tree, and `block` mode refuses the
  stop on a failure. The hook never loads the owner or receipt keys.
- **`capability status`.** One read-only card per capability: coverage, the
  current stage's critical gap, stage policies, owner approval, trail and last
  outcome per stage, receipt verification, and a residual-risk list.

## 0.10.0 — 2026-11-25

- **Signed gate receipts.** `gate --receipt` writes an HMAC-SHA256 receipt bound
  to the commit, the manifest digest, the trail head, and every oracle digest.
  `receipt verify` checks it offline and fails on any changed field, wrong key,
  or a commit/manifest/outcome mismatch. The gate refuses to sign a broken trail
  and refuses to write a receipt without a key.
- **Owner approval of the acceptance criteria.** `manifest_approval: true`
  requires the owner to sign the manifest digest via `capability accept`. The
  owner key and the receipt key are separate: who defines acceptance and who
  records the decision are different signers.
- **The product gates itself.** `.assaystone/capability.json` declares tests,
  lint, and Failure Zoo freshness; CI runs the gate, writes the trail, signs a
  receipt, verifies both, and uploads the evidence.
- The Action gains `receipt`, `receipt-key-env`, `manifest-approval`, and
  `owner-key-env`.

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
