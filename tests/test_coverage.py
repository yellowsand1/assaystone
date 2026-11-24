"""Coverage separates decided, weakly covered, and uncovered defect classes."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.contract import Contract, VerifierSpec
from assaystone.coverage import analyze_coverage, render_coverage
from assaystone.verifiers import REGISTRY, Verifier

REPO = Path(__file__).resolve().parent.parent
CONTRACTS = REPO / "examples" / "code_agent" / "contracts"


class _LowIndependenceCatcher(Verifier):
    name = "test.low_independence_catcher"
    layer = "L2"
    cost_usd = 0.000001
    independence = "low"
    claim = "Catches a tag, but cannot decide alone."
    catches = ("weak-tag",)
    blind_spots = ("independent confirmation",)

    def check(self, ctx, params):
        return True, [], []


class CoverageTest(unittest.TestCase):
    def setUp(self):
        REGISTRY[_LowIndependenceCatcher.name] = _LowIndependenceCatcher

    def tearDown(self):
        REGISTRY.pop(_LowIndependenceCatcher.name, None)

    def test_hardened_contract_covers_every_declared_defect(self):
        contract = Contract.load(CONTRACTS / "hardened.json")
        report = analyze_coverage(contract)
        self.assertEqual(len(report.declared), 8)
        self.assertEqual(report.at_risk, [])
        self.assertAlmostEqual(report.coverage_rate, 1.0)
        self.assertAlmostEqual(report.independent_rate, 1.0)
        self.assertIn("tests.harness_integrity", report.covered["test-harness-hijack"])

    def test_naive_contract_reports_residual_risk(self):
        contract = Contract.load(CONTRACTS / "naive.json")
        report = analyze_coverage(contract)
        self.assertEqual(len(report.at_risk), 7)
        self.assertIn("test-tampering", report.at_risk)
        self.assertIn("ci-bypass", report.at_risk)
        self.assertAlmostEqual(report.coverage_rate, 1 / 8)

    def test_low_independence_only_coverage_is_weak(self):
        contract = Contract(
            name="weak",
            verifiers=[VerifierSpec("test.low_independence_catcher")],
            required_defects=["weak-tag"],
        )
        report = analyze_coverage(contract)
        self.assertEqual(report.uncovered, [])
        self.assertEqual(report.low_independence_only, {"weak-tag": ["test.low_independence_catcher"]})
        self.assertIn("weak-tag", report.at_risk)
        self.assertAlmostEqual(report.independent_rate, 0.0)

    def test_undeclared_coverage_is_not_counted(self):
        contract = Contract(
            name="extra",
            verifiers=[VerifierSpec("tests.integrity")],
            required_defects=["regression"],
        )
        report = analyze_coverage(contract)
        self.assertEqual(report.uncovered, ["regression"])
        self.assertIn("test-tampering", report.not_declared)

    def test_no_declared_defects_is_not_perfect_coverage(self):
        contract = Contract(
            name="undeclared",
            verifiers=[VerifierSpec("tests.pass")],
        )
        report = analyze_coverage(contract)
        self.assertEqual(report.declared, [])
        self.assertEqual(report.coverage_rate, 0.0)
        self.assertEqual(report.independent_rate, 0.0)

    def test_declared_argument_overrides_contract(self):
        contract = Contract.load(CONTRACTS / "naive.json")
        report = analyze_coverage(contract, declared=["regression"])
        self.assertEqual(report.declared, ["regression"])
        self.assertEqual(report.at_risk, [])

    def test_render_names_at_risk_and_blind_spots(self):
        contract = Contract.load(CONTRACTS / "naive.json")
        text = render_coverage(analyze_coverage(contract))
        self.assertIn("# Contract coverage: naive", text)
        self.assertIn("## At risk", text)
        self.assertIn("## Declared blind spots", text)
        self.assertIn("`ci-bypass`", text)

    def test_json_shape(self):
        contract = Contract.load(CONTRACTS / "hardened.json")
        data = json.loads(json.dumps(analyze_coverage(contract).to_dict()))
        self.assertEqual(data["contract"], "hardened")
        self.assertEqual(data["at_risk"], [])
        self.assertEqual(data["coverage_rate"], 1.0)


class CoverageCliTest(unittest.TestCase):
    def test_hardened_passes_strict(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "coverage",
                    "--contract",
                    str(CONTRACTS / "hardened.json"),
                    "--strict",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("At risk (uncovered or low-independence only): **0**", out.getvalue())

    def test_naive_fails_strict(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "coverage",
                    "--contract",
                    str(CONTRACTS / "naive.json"),
                    "--strict",
                ]
            )
        self.assertEqual(code, 1)

    def test_json_output_is_parseable(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "coverage",
                    "--contract",
                    str(CONTRACTS / "hardened.json"),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["contract"], "hardened")

    def test_require_overrides_declared_tags(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "coverage",
                    "--contract",
                    str(CONTRACTS / "naive.json"),
                    "--require",
                    "regression",
                    "--strict",
                ]
            )
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
