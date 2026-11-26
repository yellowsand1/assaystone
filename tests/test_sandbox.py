"""A mutating oracle does not touch the tree the gate is judging."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, trail
from assaystone.plane import CapabilityManifest, evaluate_gate, render_gate

REPO = Path(__file__).resolve().parent.parent
PRICING = REPO / "examples" / "capability" / "pricing.json"
PROJECT = REPO / "examples" / "capability" / "pricing_project"


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        shutil.copytree(PROJECT, self.root)
        self.manifest = CapabilityManifest.load(PRICING)

    def test_without_a_sandbox_the_tree_changes(self):
        gate = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertTrue((self.root / "ledger.db").exists())
        self.assertFalse(gate.sandbox)

    def test_the_sandbox_leaves_the_tree_untouched(self):
        gate = evaluate_gate(self.manifest, "shadow", self.root, sandbox=True)
        self.assertTrue(gate.sandbox)
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertFalse((self.root / "ledger.db").exists())
        self.assertIn("sandbox: yes", render_gate(gate))

    def test_the_sandboxed_run_still_judges_the_work(self):
        fee = self.root / "fee.py"
        fee.write_text(
            fee.read_text(encoding="utf-8").replace(
                '"fee_cents": fee_cents(',
                '"audited": version != "old", "fee_cents": fee_cents(',
            ),
            encoding="utf-8",
        )
        gate = evaluate_gate(self.manifest, "shadow", self.root, sandbox=True)
        self.assertEqual(gate.outcome, "fail")
        parity = next(item for item in gate.results if item.oracle == "parity")
        self.assertEqual(parity.outcome, "fail")

    def test_external_oracles_still_use_the_real_root(self):
        # The branch oracle reads git metadata, which the copy does not carry.
        manifest = CapabilityManifest.from_dict(
            {
                "capability": "sandbox-git",
                "owner": "team",
                "systems": ["git"],
                "data_classes": [],
                "irreversible_actions": [],
                "risk": "low",
                "lifecycle": "shadow",
                "criteria": [],
                "oracles": [
                    {
                        "id": "branch",
                        "type": "git",
                        "payload": {"mode": "branch", "expected": "main"},
                    }
                ],
                "policies": {"shadow": {"require": ["branch"]}},
            }
        )
        import subprocess

        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root,
                       check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "one"],
            cwd=self.root,
            check=True,
        )
        gate = evaluate_gate(manifest, "shadow", self.root, sandbox=True)
        self.assertEqual(
            [item.outcome for item in gate.results], ["pass"], gate.reasons
        )

    def test_the_trail_records_the_sandbox(self):
        gate = evaluate_gate(self.manifest, "shadow", self.root, sandbox=True)
        path = self.root / "trail.jsonl"
        trail.append(path, gate, actor="ci", at="2026-11-25T00:00:00Z")
        entry = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(entry["sandbox"])

    def test_cli_sandbox(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "gate",
                    "--manifest", str(PRICING),
                    "--stage", "shadow",
                    "--root", str(self.root),
                    "--sandbox",
                    "--json",
                ]
            )
        self.assertEqual(code, 0, out.getvalue())
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["sandbox"])
        self.assertFalse((self.root / "ledger.db").exists())

    def test_dry_run_and_sandbox_together_are_refused(self):
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
                        "--sandbox",
                    ]
                )
        self.assertEqual(code, 2)
        self.assertIn("nothing to protect", err.getvalue())


if __name__ == "__main__":
    unittest.main()
