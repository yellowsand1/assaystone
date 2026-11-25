"""Composition is a weighted set cover, not a checklist."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.compose import compose, render_plan
from assaystone.contract import Contract, VerifierSpec
from assaystone.verifiers import REGISTRY, Verifier

REPO = Path(__file__).resolve().parent.parent
HARDENED = REPO / "examples" / "code_agent" / "contracts" / "hardened.json"


class _ExpensiveIntegrity(Verifier):
    name = "test.expensive_integrity"
    layer = "L1"
    cost_usd = 0.01
    independence = "high"
    claim = "Covers test tampering at a higher cost."
    catches = ("test-tampering",)
    blind_spots = ("everything else",)

    def check(self, ctx, params):
        return True, [], []


class ComposeTest(unittest.TestCase):
    def setUp(self):
        REGISTRY[_ExpensiveIntegrity.name] = _ExpensiveIntegrity

    def tearDown(self):
        REGISTRY.pop(_ExpensiveIntegrity.name, None)

    def contract(self, tags, verifiers=None, budget=0.05):
        return Contract(
            name="plan",
            domain="code",
            verifiers=verifiers
            or [
                VerifierSpec("tests.integrity"),
                VerifierSpec("diff.ci_surface"),
                VerifierSpec("quality.no_debug_prints"),
            ],
            required_defects=tags,
            max_verification_cost_usd=budget,
        )

    def test_picks_the_cheapest_cover(self):
        plan = compose(
            self.contract(["test-tampering", "ci-bypass", "debug-print"])
        )
        self.assertEqual(
            set(plan.selected),
            {"tests.integrity", "diff.ci_surface", "quality.no_debug_prints"},
        )
        self.assertAlmostEqual(plan.cost_usd, 0.00007)
        self.assertTrue(plan.ok, plan.to_dict())
        self.assertEqual(plan.uncovered, [])

    def test_one_verifier_can_cover_two_classes(self):
        plan = compose(
            self.contract(["test-harness-hijack", "module-shadow"])
        )
        self.assertEqual(plan.selected, ["tests.harness_integrity"])
        self.assertAlmostEqual(plan.cost_usd, 0.00002)
        self.assertEqual(
            sorted(plan.covered),
            ["module-shadow", "test-harness-hijack"],
        )

    def test_uncovered_class_is_reported(self):
        plan = compose(self.contract(["does-not-exist"]))
        self.assertEqual(plan.uncovered, ["does-not-exist"])
        self.assertFalse(plan.ok)

    def test_over_budget_is_reported(self):
        plan = compose(
            self.contract(
                ["test-tampering", "ci-bypass", "debug-print"], budget=0.00001
            )
        )
        self.assertFalse(plan.within_budget)
        self.assertFalse(plan.ok)
        self.assertAlmostEqual(plan.cost_usd, 0.00007)

    def test_alternatives_are_listed(self):
        plan = compose(self.contract(["test-tampering"]))
        self.assertEqual(plan.selected, ["tests.integrity"])
        self.assertIn(
            "test.expensive_integrity", plan.alternatives["test-tampering"]
        )

    def test_contract_only_pool_does_not_borrow_from_the_registry(self):
        contract = Contract(
            name="narrow",
            verifiers=[VerifierSpec("tests.pass")],
            required_defects=["test-tampering"],
        )
        plan = compose(contract, contract_only=True)
        self.assertEqual(plan.uncovered, ["test-tampering"])

    def test_plan_is_deterministic(self):
        contract = self.contract(["test-tampering", "ci-bypass", "debug-print"])
        first = compose(contract)
        second = compose(contract)
        self.assertEqual(first.selected, second.selected)
        self.assertEqual(first.cost_usd, second.cost_usd)

    def test_render_names_fragile_and_uncovered(self):
        plan = compose(
            self.contract(["test-tampering", "test-harness-hijack", "no-such-tag"])
        )
        text = render_plan(plan)
        self.assertIn("# Contract plan: plan", text)
        self.assertIn("## Uncovered", text)
        self.assertIn("## Fragile", text)

    def test_no_declared_classes_is_an_error(self):
        with self.assertRaises(ValueError):
            compose(Contract(name="empty", verifiers=[VerifierSpec("tests.pass")]))


class ComposeCliTest(unittest.TestCase):
    def test_hardened_contract_plans_within_budget(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["compose", "--contract", str(HARDENED), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertTrue(data["ok"])
        self.assertTrue(data["selected"])
        self.assertEqual(data["uncovered"], [])

    def test_no_declared_classes_exits_two(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = cli.main(["compose"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
