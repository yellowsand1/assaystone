# The acceptance plane

A verifier answers "is this artifact acceptable?" for one artifact at one
moment. A deployment needs more: *who* asked, at *which lifecycle stage*, with
*which* evidence, *what* was not checked, and *where* the decision was recorded.

The acceptance plane is that layer. Its core is domain-blind: thirteen generic
oracle primitives, a manifest that binds declared criteria to them, lifecycle
policies, and a hash-chained trail. Java/Maven, refunds, and pricing are
manifests, not code paths.

```bash
assaystone capability init --root . --owner platform-team
assaystone capability validate --manifest examples/capability/java.json
assaystone gate --manifest examples/capability/pricing.json --stage canary \
  --root examples/capability/pricing_project \
  --audit .assaystone/trail.jsonl --actor release-bot --strict
assaystone trail verify .assaystone/trail.jsonl --expect sha256:...
```

See it in one screen: `assaystone demo plane`.

## Start from a draft

```bash
assaystone capability init --root . --owner platform-team --ci --hook
```

`init` reads the repository and proposes the criteria its own structure
implies, with the evidence for each:

| what is in the repository | what is proposed |
|---|---|
| `src/main/java` and a Maven module | **the public API is unchanged** (`javap` against the baseline) |
| a test tree | **no test was deleted or weakened** (`tests.integrity`) |
| `.github/workflows` | **the CI configuration is unchanged** (`diff.ci_surface`) |
| a dependency manifest | **the dependency set is unchanged** (supply chain) |
| a Python test suite | **the change is covered by the tests** (mutation of the added lines) |
| `db/migration` and friends | **every new migration declares a down path** |

Each proposal names why it applies, and `init` writes the small payload scripts
they need into `.assaystone/checks/`. The draft then checks what this repository
actually has, instead of three build commands. That is the difference between
"an expert writes the standard" and "the standard is already visible"; the owner
still deletes the ones that do not apply.

The same inference works on a manifest that already exists, so the standard can
grow as the repository does:

```bash
assaystone capability propose --manifest .assaystone/capability.json --root .
```

```text
grown: 3 proposed addition(s)
  + tests-intact (critical) via `tests_intact`
    No test was deleted, weakened, or replaced.
    why: a test tree exists: a suite that passes because the failing test
    disappeared is the canonical agent failure
```

`--apply` adds them to the criteria, the oracles, and every policy's `require`
list, writes the helper scripts, and refuses to write a manifest that would not
validate. The owner approval is then stale — which is the correct consequence,
and `capability validate` says so.

It also looks for a build or test surface — `pom.xml`, Gradle, `package.json`
scripts, `pyproject.toml` plus tests, `go.mod`, `Cargo.toml` — and writes
`.assaystone/capability.json` with a build oracle, a test oracle where it found
tests, an artifact check for compiled stacks, and a branch check that follows
the convention the repository already uses (`feature/` or `feat/`). It never
runs a build.

The draft is deliberately incomplete, and it **permits nothing it cannot
justify**: every stage starts with `allow_merge` and `allow_deploy` off. Turning
one on is the owner's decision, and `validate` refuses a policy that allows an
irreversible action without an approval and rollback evidence. It declares no
approvals and no rollback claim, because inventing either would be exactly the
unchecked assertion this project argues against. `init` prints what to add next; the first
`gate --stage shadow` usually fails on the branch check or escalates on a
missing approval, and that failure is the onboarding.

Two flags wire the draft into the daily loop:

- `--ci` writes `.github/workflows/assaystone.yml`: install the pinned version,
  run the gate at `shadow`, verify the trail, upload the evidence, and leave a
  commented block for receipts. It runs on the first push without requiring a
  secret; the receipt block is opt-in.
- `--hook` writes `.assaystone/hook.json` so the Claude Code Stop hook can run
  the same gate. Install it with
  `assaystone hook install claude-code --manifest .assaystone/capability.json --mode block`.

Detection is heuristic and lives in `scaffold.py`, outside the plane. A new
build tool means a new detection branch that emits a command payload; the core
does not learn about it.

Exit codes: `0` pass, `1` fail, `2` escalate or a manifest/trail error. A gate
that cannot decide never exits `0`.

## Manifest

```json
{
  "capability": "pricing-change",
  "owner": "growth-pricing",
  "systems": ["pricing-service", "ledger"],
  "data_classes": ["internal", "financial"],
  "irreversible_actions": ["publish", "deploy"],
  "risk": "high",
  "lifecycle": "shadow",
  "retention": "90d",
  "registry": "oracles.json",
  "criteria": [
    {"id": "fee-parity", "kind": "invariant",
     "statement": "The refactored fee calculation matches the old one.",
     "oracle": "parity", "severity": "critical"}
  ],
  "oracles": [
    {"id": "parity", "type": "shadow", "payload": {}},
    {"id": "compile", "ref": "java.maven.compile", "version": 2}
  ],
  "policies": {
    "shadow": {"require": ["parity"], "allow_merge": false},
    "canary": {"require": ["parity"], "approvals": ["approval"], "allow_merge": true}
  }
}
```

* `criteria` is the acceptance language: typed (`precondition`, `invariant`,
  `postcondition`, `forbidden_action`, `evidence`), each bound to one oracle and
  carrying a severity.
* `oracles` are inline definitions or `ref` entries resolved from a registry.
* `policies` name the oracles a stage requires and the approvals it accepts.

`capability validate` checks the shape: non-empty owner and capability, known
risk and stage, unique ids, criteria and policies that point at declared
oracles, and a `ref` that resolves with a matching version pin.

## Primitives

Every primitive fails closed. Missing command, unreachable host, absent file or
database, missing driver, unknown mode → `escalate`. Only a check that actually
ran can return `pass` or `fail`.

