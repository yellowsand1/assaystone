"""The workspace registry: every capability in one read-only table."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, trail
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.portfolio import (
    build_portfolio,
    discover,
    render_portfolio,
)

REPO = Path(__file__).resolve().parent.parent


def manifest_data(capability):
    return {
        "capability": capability,
        "owner": "team",
        "systems": [],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": [
            {
                "id": "ok",
                "kind": "postcondition",
                "statement": "it works",
                "oracle": "ok",
                "severity": "critical",
            }
        ],
        "oracles": [
            {"id": "ok", "type": "command", "payload": {"command": ["true"]}}
        ],
        "policies": {"shadow": {"require": ["ok"], "allow_merge": False}},
    }


class PortfolioTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.manifests = {}
        for name in ("cap-a", "cap-b"):
            directory = self.root / ".assaystone" / name
            directory.mkdir(parents=True)
            path = directory / "capability.json"
            path.write_text(
                json.dumps(manifest_data(name)), encoding="utf-8"
            )
            self.manifests[name] = (path, CapabilityManifest.load(path))

    def record(self, name):
        path, manifest = self.manifests[name]
        gate = evaluate_gate(manifest, "shadow", self.root)
        trail.append(
            path.parent / "trail.jsonl",
            gate,
            actor="ci",
            at="2026-11-25T00:00:00Z",
        )

    def test_discovers_nested_capabilities(self):
        found = discover(self.root)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(".assaystone" in path.parts for path in found))

    def test_portfolio_flags_missing_evidence(self):
        self.record("cap-a")
        portfolio = build_portfolio(self.root)
        by_name = {
            entry.card.capability: entry
            for entry in portfolio.entries
            if entry.card
        }
        self.assertEqual(by_name["cap-a"].critical, [])
        self.assertIn(
            "no trail evidence", by_name["cap-b"].critical
        )
        self.assertEqual(portfolio.critical_count(), 1)
        text = render_portfolio(portfolio)
        self.assertIn("cap-a", text)
        self.assertIn("cap-b", text)
        self.assertIn("1 with critical risks", text)

    def test_strict_cli(self):
        self.record("cap-a")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                ["capability", "list", "--root", str(self.root), "--json"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(len(payload["capabilities"]), 2)
        self.assertEqual(payload["critical"], 1)

        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(
                [
                    "capability",
                    "list",
                    "--root",
                    str(self.root),
                    "--strict",
                ]
            )
        self.assertEqual(code, 1)

        self.record("cap-b")
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(
                [
                    "capability",
                    "list",
                    "--root",
                    str(self.root),
                    "--strict",
                ]
            )
        self.assertEqual(code, 0)

    def test_invalid_manifest_is_a_critical_entry(self):
        broken = self.root / ".assaystone" / "broken" / "capability.json"
        broken.parent.mkdir(parents=True)
        broken.write_text("{not json", encoding="utf-8")
        portfolio = build_portfolio(self.root)
        broken_entries = [
            entry for entry in portfolio.entries if entry.card is None
        ]
        self.assertEqual(len(broken_entries), 1)
        self.assertTrue(
            any("manifest is invalid" in issue for issue in broken_entries[0].critical)
        )

    def test_repository_discovers_its_own_capability(self):
        found = discover(REPO)
        self.assertTrue(
            any(
                path.name == "capability.json" and ".assaystone" in path.parts
                for path in found
            )
        )

    def test_empty_workspace_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["capability", "list", "--root", tmp])
        self.assertEqual(code, 0)
        self.assertIn("No capabilities found", out.getvalue())


if __name__ == "__main__":
    unittest.main()
