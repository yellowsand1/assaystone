"""A dry run shows what the gate would do without changing anything."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.plane import CapabilityManifest, evaluate_gate, render_gate

REPO = Path(__file__).resolve().parent.parent
PRICING = REPO / "examples" / "capability" / "pricing.json"
PROJECT = REPO / "examples" / "capability" / "pricing_project"


class DryRunTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        import shutil

        shutil.copytree(PROJECT, self.root)
        self.manifest = CapabilityManifest.load(PRICING)

    def test_a_dry_run_does_not_execute_a_mutating_oracle(self):
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, dry_run=True
        )
        self.assertTrue(gate.dry_run)
        seed = next(item for item in gate.results if item.oracle == "seed")
        self.assertEqual(seed.outcome, "escalate")
        self.assertIn("dry run", seed.reasons[0])
        self.assertFalse((self.root / "ledger.db").exists())

    def test_a_dry_run_never_passes(self):
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, dry_run=True
        )
        self.assertEqual(gate.outcome, "escalate")
        self.assertFalse(gate.merge_allowed)
        self.assertFalse(gate.deploy_allowed)
        self.assertTrue(
            any("not a decision" in reason for reason in gate.reasons)
        )

    def test_read_only_oracles_still_run(self):
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, dry_run=True
        )
        outcomes = {item.oracle: item.outcome for item in gate.results}
        self.assertEqual(outcomes["tests"], "pass")
        self.assertEqual(outcomes["parity"], "pass")

    def test_a_dry_run_failure_is_not_a_fail(self):
        fee = self.root / "fee.py"
        fee.write_text(
            fee.read_text(encoding="utf-8").replace(
                '"fee_cents": fee_cents(',
                '"audited": version != "old", "fee_cents": fee_cents(',
            ),
            encoding="utf-8",
        )
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, dry_run=True
        )
        self.assertEqual(gate.outcome, "escalate")

    def test_render_names_the_dry_run(self):
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, dry_run=True
        )
        self.assertIn("dry run: yes", render_gate(gate))
        real = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertIn("dry run: no", render_gate(real))

    def test_cli_dry_run_and_receipt_refusal(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "gate",
                    "--manifest", str(PRICING),
                    "--stage", "shadow",
                    "--root", str(self.root),
                    "--dry-run",
                    "--json",
                ]
            )
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["outcome"], "escalate")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "gate",
                        "--manifest", str(PRICING),
                        "--stage", "shadow",
                        "--root", str(self.root),
                        "--dry-run",
                        "--receipt", str(self.root / "r.json"),
                    ]
                )
        self.assertEqual(code, 2)
        self.assertIn("not a decision", err.getvalue())
        self.assertFalse((self.root / "r.json").exists())


if __name__ == "__main__":
    unittest.main()
