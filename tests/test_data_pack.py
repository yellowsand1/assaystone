"""The data pack proves the acceptance language is not code-shaped."""

import unittest
from pathlib import Path

from assaystone.contract import Contract
from assaystone.model import load_traces
from assaystone.protocol import check_contract
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "assaystone" / "demo_data" / "data_agent"


class DataPackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(DATA / "contracts" / "hardened.json")
        cls.traces = {trace.id: trace for trace in load_traces(DATA / "traces")}
        cls.baseline = DATA / "baseline"

    def test_contract_conforms(self):
        self.assertTrue(check_contract(self.contract).ok)
        self.assertEqual(self.contract.domain, "data")
        self.assertEqual(len(self.contract.criteria), 3)

    def test_data_verifiers_declare_the_abi(self):
        for name in ("data.schema", "data.totals", "data.no_pii"):
            cls = REGISTRY[name]
            self.assertTrue(cls.claim, name)
            self.assertTrue(cls.catches, name)
            self.assertTrue(cls.blind_spots, name)
            self.assertTrue(cls.trusts, name)

    def test_totals_mismatch_fails(self):
        result = run_contract(
            self.contract, self.traces["d01-totals-mismatch"], self.baseline
        )
        self.assertEqual(result.verdict, "fail", result.first_failure)
        outcomes = {item.id: item.outcome for item in result.criteria}
        self.assertEqual(outcomes["totals-conserved"], "fail")
        # fail_fast stops before the later PII check; an unevaluated criterion
        # is reported as escalate, not pass.
        self.assertIn(outcomes["no-pii"], {"pass", "escalate"})

    def test_pii_leak_fails(self):
        result = run_contract(
            self.contract, self.traces["d02-pii-leak"], self.baseline
        )
        self.assertEqual(result.verdict, "fail", result.first_failure)
        outcomes = {item.id: item.outcome for item in result.criteria}
        self.assertEqual(outcomes["no-pii"], "fail")
        self.assertEqual(outcomes["totals-conserved"], "pass")

    def test_clean_report_passes(self):
        result = run_contract(
            self.contract, self.traces["d03-clean"], self.baseline
        )
        self.assertEqual(result.verdict, "pass", result.first_failure)
        self.assertTrue(all(item.outcome == "pass" for item in result.criteria))


if __name__ == "__main__":
    unittest.main()
