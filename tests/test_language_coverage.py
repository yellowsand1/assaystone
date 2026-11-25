"""A changed source file in an unsupported language escalates, not passes."""

import unittest
from pathlib import Path

from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Artifact, Trace
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "examples" / "code_agent" / "baseline"


class LanguageCoverageTest(unittest.TestCase):
    def contract(self, **params) -> Contract:
        return Contract(
            name="language",
            verifiers=[
                VerifierSpec("diff.language_coverage", params=params or {})
            ],
            required_defects=["unverified-language"],
            max_verification_cost_usd=1.0,
        )

    def trace(self, path: str, content: str = "x\n") -> Trace:
        return Trace(
            id="lang", task="", artifacts=[Artifact(path, content, "modified")]
        )

    def test_java_change_escalates(self):
        result = run_contract(
            self.contract(), self.trace("src/App.java", "class App {}\n"), BASELINE
        )
        self.assertEqual(result.verdict, "escalate")
        self.assertIsNone(result.verdicts[0].ok)
        self.assertIn(".java", result.first_failure)

    def test_python_change_passes(self):
        result = run_contract(
            self.contract(), self.trace("src/app.py", "x = 1\n"), BASELINE
        )
        self.assertEqual(result.verdict, "pass", result.first_failure)

    def test_non_source_file_passes(self):
        result = run_contract(
            self.contract(), self.trace("README.md", "# readme\n"), BASELINE
        )
        self.assertEqual(result.verdict, "pass", result.first_failure)

    def test_declared_supported_language_passes(self):
        contract = self.contract(supported_suffixes=[".py", ".java"])
        result = run_contract(
            contract, self.trace("src/App.java", "class App {}\n"), BASELINE
        )
        self.assertEqual(result.verdict, "pass", result.first_failure)

    def test_verifier_declares_the_abi(self):
        cls = REGISTRY["diff.language_coverage"]
        self.assertTrue(cls.claim)
        self.assertTrue(cls.catches)
        self.assertTrue(cls.blind_spots)
        self.assertTrue(cls.trusts)


if __name__ == "__main__":
    unittest.main()
