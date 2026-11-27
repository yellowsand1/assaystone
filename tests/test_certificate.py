"""The certificate is the artifact: it must be stable, verifiable, and complete."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.certificate import (
    SCHEMA,
    build_certificate,
    content_id,
    verify_certificate,
)
from assaystone.contract import Contract, Criterion, VerifierSpec
from assaystone.model import load_traces
from assaystone.runner import run_contract

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples" / "code_agent"


class CertificateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = EXAMPLES / "baseline"
        cls.contract = Contract.load(EXAMPLES / "contracts" / "hardened.json")
        cls.traces = {trace.id: trace for trace in load_traces(EXAMPLES / "traces")}

    def certificate(self, trace_id: str, at: str = "2026-01-01T00:00:00Z"):
        trace = self.traces[trace_id]
        result = run_contract(self.contract, trace, self.baseline)
        return build_certificate(result, self.contract, trace, issued_at=at), result

    def test_schema_and_required_sections(self):
        document, _ = self.certificate("t01-correct")
        self.assertEqual(document["schema"], SCHEMA)
        self.assertIn("id", document)
        self.assertTrue(document["id"].startswith("sha256:"))
        for key in ("subject", "contract", "decision", "checks", "assurance", "cost"):
            self.assertIn(key, document)
        self.assertEqual(document["decision"]["verdict"], "pass")

    def test_same_decision_has_the_same_id(self):
        # Use checks whose evidence is deterministic; a test runner's timing is
        # excluded from the id, but this keeps the test itself honest.
        contract = Contract(
            name="deterministic",
            verifiers=[VerifierSpec("diff.syntax"), VerifierSpec("tests.integrity")],
        )
        trace = self.traces["t01-correct"]
        first = build_certificate(
            run_contract(contract, trace, self.baseline),
            contract,
            trace,
            issued_at="2026-01-01T00:00:00Z",
        )
        second = build_certificate(
            run_contract(contract, trace, self.baseline),
            contract,
            trace,
            issued_at="2030-12-31T23:59:59Z",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["issued_at"], second["issued_at"])

    def test_different_evidence_has_a_different_id(self):
        document, _ = self.certificate("t01-correct")
        edited = json.loads(json.dumps(document))
        edited["checks"][0]["evidence"].append("an extra observation")
        self.assertNotEqual(content_id(edited), document["id"])
        self.assertFalse(verify_certificate(edited)["ok"])

    def test_failure_is_preserved(self):
        document, result = self.certificate("t03-test-tampering")
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(document["decision"]["verdict"], "fail")
        failing = [check for check in document["checks"] if check["outcome"] == "fail"]
        self.assertTrue(failing)
        self.assertIn("tests.integrity", {check["id"] for check in failing})
        self.assertTrue(all(check["reasons"] for check in failing))

    def test_escalation_and_independence_are_preserved(self):
        trace = self.traces["t02-regression"]
        contract = Contract(
            name="claims-only", verifiers=[VerifierSpec("evidence.claims")]
        )
        result = run_contract(contract, trace, self.baseline)
        document = build_certificate(result, contract, trace)
        self.assertEqual(result.verdict, "escalate")
        self.assertEqual(document["decision"]["verdict"], "escalate")
        self.assertTrue(document["decision"]["unconfirmed"])
        downgraded = [
            check
            for check in document["checks"]
            if check["independence"] == "low"
            and check["declared_independence"] != "low"
        ]
        self.assertTrue(downgraded, "a testimony-reading check must be downgraded")

    def test_checks_carry_their_declaration(self):
        document, _ = self.certificate("t01-correct")
        for check in document["checks"]:
            declaration = check["declaration"]
            self.assertTrue(declaration["claim"], check["id"])
            self.assertIsInstance(declaration["blind_spots"], list)
            self.assertTrue(check["params_digest"].startswith("sha256:"))

    def test_artifacts_are_content_addressed_not_embedded(self):
        document, _ = self.certificate("t01-correct")
        for artifact in document["subject"]["artifacts"]:
            self.assertTrue(artifact["content"].startswith("sha256:"))
            self.assertNotIn("content_text", artifact)

    def test_open_obligations_are_reported(self):
        contract = Contract(
            name="with-criteria",
            verifiers=[VerifierSpec("diff.syntax")],
            criteria=[
                Criterion(
                    id="c1",
                    kind="invariant",
                    statement="the diff parses",
                    defect="syntax",
                    verifiers=["diff.syntax"],
                ),
                Criterion(
                    id="c2",
                    kind="evidence",
                    statement="the agent cites the source of the rule",
                    defect="false-claim",
                ),
            ],
        )
        trace = self.traces["t01-correct"]
        result = run_contract(contract, trace, self.baseline)
        document = build_certificate(result, contract, trace)
        self.assertEqual(document["assurance"]["open_obligations"], ["c2"])
        self.assertEqual(document["assurance"]["criteria_total"], 2)

    def test_uncovered_declared_defects_are_reported(self):
        contract = Contract(
            name="declares-more-than-it-checks",
            verifiers=[VerifierSpec("diff.syntax")],
            required_defects=["syntax-error", "pii-leak"],
        )
        trace = self.traces["t01-correct"]
        result = run_contract(contract, trace, self.baseline)
        document = build_certificate(result, contract, trace)
        self.assertEqual(document["assurance"]["declared_defects"], ["pii-leak", "syntax-error"])
        self.assertIn("syntax-error", document["assurance"]["covered_defects"])
        self.assertEqual(document["assurance"]["uncovered_defects"], ["pii-leak"])

    def test_runner_timing_is_not_evidence(self):
        from assaystone.verifiers import _stable_tail

        self.assertEqual(_stable_tail("Ran 3 tests in 0.004s\n\nOK"), "OK")
        self.assertEqual(_stable_tail("===== 2 passed in 0.12s ====="), "(no output)")

    def test_verify_accepts_a_fresh_certificate(self):
        document, _ = self.certificate("t01-correct")
        check = verify_certificate(document)
        self.assertTrue(check["ok"], check["problems"])
        self.assertEqual(check["id"], document["id"])

    def test_verify_rejects_a_tampered_verdict(self):
        document, _ = self.certificate("t03-test-tampering")
        document["decision"]["verdict"] = "pass"
        check = verify_certificate(document)
        self.assertFalse(check["ok"])
        self.assertTrue(any("content id mismatch" in item for item in check["problems"]))

    def test_verify_rejects_a_non_object(self):
        self.assertFalse(verify_certificate([])["ok"])


class CertificateCliTest(unittest.TestCase):
    def test_verify_writes_show_and_recheck(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "verify",
                        "--contract",
                        str(EXAMPLES / "contracts" / "hardened.json"),
                        "--trace",
                        str(EXAMPLES / "traces"),
                        "--baseline",
                        str(EXAMPLES / "baseline"),
                        "--certificate",
                        tmp,
                    ]
                )
            self.assertIn(code, (0, 1))  # the example set contains failing traces
            files = sorted(Path(tmp).glob("*.certificate.json"))
            self.assertEqual(len(files), len(list((EXAMPLES / "traces").glob("*.json"))))

            path = Path(tmp) / "t01-correct.certificate.json"
            self.assertTrue(path.exists())
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["decision"]["verdict"], "pass")

            with contextlib.redirect_stdout(out):
                code = cli.main(["certificate", "verify", str(path)])
            self.assertEqual(code, 0)
            self.assertIn("valid sha256:", out.getvalue())

            with contextlib.redirect_stdout(out):
                code = cli.main(["certificate", "show", str(path)])
            self.assertEqual(code, 0)
            self.assertIn("decision      PASS", out.getvalue())


if __name__ == "__main__":
    unittest.main()
