"""A verifier implemented outside the package enters through the same ABI."""

import unittest
from pathlib import Path

from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Artifact, Trace
from assaystone.protocol import check_manifest
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY
from examples.third_party_pack import todo_guard  # noqa: F401 - registers the pack

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "examples" / "code_agent" / "baseline"
SOURCE = (BASELINE / "pricing" / "discounts.py").read_text(encoding="utf-8")


class ThirdPartyPackTest(unittest.TestCase):
    def contract(self):
        return Contract(
            name="third-party",
            verifiers=[VerifierSpec("example.no_new_todo")],
            required_defects=["new-todo"],
        )

    def test_pack_registers_and_conforms(self):
        self.assertIn("example.no_new_todo", REGISTRY)
        cls = REGISTRY["example.no_new_todo"]
        self.assertTrue(cls.claim)
        self.assertEqual(cls.catches, ("new-todo",))
        self.assertTrue(cls.blind_spots)

    def test_manifest_conforms_to_the_protocol(self):
        cls = REGISTRY["example.no_new_todo"]
        manifest = {
            "name": cls.name,
            "version": "1",
            "layer": cls.layer,
            "independence": cls.independence,
            "claim": cls.claim,
            "catches": list(cls.catches),
            "blind_spots": list(cls.blind_spots),
            "cost": {"usd": cls.cost_usd},
        }
        self.assertEqual(check_manifest(manifest), [])

    def test_new_todo_fails(self):
        trace = Trace(
            id="todo",
            task="",
            artifacts=[
                Artifact(
                    "pricing/discounts.py",
                    SOURCE + "\n# TODO: remove this later\n",
                    "modified",
                )
            ],
        )
        result = run_contract(self.contract(), trace, BASELINE)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("example.no_new_todo", result.first_failure)

    def test_clean_change_passes(self):
        trace = Trace(
            id="clean",
            task="",
            artifacts=[
                Artifact("pricing/discounts.py", SOURCE + "\n# refactor only\n", "modified")
            ],
        )
        result = run_contract(self.contract(), trace, BASELINE)
        self.assertEqual(result.verdict, "pass", result.first_failure)


class ManifestCheckTest(unittest.TestCase):
    def test_missing_fields_are_reported(self):
        violations = check_manifest({"name": "x"})
        self.assertTrue(any("missing field" in item for item in violations))

    def test_bad_enums_are_reported(self):
        violations = check_manifest(
            {
                "name": "x",
                "version": "1",
                "layer": "L9",
                "independence": "sometimes",
                "claim": "c",
                "catches": ["a"],
                "blind_spots": ["b"],
                "cost": {"usd": 0.0},
            }
        )
        self.assertTrue(any("layer" in item for item in violations))
        self.assertTrue(any("independence" in item for item in violations))

    def test_empty_blind_spots_are_reported(self):
        violations = check_manifest(
            {
                "name": "x",
                "version": "1",
                "layer": "L1",
                "independence": "high",
                "claim": "c",
                "catches": ["a"],
                "blind_spots": [],
                "cost": {"usd": 0.0},
            }
        )
        self.assertIn("blind_spots must be a non-empty array", violations)


if __name__ == "__main__":
    unittest.main()
