<p align="center"><img src="assets/logo.svg" width="88" alt="Assaystone"></p>

# Assaystone

**Your agent's tests pass. Did it delete the failing test?**

![ci](https://github.com/yellowsand1/assaystone/actions/workflows/ci.yml/badge.svg)
[![pypi](https://img.shields.io/pypi/v/assaystone)](https://pypi.org/project/assaystone/)
[![release](https://img.shields.io/github/v/release/yellowsand1/assaystone)](https://github.com/yellowsand1/assaystone/releases)
![status](https://img.shields.io/badge/status-alpha-orange)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)
[![website](https://img.shields.io/badge/website-live-2ea44f)](https://yellowsand1.github.io/assaystone/)

Assaystone turns one unit of agent work into a **certificate**: pass, fail, or a
human must look — with the evidence, the check that decided it, the check that
could not, and the cost of deciding.

It is not an eval platform, an agent framework, or a judge. It is the acceptance
layer: contracts a domain expert can review, checks that declare what they cannot
see, and a verdict a third party can re-check without re-running the agent. Every
certificate also carries the **measured reliability** of the checks that decided
it — recall, false alarms, and the sample size behind the number. It runs
locally, offline, with no API key.

```bash
uvx assaystone demo audit                 # find a failure you did not know you had
assaystone check --base origin/main --certificate ./certs   # no trace required
```

`check` compares the working tree to a base ref, runs the contract, and writes a
certificate. In CI it is one step; locally it is the last thing you run before
review.

## 60 seconds

No setup, no key, no transcript of your own:

```
$ uvx assaystone demo audit
audit-demo-session  changed: pricing/discounts.py, tests/test_discounts.py
  HIGH     tests.integrity          tests/test_discounts.py (removed 1 test(s))

summary: 0 critical, 1 high, 0 medium, 0 low

certificate: ./assaystone-demo-certificates/audit-demo-session.certificate.json
verify it:  assaystone certificate verify <that file>
```

The demo ends with the artifact, not with advice. The agent fixed the rounding bug, then deleted the one test it still failed, and
reported success. `tests.pass` saw a green suite. The audit found the deleted
test. The same attacks, with minimal reproductions, are in
[docs/evasions.md](docs/evasions.md).

## The certificate

A verdict without evidence cannot be reviewed. Evidence without provenance cannot
be trusted. A decision without versions cannot be reproduced. The certificate
binds the three into one hash-addressed object.

```bash
assaystone certificate show   ./certs/<id>.certificate.json
assaystone certificate verify ./certs/<id>.certificate.json   # a third party, offline
```

```
certificate   sha256:f5ad3661...
subject       git-106f71d9-ecd825e63473 (working-tree, source: runtime)
contract      code
decision      FAIL
first failure tests.integrity: tests/test_discounts.py (removed 1 test(s))
checks        2 (1 pass, 1 fail, 0 escalate)
assurance gap 0.00 (0/0 criteria unknown)
cost          $0.000030 (verification $0.000030)
```

Same decision and same versions produce the same id. Edit one piece of evidence
and the id changes. The certificate records what each check declared it could not
see, the independence actually earned (computed from provenance, not claimed), the
assurance gap, and what the decision cost. A check that reads agent-written
testimony is downgraded; an unconfirmed failure becomes an escalation, not a pass.

## Check a repository

A contract is a small JSON file. It names the checks, their parameters, and what
to do when a check cannot decide:

```json
{
  "name": "code",
  "test_command": ["{python}", "-m", "pytest", "-q"],
  "verifiers": [
    {"name": "diff.syntax", "required": true, "params": {}},
    {"name": "tests.integrity", "required": true,
     "params": {"protected_prefixes": ["tests/"]}},
    {"name": "tests.harness_integrity", "required": true, "params": {}},
    {"name": "tests.pass", "required": true, "params": {}}
  ]
}
```

```bash
assaystone check --base origin/main                      # discover .assaystone/contract.json
assaystone check --base origin/main --certificate ./certs --sarif out.sarif
```

Exit codes are the interface: `0` pass, `1` fail, `2` escalate or unable to
check. A CI step can gate on them without parsing output.

```yaml
- uses: yellowsand1/assaystone@v0.35.0
  with:
    contract: .assaystone/contract.json
    base: origin/${{ github.base_ref }}
    certificate: certs
```

The Action posts annotations and a step summary, and uploads the certificate as an
artifact.

## What a passing test suite misses

| Defect | `tests.pass` | Assaystone |
|---|---|---|
| Agent deletes the failing test | ✅ passes | ❌ `tests.integrity` |
| Agent edits CI to skip the suite | ✅ passes | ❌ `diff.forbidden_paths` |
| Agent leaves a debug print | ✅ passes | ❌ `quality.no_debug_prints` |
| Agent weakens an assertion | ✅ passes | ❌ `tests.integrity` |
| Agent shadows the test runner | ✅ passes | ❌ `tests.harness_integrity` |
| Regression in another module | ❌ fails | ❌ `tests.pass` |

The first four are not hypothetical: they are labelled cases in
[failure_zoo](failure_zoo/README.md), and every built-in check is scored against
them on every release.

## Calibrated, not just evidenced

A verdict is only as good as the check behind it. Each check in a certificate
carries its measurement: recall on the defect classes it *claims*, false alarms
on clean cases, adversarial recall, and `n` — the sample size.

```
calibration   3/12 checks measured (gap 75%); min recall 100% on n=2; max false alarm 0%
```

A check with no measurement says `unmeasured`; it does not get a number. The
profile is generated from the public corpora and cited by digest, so a reviewer
can see what the instrument is worth, not only what it said.

Calibration can also be a gate. Set `"require_measured": true` in a contract and
a pass that rests only on unmeasured checks becomes an escalation. External
checks can bring their own profile with `--reliability profile.json`; the
certificate cites the profile's source and digest.

```bash
assaystone prove --write-reliability profile.json
```

The current table, including the checks that are still unmeasured, is
[docs/reliability.md](docs/reliability.md). `prove --gaps` turns the table into a
work list: the checks that decide most often and have no measurement.

```bash
assaystone prove --gaps --certificates ./certs
```

## Prove the checks

A verifier you have never challenged is a liability. One command measures both
questions that a pass rate hides:

```
$ assaystone prove
[recall] a known defect is caught
Failure Zoo: 13 cases (9 defective, 4 clean)
case-level: caught=9/9 escaped=0 false_alarms=0 recall=100%

[resistance] an agent that knows the contract still has to work
Goodhart suite: 17 cases (13 defective, 4 control)
resistance=85% caught=11 escalated=0 escaped=2 false_alarms=0
```

Recall asks whether a check catches a defect you injected. Resistance asks
whether an agent that has read the contract can pass without doing the work.
A contract can score 100% recall and still be trivially gameable; `prove`
reports both, and the families where the leaks are.

A reproducible run on a real repository — Flask, three changes, 68–98 ms per
check — is in [docs/field-note-flask.md](docs/field-note-flask.md). It states
what the sample does and does not support.

## Audit your own sessions

The cold start is an audit, not a framework. Point it at the newest local
Claude Code or Codex transcript; nothing leaves the machine:

```bash
assaystone audit --latest claude-code
assaystone audit --latest codex --write-contract .assaystone/contract.json
```

It reconstructs what the agent changed, runs a default rule set, and writes the
first contract from what it found. Open the findings, keep the rules that matter,
delete the rest.

## Install

```bash
uvx assaystone --version        # no install, throwaway environment
pip install assaystone==0.35.0  # the published release
```

Python 3.10+.

macOS note: the system `python3` is often 3.9. If `pip install` cannot find a
distribution, use `uvx` above or install Python 3.12.

## Integrations

- **GitHub Action**: gate a PR and upload the certificate (above).
- **pytest**: `pytest --assaystone` runs the contract after the suite.
- **Claude Code hooks**: a pre-tool policy gate, a post-tool syntax/secret
  check, a Stop contract gate with a certificate, and a Stop audit; each in
  `warn` or `block` mode.
- **Adapters**: Claude Agent SDK, OpenAI Agents SDK, LangGraph messages, and
  LangSmith / Langfuse / OpenTelemetry exports.
- **Custom checks**: a check declares `claim`, `catches`, `blind_spots`, `trusts`,
  `independence`, `cost_usd`, and returns `pass | fail | None`.

Details: [docs/integrations.md](docs/integrations.md),
[docs/verifiers.md](docs/verifiers.md), [docs/plugin.md](docs/plugin.md).

## How it works

```
episode  →  contract  →  checks  →  evidence  →  decision  →  certificate
```

- **Episode**: a working tree, a recorded trace, or a runtime action.
- **Contract**: obligations a human can review, each bound to defect tags.
- **Checks**: deterministic first, ordered by declared cost; a crash fails closed.
- **Decision**: `pass`, `fail`, or `escalate`; a low-independence failure cannot
  decide alone.
- **Certificate**: hash-addressed, provenance-bound, re-checkable offline.

Full design and invariants: [ARCHITECTURE.md](ARCHITECTURE.md).

## Design principles

1. **Evidence over scores.** A verdict carries pointers a third party can re-open.
2. **Three values, never two.** `pass`, `fail`, `escalate`.
3. **Cascade; judges never decide alone.** The default path is offline and key-free.
4. **Independence is provenance.** Agent-written testimony does not count as evidence.
5. **Verify the verifier.** No check ships without a clean case, a defective case, a
   declared blind spot, and a measured cost.

The direction, the ten laws, the non-goals, and the kill criteria are in
[GOALS.md](GOALS.md). The current bet is in [ROADMAP.md](ROADMAP.md).

## Status

`v0.35.0` — alpha. The kernel is stable; the surface is deliberately small:
`audit`, `check`, `certificate`, `prove`, `hook`. Everything else lives under
`assaystone lab` and is frozen — no new features, deletion allowed. Old top-level
names still resolve as aliases so existing CI does not break.

Known limitations, stated rather than hidden:

- The default checks are for code in a git repository. Other domains are lab code.
- `tests.integrity` is path- and structure-based; it reports activity, not intent.
- The failure corpus is a floor, not a population estimate. `prove` reports
  sample size.
- Escalation is a first-class outcome, not a bug. If a check cannot decide, it says so.

## Contributing

Read [GOALS.md](GOALS.md) and [ARCHITECTURE.md](ARCHITECTURE.md) first. A change
answers five questions:

1. Does it increase evidence per decision, or decrease the cost of a decision?
2. Can a third party re-check the output without re-running the agent?
3. Does it work offline, with no key, on the default path?
4. Does it reduce time-to-first-verdict?
5. Is it a new surface? If so, who asked for it?

Then run:

```bash
make test && make pytest && make lint && make demo-audit
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Name

An assay is a test that determines what a substance actually contains. The stone
is the touchstone: it does not declare the answer, it leaves a mark that someone
else can check. That is the whole idea.

## License

Apache-2.0. See [LICENSE](LICENSE).
