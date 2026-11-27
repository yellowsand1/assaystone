"""The task brief is a view of the manifest for the agent's input."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.brief import render_brief
from assaystone.plane import CapabilityManifest

REPO = Path(__file__).resolve().parent.parent
CAPABILITIES = REPO / "examples" / "capability"


class BriefTest(unittest.TestCase):
    def test_pricing_brief_contains_the_criteria_and_the_gate(self):
        manifest = CapabilityManifest.load(CAPABILITIES / "pricing.json")
        text = render_brief(
            manifest, manifest_path=".assaystone/capability.json",
            task="Refactor the fee calculation.",
        )
        self.assertIn("# Capability: pricing-change", text)
        self.assertIn("Refactor the fee calculation.", text)
        self.assertIn("The fee test suite passes.", text)
        self.assertIn("ledger-conserved", text)
        self.assertIn("`parity` (shadow)", text)
        self.assertIn(
            "python3 -m assaystone gate --manifest .assaystone/capability.json "
            "--stage shadow --root . --json",
            text,
        )
        self.assertIn("Do not edit tests, CI, or the capability manifest", text)
        self.assertIn("stop and explain", text)

    def test_production_brief_names_approval_rollback_and_chain(self):
        manifest = CapabilityManifest.load(CAPABILITIES / "pricing.json")
        text = render_brief(manifest, stage="production")
        self.assertIn("Approvals: `approval`", text)
        self.assertIn("Rollback evidence: `rollback`", text)
        self.assertIn("Chained after a recorded `canary` pass", text)

    def test_registry_manifest_resolves_oracles(self):
        manifest = CapabilityManifest.load(CAPABILITIES / "java.json")
        text = render_brief(manifest)
        self.assertIn("`compile` (command): Maven compile, tests skipped", text)
        self.assertIn("Maven compile", text)

    def test_table_cells_are_escaped(self):
        manifest = CapabilityManifest.from_dict(
            {
                "capability": "escape",
                "owner": "team",
                "systems": [],
                "data_classes": [],
                "irreversible_actions": [],
                "risk": "low",
                "lifecycle": "design",
                "criteria": [
                    {
                        "id": "c",
                        "kind": "invariant",
                        "statement": "a | b",
                        "oracle": "ok",
                        "severity": "high",
                    }
                ],
                "oracles": [
                    {"id": "ok", "type": "command", "payload": {"command": ["true"]}}
                ],
                "policies": {"shadow": {"require": ["ok"]}},
            }
        )
        text = render_brief(manifest)
        self.assertIn("a \\| b", text)

    def test_cli_stdout_and_out(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability",
                    "brief",
                    "--manifest",
                    str(CAPABILITIES / "pricing.json"),
                    "--task",
                    "Fix the ledger.",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("Fix the ledger.", out.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "brief.md"
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "capability",
                        "brief",
                        "--manifest",
                        str(CAPABILITIES / "pricing.json"),
                        "--out",
                        str(target),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("# Capability: pricing-change", target.read_text())


if __name__ == "__main__":
    unittest.main()
