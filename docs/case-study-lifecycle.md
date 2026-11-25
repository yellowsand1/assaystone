# A lifecycle trial: green build, broken API, blocked promotion, real rollback

The 0.8.0 release has the pieces. This is the first run of all of them together
on a real repository, with a failure that a green build cannot see.

It was run locally on a temporary clone of an internal Maven module. No source,
class name, SQL, or session content from that repository is published here.

## The setup

The module is small: seven classes, no tests, Lombok-generated accessors. That is
the point. A public API change compiles cleanly, leaves "tests" green because
there are none, and breaks every downstream consumer.

The manifest declared five criteria:

| criterion | oracle |
|---|---|
| The module compiles | `command`: `mvn -q -o -DskipTests compile` |
| Compiled classes exist | `file`: `target/classes` |
| **The public API is unchanged** | `command`: `javap -public` diff against `HEAD` |
| The change is on a feature branch | `git` |
| The owner approved promotion | `human`, signed with `hmac_env` |
| The last commit can be reversed | `command`: `git diff HEAD~1 HEAD \| git apply --check -R` |

The API oracle is an example payload,
[`examples/capability/java_api_diff.py`](../examples/capability/java_api_diff.py):
it compiles the baseline in a temporary worktree, runs `javap -public` on both
trees, and fails when a class or a public signature differs.

## What happened

A public accessor pair on a DTO was renamed. The module compiled. The artifact
existed. The branch was correct. The API oracle failed:

```text
outcome: fail
build     pass
artifact  pass
api       fail   exit 1 != expected 0
branch    pass
  public API changed:
    ...: removed public java.lang.String getOauthUnitValue();
         public void setOauthUnitValue(java.lang.String);
```

The trail recorded the full sequence:

| seq | stage | outcome | what it shows |
|---|---|---|---|
| 0 | shadow | fail | compile and artifact green, API broken |
| 1 | shadow | pass | the rename was reverted |
| 2 | canary | escalate | promotion attempted without an approval record |
| 3 | production | escalate | chained to the escalated canary, as designed |
| 4 | canary | pass | signed owner approval present |
| 5 | production | pass | chained to seq 4; rollback oracle passed |
| 6 | shadow | pass | state after rollback |

`trail verify`: 7 entries, chain intact. Production at seq 5 carries
`prior = canary#4`; it would not have run while the latest canary entry was an
escalation.

The promotion used a documentation-only commit. Rollback was a real
`git revert`, not a claim:

- the working tree equals the pre-change commit (`git diff --quiet`);
- `javap` against the pre-change commit reports the same public API;
- a shadow gate on the rolled-back tree passes and is recorded in the trail.

## A second domain, same plane

The same commands ran against a pricing project with two different defects:

| defect | caught by | evidence |
|---|---|---|
| the new implementation adds a field to its output | `shadow` | `fees.0.audited: False != True` |
| an order amount changes | `sql` | `row 0.total: 12400 != 12300` |

Canary (with the owner approval) and production (chained to canary, rollback
oracle) passed after the defects were reverted. The SQL trail has 5 entries and
verifies. No core code changed between the two domains.

## Cost on this machine

| gate | wall time |
|---|---|
| Maven module, shadow (two compiles: working tree + baseline worktree) | 5.42 s |
| pricing/SQLite, shadow | 0.22 s |

The API oracle is the expensive part: it compiles the baseline. That is still
seconds, not minutes, and it is the difference between "the build is green" and
"the consumers still compile".

## What this proves

- A defect class that compilation and a green suite cannot see is caught by a
  declared oracle, with the removed signature in the evidence.
- A missing approval escalates; a signed approval unlocks canary.
- Production refuses to follow an escalated canary, and records the prior entry.
- A rollback can be executed and verified; the trail covers the whole sequence.
- The same plane, commands, and trail work on a Java module and a SQL fixture.

## What it does not prove

- **The defect was authored by us.** This measures the gate, not an agent's
  behavior.
- **No human approved anything.** The signature came from a trial key; the
  record was not written by an approval system.
- **"Green tests" means no tests exist** in the module. That makes the API oracle
  more important, not the gate more general.
- **The SQL domain is a fixture**, not a production service.
- **Semantic correctness is untouched.** A behavior change with no oracle still
  routes to a human; the Goodhart semantic family remains 0% resistance.
- **No external user was involved.** This is a reproducibility artifact, not
  adoption evidence.

## What the trial exposed

Only one missing piece: a Java public-API oracle is not something most teams
have. The trial had to write one. It now ships as an example payload and is
documented in [plane.md](plane.md).

Two things worked without changes:

- forgetting the signing key escalated instead of passing;
- the chain blocked production after an escalated canary, then allowed it after a
  fresh canary pass.

No core change was needed. That is the result the design was aiming for, and the
reason the next step is a design-partner run, not another primitive.

## Reproduce it

The trial used a manifest like this (copy the API script into the repository
first):

```json
{
  "capability": "api-change",
  "criteria": [
    {"id": "api-stable", "kind": "invariant",
     "statement": "The public API is unchanged.",
     "oracle": "api", "severity": "critical"}
  ],
  "oracles": [
    {"id": "build", "type": "command",
     "payload": {"command": ["mvn", "-q", "-o", "-DskipTests", "compile"]}},
    {"id": "api", "type": "command",
     "payload": {"command": ["python3", ".assaystone/java_api_diff.py",
                             "--baseline", "HEAD"]}},
    {"id": "approve", "type": "human",
     "payload": {"action": "promote", "record": "approvals.json",
                 "hmac_env": "ASSAYSTONE_APPROVAL_KEY"}},
    {"id": "revert", "type": "command",
     "payload": {"command": ["sh", "-c",
                 "git diff HEAD~1 HEAD | git apply --check -R"]}}
  ],
  "policies": {
    "shadow": {"require": ["build", "api"], "allow_merge": false},
    "canary": {"require": ["build", "api"], "approvals": ["approve"],
               "allow_merge": true},
    "production": {"require": ["build", "api"], "approvals": ["approve"],
                   "allow_merge": true, "allow_deploy": true,
                   "rollback_required": true, "rollback": "revert",
                   "after": "canary"}
  }
}
```

Run `shadow`, break a public signature, run `shadow` again, then promote with
`--audit`, and keep the trail. The failure is the evidence.
