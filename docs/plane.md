# The acceptance plane

A verifier answers "is this artifact acceptable?" for one artifact at one
moment. A deployment needs more: *who* asked, at *which lifecycle stage*, with
*which* evidence, *what* was not checked, and *where* the decision was recorded.

The acceptance plane is that layer. Its core is domain-blind: eight generic
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
assaystone capability init --root . --owner platform-team
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
* Matchers: `equals`, `contains`, `regex`, applied to the value at `json_path`.

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
  the oracle escalates instead of skipping;
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
                "rollback_required": true, "rollback": "rollback_plan"}}
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

## Self-weakening and forged approvals

Two attacks are specific to a gate that reads its own inputs from the working
tree. Both have a concrete mechanism, and both have a remaining limit.

**The agent weakens the manifest.** Deleting a criterion or a required oracle is
the cheapest way to pass. The trail records `manifest_digest`, and the next gate
on the same trail escalates when it changes: the edit is visible and needs an
explicit `--accept-manifest-change`. The limit is the trail itself; keep it
outside the agent's write access and anchor its head.

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
2. Bind each criterion to one of the eight primitives. If none fits, that is a
   finding about the domain, not a reason to add a code path.
3. Put shared definitions in a registry and pin their versions.
4. Declare what each lifecycle stage requires, and which approvals it accepts.
5. Run `gate` at `shadow` first. Every gap and every escalation is either a
   missing manifest entry or a missing oracle.

The audit rule: if adapting a domain changed any Python file, the abstraction
failed. The pricing vertical is the reference — it added `sql`, `shadow`, and
the trail with no domain-specific code.

## In CI

A gate is a command, so it fits any pipeline:

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

## Limits

* `http` and `sql` perform reads and, with explicit opt-in, a single write.
  They are not a sandbox: a manifest you run is a manifest you trust.
* Oracle evidence can contain sensitive text; use `--json` output carefully and
  keep the trail, which stores digests only, as the durable record.
* A trail is a local file: concurrency is the caller's responsibility (single
  writer, append-only).
* `mysql` needs `pymysql`; without it the oracle escalates. There is no bundled
  driver and no auto-install.
