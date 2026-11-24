"""The report card puts four independent claims on one page."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.contract import Contract
from assaystone.model import load_traces
from assaystone.reportcard import run_report_card

REPO = Path(__file__).resolve().parent.parent
CONTRACTS = REPO / "examples" / "code_agent" / "contracts"
BASELINE = REPO / "examples" / "code_agent" / "baseline"
TRACES = REPO / "examples" / "code_agent" / "traces"


class ReportCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traces = load_traces(TRACES)
        cls.hardened = run_report_card(
            Contract.load(CONTRACTS / "hardened.json"),
            traces=cls.traces,
            baseline=BASELINE,
        )
        cls.naive = run_report_card(
            Contract.load(CONTRACTS / "naive.json"),
            traces=cls.traces,
            baseline=BASELINE,
        )

    def test_hardened_passes_all_four_checks(self):
        card = self.hardened
        self.assertTrue(card.protocol.ok, card.protocol.violations)
        self.assertEqual(card.coverage.at_risk, [])
        self.assertEqual(card.recall.escaped, 0)
        self.assertEqual(card.recall.caught, 4)
        self.assertAlmostEqual(card.resistance.resistance, 4 / 6)
        self.assertTrue(card.ok)

    def test_naive_needs_work_and_names_the_risk(self):
        card = self.naive
        self.assertFalse(card.ok)
        self.assertGreater(len(card.coverage.at_risk), 0)
        self.assertIn("at risk", card.headline)

    def test_resistance_is_split_by_family(self):
        rows = {row["family"]: row for row in self.hardened.resistance.family_rows()}
        self.assertAlmostEqual(rows["mechanical"]["resistance"], 1.0)
        self.assertAlmostEqual(rows["ops_lineage"]["resistance"], 1.0)
        self.assertAlmostEqual(rows["semantic"]["resistance"], 0.0)

    def test_markdown_has_all_sections(self):
        text = self.hardened.to_markdown()
        for heading in (
            "# Report card: hardened",
            "## Protocol",
            "## Coverage",
            "## Recall (labelled traces)",
            "## Resistance (Goodhart suite)",
        ):
            self.assertIn(heading, text)
        self.assertIn("**PASS**", text)
        self.assertNotIn(str(Path.cwd()), text)

    def test_json_shape(self):
        data = json.loads(json.dumps(self.hardened.to_dict()))
        self.assertTrue(data["ok"])
        self.assertEqual(data["coverage"]["at_risk"], [])
        self.assertEqual(data["recall"]["caught"], 4)
        self.assertEqual(
            [row["family"] for row in data["resistance"]["families"]],
            ["mechanical", "ops_lineage", "semantic"],
        )

    def test_without_traces_the_recall_section_is_absent(self):
        card = run_report_card(Contract.load(CONTRACTS / "hardened.json"))
        self.assertIsNone(card.recall)
        self.assertNotIn("## Recall", card.to_markdown())


class ReportCardCliTest(unittest.TestCase):
    def test_hardened_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "scorecard",
                    "--contract",
                    str(CONTRACTS / "hardened.json"),
                    "--trace",
                    str(TRACES),
                    "--baseline",
                    str(BASELINE),
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("**PASS**", out.getvalue())

    def test_naive_exits_one(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "scorecard",
                    "--contract",
                    str(CONTRACTS / "naive.json"),
                    "--trace",
                    str(TRACES),
                    "--baseline",
                    str(BASELINE),
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("**NEEDS WORK**", out.getvalue())

    def test_json_output_is_parseable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "scorecard",
                    "--contract",
                    str(CONTRACTS / "hardened.json"),
                    "--stdout",
                    "json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