| Primitive | What it asserts | Payload |
|---|---|---|
| `command` | a process exits as expected | `command`, `expect_exit`, `unknown_exit`, `cwd`, `timeout` |
| `file` | an artifact exists / parses / contains | `path`, `mode`: `exists`, `json`, `contains`, `regex` |
| `git` | the change is on a branch / the tree is clean | `mode`: `branch`, `clean` |
| `human` | a named action was approved | `action`, `record` |
| `http` | an endpoint answers as declared | `url`, `method`, `expect_status`, `json_path`, matcher |
| `sql` | a read-only query returns the expected rows | `driver`, `database`/`dsn_env`, `query`, `expect` |
| `shadow` | old and new implementations agree on the same input | `old`, `new`, `compare` |
| `transcript` | the agent's recorded session passes the audit | `transcript`, `baseline`, `fail_on` |
| `verifier` | a declared verifier decides the working-tree diff | `name`, `params`, `test_command` |
| `runtime` | the session's supervisor record still describes this code | `record`, `require_outcome`, `max_age_minutes` |
| `drill` | a recorded proof that the compensation restores the state | `manifest`, `id`, `max_age_minutes` |
| `mutation` | the tests actually cover the added lines | `command`, `against`, `threshold`, `max_mutants` |
| `canary` | the candidate is not worse than the incumbent, beyond noise | `baseline`, `candidate`, `samples`, `max_relative_increase` |

### `http`

```json
{
  "url": "https://staging.example.com/health",
  "method": "GET",
  "expect_status": 200,
  "json_path": "data.status",
  "equals": "ok",
  "headers": {"Authorization": "env:STAGING_TOKEN"},
  "timeout": 10
}
```

* Header values of the form `env:NAME` are read from the environment. A missing
  variable escalates; values are never written to evidence.
* Redirects are not followed. A redirect can move a request — and its
  credentials — to a host the manifest never named, so a 3xx escalates.
* Only `GET`, `HEAD`, and `OPTIONS` run by default. Any other method needs
  `"allow_write": true` in the payload.
* Loopback hosts bypass `http_proxy`/`https_proxy`, so a local staging service
  is either reachable or refused; a proxy error page must not read as a verdict.
* `max_bytes` (default 256 KiB) caps the response; a larger response escalates
  because the declared check cannot be completed.
* Matchers: `equals`, `contains`, `regex`, and the numeric thresholds `lte`,
  `gte`, `lt`, `gt`, applied to the value at `json_path`. A boolean is not a
  number: a metric that arrives as `true` fails the threshold instead of
  comparing as 1.
* A canary policy can therefore require service metrics directly:

  ```json
  {"id": "error-rate", "type": "http", "payload": {
     "url": "https://staging.example.com/metrics",
     "json_path": "error_rate", "lte": 0.01}}
  ```

### `sql`

```json
{
  "driver": "sqlite",
  "database": "ledger.db",
  "query": "select count(*) as n, sum(amount_cents) as total from orders",
  "expect": {"mode": "rows", "equals": [{"n": 3, "total": 12300}]}
}
```

Read-only by construction, not by convention:

* the query must start with `SELECT` or `WITH`, contain one statement, and carry
  no write keyword outside string literals;
* SQLite is opened with `mode=ro` and `PRAGMA query_only = ON`;
* MySQL uses `SET SESSION TRANSACTION READ ONLY`, and needs `pymysql` — absent,
  the oracle escalates instead of skipping. The session flag is queryable
  (`select @@session.transaction_read_only`), so the read-only claim is
  evidence, not configuration. Validated on MySQL 8.0.31 against a live local
  server; MySQL returns `DECIMAL` for arithmetic, and comparisons handle it
  numerically with `tolerance`;
* results are capped at 1000 rows; a larger result escalates;
* the database path must stay inside the gate root.

Expectations: `scalar` with `equals`, `rows` with `equals` or a `baseline` JSON
file, or `empty`. `tolerance` applies to numeric comparisons; `ignore` lists
columns that are known to differ. No expectation means "the query ran", and the
evidence says so.

### `transcript`

The other seven primitives look at the repository. This one looks at what the
agent did:

```json
{
  "type": "transcript",
  "payload": {
    "transcript": ".assaystone/traces/session.jsonl",
    "baseline": ".assaystone/preimage",
    "fail_on": "high"
  }
}
```

It runs the session audit over a transcript, a trace JSON, or a directory, and
fails when a finding meets `fail_on` (`any`, `high` default, `medium`, `low`, or
`none` to report without failing). Findings inherit the kernel's provenance
rules: a check that trusts agent-written testimony arrives as `escalate`, not as
a decision. A clean session passes and its findings are attached as evidence.

* The transcript and baseline must stay inside the gate root. Copy the session
  file into the repository before gating; do not point the gate at an
  arbitrary home directory.
* `baseline` is the pre-session tree. Use `git_preimage: true` when the changes
  are uncommitted, or `workspace: true` when the working tree is post-session
  and the edits were already applied.
* `run_tests` is off by default; a transcript oracle should not execute the
  repository's test command unless the manifest says so.
* `ignore` lists paths or globs excluded from the session artifacts, for
  example `[".assaystone/"]`. The gate's own tooling and config are not a change
  under review; without this, an untracked helper script can become a finding.
* A session with no artifacts escalates: there is nothing to diff, and a
  read-only session must not read as a clean change. Set
  `allow_empty_artifacts: true` only when the criterion is genuinely about the
  absence of work.
* This is the bridge to the audit layer, not a replacement for it: the audit
  rule set is code- and ops-centric, and an unsupported language escalates.

### `shadow`

```json
{
  "old": {"type": "command", "payload": {"command": ["python3", "fee.py", "old"]}},
  "new": {"type": "command", "payload": {"command": ["python3", "fee.py", "new"]}},
  "compare": {"mode": "json", "ignore": ["generated_at"], "tolerance": 0.001}
}
```

The claim is equivalence: the same input through both implementations produces
the same result. `compare.mode` is `text` (whitespace-normalised, optional
`ignore` regexes), `json` (sorted keys, ignored paths, numeric tolerance), or
`exit`.

* Divergence → `fail`, with the first differing path.
* Either side escalating → `escalate`.
* Both sides failing identically → `escalate`: a broken baseline cannot prove a
  preserved behaviour.
* Shadow cannot nest inside shadow.

For an intentional behaviour change, assert the new expected output directly
with a `file`, `sql`, or `command` oracle; shadow is for "nothing should have
changed".

### `canary`

One request is not a canary: two healthy services differ run to run. This oracle
samples both sides and asks whether the difference is larger than the tolerance
**and** supported by the data:

