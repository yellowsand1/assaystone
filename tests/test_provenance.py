"""Independence is downgraded when a check trusts an agent-written testimony."""

import tempfile
import unittest
from pathlib import Path

from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Trace
from assaystone.runner import run_contract
from assaystone.runtime import RuntimeGuard
from assaystone.verifiers import (
    REGISTRY,
    Verifier,
    effective_independence,
)


class _EvidenceFail(Verifier):
    name = "test.evidence_fail"
    layer = "L3"
    cost_usd = 0.000001
    independence = "high"
    claim = "Reads the evidence channel and fails."
    catches = ("false-claim",)
    blind_spots = ("forged evidence",)
    trusts = ("evidence",)

    def check(self, ctx, params):
        return False, ["claim without evidence"], []


class _ArtifactFail(Verifier):
    name = "test.artifact_fail"
    layer = "L1"
    cost_usd = 0.000001
    independence = "high"
    claim = "Reads the artifact and fails."
    catches = ("regression",)
    blind_spots = ("semantic drift",)
    trusts = ("artifacts",)

    def check(self, ctx, params):
        return False, ["artifact check failed"], []


class ProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.baseline = Path(cls._tmp.name)
        (cls.baseline / "note.txt").write_text("baseline\n", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        REGISTRY[_EvidenceFail.name] = _EvidenceFail
        REGISTRY[_ArtifactFail.name] = _ArtifactFail

    def tearDown(self):
        REGISTRY.pop(_EvidenceFail.name, None)
        REGISTRY.pop(_ArtifactFail.name, None)

    def contract(self, verifier: str) -> Contract:
        return Contract(
            name="provenance",
            verifiers=[VerifierSpec(verifier)],
            max_verification_cost_usd=1.0,
        )

    def test_effective_independence_depends_on_the_source(self):
        agent = Trace(id="a", task="", source="agent")
        runtime = Trace(id="r", task="", source="runtime")
        self.assertEqual(
            effective_independence(_EvidenceFail(), agent), "low"
        )
        self.assertEqual(
            effective_independence(_EvidenceFail(), runtime), "high"
        )
        self.assertEqual(
            effective_independence(_ArtifactFail(), agent), "high"
        )

    def test_evidence_failure_escalates_on_an_agent_trace(self):
        trace = Trace(id="agent", task="", source="agent")
        result = run_contract(
            self.contract("test.evidence_fail"), trace, self.baseline
        )
        self.assertEqual(result.verdict, "escalate")
        self.assertEqual(result.verdicts[0].independence, "low")
        self.assertEqual(result.verdicts[0].declared_independence, "high")
        self.assertTrue(result.unconfirmed)

    def test_evidence_failure_decides_on_a_runtime_trace(self):
        trace = Trace(id="runtime", task="", source="runtime")
        result = run_contract(
            self.contract("test.evidence_fail"), trace, self.baseline
        )
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.verdicts[0].independence, "high")
        self.assertEqual(result.unconfirmed, [])

    def test_artifact_failure_decides_on_an_agent_trace(self):
        trace = Trace(id="agent", task="", source="agent")
        result = run_contract(
            self.contract("test.artifact_fail"), trace, self.baseline
        )
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.verdicts[0].independence, "high")

    def test_runtime_guard_writes_a_runtime_trace(self):
        guard = RuntimeGuard(
            self.contract("test.evidence_fail"),
            baseline=self.baseline,
        )
        trace = guard.session(task="t").snapshot()
        self.assertEqual(trace.source, "runtime")

    def test_trace_roundtrip_preserves_the_source(self):
        runtime = Trace(id="r", task="", source="runtime")
        clone = Trace.from_dict(runtime.to_dict())
        self.assertEqual(clone.source, "runtime")
        self.assertEqual(Trace(id="a", task="").source, "agent")


if __name__ == "__main__":
    unittest.main()
