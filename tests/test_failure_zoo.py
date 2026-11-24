import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.failure_zoo import (
    DEFAULT_CORPUS,
    DEFAULT_THRESHOLDS,
    VerifierRow,
    check_thresholds,
    render_summary,
    run_benchmark,
)


class FailureZooTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_benchmark()
        cls.rows = {row.name: row for row in cls.result.verifiers}

    def test_default_corpus_totals(self):
        self.assertEqual(len(self.result.cases), 13)
        self.assertEqual(self.result.defective, 9)
        self.assertEqual(self.result.clean, 4)
        self.assertEqual(self.result.caught, 9)
        self.assertEqual(self.result.escaped, 0)
        self.assertEqual(self.result.false_alarms, 0)
        self.assertTrue(self.result.thresholds_passed, self.result.threshold_failures)

    def test_clean_and_defective_cases_are_both_represented(self):
        verdicts = {case.human for case in self.result.cases}
        self.assertEqual(verdicts, {"pass", "fail"})

    def test_known_defect_verifier_pairs(self):
        expected = {
            "tests.pass": "t02-regression",
            "tests.integrity": "t03-test-tampering",
            "diff.forbidden_paths": "t04-forbidden-path",
            "quality.no_debug_prints": "t05-debug-print",
            "ops.refund_limit": "t02-over-limit",
            "ops.no_double_refund": "t03-double-refund",
            "ops.approval_recorded": "t04-missing-approval",
            "ops.status_consistent": "t05-bad-status",
        }
        caught = {
            (result.verifier, result.case.trace_id)
            for result in self.result.results
            if result.outcome == "caught"
        }
        for verifier, trace_id in expected.items():
            self.assertIn((verifier, trace_id), caught)
        self.assertEqual(self.rows["tests.integrity"].caught, 2)
        self.assertIn(
            ("tests.integrity", "audit-demo-session"),
            caught,
        )

    def test_no_false_alarms_on_clean_cases(self):
        for row in self.result.verifiers:
            self.assertEqual(row.false_alarms, 0, row.name)
            self.assertEqual(row.false_alarm_rate, 0.0, row.name)

    def test_audit_transcript_without_labels_is_labelled_by_manifest(self):
        audit_cases = [
            case for case in self.result.cases if case.family == "audit"
        ]
        self.assertEqual([case.trace_id for case in audit_cases], ["audit-demo-session"])
        self.assertEqual(audit_cases[0].human, "fail")
        self.assertEqual(audit_cases[0].defect, "test-tampering")

    def test_output_is_deterministic(self):
        second = run_benchmark()
        self.assertEqual(self.result.to_markdown(), second.to_markdown())
        self.assertEqual(self.result.to_json(), second.to_json())
        self.assertEqual(self.result.to_csv(), second.to_csv())

    def test_markdown_mentions_every_verifier_and_case(self):
        text = self.result.to_markdown()
        self.assertIn("# Failure Zoo benchmark", text)
        self.assertIn("## Per-verifier results", text)
        self.assertIn("## Regression thresholds", text)
        for name in self.rows:
            self.assertIn(f"`{name}`", text)
        for case in self.result.cases:
            self.assertIn(f"`{case.trace_id}`", text)
        self.assertNotIn(str(Path.cwd()), text)

    def test_csv_has_one_row_per_verifier_case(self):
        lines = self.result.to_csv().splitlines()
        self.assertEqual(
            lines[0], "family,case,human,defect,verifier,outcome,reason"
        )
        self.assertEqual(len(lines) - 1, len(self.result.results))
        self.assertTrue(self.result.to_csv().endswith("\n"))

    def test_json_has_stable_shape(self):
        data = json.loads(self.result.to_json())
        self.assertEqual(data["benchmark"], "failure-zoo")
        self.assertEqual(data["summary"]["caught"], 9)
        self.assertEqual(data["thresholds"]["status"], "pass")
        self.assertEqual(
            [family["family"] for family in data["families"]],
            ["code_agent", "ops_agent", "audit"],
        )

    def test_summary_lists_threshold_status(self):
        text = render_summary(self.result)
        self.assertIn("thresholds: pass", text)
        self.assertIn("thresholds.json", text)

    def test_threshold_regression_is_detected(self):
        manifest = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
        for family in manifest["families"]:
            family["source"] = str((DEFAULT_CORPUS.parent / family["source"]).resolve())
            family["baseline"] = str((DEFAULT_CORPUS.parent / family["baseline"]).resolve())
            family["verifiers"] = [
                spec for spec in family["verifiers"] if spec["name"] != "tests.integrity"
            ]
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.json"
            corpus.write_text(json.dumps(manifest), encoding="utf-8")
            result = run_benchmark(corpus, DEFAULT_THRESHOLDS)
        self.assertFalse(result.thresholds_passed)
        failures = "\n".join(result.threshold_failures)
        self.assertIn("case-level caught 7 is below the threshold 9", failures)
        self.assertIn("tests.integrity: verifier is missing", failures)

    def test_per_verifier_recall_drop_is_detected(self):
        manifest = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
        for family in manifest["families"]:
            family["source"] = str((DEFAULT_CORPUS.parent / family["source"]).resolve())
            family["baseline"] = str((DEFAULT_CORPUS.parent / family["baseline"]).resolve())
            if family["name"] == "code_agent":
                family["verifiers"] = [
                    spec
                    for spec in family["verifiers"]
                    if spec["name"] != "tests.integrity"
                ]
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.json"
            corpus.write_text(json.dumps(manifest), encoding="utf-8")
            result = run_benchmark(corpus, DEFAULT_THRESHOLDS)
        failures = "\n".join(result.threshold_failures)
        self.assertIn(
            "tests.integrity: caught 1 is below the threshold 2", failures
        )
        self.assertIn("case-level caught 8 is below the threshold 9", failures)

    def test_threshold_check_flags_new_false_alarms(self):
        result = run_benchmark(thresholds=None)
        result.verifiers = [
            row for row in result.verifiers if row.name != "tests.pass"
        ]
        result.verifiers.append(
            VerifierRow(
                name="tests.pass",
                layer="L1",
                cases=6,
                caught=1,
                escaped=3,
                false_alarms=1,
                clean_passes=1,
            )
        )
        failures = check_thresholds(
            result, {"verifiers": {"tests.pass": {"max_false_alarms": 0}}}
        )
        self.assertIn("tests.pass: false alarms 1 exceeds the threshold 0", failures)


