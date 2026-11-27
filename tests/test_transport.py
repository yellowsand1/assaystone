"""The certificate says which view of the execution the verifier saw."""

import unittest
from pathlib import Path

from assaystone.audit import _claude_view
from assaystone.certificate import build_certificate
from assaystone.contract import Contract, VerifierSpec
from assaystone.model import load_traces
from assaystone.runner import run_contract

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples" / "code_agent"


class TransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = EXAMPLES / "baseline"
        cls.trace = {t.id: t for t in load_traces(EXAMPLES / "traces")}["t01-correct"]
        cls.contract = Contract(
            name="transport", verifiers=[VerifierSpec("tests.integrity")]
        )

    def certificate(self, view):
        import copy

        trace = copy.deepcopy(self.trace)
        trace.view = view
        result = run_contract(self.contract, trace, self.baseline)
        return build_certificate(
            result, self.contract, trace, issued_at="2026-01-01T00:00:00Z"
        )

    def test_a_native_view_is_low_risk(self):
        document = self.certificate({"kind": "native", "adapter": "git-worktree"})
        transport = document["assurance"]["transport"]
        self.assertEqual(transport["view"], "native")
        self.assertEqual(transport["risk"], "low")
        self.assertNotIn("reason", transport)
        self.assertEqual(document["subject"]["view"]["kind"], "native")

    def test_a_compacted_view_is_high_risk(self):
        document = self.certificate(
            {"kind": "compacted", "adapter": "claude-code", "truncated": True}
        )
        transport = document["assurance"]["transport"]
        self.assertEqual(transport["risk"], "high")
        self.assertTrue(transport["truncated"])
        self.assertIn("may not transport", transport["reason"])

    def test_an_unknown_view_is_medium_risk(self):
        document = self.certificate({})
        self.assertEqual(document["assurance"]["transport"]["risk"], "medium")

    def test_require_native_view_escalates_a_compacted_pass(self):
        import copy

        contract = Contract(
            name="strict",
            verifiers=[VerifierSpec("tests.integrity")],
            require_native_view=True,
        )
        compacted = copy.deepcopy(self.trace)
        compacted.view = {"kind": "compacted", "truncated": True}
        result = run_contract(contract, compacted, self.baseline)
        self.assertEqual(result.verdict, "escalate")
        self.assertIn("transport required", result.first_failure or "")

        native = copy.deepcopy(self.trace)
        native.view = {"kind": "native"}
        self.assertEqual(
            run_contract(contract, native, self.baseline).verdict, "pass"
        )

    def test_claude_compaction_markers_are_detected(self):
        self.assertEqual(
            _claude_view([{"type": "user"}, {"isCompactSummary": True}])["kind"],
            "compacted",
        )
        self.assertEqual(
            _claude_view([{"type": "summary"}])["kind"], "compacted"
        )
        self.assertEqual(
            _claude_view([{"type": "user"}])["kind"], "native"
        )


if __name__ == "__main__":
    unittest.main()
