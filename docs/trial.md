# A trial you can run

This is the whole acceptance loop on a small service, executed by
`scripts/trial.py`. Every line below is real output: `make trial` regenerates the
file and CI diffs it, so the document cannot drift from the code.

It needs no network, no key, and no deployment: a temporary directory, a git
repository, and the package itself.

Timestamps, content hashes, and signatures are normalised so the file can be
diffed; every other line is verbatim.

```bash
python3 scripts/trial.py
```

## What to look at

1. **The repository proposed its own criteria.** Seven checks, each with the
   evidence that justifies it — including "the change is covered by the tests",
   derived from the fact that a Python test suite exists.
2. **Every stage permits nothing.** `allow_merge` and `allow_deploy` are off;
   promotion is the owner's decision, and `validate` refuses a policy that
   allows an irreversible action without approval and rollback.
3. **The gate refused a change that looks done.** A function was added with no
   test: the suite passes, the build passes, and the mutation oracle reports six
   of six mutants surviving. That is the failure this product exists for.
4. **Adding the test turned it green**, and the decision was written to a trail
   and signed into a receipt bound to the commit.
5. **The card says what is unresolved.** A decision made before the commit is
   marked stale, because a decision covers the code it saw.

## What it does not show

- A real deployment: canary against live traffic, a rollback of a running
  system, an organisation's approval system.
- A repository whose tests are wrong. The mutation oracle shows the change is
  covered; it cannot show the test asserts the right thing.

```
== 1. the repository proposes the checks it implies
wrote .assaystone/capability.json
stack: python
oracles: tests, branch, tests_intact, ci_intact, mutation, deps, migrations_down
note: branch oracle expects a feature/* branch; adjust it if your convention differs
note: proposed tests-intact: a test tree exists: a suite that passes because the failing test disappeared is the canonical agent failure
note: proposed ci-intact: .github/workflows exists: weakening CI is cheaper than fixing the code, so it is a defect even when the build is green
note: proposed change-covered: a Python test suite exists: passing tests do not prove the change is covered, and a surviving mutant is a behaviour nobody checks
note: proposed deps-unchanged: a dependency manifest exists: adding a dependency is a supply-chain change that a test suite will not notice
note: proposed migrations-reversible: db/migration exists: a migration without a down path is a one-way door
wrote .github/workflows/assaystone.yml
wrote .assaystone/hook.json
install the hook: assaystone hook install claude-code --manifest .assaystone/capability.json --mode block
next:
  - to allow merging: add an approval oracle to canary and production, then set allow_merge — validate refuses a policy that allows an irreversible action without one
  - to allow deploying: add a rollback oracle, set rollback_required and allow_deploy on production
  - run the gate and inspect every escalation before trusting the draft
  - read each proposed criterion and delete the ones your repository does not actually need

run: assaystone gate --manifest .assaystone/capability.json --stage shadow --root .

== 2. the draft is valid, and every stage permits nothing yet
capability quote-service: ok
  owner=platform-team risk=high lifecycle=design
  oracles=7 criteria=7 policies=3
  criteria gated by some stage: 7/7
{
  "require": [
    "tests",
    "branch",
    "tests_intact",
    "ci_intact",
    "mutation",
    "deps",
    "migrations_down"
  ],
  "allow_merge": false,
  "allow_deploy": false
}

== 3. the acceptance criteria, handed to the agent
# Capability: quote-service

Owner: platform-team
Risk: high
Current lifecycle: design
Irreversible actions: merge

## Acceptance criteria
  ...

== 4. the agent adds behaviour and no test
outcome: fail
  tests            pass      
  branch           pass      
  tests_intact     pass      
  ci_intact        pass      
  mutation         fail      6 of 6 mutants survived (score 0%, required 50%): the tests do not cover these behaviours
  deps             pass      
  migrations_down  pass      
exit: 1

== 5. the agent adds the test
capability: quote-service
stage: shadow
outcome: pass
dry run: no
sandbox: no
cost: $0.0500
merge allowed: no
deploy allowed: no

oracle               type      outcome    reason
tests                command   pass
branch               git       pass
tests_intact         verifier  pass
ci_intact            verifier  pass
mutation             mutation  pass
deps                 command   pass
migrations_down      command   pass

  shadow requires: tests, branch, tests_intact, ci_intact, mutation, deps, migrations_down

trail: .assaystone/trail.jsonl entry 0 hash <sha256>...
receipt: .assaystone/receipt.json commit 65991ce60242aed6068182315cab9f76d9af5cab signature <signature>...
exit: 0

== 6. the trail verifies and the receipt binds the decision
trail: .assaystone/trail.jsonl
entries: 1
head: <sha256>
chain: intact
note: a local chain proves integrity, not authenticity; anchor the head hash externally (CI log, signed commit, transparency log).
receipt: valid
capability: quote-service
stage: shadow
outcome: pass
commit: 65991ce60242aed6068182315cab9f76d9af5cab
trail head: <sha256>
note: an HMAC receipt proves the signer held the key; it is not a public signature.
note: the gate ran on the working tree and the commit came after, so the card marks
      the decision stale against the new commit. That is the rule working, not a defect:
      a decision covers the code it saw.

== 7. what blocks the next stage
quote-service: design -> canary

1 blocker(s)

1. `canary` exists but does not allow merging, so nothing can move through it
   add to the manifest:
         {
           "id": "reviewer",
           "type": "human",
           "description": "a named reviewer approved promotion",
           "payload": {"action": "promote", "record": "approvals.json"}
         }
   then: add `approvals: ["reviewer"]` and `allow_merge: true` to the policy, then re-run `capability next`

== 8. one table across repositories
capability               owner            risk     lifecycle  criteria  last                         approval  receipt  critical
quote-service            platform-team    high     design     7/7       shadow:pass                  -         ok              1

1 capabilities, 1 with critical risks
  quote-service: no recorded `design` gate for the current lifecycle
```
