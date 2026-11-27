"""A certificate carries the measured reliability of the checks that decided it."""

import unittest
from pathlib import Path

from assaystone.certificate import build_certificate
from assaystone.contract import Contract, VerifierSpec
from assaystone.model import load_traces
from assaystone.reliability import SCHEMA, build, calibration, profile_for
from assaystone.runner import run_contract

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples" / "code_agent"


def fake_profile(entry: dict | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "measured_at": "2026-01-01T00:00:00Z",
        "tool_version": "test",
        "corpus_digest": "sha256:corpus",
        "checks": {"diff.syntax": entry} if entry is not None else {},
    }


class ReliabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = build()

    def test_the_packaged_profile_measures_known_checks(self):
        entry = self.profile["checks"]["tests.integrity"]
        self.assertEqual(entry["status"], "measured")
        self.assertEqual(entry["recall"], 1.0)
        self.assertGreaterEqual(entry["declared_cases"], 1)
        self.assertTrue(self.profile["corpus_digest"].startswith("sha256:"))

    def test_a_check_without_cases_is_unmeasured(self):
        entry = self.profile["checks"]["diff.syntax"]
        self.assertEqual(entry["status"], "unmeasured")
        self.assertIsNone(entry["recall"])

    def test_profile_for_unknown_check_is_explicit(self):
        self.assertEqual(profile_for("nope", fake_profile()), {"status": "unmeasured"})

    def test_calibration_counts_measured_and_unmeasured(self):
        result = calibration(
            ["diff.syntax", "tests.integrity"],
            fake_profile(
                {
                    "status": "measured",
                    "recall": 0.5,
                    "declared_cases": 4,
                    "false_alarm_rate": 0.0,
                    "clean_cases": 3,
                }
            ),
        )
        self.assertEqual(result["measured_checks"], 1)
        self.assertEqual(result["unmeasured_checks"], 1)
        self.assertEqual(result["calibration_gap"], 0.5)
        self.assertEqual(result["min_recall"], 0.5)


class CertificateReliabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = EXAMPLES / "baseline"
        cls.contract = Contract(
            name="syntax", verifiers=[VerifierSpec("diff.syntax")]
        )
        cls.trace = {trace.id: trace for trace in load_traces(EXAMPLES / "traces")}["t01-correct"]
        cls.result = run_contract(cls.contract, cls.trace, cls.baseline)

    def build(self, entry=None):
        return build_certificate(
            self.result,
            self.contract,
            self.trace,
            issued_at="2026-01-01T00:00:00Z",
            reliability=fake_profile(entry),
        )

    def test_measured_check_is_attached_with_its_sample_size(self):
        document = self.build(
            {
                "status": "measured",
                "recall": 1.0,
                "declared_cases": 3,
                "false_alarm_rate": 0.0,
                "clean_cases": 2,
            }
        )
        check = document["checks"][0]
        self.assertEqual(check["reliability"]["recall"], 1.0)
        self.assertEqual(check["reliability"]["declared_cases"], 3)
        self.assertTrue(check["reliability_digest"].startswith("sha256:"))
        calibration_block = document["assurance"]["calibration"]
        self.assertEqual(calibration_block["measured_checks"], 1)
        self.assertEqual(calibration_block["corpus_digest"], "sha256:corpus")

    def test_unmeasured_check_says_so(self):
        document = self.build()
        self.assertEqual(document["checks"][0]["reliability"], {"status": "unmeasured"})
        self.assertEqual(document["assurance"]["calibration"]["measured_checks"], 0)
        self.assertEqual(document["assurance"]["calibration"]["unmeasured_checks"], 1)

    def test_a_different_calibration_is_a_different_decision(self):
        measured = self.build({"status": "measured", "recall": 1.0, "declared_cases": 3})
        unmeasured = self.build()
        self.assertNotEqual(measured["id"], unmeasured["id"])


if __name__ == "__main__":
    unittest.main()
