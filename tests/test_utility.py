"""Which required checks have ever observed a failure."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, trail
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.utility import build_report, render_report, required_oracles


def manifest_data(extra_oracle=True, merge=False):
    oracles = [
        {"id": "a", "type": "command", "payload": {"command": ["true"]}},
        {"id": "b", "type": "command", "payload": {"command": ["true"]}},
    ]
    if extra_oracle:
        oracles.append(
            {"id": "spare", "type": "command", "payload": {"command": ["true"]}}
        )
    policy = {"require": ["a", "b"], "allow_merge": False}
    return {
        "capability": "utility-test",
        "owner": "team",
        "systems": [],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "medium",
        "lifecycle": "shadow",
        "criteria": [],
        "oracles": oracles,
        "policies": {"shadow": policy},
    }


class UtilityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.trail = self.root / "trail.jsonl"
        self.manifest = CapabilityManifest.from_dict(manifest_data())

    def record(self, manifest=None, stage="shadow"):
        gate = evaluate_gate(manifest or self.manifest, stage, self.root)
        trail.append(self.trail, gate, actor="ci", at="2026-11-25T00:00:00Z")
        return gate

    def failing(self):
        data = manifest_data()
        data["oracles"][0]["payload"]["command"] = ["false"]
        return CapabilityManifest.from_dict(data)

    def test_required_oracles_are_collected_from_every_stage(self):
        data = manifest_data()
        data["policies"]["production"] = {
            "require": ["a"],
            "approvals": ["b"],
            "allow_merge": True,
        }
        manifest = CapabilityManifest.from_dict(data)
        self.assertEqual(set(required_oracles(manifest)), {"a", "b"})

    def test_a_check_that_never_failed_is_reported_as_a_fact(self):
        for _ in range(3):
            self.record()
        report = build_report(self.manifest, self.trail)
        self.assertEqual(report.entries, 3)
        self.assertEqual(report.never_failed, ["a", "b"])
        text = render_report(report)
        self.assertIn("never observed a failure: a, b", text)
        self.assertIn("this is a fact, not a verdict", text)

    def test_a_check_that_failed_is_not_reported_as_never_failing(self):
        self.record()
        self.record(self.failing())
        report = build_report(self.manifest, self.trail)
        stats = {item.id: item for item in report.oracles}
        self.assertEqual(stats["a"].runs, 2)
        self.assertEqual(stats["a"].fails, 1)
        self.assertEqual(stats["a"].passed, 1)
        self.assertEqual(report.never_failed, ["b"])

    def test_stage_counts(self):
        self.record()
        self.record(self.failing())
        report = build_report(self.manifest, self.trail)
        stage = report.stages[0]
        self.assertEqual((stage.runs, stage.passes, stage.fails), (2, 1, 1))

    def test_a_required_oracle_never_recorded_is_named(self):
        # The trail was recorded before `spare` became required.
        self.record()
        data = manifest_data()
        data["policies"]["shadow"]["require"] = ["a", "b", "spare"]
        manifest = CapabilityManifest.from_dict(data)
        report = build_report(manifest, self.trail)
        self.assertEqual(report.never_recorded, ["spare"])
        self.assertIn("required but never recorded", render_report(report))

    def test_a_declared_oracle_no_policy_uses_is_named(self):
        self.record()
        report = build_report(self.manifest, self.trail)
        self.assertEqual(report.declared_unused, ["spare"])

    def test_another_capability_is_ignored(self):
        data = manifest_data()
        data["capability"] = "other"
        other = CapabilityManifest.from_dict(data)
        self.record(other)
        self.record()
        report = build_report(self.manifest, self.trail)
        self.assertEqual(report.entries, 1)

    def test_no_trail_is_reported_not_invented(self):
        report = build_report(self.manifest, None)
        self.assertFalse(report.errors == [])
        self.assertEqual(report.entries, 0)
        self.assertIn("no trail", render_report(report))

    def test_a_broken_trail_is_not_read(self):
        self.record()
        entry = json.loads(self.trail.read_text(encoding="utf-8"))
        entry["outcome"] = "fail"
        self.trail.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        report = build_report(self.manifest, self.trail)
        self.assertFalse(report.trail_ok)

    def test_cli_json(self):
        self.record()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability", "utility",
                    "--manifest", str(self.write_manifest()),
                    "--trail", str(self.trail),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["entries"], 1)
        self.assertEqual(payload["never_failed"], ["a", "b"])

    def test_cli_reports_a_missing_trail(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability", "utility",
                    "--manifest", str(self.write_manifest()),
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("no trail supplied", out.getvalue())

    def write_manifest(self):
        path = self.root / "capability.json"
        path.write_text(json.dumps(manifest_data()), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