```json
{"id": "canary", "type": "canary", "payload": {
  "baseline": {"type": "http", "payload": {"url": "https://prod.example.com/metrics"}},
  "candidate": {"type": "http", "payload": {"url": "https://canary.example.com/metrics"}},
  "json_path": "p95_ms", "samples": 12,
  "max_relative_increase": 0.10, "confidence": 0.95}}
```

```text
outcome: fail
  the candidate is +30.0% worse than the baseline (limit +10.0%) and the 95%
  interval for the difference is [26.1, 33.7], which excludes zero
```

* Each side is any oracle that produces a number; `json_path` reads it from the
  output, or the first bare number in the text.
* The interval is a **bootstrap** over the two samples with a fixed seed, so the
  verdict is reproducible; a gate that flipped on a random draw would be worse
  than no gate.
* A regression needs both a relative change over the limit **and** an interval
  that excludes zero. Noise does not fail; a large change with a wide interval
  does not fail yet either, and the evidence says so.
* Fewer than five usable measurements per side escalates: at that size a canary
  cannot tell a regression from noise.
* A side that does not answer, or produces no number, escalates.

### Canary across two JSON bodies

A canary asks one question: does the candidate behave like the incumbent? That is
`shadow` with two endpoints:

```json
{"id": "canary", "type": "shadow", "payload": {
  "old": {"type": "http", "payload": {"url": "https://prod.example.com/quote?sku=1"}},
  "new": {"type": "http", "payload": {"url": "https://canary.example.com/quote?sku=1"}},
  "compare": {"mode": "json", "ignore": ["served_by", "generated_at"],
              "tolerance": 0.001}}}
```

Use this when the whole body matters; use the `canary` oracle when one number
does.

`ignore` is what makes a live comparison usable: version strings, timestamps, and
request ids always differ. `tolerance` absorbs floating-point noise. For a metric
that is already aggregated at the endpoint (an error rate, a p95), an `http`
oracle with a numeric threshold is the same check with less machinery:

```json
{"type": "http", "payload": {"url": "https://canary.example.com/metrics",
                             "json_path": "error_rate", "lte": 0.01}}
```

Both run offline against a recorded baseline when a staging service is not
available. Neither is a distribution test: they compare one measurement, and both
sides must be reachable. The gate reports `escalate` when they are not.

### `mutation`

"Tests pass" says nothing about whether the tests *cover the change*. This oracle
injects one plausible defect at a time into the **added** lines, runs the suite,
and requires most mutants to be killed:

```json
{"id": "mutation", "type": "mutation",
 "payload": {"command": ["python3", "-m", "pytest", "-q"],
             "against": "HEAD", "threshold": 0.5, "max_mutants": 6}}
```

* Only lines this change added are mutated (`git diff -U0`); mutating the whole
  file measures whether the file is covered, not whether the change is.
* **Test files are never mutated.** A mutant of a test is a different test; whether
  it passes says nothing about the change.
* The suite must already pass on the unmutated code, or the check escalates: it
  would only re-measure that failure.
* A surviving mutant is a behaviour nobody checks. Below `threshold` the oracle
  **fails** and names the survivors; no mutants at all escalates.
* It is Python-only, and a survivor may be an equivalent mutant. It is the closest
  a deterministic check gets to "the behaviour is verified", and the docs say what
  it cannot do.

### `drill`

`rollback` checks that a diff reverse-applies. That is a claim about a patch, not
about the world. A drill is the stronger statement: take the state, perform the
irreversible action, perform its declared compensation, and require the state to
be identical again.

```json
"reversibility": [
  {"id": "build-dist", "action": "build_pkg", "compensation": "clean_dist",
   "state": ["dist"], "note": "the release build leaves only dist/"}
]
```

```bash
assaystone capability drill --manifest .assaystone/capability.json --root .
```

The drill takes a hash of every state path, runs the action, takes a second hash,
runs the compensation, and takes a third:

* the action must pass, and it must **change** something — otherwise the drill
  proves nothing and fails;
* the compensation must pass;
* the final hash must equal the first.

A directory is hashed by its contents, not by its inode, so a build directory is
a real state path. The record is written to `.assaystone/drills/<id>.json`, bound
to the manifest digest and the commit. The `drill` oracle then decides:

| condition | outcome |
|---|---|
| no record | escalate |
| recorded under different acceptance rules, or for another commit | escalate |
| older than the window | escalate |
| the last drill failed | **fail** |
| record present, current, passed | pass |

Records are machine-local (`.assaystone/drills/` is git-ignored): a record bound
to a commit becomes stale the moment it is committed. Run the drill in the same
CI job as the gate, at the commit you are about to release — the release workflow
of this repository does exactly that.

### `runtime`

The transcript oracle reads a file the agent's harness wrote, so it is treated
as testimony. This oracle reads what the **supervisor** observed:

```json
{"id": "session", "type": "runtime",
 "payload": {"record": ".assaystone/runtime/last.json",
             "require_outcome": "pass", "max_age_minutes": 60}}
```

The Claude Code Stop hook writes that record when a session ends: the commit,
the session id, a content hash for every file it saw, the gate outcome it
triggered, and the audit finding count. The oracle decides:

| condition | outcome |
|---|---|
| record missing, unreadable, or not `source: runtime` | escalate |
| the session ended with a gate outcome other than required | **fail** |
| the record has no observed files, or no commit | escalate |
| the record is older than `max_age_minutes` | escalate |
| the record's commit is not `HEAD` of `--root` | escalate |
| a recorded file's hash changed since the session ended | escalate |

The distinction matters. A failed session is a decision (`fail`); evidence that
does not apply to this code is not a decision (`escalate`). The record is
unsigned — it is supervisor observation next to the work, not a receipt. If you
need a signed decision, that is `gate --receipt`.

**The session and the decision point at each other.** Set `"trail"` in the
payload and the oracle also checks that the decision the record names is really
on that trail, for the same commit:

```json
{"id": "session", "type": "runtime",
 "payload": {"record": ".assaystone/runtime/last.json",
             "trail": ".assaystone/trail.jsonl"}}
```

