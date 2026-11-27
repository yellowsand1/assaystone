import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assaystone.audit import audit_traces, build_audit_contract, load_audit_traces
from assaystone.cli import _write_github_outputs
from assaystone.contract import Contract
from assaystone.model import RunResult, Trace, Verdict, load_traces
from assaystone.reports import (
    write_audit_junit,
    write_audit_sarif,
    write_junit,
    write_sarif,
)
from assaystone.runner import run_contract

REPO = Path(__file__).resolve().parent.parent
CODE = REPO / "examples" / "code_agent"
AUDIT = REPO / "examples" / "audit"


class VerifyReportsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(CODE / "contracts" / "hardened.json")
        cls.traces = load_traces(CODE / "traces")
        cls.results = [
            run_contract(cls.contract, trace, CODE / "baseline") for trace in cls.traces
        ]

    def test_sarif(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sarif(Path(tmp) / "out.sarif", self.traces, self.results)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], "2.1.0")
            results = data["runs"][0]["results"]
            integrity = [result for result in results if result["ruleId"] == "tests.integrity"]
            self.assertTrue(integrity)
            self.assertEqual(
                integrity[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
                "tests/test_discounts.py",
            )
            self.assertTrue(any(result["level"] == "error" for result in results))

    def test_junit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_junit(Path(tmp) / "out.xml", self.results)
            text = path.read_text(encoding="utf-8")
            self.assertIn("<testsuite", text)
            self.assertIn("t03-test-tampering", text)
            self.assertIn("<failure", text)

    def test_github_action_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outputs.txt"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(path)}):
                _write_github_outputs(self.results)
            values = path.read_text(encoding="utf-8")
            self.assertIn("verdict=fail\n", values)
            self.assertIn(f"traces={len(self.results)}\n", values)
            self.assertNotIn("findings=0\n", values)


class AuditReportsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traces = load_audit_traces(
            AUDIT / "transcript.jsonl", baseline=AUDIT / "baseline"
        )
        cls.report = audit_traces(
            build_audit_contract(AUDIT / "baseline"),
            cls.traces,
            AUDIT / "baseline",
        )

    def test_audit_sarif(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_audit_sarif(Path(tmp) / "audit.sarif", self.report)
            data = json.loads(path.read_text(encoding="utf-8"))
            results = data["runs"][0]["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["ruleId"], "tests.integrity")
            self.assertEqual(
                results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
                "tests/test_discounts.py",
            )

    def test_audit_junit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_audit_junit(Path(tmp) / "audit.xml", self.report)
            text = path.read_text(encoding="utf-8")
            self.assertIn("tests.integrity", text)
            self.assertIn("<failure", text)


class UnconfirmedReportsTest(unittest.TestCase):
    """An unconfirmed low-independence failure must be visible to CI."""

    def result(self):
        return RunResult(
            trace_id="t-1",
            contract="contract",
            verdict="escalate",
            verdicts=[
                Verdict(
                    verifier="test.low",
                    layer="L1",
                    ok=False,
                    reasons=["low-independence failure"],
                    independence="low",
                )
            ],
            first_failure="unconfirmed low-independence failure: test.low",
            unconfirmed=["test.low: low-independence failure"],
        )

    def test_sarif_surfaces_unconfirmed_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sarif(Path(tmp) / "out.sarif", [Trace(id="t-1", task="")], [self.result()])
            data = json.loads(path.read_text(encoding="utf-8"))
            results = data["runs"][0]["results"]
            unconfirmed = [
                item for item in results
                if item["ruleId"] == "assaystone.unconfirmed"
            ]
            self.assertEqual(len(unconfirmed), 1)
            self.assertEqual(unconfirmed[0]["level"], "warning")
            self.assertIn("low-independence", unconfirmed[0]["message"]["text"])

    def test_junit_includes_unconfirmed_in_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_junit(Path(tmp) / "out.xml", [self.result()])
            text = path.read_text(encoding="utf-8")
            self.assertIn("unconfirmed:", text)
            self.assertIn("low-independence failure", text)


if __name__ == "__main__":
    unittest.main()
