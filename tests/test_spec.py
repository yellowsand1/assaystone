"""A task spec compiles into obligations the certificate can report on."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.certificate import build_certificate
from assaystone.contract import Contract
from assaystone.model import load_traces
from assaystone.runner import run_contract
from assaystone.spec import (
    SCHEMA,
    SpecError,
    criteria_from_spec,
    load,
    validate,
)

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples" / "code_agent"


def spec(obligations, task="test task"):
    return {"schema": SCHEMA, "task": task, "obligations": obligations}


class SpecValidationTest(unittest.TestCase):
    def test_a_valid_spec_has_no_problems(self):
        data = spec(
            [
                {
                    "id": "one",
                    "statement": "One thing changed.",
                    "evidence": [{"kind": "path", "glob": "src/*.py"}],
                }
            ]
        )
        self.assertEqual(validate(data), [])

    def test_missing_evidence_and_duplicate_ids_are_rejected(self):
        problems = validate(
            spec(
                [
                    {"id": "one", "statement": "a", "evidence": []},
                    {"id": "one", "statement": "b", "evidence": [{"kind": "path"}]},
                ]
            )
        )
        self.assertTrue(any("evidence" in item for item in problems))
        self.assertTrue(any("duplicate" in item for item in problems))

    def test_load_rejects_a_bad_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(
                json.dumps(
                    spec(
                        [
                            {
                                "id": "one",
                                "statement": "a",
                                "evidence": [{"kind": "magic", "glob": "x"}],
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SpecError):
                load(path)


class SpecRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = EXAMPLES / "baseline"
        cls.trace = {t.id: t for t in load_traces(EXAMPLES / "traces")}["t01-correct"]

    def run_spec(self, obligations):
        data = spec(obligations)
        contract = Contract(
            name="spec", verifiers=[], criteria=criteria_from_spec(data)
        )
        return run_contract(contract, self.trace, self.baseline), data

    def test_each_rule_kind_is_decided_from_evidence(self):
        result, _ = self.run_spec(
            [
                {
                    "id": "source",
                    "statement": "The pricing module changed.",
                    "evidence": [{"kind": "path", "glob": "pricing/*.py"}],
                },
                {
                    "id": "tests",
                    "statement": "A test file exists.",
                    "evidence": [{"kind": "exists", "glob": "tests/*.py"}],
                },
                {
                    "id": "ci",
                    "statement": "CI is untouched.",
                    "evidence": [{"kind": "absent", "glob": ".github/*"}],
                },
                {
                    "id": "contains",
                    "statement": "The fix is in the file.",
                    "evidence": [
                        {"kind": "contains", "glob": "pricing/*.py", "text": "round"}
                    ],
                },
            ]
        )
        self.assertEqual(result.verdict, "pass", result.first_failure)
        outcomes = {item.id: item.outcome for item in result.criteria}
        self.assertEqual(set(outcomes.values()), {"pass"})
        self.assertTrue(all(item.source == "evidence" for item in result.criteria))

    def test_a_missing_obligation_fails_the_run(self):
        result, _ = self.run_spec(
            [
                {
                    "id": "migration",
                    "statement": "A migration was added.",
                    "evidence": [
                        {
                            "kind": "path",
                            "glob": "migrations/*.sql",
                            "change": "added",
                        }
                    ],
                }
            ]
        )
        self.assertEqual(result.verdict, "fail")
        self.assertIn("migration", result.first_failure or "")

    def test_the_certificate_reports_spec_coverage(self):
        result, data = self.run_spec(
            [
                {
                    "id": "source",
                    "statement": "The pricing module changed.",
                    "evidence": [{"kind": "path", "glob": "pricing/*.py"}],
                }
            ]
        )
        document = build_certificate(
            result,
            Contract(name="spec", verifiers=[], criteria=criteria_from_spec(data)),
            self.trace,
            issued_at="2026-01-01T00:00:00Z",
            spec={"task": "t", "digest": "sha256:spec"},
        )
        block = document["assurance"]["spec"]
        self.assertEqual(block["total"], 1)
        self.assertEqual(block["satisfied"], ["source"])
        self.assertEqual(block["coverage"], 1.0)
        self.assertEqual(document["contract"]["spec"]["digest"], "sha256:spec")


class SpecCliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "pricing").mkdir()
        (self.root / "tests").mkdir()
        (self.root / ".assaystone").mkdir()
        (self.root / "pricing" / "app.py").write_text(
            "def discount(total):\n    return round(total * 0.9, 2)\n", encoding="utf-8"
        )
        (self.root / "tests" / "test_app.py").write_text(
            "def test_x():\n    assert True\n", encoding="utf-8"
        )
        (self.root / ".assaystone" / "contract.json").write_text(
            json.dumps(
                {
                    "name": "c",
                    "verifiers": [
                        {
                            "name": "tests.integrity",
                            "params": {"protected_prefixes": ["tests/"]},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        git = ["git", "-C", str(self.root), "-c", "user.email=a@b", "-c", "user.name=a"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        (self.root / "pricing" / "app.py").write_text(
            "def discount(total):\n    return round(total * 0.91, 2)\n", encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def run_check(self, obligations):
        spec_path = self.root / ".assaystone" / "spec.json"
        spec_path.write_text(json.dumps(spec(obligations)), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "check",
                    "--repo",
                    str(self.root),
                    "--base",
                    "HEAD",
                    "--spec",
                    str(spec_path),
                    "--json",
                ]
            )
        return code, json.loads(out.getvalue())

    def test_check_compiles_the_spec_and_reports_it(self):
        code, document = self.run_check(
            [
                {
                    "id": "source",
                    "statement": "The pricing module changed.",
                    "evidence": [{"kind": "path", "glob": "pricing/*.py"}],
                },
                {
                    "id": "tests",
                    "statement": "A test file exists.",
                    "evidence": [{"kind": "exists", "glob": "tests/*.py"}],
                },
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(document["decision"]["verdict"], "pass")
        self.assertEqual(document["assurance"]["spec"]["total"], 2)
        self.assertEqual(document["assurance"]["spec"]["coverage"], 1.0)

    def test_a_violated_obligation_fails_the_check(self):
        code, document = self.run_check(
            [
                {
                    "id": "migration",
                    "statement": "A migration was added.",
                    "evidence": [
                        {"kind": "path", "glob": "migrations/*.sql", "change": "added"}
                    ],
                }
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(document["assurance"]["spec"]["violated"], ["migration"])


if __name__ == "__main__":
    unittest.main()
