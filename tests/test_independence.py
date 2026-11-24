"""The independence contract: a low-independence failure cannot decide alone."""

import tempfile
import unittest
from pathlib import Path

from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Trace
from assaystone.packs import ops  # noqa: F401 - registers the ops pack
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY, Verifier


class _AlwaysPass(Verifier):
    name = "test.always_pass"
    layer = "L1"
    cost_usd = 0.000001
    independence = "high"
    claim = "Always passes; used to test aggregation."
    catches = ("never",)
    blind_spots = ("everything",)

    def check(self, ctx, params):
        return True, [], []


class _AlwaysFail(Verifier):
    name = "test.always_fail"
    layer = "L1"
    cost_usd = 0.000001
    independence = "high"
    claim = "Always fails; used to test aggregation."
    catches = ("always",)
    blind_spots = ()

    def check(self, ctx, params):
        return False, ["failed on purpose"], []


class _LowIndependenceFail(Verifier):
    name = "test.low_independence_fail"
    layer = "L1"
    cost_usd = 0.000001
    independence = "low"
    claim = "Fails, but shares too much context with the generator to decide alone."
    catches = ("always",)
    blind_spots = ("independent confirmation",)

    def check(self, ctx, params):
        return False, ["low-independence failure"], []


class _UnknownIndependenceFail(Verifier):
    name = "test.unknown_independence_fail"
    layer = "L1"
    cost_usd = 0.000001
    independence = "whatever"
    claim = "Declares an unknown independence level."
    catches = ("always",)
    blind_spots = ("a correct independence declaration",)

    def check(self, ctx, params):
        return False, ["unknown-independence failure"], []


class IndependenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.baseline = Path(cls._tmp.name)
        (cls.baseline / "note.txt").write_text("baseline\n", encoding="utf-8")
        cls.trace = Trace(id="t", task="aggregation")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        for cls in (
            _AlwaysPass,
            _AlwaysFail,
            _LowIndependenceFail,
            _UnknownIndependenceFail,
        ):
            REGISTRY[cls.name] = cls

    def tearDown(self):
        for name in (
            "test.always_pass",
            "test.always_fail",
            "test.low_independence_fail",
            "test.unknown_independence_fail",
        ):
            REGISTRY.pop(name, None)

    def contract(self, *names):
        return Contract(name="independence", verifiers=[VerifierSpec(n) for n in names])

    def test_low_independence_failure_escalates(self):
        result = run_contract(
            self.contract("test.low_independence_fail"), self.trace, self.baseline
        )
        self.assertEqual(result.verdict, "escalate")
        self.assertEqual(len(result.unconfirmed), 1)
        self.assertIn("low-independence", result.first_failure)

    def test_low_independence_failure_confirmed_by_independent_check(self):
        result = run_contract(
            self.contract("test.low_independence_fail", "test.always_fail"),
            self.trace,
            self.baseline,
        )
        self.assertEqual(result.verdict, "fail")
        self.assertIn("test.always_fail", result.first_failure)

    def test_low_independence_failure_not_cancelled_by_pass(self):
        result = run_contract(
            self.contract("test.low_independence_fail", "test.always_pass"),
            self.trace,
            self.baseline,
        )
        self.assertEqual(result.verdict, "escalate")
        self.assertEqual(len(result.unconfirmed), 1)

    def test_unknown_independence_is_treated_as_low(self):
        result = run_contract(
            self.contract("test.unknown_independence_fail"), self.trace, self.baseline
        )
        self.assertEqual(result.verdict, "escalate")
        self.assertEqual(result.verdicts[0].independence, "whatever")

    def test_verdict_records_independence(self):
        result = run_contract(
            self.contract("test.always_pass"), self.trace, self.baseline
        )
        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.verdicts[0].independence, "high")
        self.assertEqual(result.to_dict()["verdicts"][0]["independence"], "high")

    def test_every_builtin_verifier_declares_its_abi(self):
        for name, cls in sorted(REGISTRY.items()):
            # Only enforce the ABI on the verifiers this package ships.
            # Third-party packs and test doubles are allowed to be incomplete.
            if not cls.__module__.startswith("assaystone"):
                continue
            if name.startswith("test."):
                continue
            self.assertTrue(cls.claim, f"{name} has no claim")
            self.assertTrue(cls.catches, f"{name} claims to catch nothing")
            self.assertTrue(
                cls.blind_spots, f"{name} declares no blind spots"
            )
            self.assertIn(
                cls.independence,
                {"low", "medium", "high"},
                f"{name} has an invalid independence level",
            )


if __name__ == "__main__":
    unittest.main()
