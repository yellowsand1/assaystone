"""A stage can price its verification, and a budget stops it honestly."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, trail
from assaystone.plane import (
    CapabilityManifest,
    PlaneError,
    evaluate_gate,
    oracle_cost,
)

REPO = Path(__file__).resolve().parent.parent
PRICING = REPO / "examples" / "capability" / "pricing.json"
PROJECT = REPO / "examples" / "capability" / "pricing_project"


def manifest_data(costs, budget=None):
    policy = {"require": ["a", "b"], "allow_merge": True}
    if budget is not None:
        policy["budget_usd"] = budget
    return {
        "capability": "budget-test",
        "owner": "team",
        "systems": [],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": [],
        "oracles": [
            {
                "id": "a",
                "type": "command",
                "payload": {"command": ["true"], "cost_usd": costs[0]},
            },
            {
                "id": "b",
                "type": "command",
                "payload": {"command": ["true"], "cost_usd": costs[1]},
            },
        ],
        "policies": {"shadow": policy},
    }


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def gate(self, costs, budget=None):
        manifest = CapabilityManifest.from_dict(manifest_data(costs, budget))
        return evaluate_gate(manifest, "shadow", self.root)

    def test_cost_is_summed_and_reported(self):
        gate = self.gate([0.01, 0.02])
        self.assertEqual(gate.outcome, "pass")
        self.assertAlmostEqual(gate.cost_usd, 0.03)
        self.assertEqual(len(gate.results), 2)

    def test_a_budget_that_fits_does_not_interfere(self):
        gate = self.gate([0.01, 0.02], budget=0.05)
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertAlmostEqual(gate.cost_usd, 0.03)

    def test_an_exhausted_budget_escalates_and_stops(self):
        gate = self.gate([0.01, 0.10], budget=0.05)
        self.assertEqual(gate.outcome, "escalate")
        self.assertEqual([item.oracle for item in gate.results], ["a"])
        self.assertTrue(
            any("budget" in reason for reason in gate.reasons)
        )
        self.assertFalse(gate.merge_allowed)

    def test_the_first_oracle_over_budget_runs_nothing(self):
        gate = self.gate([0.10, 0.10], budget=0.05)
        self.assertEqual(gate.outcome, "escalate")
        self.assertEqual(gate.results, [])
        self.assertAlmostEqual(gate.cost_usd, 0.0)

    def test_a_negative_budget_is_rejected(self):
        data = manifest_data([0, 0], budget=-1)
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

    def test_a_non_numeric_cost_counts_as_zero(self):
        from assaystone.oracles import OracleSpec

        spec = OracleSpec(id="x", type="command", payload={"cost_usd": "free"})
        self.assertEqual(oracle_cost(spec), 0.0)
        self.assertEqual(oracle_cost(OracleSpec(id="y", type="command")), 0.0)

    def test_cost_reaches_the_trail_and_the_output(self):
        manifest = CapabilityManifest.from_dict(manifest_data([0.01, 0.02]))
        gate = evaluate_gate(manifest, "shadow", self.root)
        path = self.root / "trail.jsonl"
        trail.append(path, gate, actor="ci", at="2026-11-25T00:00:00Z")
        entry = json.loads(path.read_text(encoding="utf-8"))
        self.assertAlmostEqual(entry["cost_usd"], 0.03)
        self.assertFalse(entry["dry_run"])

    def test_the_pricing_gate_reports_its_cost(self):
        root = Path(self._tmp.name) / "project"
        shutil.copytree(PROJECT, root)
        manifest = CapabilityManifest.load(PRICING)
        gate = evaluate_gate(manifest, "shadow", root)
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertGreaterEqual(gate.cost_usd, 0.0)

    def test_cli_reports_the_cost(self):
        root = Path(self._tmp.name) / "cli"
        shutil.copytree(PROJECT, root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "gate",
                    "--manifest", str(PRICING),
                    "--stage", "shadow",
                    "--root", str(root),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("cost_usd", payload)


if __name__ == "__main__":
    unittest.main()
