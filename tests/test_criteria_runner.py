"""Criteria, not verifier lists, decide the verdict when a contract declares them."""

import tempfile
import unittest
from pathlib import Path

from assaystone.contract import Contract, Criterion, VerifierSpec
from assaystone.model import Trace
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY, Verifier


class _Pass(Verifier):
    name = "test.crit_pass"
    layer = "L1"
    cost_usd = 0.000001
    independence = "high"
    claim = "Passes on purpose."
    catches = ("d",)
    blind_spots = ("everything else",)

    def check(self, ctx, params):
        return True, [], []


class _Fail(Verifier):
    name = "test.crit_fail"
    layer = "L1"
    cost_usd = 0.000001
    independence = "high"
    claim = "Fails on purpose."
    catches = ("d",)
    blind_spots = ("everything else",)

    def check(self, ctx, params):
        return False, ["failed on purpose"], []


class _Escalate(Verifier):
    name = "test.crit_escalate"
    layer = "L1"
    cost_usd = 0.000001
    independence = "high"
    claim = "Cannot decide on purpose."
    catches = ("d",)
    blind_spots = ("everything else",)

    def check(self, ctx, params):
        return None, ["cannot decide"], []


class CriteriaRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.baseline = Path(cls._tmp.name)
        (cls.baseline / "note.txt").write_text("baseline\n", encoding="utf-8")
        cls.trace = Trace(id="t", task="criteria")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for cls in (_Pass, _Fail, _Escalate):
            REGISTRY[cls.name] = cls

    def tearDown(self):
        for name in ("test.crit_pass", "test.crit_fail", "test.crit_escalate"):
            REGISTRY.pop(name, None)

    def contract(
        self,
        verifier: str,
        *,
        defect: str = "d",
        severity: str = "critical",
        on_unknown: str = "escalate",
        bind: bool = True,
    ) -> Contract:
        return Contract(
            name="criteria",
            verifiers=[VerifierSpec(verifier)],
            required_defects=[defect],
            criteria=[
                Criterion(
                    id="c",
                    kind="invariant",
                    statement="the statement",
                    defect=defect,
                    verifiers=[verifier] if bind else [],
                    severity=severity,
                    on_unknown=on_unknown,
                )
            ],
        )

    def test_pass_criterion(self):
        result = run_contract(
            self.contract("test.crit_pass"), self.trace, self.baseline
        )
        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.criteria[0].outcome, "pass")

    def test_fail_criterion(self):
        result = run_contract(
            self.contract("test.crit_fail"), self.trace, self.baseline
        )
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.criteria[0].outcome, "fail")
        self.assertIn("failed on purpose", result.first_failure)

    def test_unknown_criterion_escalates(self):
        result = run_contract(
            self.contract("test.crit_escalate"), self.trace, self.baseline
        )
        self.assertEqual(result.verdict, "escalate")
        self.assertEqual(result.criteria[0].outcome, "escalate")

    def test_on_unknown_fail_turns_unknown_into_failure(self):
        result = run_contract(
            self.contract("test.crit_escalate", on_unknown="fail"),
            self.trace,
            self.baseline,
        )
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.criteria[0].outcome, "fail")
        self.assertIn("on_unknown=fail", result.criteria[0].reasons)

    def test_unbound_critical_criterion_escalates(self):
        # The verifier does not catch the criterion's defect, so the criterion
        # has no check: an assurance gap that gates the run.
        result = run_contract(
            self.contract("test.crit_pass", defect="uncovered", bind=False),
            self.trace,
            self.baseline,
        )
        self.assertEqual(result.verdict, "escalate")
        self.assertEqual(result.criteria[0].outcome, "escalate")
        self.assertIn("no bound verifier", result.criteria[0].reasons[0])

    def test_low_severity_gap_is_reported_but_does_not_gate(self):
        result = run_contract(
            self.contract(
                "test.crit_pass",
                defect="uncovered",
                severity="low",
                bind=False,
            ),
            self.trace,
            self.baseline,
        )
        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.criteria[0].outcome, "escalate")

    def test_auto_binding_by_defect_tag(self):
        result = run_contract(
            self.contract("test.crit_pass", bind=False),
            self.trace,
            self.baseline,
        )
        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.criteria[0].verifiers, ["test.crit_pass"])

    def test_result_json_includes_criteria(self):
        result = run_contract(
            self.contract("test.crit_fail"), self.trace, self.baseline
        )
        data = result.to_dict()
        self.assertEqual(data["criteria"][0]["id"], "c")
        self.assertEqual(data["criteria"][0]["outcome"], "fail")


if __name__ == "__main__":
    unittest.main()
