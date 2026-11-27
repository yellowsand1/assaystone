"""The research pack proves the evidence criteria are domain-neutral."""

import unittest
from pathlib import Path

from assaystone.contract import Contract
from assaystone.model import load_traces
from assaystone.protocol import check_contract
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY

REPO = Path(__file__).resolve().parent.parent
RESEARCH = REPO / "assaystone" / "demo_data" / "research_agent"


class ResearchPackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(RESEARCH / "contracts" / "hardened.json")
        cls.traces = {trace.id: trace for trace in load_traces(RESEARCH / "traces")}
        cls.baseline = RESEARCH / "baseline"

    def test_contract_conforms(self):
        self.assertTrue(check_contract(self.contract).ok)
        self.assertEqual(self.contract.domain, "research")
        self.assertEqual(len(self.contract.criteria), 3)

    def test_research_verifiers_declare_the_abi(self):
        for name in (
            "research.citations",
            "research.sources_exist",
            "research.quotes_verbatim",
        ):
            cls = REGISTRY[name]
            self.assertTrue(cls.claim, name)
            self.assertTrue(cls.catches, name)
            self.assertTrue(cls.blind_spots, name)
            self.assertTrue(cls.trusts, name)

    def test_uncited_claim_fails(self):
        result = run_contract(
            self.contract, self.traces["r01-uncited-claim"], self.baseline
        )
        self.assertEqual(result.verdict, "fail", result.first_failure)
        outcomes = {item.id: item.outcome for item in result.criteria}
        self.assertEqual(outcomes["claims-cited"], "fail")

    def test_fabricated_quote_fails(self):
        result = run_contract(
            self.contract, self.traces["r02-fabricated-quote"], self.baseline
        )
        self.assertEqual(result.verdict, "fail", result.first_failure)
        outcomes = {item.id: item.outcome for item in result.criteria}
        self.assertEqual(outcomes["quotes-verbatim"], "fail")

    def test_clean_report_passes(self):
        result = run_contract(
            self.contract, self.traces["r03-clean"], self.baseline
        )
        self.assertEqual(result.verdict, "pass", result.first_failure)
        self.assertTrue(all(item.outcome == "pass" for item in result.criteria))


if __name__ == "__main__":
    unittest.main()
