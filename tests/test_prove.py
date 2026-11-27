"""`prove` is the one command that answers: can the checks be trusted?"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli


class ProveTest(unittest.TestCase):
    def test_prove_reports_recall_resistance_and_pass_status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["prove", "--json"])
        self.assertEqual(code, 0)
        document = json.loads(out.getvalue())
        self.assertTrue(document["passed"])
        self.assertIn("recall", document)
        self.assertIn("resistance", document)

    def test_prove_human_output_names_both_questions(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["prove"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("[recall]", text)
        self.assertIn("[resistance]", text)


class ProveGapsTest(unittest.TestCase):
    def run_json(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["prove", "--gaps", "--json", *args])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_gaps_count_deciding_checks_from_certificates(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(2):
                document = {
                    "checks": [
                        {"id": "diff.syntax", "outcome": "pass"},
                        {"id": "tests.integrity", "outcome": "pass"},
                    ],
                    "decision": {"verdict": "pass"},
                }
                Path(tmp, f"c{index}.certificate.json").write_text(
                    json.dumps(document), encoding="utf-8"
                )
            report = self.run_json("--certificates", tmp)
        gaps = {item["check"]: item for item in report["gaps"]}
        self.assertEqual(gaps["diff.syntax"]["decisions"], 2)
        self.assertNotIn("tests.integrity", gaps)
        self.assertEqual(report["decisions"], {"pass": 2})
        self.assertGreater(report["gap"], 0.0)

    def test_gaps_can_come_from_a_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp, "contract.json")
            contract.write_text(
                json.dumps(
                    {
                        "name": "gap",
                        "verifiers": [
                            {"name": "diff.syntax"},
                            {"name": "tests.integrity"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = self.run_json("--contract", str(contract))
        self.assertEqual([item["check"] for item in report["gaps"]], ["diff.syntax"])

    def test_no_gaps_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp, "contract.json")
            contract.write_text(
                json.dumps({"name": "ok", "verifiers": [{"name": "tests.integrity"}]}),
                encoding="utf-8",
            )
            report = self.run_json("--contract", str(contract))
        self.assertEqual(report["gaps"], [])
        self.assertEqual(report["gap"], 0.0)


if __name__ == "__main__":
    unittest.main()
