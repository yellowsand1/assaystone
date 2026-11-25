"""Acceptance criteria are the domain-neutral layer above verifiers."""

import unittest
from pathlib import Path

from assaystone.contract import Contract
from assaystone.coverage import analyze_coverage
from assaystone.protocol import check_contract
from assaystone.reportcard import run_report_card

REPO = Path(__file__).resolve().parent.parent
HARDENED = REPO / "examples" / "code_agent" / "contracts" / "hardened.json"


def contract_with(criteria, verifiers=None):
    return Contract.from_dict(
        {
            "name": "criteria",
            "verifiers": verifiers or [{"name": "tests.integrity"}],
            "criteria": criteria,
        }
    )


class CriteriaTest(unittest.TestCase):
    def test_criteria_derive_required_defects(self):
        contract = contract_with(
            [
                {
                    "id": "no-tamper",
                    "kind": "invariant",
                    "statement": "No protected test file changes.",
                    "defect": "test-tampering",
                    "verifiers": ["tests.integrity"],
                }
            ]
        )
        self.assertEqual(contract.required_defects, ["test-tampering"])
        self.assertEqual(contract.criteria[0].id, "no-tamper")

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            contract_with(
                [
                    {
                        "id": "x",
                        "kind": "vibes",
                        "statement": "s",
                        "defect": "d",
                    }
                ]
            )

    def test_missing_statement_is_rejected(self):
        with self.assertRaises(ValueError):
            contract_with(
                [{"id": "x", "kind": "invariant", "defect": "d"}]
            )

    def test_duplicate_criterion_ids_are_a_violation(self):
        contract = contract_with(
            [
                {
                    "id": "same",
                    "kind": "invariant",
                    "statement": "a",
                    "defect": "test-tampering",
                },
                {
                    "id": "same",
                    "kind": "postcondition",
                    "statement": "b",
                    "defect": "test-tampering",
                },
            ]
        )
        violations = check_contract(contract).violations
        self.assertTrue(
            any("duplicate criterion id" in item for item in violations)
        )

    def test_criterion_verifier_must_be_in_the_contract(self):
        contract = contract_with(
            [
                {
                    "id": "x",
                    "kind": "invariant",
                    "statement": "s",
                    "defect": "test-tampering",
                    "verifiers": ["tests.pass"],
                }
            ],
            verifiers=[{"name": "tests.integrity"}],
        )
        violations = check_contract(contract).violations
        self.assertTrue(
            any(
                "is not in the contract's verifiers" in item
                for item in violations
            )
        )

    def test_hardened_contract_has_no_assurance_gap(self):
        contract = Contract.load(HARDENED)
        report = analyze_coverage(contract)
        self.assertEqual(len(report.criteria), 9)
        self.assertEqual(report.assurance_gap, [])
        self.assertTrue(all(row["independent"] for row in report.criteria))

    def test_criterion_with_no_verifier_is_an_assurance_gap(self):
        contract = contract_with(
            [
                {
                    "id": "open",
                    "kind": "postcondition",
                    "statement": "The report cites a source.",
                    "defect": "uncited-claim",
                }
            ],
            verifiers=[{"name": "tests.pass"}],
        )
        report = analyze_coverage(contract)
        self.assertEqual(report.assurance_gap, ["open"])
        self.assertEqual(report.criteria[0]["covered_by"], [])
        self.assertEqual(report.declared, ["uncited-claim"])

    def test_report_card_shows_criteria_and_the_gap(self):
        card = run_report_card(Contract.load(HARDENED))
        text = card.to_markdown()
        self.assertIn("### Acceptance criteria", text)
        self.assertIn("Assurance gap", text)
        self.assertIn("`no-harness-hijack`", text)


if __name__ == "__main__":
    unittest.main()
