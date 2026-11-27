"""Run the whole acceptance loop and print a reproducible transcript.

This is the artefact a reader can execute. It builds a small service, has it
inspected, then walks a change from "the agent says it is done" to a signed
decision — including the case where the gate refuses.

Output is normalised (timestamps and absolute paths) so `docs/trial.md` can be
diffed against it in CI. Nothing here needs a network, a key, or a real
deployment.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
OWNER_KEY = "trial-owner-key"
RECEIPT_KEY = "trial-receipt-key"

APP = '''"""Quote calculation."""


def fee_cents(amount_cents: int, region: str) -> int:
    if region == "us":
        return amount_cents * 290 // 10000
    return amount_cents * 250 // 10000
'''

TEST = '''import unittest

from app import fee_cents


class FeeTest(unittest.TestCase):
    def test_us(self):
        self.assertEqual(fee_cents(4000, "us"), 116)

    def test_elsewhere(self):
        self.assertEqual(fee_cents(4000, "eu"), 100)
'''

UNCOVERED = '''

def surcharge_cents(amount_cents: int, tier: str) -> int:
    if tier == "gold":
        return amount_cents // 100
    return 0
'''

COVERING_TEST = '''

class SurchargeTest(unittest.TestCase):
    def test_gold(self):
        from app import surcharge_cents
        self.assertEqual(surcharge_cents(10000, "gold"), 100)

    def test_other_tier(self):
        from app import surcharge_cents
        self.assertEqual(surcharge_cents(10000, "bronze"), 0)
'''


def run(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    env["ASSAYSTONE_OWNER_KEY"] = OWNER_KEY
    env["ASSAYSTONE_RECEIPT_KEY"] = RECEIPT_KEY
    env.update({"GIT_AUTHOR_NAME": "trial", "GIT_COMMITTER_NAME": "trial",
                "GIT_AUTHOR_EMAIL": "trial@example.invalid",
                "GIT_COMMITTER_EMAIL": "trial@example.invalid",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
    proc = subprocess.run(
        [sys.executable, "-m", "assaystone.cli", *args],
        cwd=cwd, capture_output=True, text=True, env=env,
    )
    if check and proc.returncode != 0:
        raise SystemExit(
            f"command failed: {' '.join(args)}\n{proc.stdout}{proc.stderr}"
        )
    return proc


def git(cwd: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "trial", "GIT_COMMITTER_NAME": "trial",
                "GIT_AUTHOR_EMAIL": "trial@example.invalid",
                "GIT_COMMITTER_EMAIL": "trial@example.invalid",
                "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, env=env)


def build(root: Path) -> None:
    (root / "app.py").write_text(APP, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text(TEST, encoding="utf-8")
    (root / "db" / "migration").mkdir(parents=True)
    (root / "db" / "migration" / "V1__init.sql").write_text(
        "-- up\ncreate table quote (id int);\n-- down\ndrop table quote;\n",
        encoding="utf-8",
    )
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo test\n",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(
        ".assaystone/\n__pycache__/\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "quote-service"\nversion = "0.1.0"\n'
        'dependencies = ["requests>=2"]\n',
        encoding="utf-8",
    )
    git(root, "init", "-q", "-b", "feature/trial")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "baseline")


def normalise(text: str, root: Path) -> str:
    text = TIME.sub("<time>", text)
    text = re.sub(r"sha256:[0-9a-f]{64}", "<sha256>", text)
    text = re.sub(r"sha256:[0-9a-f]{16}\.\.\.", "<sha256>...", text)
    text = re.sub(r"hmac-sha256:[0-9a-f]+", "<signature>", text)
    text = re.sub(r"\b[0-9a-f]{12}\b", "<sha>", text)
    text = text.replace(str(root), ".")
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def say(lines: list[str], title: str) -> None:
    lines.append("")
    lines.append(f"== {title}")


MARKDOWN = """# A trial you can run

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
"""


def main() -> int:
    out: list[str] = []
    markdown = "--markdown" in sys.argv[1:]
    try:
        code = _run(out)
    finally:
        body = "\n".join(out).lstrip()
        if markdown:
            print(MARKDOWN + body + "\n```", file=sys.stdout)
        else:
            print(body, file=sys.stdout)
    return code


def _run(out: list[str]) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "quote-service"
        root.mkdir()
        build(root)

        say(out, "1. the repository proposes the checks it implies")
        proc = run(root, "capability", "init", "--root", ".", "--owner",
                   "platform-team", "--ci", "--hook")
        out.append(normalise(proc.stdout, root))

        say(out, "2. the draft is valid, and every stage permits nothing yet")
        proc = run(root, "capability", "validate", "--manifest",
                   ".assaystone/capability.json", "--strict")
        out.append(normalise(proc.stdout, root))
        draft = json.loads((root / ".assaystone" / "capability.json").read_text())
        out.append(json.dumps(draft["policies"]["production"], indent=2))

        say(out, "3. the acceptance criteria, handed to the agent")
        proc = run(root, "capability", "brief", "--manifest",
                   ".assaystone/capability.json", "--stage", "shadow")
        brief = normalise(proc.stdout, root).splitlines()
        out.extend(brief[:8])
        out.append("  ...")

        say(out, "4. the agent adds behaviour and no test")
        (root / "app.py").write_text(APP + UNCOVERED, encoding="utf-8")
        proc = run(root, "gate", "--manifest", ".assaystone/capability.json",
                   "--stage", "shadow", "--root", ".", "--json", check=False)
        payload = json.loads(proc.stdout)
        out.append(f"outcome: {payload['outcome']}")
        for item in payload["results"]:
            reason = (item["reasons"] or [""])[0][:200]
            out.append(f"  {item['oracle']:<16} {item['outcome']:<9} {reason}")
        out.append(f"exit: {proc.returncode}")

        say(out, "5. the agent adds the test")
        (root / "tests" / "test_app.py").write_text(
            TEST + COVERING_TEST, encoding="utf-8"
        )
        proc = run(root, "gate", "--manifest", ".assaystone/capability.json",
                   "--stage", "shadow", "--root", ".",
                   "--audit", ".assaystone/trail.jsonl",
                   "--receipt", ".assaystone/receipt.json", "--actor", "agent",
                   check=False)
        out.append(normalise(proc.stdout, root))
        out.append(f"exit: {proc.returncode}")

        say(out, "6. the trail verifies and the receipt binds the decision")
        proc = run(root, "trail", "verify", ".assaystone/trail.jsonl")
        out.append(normalise(proc.stdout, root))
        proc = run(root, "receipt", "verify", ".assaystone/receipt.json",
                   "--commit", "HEAD", "--outcome", "pass")
        out.append(normalise(proc.stdout, root))
        git(root, "add", "-A")
        git(root, "commit", "-qm", "add surcharge with a test")

        out.append(
            "note: the gate ran on the working tree and the commit came after, "
            "so the card marks\n      the decision stale against the new "
            "commit. That is the rule working, not a defect:\n      a decision "
            "covers the code it saw."
        )
        say(out, "7. what blocks the next stage")
        proc = run(root, "capability", "next", "--manifest",
                   ".assaystone/capability.json",
                   "--trail", ".assaystone/trail.jsonl", "--stage", "canary")
        out.append(normalise(proc.stdout, root))

        say(out, "7b. one command later, the stage is declared")
        proc = run(root, "capability", "next", "--manifest",
                   ".assaystone/capability.json", "--stage", "canary",
                   "--apply")
        out.append(normalise(proc.stdout, root))
        proc = run(root, "capability", "next", "--manifest",
                   ".assaystone/capability.json", "--stage", "canary")
        out.append(normalise(proc.stdout, root))
        proc = run(root, "capability", "validate", "--manifest",
                   ".assaystone/capability.json")
        out.append(normalise(proc.stdout, root))

        say(out, "8. one table across repositories")
        proc = run(root, "capability", "list", "--root", ".")
        out.append(normalise(proc.stdout, root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