class FailureZooCliTest(unittest.TestCase):
    def test_cli_writes_scorecard(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "scorecard.md"
            data = Path(tmp) / "results.json"
            rows = Path(tmp) / "results.csv"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "benchmark",
                        "failure-zoo",
                        "--md",
                        str(markdown),
                        "--json",
                        str(data),
                        "--csv",
                        str(rows),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("Failure Zoo: 13 cases", out.getvalue())
            self.assertIn("thresholds: pass", out.getvalue())
            self.assertTrue(markdown.exists())
            self.assertTrue(data.exists())
            self.assertTrue(rows.exists())
            self.assertIn("# Failure Zoo benchmark", markdown.read_text(encoding="utf-8"))

    def test_cli_returns_one_on_threshold_regression(self):
        manifest = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
        for family in manifest["families"]:
            family["source"] = str((DEFAULT_CORPUS.parent / family["source"]).resolve())
            family["baseline"] = str((DEFAULT_CORPUS.parent / family["baseline"]).resolve())
            family["verifiers"] = [
                spec for spec in family["verifiers"] if spec["name"] != "tests.integrity"
            ]
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.json"
            corpus.write_text(json.dumps(manifest), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    ["benchmark", "failure-zoo", "--corpus", str(corpus)]
                )
            self.assertEqual(code, 1)
            self.assertIn("thresholds: FAIL", out.getvalue())

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "benchmark",
                        "failure-zoo",
                        "--corpus",
                        str(corpus),
                        "--no-thresholds",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("thresholds: not checked", out.getvalue())

    def test_cli_json_stdout_is_parseable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["benchmark", "failure-zoo", "--stdout", "json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["summary"]["defective"], 9)


if __name__ == "__main__":
    unittest.main()