The hook writes the record *after* appending its own trail entry, so the record
carries `gate.entry_hash`. The oracle then publishes facts —
`session`, `record` (the file's digest), `entry`, `record_commit` — which reach
the trail entry and the signed receipt. A reviewer holding a receipt can check it
against the file it cites:

```bash
assaystone receipt verify receipt.json --runtime-record .assaystone/runtime/last.json
```

That fails if the record was edited, or if it belongs to a different session.

**The supervisor does not cite itself.** The hook's own gate skips `runtime` and
`drill` oracles and reports them as *not evaluated here*: the process that writes
the session evidence cannot require that evidence to exist already. CI, which
runs after the session, evaluates them normally.

`.assaystone/runtime/` is machine-local: add it to `.gitignore`. Keep
`record: false` in `.assaystone/hook.json` if you do not want the hook to write
one.

### `verifier`

A capability can bind a check from the verifier ABI instead of inventing a new
payload. The gate compares the working tree with `HEAD` in a temporary
worktree, runs the named check, and returns its verdict:

```json
{"type": "verifier", "payload": {"name": "tests.integrity", "params": {}}}
```

* Only checks that trust artifacts run this way. A check that trusts
  `trace` or `evidence` escalates: without a session it would be guessing.
  Bind the `transcript` oracle when the decision needs the agent's trajectory.
* `tests.pass` executes the test command, so it needs `run_tests: true` and an
  optional `test_command`. Every other check is passive.
* The gate root must be inside a git repository; the repository top level is
  the unit of comparison. Without git, the oracle escalates. The check runs in
  a temporary copy of `HEAD` (heavy directories are excluded), so it costs
  more than the file-based primitives; use it where the diff itself is the
  risk.
* The verifier's declared `claim`, `blind_spots`, and independence travel with
  the result. This is the same check the Goodhart suite scores, now deciding a
  deployment stage.

`transcript` and `verifier` answer different questions: *what did the agent do*
versus *what does the diff contain*. A manifest can require both.

## Oracle registry

A platform team owns the oracle definitions; capability authors pin them.

```json
{
  "version": 1,
  "oracles": [
    {"id": "java.maven.compile", "version": 2, "owner": "platform-team",
     "type": "command",
     "payload": {"command": ["mvn", "-q", "-DskipTests", "compile"], "timeout": 600}}
  ]
}
```

```json
{"id": "compile", "ref": "java.maven.compile", "version": 2}
```

* A manifest may declare `"registry": "oracles.json"`, resolved relative to the
  manifest; `--registry PATH` overrides it.
* `version` pins the registry entry. A mismatch is a manifest error.
* A `ref` cannot also carry `type` or `payload`. That is the point: a capability
  cannot quietly weaken a shared oracle.
* Every oracle carries a fingerprint — `sha256` of its type and payload. The
  trail records it, so an audit entry names the exact definition that ran.
* The manifest records a fingerprint of the whole registry as well.

## Lifecycle gates

A stage declares what evidence it needs:

```json
{"canary": {"require": ["compile", "tests"],
            "approvals": ["reviewer"],
            "allow_merge": true},
 "production": {"require": ["compile", "tests"],
                "approvals": ["reviewer"],
                "allow_merge": true, "allow_deploy": true,
                "rollback_required": true, "rollback": "rollback_plan",
                "after": "canary"}}
```

* All required oracles and approvals run. Any `fail` fails the gate; any
  missing oracle or `escalate` escalates; otherwise it passes.
* `allow_merge` and `allow_deploy` are only granted on a pass. A stage that
  allows merging *and* deploying needs both flags.
* **A policy may not permit what it cannot justify.** A stage that sets
  `allow_deploy` must name an approval oracle (or set `manifest_approval`) and
  must require rollback evidence with a named rollback oracle. A stage that
  allows `allow_merge` must have an approval when the manifest declares `merge`
  irreversible. `capability validate` refuses the manifest otherwise.

  This exists because the onboarding draft used to allow deploy on `production`
  with no approval and no rollback: a new user could get a green light from a
  manifest that checked almost nothing.
* `rollback_required` must name a `rollback` oracle. The gate runs it like any
  other required check, so "rollback required" is evidence, not a claim. A
  policy that asserts rollback without naming an oracle is a manifest error —
  the same rule this project applies to verifiers applies to itself. The rollout
  can be a human attestation, a command that the old implementation still runs,
  or a file that the rollback script exists. The trail records the oracle, its
  outcome, and its digest.
* A stage with no policy escalates rather than passing by default.
* `after` chains a stage to a recorded pass of an earlier one. `production`
  with `"after": "canary"` will not run unless the trail holds a passing
  `canary` gate for **the same capability, the same manifest digest, and the
  same commit**. No trail, no entry, a later failure, a changed manifest, or
  different code escalates. The chain check verifies the trail first: an edited
  trail cannot unlock the next stage. Circular `after` policies are rejected
  when the manifest is validated.

  The commit matters: without it, a canary pass recorded on a benign commit
  would authorise any later commit. The gate reads `HEAD` of `--root` and
  compares it with the chain entry; a mismatch says *re-run canary on this
  code*, because that is the only honest next step.

### Assurance gap and `--strict`

A gate only runs the oracles its stage names. A manifest can therefore declare a
critical criterion and never check it at `shadow`. That is an assurance gap: the
gate reports every declared criterion that this stage does not gate.

```text
assurance gap (declared, not gated at this stage):
  publish-approved  critical  The pricing owner approved publishing.
```

`--strict` escalates when a `critical` criterion is ungated (except at
`design`, where nothing is deployed yet). A failure still outranks the gap: the
gate reports `fail`, not `escalate`.

`capability validate` reports a stronger, static case: a criterion no stage
gates at all. That is a manifest defect, not a stage decision, so it is visible
before the first gate:

```text
criteria gated by some stage: 3/4
not gated by any stage: publish-approved (critical)
```

`capability validate --strict` exits `1` when a critical criterion is in that
list.

## Audit trail

`gate --audit PATH` appends one JSON line:

```json
{"seq": 0, "at": "2026-11-25T03:01:38Z", "capability": "pricing-change",
 "stage": "shadow", "outcome": "pass", "actor": "qa-bot",
 "merge_allowed": false, "deploy_allowed": false,
 "rollback_required": false, "rollback": "", "manifest_lifecycle": "shadow",
 "manifest_digest": "sha256:...",
 "oracles": [{"id": "ledger", "type": "sql", "outcome": "pass",
              "digest": "sha256:...", "fingerprint": "sha256:..."}],
 "missing": [], "gap": ["publish-approved"], "strict": false,
 "prior": {"stage": "canary", "seq": 0, "hash": "sha256:...", "outcome": "pass"},
 "prev": "sha256:0000...", "hash": "sha256:..."}
```

* `digest` covers outcome, reasons, evidence, and raw output. The trail stores
  the digest, not the evidence, so long-lived logs do not accumulate query
  results or response bodies.
* `actor` comes from `--actor`, then `ASSAYSTONE_ACTOR`, then `$USER`.
* `manifest_digest` is the identity of the acceptance rules themselves: the
  manifest with its registry payloads, excluding the registry path. On a trail
  with a previous entry, a changed digest escalates the gate until someone
  re-runs with `--accept-manifest-change`. An agent can still edit the
  manifest; it cannot do so silently.
* `trail verify` recomputes every hash, checks the `prev` links and `seq`
  positions, and reports the head. Editing a field or deleting a middle entry
  breaks the chain.

What the chain does **not** prove:

* **authenticity** — whoever can write the file can rewrite the whole chain;
* **freshness** — truncating the tail leaves a valid chain.

Anchor the head hash where the gate writer does not control it — a CI log, a
signed commit, a transparency log — and pass it to `trail verify --expect HASH`.
The verifier then detects truncation as well as edits. This is a stated limit,
not an oversight.

A [signed receipt](#signed-gate-receipts) closes the authenticity gap for
holders of the key: it signs the trail head, the manifest digest, and the
commit. Tail truncation is detectable by comparing the receipt with the trail.

## Signed gate receipts

A trail proves that a file was not edited in place. It does not prove who wrote
it. A receipt is a small signed statement of one decision:

```bash
export ASSAYSTONE_RECEIPT_KEY=...        # held by the gate runner, not the agent
assaystone gate --manifest .assaystone/capability.json --stage canary \
  --root . --audit .assaystone/trail.jsonl \
  --receipt .assaystone/receipt.json

assaystone receipt verify .assaystone/receipt.json \
  --commit "$GITHUB_SHA" --manifest-digest sha256:... --outcome pass
```

The receipt binds:

- capability, stage, outcome, `merge_allowed`, `deploy_allowed`;
- the git commit and whether tracked files were dirty;
- the manifest digest and the trail head + entry count;
- the actor, timestamp, per-oracle id/type/outcome/digest, assurance gap, chain
  prior, and rollback oracle;
- an HMAC-SHA256 signature under `ASSAYSTONE_RECEIPT_KEY`.

Verification fails on any changed field, a wrong key, or a commit, manifest
digest, or outcome that does not match. `--commit` accepts a SHA or a ref; an
annotated tag is resolved to its commit, because `git rev-parse v1.2.3` returns
the tag object, not the commit the receipt signs. The gate refuses to sign a trail that
does not verify, and refuses to write a receipt without a key (exit `2`).

**Trust model.** HMAC is symmetric: a verifier needs the same key. The receipt
proves the decision came from someone holding the key — normally the CI gate
job — not that it is publicly verifiable. Hold the key only in the gate job, make
the gate + verify a required branch check, and protect the workflow from
unreviewed edits. Do not put the key in the agent's environment.

**Ed25519 receipts.** With the optional `cryptography` extra, the gate can sign
with a private key and a reviewer can verify with only the public key:

```bash
python -m pip install "assaystone[crypto]"
assaystone key generate --private owner.key --public owner.pub
assaystone gate ... --receipt receipt.json --receipt-key-file owner.key
assaystone receipt verify receipt.json --public-key owner.pub --outcome pass
```

The verifier cannot sign, and the private key never leaves the signer. In CI,
write the private key from a secret to a `0600` file for the gate step and remove
it afterwards; keep the public key in the repository or a policy store. HMAC
remains the default and needs no extra.

### Revoking a key

A key id is only useful if a lost key can be retired. `capability.revocations.json`
sits next to the manifest:

```json
{
  "version": 1,
  "revoked": [
    {"key_id": "sha256:4588...", "reason": "laptop lost", "at": "2026-11-25"}
  ]
}
```

Every owner approval, waiver, and receipt key id is checked against the list. A
listed key does not make the past decision false; it makes it unable to stand:
the gate **escalates** and says which artifact and which reason, so a human
re-decides under a current key. An unreadable list escalates as well. The list's
own integrity comes from repository review — commit it before or with the key
rotation. A revocation list with no reasons is rejected.

Ed25519 artifacts carry a **key id** — the SHA-256 fingerprint of the public key
— inside the signed body. Verification checks it whenever the public key is
supplied, so a key substitution fails even if the signature is otherwise valid.
`assaystone key fingerprint --public owner.pub` prints it, and `key generate`
shows it. To rotate, publish a new key id; old artifacts keep the old id. A
revoked id is refused by the gate (see above). There is no identity system and
no expiry, and the docs say so.

## A Java public API oracle

A Java change can compile, leave every test green, and still break downstream
consumers by removing or changing a public signature. The cheap oracle is
`javap -public` against the baseline:

```json
{"id": "api", "type": "command",
 "payload": {"command": ["python3", ".assaystone/java_api_diff.py",
                         "--baseline", "HEAD"]}}
```

[`examples/capability/java_api_diff.py`](../examples/capability/java_api_diff.py)
compiles the baseline in a temporary worktree and compares both trees. It is a
payload, not a primitive: copy it into the repository and bind it to a criterion.
The full run is in
[case-study-lifecycle.md](case-study-lifecycle.md): a green build, a broken API,
an escalated promotion, and a verified `git revert`.

## Hand the criteria to the agent

A gate is post-hoc unless the agent knows what it will be judged on. The manifest
already holds the criteria; render them as the agent's brief:

```bash
assaystone capability brief --manifest .assaystone/capability.json \
  --task "Rename the accessor and keep the module compiling." \
  --out .assaystone/brief.md
```

The brief contains the criteria, the oracle binding, the current stage's
requirements, the exact gate command, and three rules: do not edit tests, CI, or
the manifest to pass; stop and explain a conflict with a criterion; a pass is
evidence, not a claim.

In the [lifecycle case study](case-study-lifecycle.md#the-same-task-with-the-criteria-in-the-input),
the same task was run twice. Without the brief, the agent renamed a public
accessor, reported a verified build, and failed the API oracle. With the brief,
it ran the gate three times, reverted its own edit, and reported the conflict
instead of claiming success. The brief is a view of the manifest, not a new
source of truth.

## Approved exceptions

A strict gate with no exception path gets bypassed. A waiver is the auditable
alternative: the owner accepts one named criterion, for a stated reason, until a
date, under the exact manifest digest that was reviewed.

```json
{"capability": "pricing-change", "waivers": true, "...": "..."}
```

```bash
# HMAC
export ASSAYSTONE_OWNER_KEY=...
assaystone capability waive --manifest .assaystone/capability.json \
  --criterion fee-parity --reason "accepted for the migration window" \
  --expires 2026-12-31 --approver pricing-owner

# Ed25519
assaystone capability waive --manifest .assaystone/capability.json \
  --criterion fee-parity --reason "accepted for the migration window" \
  --expires 2026-12-31 --approver pricing-owner \
  --private-key-file owner.key
assaystone gate ... --owner-public-key owner.pub
```

The waiver is written to `capability.waivers.json`, signed per entry and bound to
the capability and the manifest digest. The gate applies it only when:

- the entry's signature verifies under the owner key;
- the waiver has not expired;
- **every** criterion bound to the failing oracle is waived;
- the failure is a `fail`, not an `escalate` — a waiver accepts a known failure,
  it does not resolve uncertainty;
- the manifest still has the same digest. Changing a criterion invalidates all
  waivers for it.

A waived oracle is reported in the trail, the receipt, and the status card as an
active residual risk with the approver and expiry. It never appears as a clean
pass. If waivers are enabled and a failure occurs without the owner key, the gate
escalates rather than guessing.

## The registry

A capability is a directory, not only a file:

```text
.assaystone/
  capability.json
  trail.jsonl
  receipt.json
  capability.approval.json
  capability.waivers.json
```

Any nested `.assaystone` directory is another capability. The registry scans the
workspace and prints one row per capability:

```bash
assaystone capability list --root . --strict
```

```text
capability    owner   risk  lifecycle  criteria  last             approval  receipt  critical
pricing       growth  high  shadow     4/4       shadow:pass      ok        ok       0
refunds       support high  shadow     3/3       canary:pass      ok        -        0
```

`--strict` exits `1` when any capability has a critical risk: no trail, no
recorded gate for the capability's current lifecycle stage, a **current-stage
decision made on a different commit**, a recorded stage whose last decision did
not pass, an ungated critical criterion, an invalid approval, receipt, or
waiver, or an invalid manifest. A future stage with no
evidence yet is not a current defect; the per-stage gap stays on the card. `--json` returns the same data.

The registry is read-only and creates no second source of truth: every cell comes
from the capability card. It is how a team answers "where do we stand?" without
opening each repository.

### Several repositories

Aggregate without a service — pass more roots, or an index file:

```bash
assaystone capability list --root ../api --root ../worker --strict
assaystone capability list --index .assaystone/repos.json
```

```json
{"roots": ["api", "worker", "services/billing"]}
```

Paths in the index resolve relative to the index file. With more than one root the
table gains a `repo` column and every critical risk is prefixed with its
repository. Duplicate roots are counted once; `--strict` exits `1` if any
capability in any repository has a critical risk.

Evidence verification needs the keys: without `ASSAYSTONE_OWNER_KEY` (or
`--owner-public-key`) and the receipt key, an approval or receipt that requires
one is reported as unverified, which is the honest answer rather than a green
tick.

## Reviewing a change to the criteria

An owner approval is bound to a digest, so any edit forces a new review. The
reviewer needs to see what changed, not a JSON diff:

```bash
assaystone capability diff --manifest .assaystone/capability.json \
  --old ../previous/capability.json
```

```text
- this change removes or lowers assurance

criteria removed:
  - ledger-conserved (critical)

criteria changed:
  ~ tests-pass: severity: 'critical' -> 'medium'

oracles removed: ledger

policies:
  ~ production: require={'added': [], 'removed': ['ledger']},
                rollback_required={'before': True, 'after': False}
```

`--json` returns the same structure. A change that removes a criterion, an
oracle, a stage, an approval, a rollback, or lowers a risk rating is flagged as
**weakening**. Additions and tightened requirements are shown but not flagged.
The diff never decides anything; it tells the owner what they are being asked to
re-approve.

## Do not judge a tree you have modified

Several checks change the thing they check: a seed builds a database, a
migration runs, a build writes an output directory. `--sandbox` runs those in a
disposable copy:

```bash
assaystone gate --manifest .assaystone/capability.json --stage shadow \
  --root . --sandbox
```

```text
outcome: pass
sandbox: yes
seed      command  pass
tests     command  pass
ledger    sql      pass
parity    shadow   pass
```

Afterwards the real tree is untouched — no `ledger.db`. The rule is explicit:

* workspace checks (`command`, `file`, `sql` with a local database, `shadow`,
  `verifier`, `runtime`, `drill`, `mutation`) run in the copy, so a seed and the
  query that reads it see consistent state;
* only checks that reach outside the workspace — `git` (repository metadata),
  `http` (an endpoint), `human` (an approval queue), and `sql` with `dsn_env` —
  use the real root.

`--sandbox` and `--dry-run` are mutually exclusive: a dry run skips mutating
oracles, so there is nothing to protect. The result and the trail record
`sandbox: true`, because "this passed in a copy" is different evidence from
"this passed here".

## Price the verification

A stage can declare what its checks may cost, and an oracle can declare its own
price. The gate adds them up and stops honestly:

```json
{"shadow": {"require": ["build", "api", "soak"], "budget_usd": 0.50}}
```

```json
{"id": "soak", "type": "command",
 "payload": {"command": ["./soak.sh"], "cost_usd": 0.40, "timeout": 900}}
```

```text
outcome: escalate
cost: $0.0100
  verification budget $0.5000 would be exceeded before `soak` ($0.4000);
  spent $0.0100
```

* Declared order is preserved, because oracles often depend on each other (a
  seed before a query). The gate does not reorder to cheap-first.
* An exhausted budget **escalates**, never passes: an unchecked requirement is
  not a satisfied one.
* `cost_usd` reaches the gate result, the trail, and the receipt, so a reviewer
  can see what a decision cost.
* A non-numeric cost counts as zero; a negative budget is a manifest error.

## Try it before you run it

A gate can be expensive or destructive: it seeds a ledger, applies a migration,
calls a staging endpoint. `--dry-run` executes only the oracles that do not
declare a mutation, and **never returns pass**:

```bash
assaystone gate --manifest .assaystone/capability.json \
  --stage shadow --root . --dry-run
```

```text
outcome: escalate
dry run: yes
seed      command  escalate  not executed: a dry run does not perform an oracle that declares it mutates state
tests     command  pass
ledger    sql      escalate  database not found: ledger.db
parity    shadow   pass
```

An oracle declares `"mutates": true` in its payload when it changes state — a
seed command, a write request, a migration. Everything else runs.

Three rules make dry-run safe to use as a first step:

* it never returns `pass` — a dry run is not a decision;
* a real failure in a read-only oracle is reported as `escalate`, not `fail`, so
  a dry run cannot impersonate a red build either;
* `--receipt` is refused, so a dry run cannot leave signed evidence behind.

What it tells you: whether the manifest is sane, which oracles are read-only,
and what would change. What it does not: whether the mutating oracle works.

## What blocks the next stage

A residual-risk list tells you what is unresolved. This tells you what to do:

```bash
assaystone capability next --manifest .assaystone/capability.json \
  --trail .assaystone/trail.jsonl --stage canary
```

```text
quote-service: shadow -> canary

1 blocker(s)

1. `canary` exists but does not allow merging, so nothing can move through it
   add to the manifest:
         {
           "id": "reviewer",
           "type": "human",
           "description": "a named reviewer approved promotion",
           "payload": {"action": "promote", "record": "approvals.json"}
         }
   then: add `approvals: ["reviewer"]` and `allow_merge: true` to the policy
```

It reports, in order: a missing stage policy (with the policy to add), a stage
that permits nothing, a critical criterion the stage does not gate, and — when a
trail is supplied — a required oracle with no passing decision on that trail.

`--apply` carries out everything that is mechanical:

```text
applied 3 change(s) to .assaystone/capability.json:
  + added oracle `reviewer`
  + `canary` now lists `reviewer` in approvals
  + `canary` allows merging
```

It adds the approval oracle, the policy, and the missing `require` entries, then
refuses to write a manifest that would not validate. What it will not do is
invent evidence: a compensation oracle has to be a real command, and an approval
has to come from a person. Those stay on the "still needs a person" list. If the
manifest requires an owner approval, applying changes makes it stale, and the
command says so.

## What the environment owes

`next` makes the manifest able to express a stage. This checks the things outside
it that the gate reads:

```bash
assaystone capability prepare --manifest .assaystone/capability.json \
  --stage canary --root .
```

```text
pricing-change at `canary`

1 thing(s) the gate will not find

1. [approver] approvals.json does not exist; `approval` will escalate until
   someone records the `publish` approval
   the approver writes approvals.json; shape:
     {
       "approvals": [
         {
           "action": "publish",
           "approved": true,
           "approver": "<the person who approved>",
           "scope": "<what they approved>"
         }
       ]
     }
```

It checks, per required oracle: an approval record that exists, names the
action, and is granted (and signed, when the oracle asks for a signature); a
drill record that exists and passed; a session record the hook will write. Each
need names **who** has to act — `approver` or `operator` — because an approval is
a person's decision and a drill is a claim about the world. Nothing is created on
the operator's behalf.

## Which checks earn their keep

The trail already records, per decision, which oracle ran and what it said. That
is the empirical version of "price the verification":

```bash
assaystone capability utility --manifest .assaystone/capability.json \
  --trail .assaystone/trail.jsonl
```

```text
capability: util-demo
decisions on this trail: 6

oracle     runs  pass  fail  esc  required  last
compile       6     5     1    0       yes  pass
lint          6     6     0    0       yes  pass

by stage
  shadow          6 runs (5 pass, 1 fail, 0 escalate)

never observed a failure: lint
  this is a fact, not a verdict: the check may be doing its job, or it may be
  unable to fail
declared but no policy uses it: unused
```

Three findings it can produce:

* **required but never recorded** — the check was added to a policy after the
  evidence stopped accumulating, or the gate never reached it;
* **never observed a failure** — a fact, not a verdict: the check may be doing
  its job, or it may be unable to fail. This is the same distinction as recall
  versus resistance: an oracle you have never seen reject anything is untested,
  not proven;
* **declared but unused**, or **ran but no policy requires it now** — dead weight
  and stale policy respectively.

The report does not delete anything. Removing a check is an owner decision, and
`capability diff` will show it as weakening.

## The capability card

The gate answers one run; the card answers the operator's question.

```bash
assaystone capability status --manifest .assaystone/capability.json \
  --trail .assaystone/trail.jsonl --receipt .assaystone/receipt.json \
  --stage shadow
```

It reports:

- static assurance gaps and the critical gaps at the current stage;
- **stale evidence**: a stage decision recorded for a different commit than the
  code at `--root` is marked `[stale commit]` and listed as residual risk;
- **the runtime record**: whether a supervisor record exists, which session and
  commit it names, and whether it still describes this code;
- each stage's requirements, approvals, rollback oracle, and chain;
- whether the owner approval is present and valid;
- the trail chain, its head, and the last outcome per stage;
- whether the receipt verifies, and the commit and trail head it binds;
- a **residual risk** list.

It is read-only. Missing evidence is a residual risk, never a pass. `--json`
returns the same card for a dashboard or a job summary.

## Who approves the criteria

A gate is only as trustworthy as the rules it checks. If the agent can edit the
manifest, it can remove the criterion it fails. A capability can require the
owner to sign its manifest digest:

```json
{"capability": "pricing-change", "manifest_approval": true, "...": "..."}
```

```bash
# HMAC: the verifier needs the same key.
export ASSAYSTONE_OWNER_KEY=...
assaystone capability accept --manifest .assaystone/capability.json \
  --approver pricing-owner

# Ed25519: the owner keeps the private key; CI holds only the public key.
assaystone key generate --private owner.key --public owner.pub
assaystone capability accept --manifest .assaystone/capability.json \
  --approver pricing-owner --private-key-file owner.key
assaystone gate ... --owner-public-key owner.pub
# writes .assaystone/capability.approval.json
```

The gate verifies the capability, the digest, and the signature **before it runs
any oracle**. A missing file, a missing key, a changed manifest, or a bad
signature escalates. This is a governance decision, not a failed check.

| key | held by | signs |
|---|---|---|
| `ASSAYSTONE_OWNER_KEY` (HMAC) or the owner private key (Ed25519) | the capability owner | the manifest digest |
| `ASSAYSTONE_RECEIPT_KEY` (HMAC) or the gate private key (Ed25519) | the gate runner (CI) | one gate decision |

**The digest is stable across upgrades.** It covers only what you declared: keys
that existed when approvals were first issued stay present even when empty, and
a field added later appears only when it is set. Adding `budget_usd` changed
every digest and invalidated an approval during development — the self-gate
refused on CI — so the serialised shape is now frozen and pinned by a test.

Keep them separate. The owner decides what "acceptable" means; CI records that
the decision was made. HMAC is symmetric; Ed25519 lets CI hold only a public key,
so it can verify an owner decision without being able to make one. Ed25519
approvals and waivers carry a key id, so the gate can reject a substituted
public key. The approval has no expiry; it is valid while the digest is
unchanged. A review window and key revocation are declared future gaps.

## Self-weakening and forged approvals

Two attacks are specific to a gate that reads its own inputs from the working
tree. Both have a concrete mechanism, and both have a remaining limit.

**The agent weakens the manifest.** Deleting a criterion or a required oracle is
the cheapest way to pass. The trail records `manifest_digest`, and the next gate
on the same trail escalates when it changes: the edit is visible and needs an
explicit `--accept-manifest-change`. With `manifest_approval: true`, the change
also invalidates the owner's signature, so accepting the change is an owner
decision, not a flag anyone can pass. The limit is key custody: the owner key
must not be available to the agent.

**The agent writes its own approval.** `approvals.json` is a file. If the
approval system cannot write somewhere the agent cannot, the `human` oracle is
testimony, not evidence. For a real deployment, sign the record:

```json
{"id": "approval", "type": "human",
 "payload": {"action": "publish", "record": "approvals.json",
             "hmac_env": "ASSAYSTONE_APPROVAL_KEY"}}
```

The record is `{"approvals": [...], "signature": "..."}` where the signature is
HMAC-SHA256 over the canonical JSON of `{"approvals": [...]}` with the key from
the environment. A missing key escalates; an unsigned or altered record fails.
Without `hmac_env`, the oracle reads an unsigned file and the documentation
says so rather than implying a guarantee.

Neither mechanism makes a compromised host safe. They make the decision
*tamper-evident*: an edit or a forged approval has to be explained.

## Adapting a new domain

1. Write the manifest: systems, irreversible actions, criteria, severity.
2. Bind each criterion to one of the thirteen primitives. If none fits, that is a
   finding about the domain, not a reason to add a code path.
3. Put shared definitions in a registry and pin their versions.
4. Declare what each lifecycle stage requires, and which approvals it accepts.
5. Run `gate` at `shadow` first. Every gap and every escalation is either a
   missing manifest entry or a missing oracle.

The audit rule: if adapting a domain changed any Python file, the abstraction
failed. The pricing vertical is the reference — it added `sql`, `shadow`, and
the trail with no domain-specific code.

## In CI

A gate is a command, so it fits any pipeline. The bundled Action wraps it:

```yaml
- uses: yellowsand1/assaystone@v0.7.0
  with:
    manifest: .assaystone/capability.json
    stage: canary
    root: .
    audit: .assaystone/trail.jsonl
    actor: ${{ github.actor }}
```

The action writes the oracle table to the step summary, sets `verdict` and
`findings` outputs, and exits non-zero on `fail` or `escalate`. The raw form is
equivalent:

```yaml
- run: pip install assaystone
- run: |
    assaystone gate --manifest .assaystone/capability.json \
      --stage canary --root . \
      --audit .assaystone/trail.jsonl --actor "$GITHUB_ACTOR"
- run: assaystone trail verify .assaystone/trail.jsonl
```

Make the trail job artifact immutable and log the head hash; pass it back with
`--expect HASH` on the next run. Exit codes let the pipeline stop on `fail` and
route `escalate` to a required reviewer instead of retrying.

Assaystone's own release workflow is the reference: it runs `gate --stage
production` before it builds, with a committed owner approval verified by the
owner public key, the tests/lint/benchmark oracles, the rollback check, an
Ed25519 release receipt whose private key is a GitHub secret, and an evidence
artifact. Starting with 0.17.0, the release is the first tag gated this way.

If a stage declares `after`, carry the **same trail artifact** from the earlier
stage into the later job. Two separate trails are two separate histories, and
the chain check escalates rather than guessing which one is real.

## Limits

* `http` and `sql` perform reads and, with explicit opt-in, a single write.
  They are not a sandbox: a manifest you run is a manifest you trust.
* Oracle evidence can contain sensitive text; use `--json` output carefully and
  keep the trail, which stores digests only, as the durable record.
* A trail is a local file: concurrency is the caller's responsibility (single
  writer, append-only).
* `mysql` needs `pymysql`; without it the oracle escalates. There is no bundled
  driver and no auto-install. The optional tests run only when
  `ASSAYSTONE_TEST_MYSQL_DSN` is set:

  ```bash
  ASSAYSTONE_TEST_MYSQL_DSN='mysql://user:pass@127.0.0.1:3306/db' \
    python3 -m unittest discover -s tests -t . -p 'test_mysql_optional.py'
  ```
