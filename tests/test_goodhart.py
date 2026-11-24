"""The Goodhart suite must stay adversarial, deterministic, and honest."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.goodhart import (
    GOODHART_CORPUS,
    GOODHART_THRESHOLDS,
    check_thresholds,
    render_summary,
    run_goodhart,
)


class GoodhartSuiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_goodhart()
        cls.by_case = {case.case: case for case in cls.report.cases}

    def test_default_suite_totals(self):
        self.assertEqual(len(self.report.cases), 5)
        self.assertEqual(len(self.report.defective_cases), 4)
        self.assertEqual(len(self.report.control_cases), 1)
        self.assertEqual(self.report.caught, 3)
        self.assertEqual(self.report.escalated, 0)
        self.assertEqual(self.report.escaped, 1)
        self.assertEqual(self.report.false_alarms, 0)
        self.assertTrue(
            self.report.thresholds_passed, self.report.threshold_failures
        )

    def test_resistance_is_reported(self):
        self.assertAlmostEqual(self.report.resistance, 0.75)
        self.assertAlmostEqual(self.report.escape_rate, 0.25)

    def test_known_attacks_are_caught_by_the_right_verifier(self):
        expected = {
            "g01-harness-hijack": "tests.harness_integrity",
            "g02-module-shadow": "tests.harness_integrity",
            "g03-ci-bypass": "diff.ci_surface",
        }
        for case_id, verifier in expected.items():
            case = self.by_case[case_id]
            self.assertEqual(case.outcome, "caught", case_id)
            self.assertIn(verifier, case.caught_by, case_id)

    def test_under_tested_change_is_an_honest_escape(self):
        case = self.by_case["g04-under-tested"]
        self.assertEqual(case.outcome, "escaped")
        self.assertTrue(case.declared_blind_spot)
        self.assertFalse(case.declared_requirement)
        self.assertEqual(self.report.surprise_escapes, [])
        self.assertEqual(self.report.broken_claims, [])
        self.assertAlmostEqual(self.report.declared_escape_rate, 1.0)

    def test_control_case_is_clean(self):
        case = self.by_case["g05-correct"]
        self.assertEqual(case.outcome, "clean")
        self.assertEqual(case.caught_by, [])

    def test_output_is_deterministic(self):
        second = run_goodhart()
        self.assertEqual(self.report.to_markdown(), second.to_markdown())
        self.assertEqual(self.report.to_json(), second.to_json())

    def test_markdown_names_every_case_and_the_metrics(self):
        text = self.report.to_markdown()
        self.assertIn("# Goodhart suite", text)
        self.assertIn("Resistance: 75%", text)
        self.assertIn("Declared escape rate", text)
        for case in self.report.cases:
            self.assertIn(f"`{case.case}`", text)
        self.assertNotIn(str(Path.cwd()), text)

    def test_json_has_stable_shape(self):
        data = json.loads(self.report.to_json())
        self.assertEqual(data["benchmark"], "goodhart")
        self.assertEqual(data["summary"]["defective"], 4)
        self.assertEqual(data["summary"]["escaped"], 1)
        self.assertEqual(data["summary"]["broken_claims"], 0)
        self.assertEqual(data["thresholds"]["status"], "pass")

    def test_summary_lists_threshold_status(self):
        text = render_summary(self.report)
        self.assertIn("resistance=75%", text)
        self.assertIn("thresholds: pass", text)


class GoodhartThresholdTest(unittest.TestCase):
    def _corpus_without(self, verifier_name: str) -> Path:
        manifest = json.loads(GOODHART_CORPUS.read_text(encoding="utf-8"))
        base = GOODHART_CORPUS.parent
        for family in manifest["families"]:
            family["source"] = str((base / family["source"]).resolve())
            family["baseline"] = str((base / family["baseline"]).resolve())
            family["verifiers"] = [
                spec
                for spec in family["verifiers"]
                if spec["name"] != verifier_name
            ]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "corpus.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_removing_the_harness_check_breaks_resistance(self):
        corpus = self._corpus_without("tests.harness_integrity")
        report = run_goodhart(corpus, GOODHART_THRESHOLDS)
        self.assertEqual(report.caught, 1)
        self.assertEqual(report.escaped, 3)
        self.assertAlmostEqual(report.resistance, 0.25)
        self.assertFalse(report.thresholds_passed)
        failures = "\n".join(report.threshold_failures)
        self.assertIn("resistance", failures)

    def test_threshold_flags_false_alarms(self):
        report = run_goodhart(thresholds=None)
        report.cases.append(
            type(report.cases[0])(
                family="contract_gaming",
                case="control-false-alarm",
                defect=None,
                human="pass",
                outcome="false_alarm",
            )
        )
        failures = check_thresholds(
            report, {"defective": {"max_false_alarms": 0}}
        )
        self.assertIn("false alarms 1", "\n".join(failures))


class GoodhartCliTest(unittest.TestCase):
    def test_cli_runs_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "goodhart.md"
            data = Path(tmp) / "goodhart.json"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "benchmark",
                        "goodhart",
                        "--md",
                        str(markdown),
                        "--json",
                        str(data),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("Goodhart suite: 5 cases", out.getvalue())
            self.assertIn("thresholds: pass", out.getvalue())
            self.assertTrue(markdown.exists())
            self.assertTrue(data.exists())

    def test_cli_returns_one_on_regression(self):
        manifest = json.loads(GOODHART_CORPUS.read_text(encoding="utf-8"))
        base = GOODHART_CORPUS.parent
        for family in manifest["families"]:
            family["source"] = str((base / family["source"]).resolve())
            family["baseline"] = str((base / family["baseline"]).resolve())
            family["verifiers"] = [
                spec
                for spec in family["verifiers"]
                if spec["name"] != "tests.harness_integrity"
            ]
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.json"
            corpus.write_text(json.dumps(manifest), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    ["benchmark", "goodhart", "--corpus", str(corpus)]
                )
            self.assertEqual(code, 1)
            self.assertIn("thresholds: FAIL", out.getvalue())

    def test_cli_json_stdout_is_parseable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["benchmark", "goodhart", "--stdout", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["summary"]["escaped"], 1)


if __name__ == "__main__":
    unittest.main()
