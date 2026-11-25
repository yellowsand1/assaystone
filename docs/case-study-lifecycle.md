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

## The same run with a real agent

The lifecycle run above was authored by us. The same gate was then pointed at a
change made by a real coding agent in a fresh clone.

The task was narrow: rename a public accessor pair on a DTO and keep the module
compiling. The agent reported success and said the build was verified. Both
statements were true:

```text
agent:    "已完成修改并验证通过" (done, build verified)
gate:     fail
build     pass
artifact  pass
api       fail   removed ... getOauthUnitValue(); setOauthUnitValue(...)
```

Compilation passed because every internal caller was updated (there were none).
The public API was still broken. The agent did what it was asked and reported it
correctly; the acceptance criterion it had no reason to know about is what
failed.

The session audit added one honest limit and exposed one bug:

- Before the `ignore` option, it treated the gate's own untracked
  `.assaystone/api_diff.py` as agent output and flagged its `print()` calls.
  Tooling that lives in the repository is not a change under review.
- With `ignore: [".assaystone/"]`, the only finding left is
  `diff.language_coverage`: none of the audit checks understand Java, so the
  session oracle escalates. The API oracle is the one that decides.

That division is deliberate: the session layer says "I cannot decide this
language", not "pass".

## The same task with the criteria in the input

The agent run above had no access to the acceptance criteria. A second run used
the same clone, the same task, and the same gate, with one difference: a brief
listed the criteria, the gate command, and the rule to stop on a conflict.

| | without the brief | with the brief |
|---|---|---|
| source change | rename applied | one edit, then reverted |
| build | pass | pass |
| gate | **fail** (public API) | **pass** (tree restored) |
| agent ran the gate | 0 times | 3 times |
| final report | "done, build verified" | "task conflicts with a criterion; stopped" |

The agent's shell history shows the loop, not a lucky guess: three Maven runs,
three gate runs, one revert, and a final clean gate. It did not claim success
while the API was broken.

This is the missing half of the original problem. The gate alone is post-hoc: an
agent optimizes for the task as stated. When the acceptance criteria are part of
the task, the gate becomes the agent's feedback channel, and the work stops
before the broken change is proposed.

What this does not prove:

- the brief explicitly told the agent to run the gate and to stop on a conflict;
  it does not show that agents infer unstated criteria;
- the agent spent 24 shell calls and three gate runs on a one-method rename;
  cost is real;
- a refusal is the right outcome here because the task and the criterion are
  incompatible, but it is not a delivery;
- no human approved anything, and the SQL domain remains a fixture.

Product implication: the brief should not be hand-written. It is a view of the
manifest, and it can be generated. The experiment above used a hand-written
brief; `assaystone capability brief` now renders the same content (criteria,
oracles, stage policy, gate command, rules) from the manifest.

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

1. **A Java public-API oracle is not something most teams have.** The trial had
   to write one. It now ships as
   [`examples/capability/java_api_diff.py`](../examples/capability/java_api_diff.py).
2. **Gate tooling looked like agent output.** With a real agent session, the
   untracked `.assaystone/` directory was included in the artifacts and its
   `print()` calls became a false finding. The transcript oracle now accepts
   `ignore` (paths or globs), and the session was audited with
   `.assaystone/` excluded.
3. **The session oracle cannot decide an unsupported language.** It escalates;
   the API oracle decides. That is the honest division, not a gap to paper over.

Two things worked without changes:

- forgetting the signing key escalated instead of passing;
- the chain blocked production after an escalated canary, then allowed it after a
  fresh canary pass.

No change to the gate core was needed for the agent run. The fixes were
connectors: an example Java oracle and an exclusion for the gate's own files.

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
