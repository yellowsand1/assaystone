"""Third-party tools enter through the same ABI and keep their blind spots."""

import importlib.util
import subprocess
import unittest
from pathlib import Path

from assaystone.contract import Contract, VerifierSpec
from assaystone.model import load_traces
from assaystone.packs.external import ExternalPytest, ExternalRuffDebugPrint
from assaystone.runner import run_contract
from assaystone.verifiers import REGISTRY

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "examples" / "code_agent" / "baseline"
TRACES = REPO / "examples" / "code_agent" / "traces"

HAS_PYTEST = importlib.util.find_spec("pytest") is not None
HAS_RUFF = importlib.util.find_spec("ruff") is not None


class FakeWorkspace:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self._result = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def run(self, command, timeout=60):
        return self._result


class FakeContext:
    def __init__(self, workspace):
        self.workspace = workspace


class ExternalPackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traces = {trace.id: trace for trace in load_traces(TRACES)}

    def contract(self):
        return Contract(
            name="external",
            verifiers=[
                VerifierSpec("external.pytest"),
                VerifierSpec("external.ruff_debug_print"),
            ],
            max_verification_cost_usd=1.0,
        )

    def test_registered_and_conformant(self):
        for name in ("external.pytest", "external.ruff_debug_print"):
            self.assertIn(name, REGISTRY)
            cls = REGISTRY[name]
            self.assertTrue(cls.claim)
            self.assertTrue(cls.catches)
            self.assertTrue(cls.blind_spots)
            self.assertIn(cls.independence, {"low", "medium", "high"})

    def test_pytest_independence_is_medium(self):
        # It runs Python in the same workspace, so it shares the hijack surface.
        self.assertEqual(ExternalPytest.independence, "medium")
        self.assertIn("module-shadow", ExternalPytest.blind_spots)
        self.assertIn("test-harness-hijack", ExternalPytest.blind_spots)

    @unittest.skipUnless(HAS_PYTEST, "pytest is not installed")
    def test_pytest_catches_a_regression(self):
        result = run_contract(
            self.contract(), self.traces["t02-regression"], BASELINE
        )
        self.assertEqual(result.verdict, "fail")
        self.assertIn("external.pytest", result.first_failure)

    @unittest.skipUnless(HAS_RUFF, "ruff is not installed")
    def test_ruff_catches_a_debug_print(self):
        result = run_contract(
            self.contract(), self.traces["t05-debug-print"], BASELINE
        )
        self.assertEqual(result.verdict, "fail")
        self.assertIn("external.ruff_debug_print", result.first_failure)

    @unittest.skipUnless(HAS_PYTEST and HAS_RUFF, "pytest and ruff are required")
    def test_external_tools_miss_test_tampering(self):
        # Both tools pass a deleted test: the suite is still green and the
        # source still has no print. This is why external tools alone are not
        # an acceptance contract.
        result = run_contract(
            self.contract(), self.traces["t03-test-tampering"], BASELINE
        )
        self.assertEqual(result.verdict, "pass")

    @unittest.skipUnless(HAS_PYTEST and HAS_RUFF, "pytest and ruff are required")
    def test_correct_patch_passes(self):
        result = run_contract(self.contract(), self.traces["t01-correct"], BASELINE)
        self.assertEqual(result.verdict, "pass", result.first_failure)

    def test_missing_pytest_escalates(self):
        ctx = FakeContext(FakeWorkspace(1, stderr="No module named pytest"))
        ok, reasons, _ = ExternalPytest().check(ctx, {})
        self.assertIsNone(ok)
        self.assertIn("not installed", reasons[0])

    def test_missing_ruff_escalates(self):
        ctx = FakeContext(FakeWorkspace(1, stderr="No module named ruff"))
        ok, reasons, _ = ExternalRuffDebugPrint().check(ctx, {})
        self.assertIsNone(ok)
        self.assertIn("not installed", reasons[0])

    def test_pytest_errors_escalate(self):
        ctx = FakeContext(FakeWorkspace(2, stderr="interrupted"))
        ok, _reasons, _ = ExternalPytest().check(ctx, {})
        self.assertIsNone(ok)

    def test_ruff_errors_escalate(self):
        ctx = FakeContext(FakeWorkspace(2, stderr="edition not found"))
        ok, _reasons, _ = ExternalRuffDebugPrint().check(ctx, {})
        self.assertIsNone(ok)


if __name__ == "__main__":
    unittest.main()
