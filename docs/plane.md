# The acceptance plane

A verifier answers "is this artifact acceptable?" for one artifact at one
moment. A deployment needs more: *who* asked, at *which lifecycle stage*, with
*which* evidence, *what* was not checked, and *where* the decision was recorded.

The acceptance plane is that layer. Its core is domain-blind: nine generic
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

`init` looks for a build or test surface — `pom.xml`, Gradle, `package.json`
scripts, `pyproject.toml` plus tests, `go.mod`, `Cargo.toml` — and writes
`.assaystone/capability.json` with a build oracle, a test oracle where it found
tests, an artifact check for compiled stacks, and a branch check that follows
the convention the repository already uses (`feature/` or `feat/`). It never
runs a build.

The draft is deliberately incomplete. It declares no approvals and no rollback
claim, because inventing either would be exactly the unchecked assertion this
project argues against. `init` prints what to add next; the first
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
| `command` | a process exits as expected | `command`, `expect_exit`, `cwd`, `timeout` |
| `file` | an artifact exists / parses / contains | `path`, `mode`: `exists`, `json`, `contains`, `regex` |
| `git` | the change is on a branch / the tree is clean | `mode`: `branch`, `clean` |
| `human` | a named action was approved | `action`, `record` |
| `http` | an endpoint answers as declared | `url`, `method`, `expect_status`, `json_path`, matcher |
| `sql` | a read-only query returns the expected rows | `driver`, `database`/`dsn_env`, `query`, `expect` |
| `shadow` | old and new implementations agree on the same input | `old`, `new`, `compare` |
| `transcript` | the agent's recorded session passes the audit | `transcript`, `baseline`, `fail_on` |
| `verifier` | a declared verifier decides the working-tree diff | `name`, `params`, `test_command` |

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
  `canary` gate for the same capability and the same manifest digest. No trail,
  no entry, a later failure, or a changed manifest escalates. The chain check
  verifies the trail first: an edited trail cannot unlock the next stage.
  Circular `after` policies are rejected when the manifest is validated. The
  decision chain is evidence, not an assumption that someone ran the previous
  stage.

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
recorded gate for the capability's current lifecycle stage, a recorded stage
whose last decision did not pass, an ungated critical criterion, an invalid
approval, receipt, or waiver, or an invalid manifest. A future stage with no
evidence yet is not a current defect; the per-stage gap stays on the card. `--json` returns the same data.

The registry is read-only and creates no second source of truth: every cell comes
from the capability card. It is how a team answers "where do we stand?" without
opening each repository.

## The capability card

The gate answers one run; the card answers the operator's question.

```bash
assaystone capability status --manifest .assaystone/capability.json \
  --trail .assaystone/trail.jsonl --receipt .assaystone/receipt.json \
  --stage shadow
```

It reports:

- static assurance gaps and the critical gaps at the current stage;
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
2. Bind each criterion to one of the nine primitives. If none fits, that is a
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
