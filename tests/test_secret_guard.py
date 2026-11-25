"""A second outside-the-package verifier enters through the same ABI."""

import tempfile
import unittest
from pathlib import Path

from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Artifact, Trace
from assaystone.protocol import check_manifest
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY
from examples.third_party_pack import secret_guard  # noqa: F401 - registers the pack

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "examples" / "code_agent" / "baseline"
SOURCE = (BASELINE / "pricing" / "discounts.py").read_text(encoding="utf-8")

# Deliberately fake, but shaped like a real credential.
FAKE_AWS_KEY = "AKIA" + "A" * 16


class SecretGuardTest(unittest.TestCase):
    def contract(self):
        return Contract(
            name="secret-guard",
            domain="code",
            verifiers=[VerifierSpec("example.no_new_secrets")],
            required_defects=["secret-leak"],
        )

    def trace(self, content: str, change: str = "modified") -> Trace:
        return Trace(
            id="secret",
            task="",
            artifacts=[Artifact("pricing/discounts.py", content, change)],
        )

    def test_pack_registers_and_conforms(self):
        self.assertIn("example.no_new_secrets", REGISTRY)
        cls = REGISTRY["example.no_new_secrets"]
        self.assertEqual(cls.catches, ("secret-leak",))
        self.assertTrue(cls.blind_spots)
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

    def test_new_secret_fails(self):
        trace = self.trace(SOURCE + f'\nAWS_KEY = "{FAKE_AWS_KEY}"\n')
        result = run_contract(self.contract(), trace, BASELINE)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("example.no_new_secrets", result.first_failure)

    def test_clean_change_passes(self):
        trace = self.trace(SOURCE + "\n# refactor only\n")
        result = run_contract(self.contract(), trace, BASELINE)
        self.assertEqual(result.verdict, "pass", result.first_failure)

    def test_secret_already_in_baseline_is_not_flagged(self):
        # The verifier only looks at added lines, so a secret already in the
        # baseline is not a finding. That is declared, not hidden.
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp)
            (baseline / "pricing").mkdir()
            original = f'AWS_KEY = "{FAKE_AWS_KEY}"\n'
            (baseline / "pricing" / "discounts.py").write_text(
                original, encoding="utf-8"
            )
            trace = Trace(
                id="baseline-secret",
                task="",
                artifacts=[
                    Artifact(
                        "pricing/discounts.py", original + "# edit\n", "modified"
                    )
                ],
            )
            result = run_contract(self.contract(), trace, baseline)
        self.assertEqual(result.verdict, "pass", result.first_failure)


if __name__ == "__main__":
    unittest.main()
