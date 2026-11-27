"""Applying the next-step patch, and refusing to invent what needs a person."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.nextstep import apply_patches, plan
from assaystone.plane import CapabilityManifest


def data(policies, criteria=None):
    return {
        "capability": "apply-test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": criteria or [],
        "oracles": [
            {"id": "build", "type": "command", "payload": {"command": ["true"]}},
            {"id": "audit", "type": "command", "payload": {"command": ["true"]}},
        ],
        "policies": policies,
    }


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / "capability.json"

    def write(self, **kwargs):
        self.path.write_text(json.dumps(data(**kwargs)), encoding="utf-8")
        return CapabilityManifest.load(self.path)

    def run_cli(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                ["capability", "next", "--manifest", str(self.path), *extra]
            )
        return code, out.getvalue()

    def test_apply_unlocks_a_locked_stage(self):
        self.write(policies={
            "shadow": {"require": ["build"]},
            "canary": {"require": ["build"], "allow_merge": False},
        })
        code, out = self.run_cli("--stage", "canary", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("added oracle `reviewer`", out)
        self.assertIn("allows merging", out)
        manifest = CapabilityManifest.load(self.path)
        self.assertTrue(manifest.policies["canary"].allow_merge)
        self.assertEqual(manifest.policies["canary"].approvals, ["reviewer"])
        self.assertIn("reviewer", {item.id for item in manifest.oracles})

    def test_apply_adds_a_missing_stage(self):
        self.write(policies={"shadow": {"require": ["build"]}})
        code, out = self.run_cli("--stage", "canary", "--apply")
        self.assertEqual(code, 0, out)
        manifest = CapabilityManifest.load(self.path)
        self.assertIn("canary", manifest.policies)
        self.assertTrue(manifest.policies["canary"].allow_merge)

    def test_apply_gates_an_ungated_criterion(self):
        criteria = [
            {
                "id": "api-stable",
                "kind": "invariant",
                "statement": "the API is stable",
                "oracle": "audit",
                "severity": "critical",
            }
        ]
        self.write(
            policies={
                "shadow": {"require": ["build"]},
                "canary": {
                    "require": ["build"],
                    "approvals": ["build"],
                    "allow_merge": True,
                },
            },
            criteria=criteria,
        )
        code, out = self.run_cli("--stage", "canary", "--apply")
        self.assertEqual(code, 0, out)
        manifest = CapabilityManifest.load(self.path)
        self.assertIn("audit", manifest.policies["canary"].require)

    def test_a_deploy_policy_without_rollback_is_refused_by_validate(self):
        # The planner never has to invent compensation: validate refuses a
        # manifest that allows deploy without rollback evidence in the first
        # place, so the only honest path is to add a real one.
        from assaystone.plane import PlaneError

        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(
                data(
                    {
                        "shadow": {"require": ["build"]},
                        "production": {
                            "require": ["build"],
                            "approvals": ["build"],
                            "allow_merge": True,
                            "allow_deploy": True,
                        },
                    }
                )
            )

    def test_applying_twice_changes_nothing(self):
        self.write(policies={
            "shadow": {"require": ["build"]},
            "canary": {"require": ["build"], "allow_merge": False},
        })
        self.run_cli("--stage", "canary", "--apply")
        before = self.path.read_text(encoding="utf-8")
        code, out = self.run_cli("--stage", "canary", "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_apply_reports_an_invalid_result(self):
        # A policy that names an approval oracle the manifest lacks cannot be
        # repaired by adding flags alone; the result must be refused.
        self.write(policies={
            "shadow": {"require": ["build"]},
            "canary": {"require": ["build"], "allow_merge": False},
        })
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["oracles"] = [
            item for item in raw["oracles"] if item["id"] != "reviewer"
        ]
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        code, out = self.run_cli("--stage", "canary", "--apply")
        self.assertEqual(code, 0, out)
        CapabilityManifest.load(self.path)

    def test_apply_patches_is_idempotent(self):
        manifest = CapabilityManifest.from_dict(
            data({"shadow": {"require": ["build"]}, "canary": {
                "require": ["build"], "allow_merge": False}})
        )
        raw = json.loads(json.dumps(data({
            "shadow": {"require": ["build"]},
            "canary": {"require": ["build"], "allow_merge": False},
        })))
        first, _ = apply_patches(raw, plan(manifest, target="canary"))
        second, _ = apply_patches(raw, plan(manifest, target="canary"))
        self.assertTrue(first)
        self.assertEqual(second, [])

    def test_no_appliable_blocker_says_so(self):
        self.write(policies={
            "shadow": {"require": ["build"]},
            "canary": {
                "require": ["build"],
                "approvals": ["build"],
                "allow_merge": True,
            },
        })
        code, out = self.run_cli("--stage", "canary", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("nothing to apply", out)


if __name__ == "__main__":
    unittest.main()
