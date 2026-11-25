"""The acceptance plane: generic oracles and lifecycle gates."""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.plane import (
    CapabilityManifest,
    PlaneError,
    evaluate_gate,
    run_oracle,
)


def base(oracles, policies, criteria=None):
    return {
        "capability": "test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": ["internal"],
        "irreversible_actions": ["merge"],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": criteria or [],
        "oracles": oracles,
        "policies": policies,
    }


def command_oracle(name, code, expect=0):
    return {
        "id": name,
        "type": "command",
        "payload": {
            "command": [sys.executable, "-c", code],
            "expect_exit": expect,
        },
    }


class ManifestTest(unittest.TestCase):
    def test_valid_manifest(self):
        manifest = CapabilityManifest.from_dict(
            base(
                [command_oracle("ok", "print('ok')")],
                {"shadow": {"require": ["ok"]}},
            )
        )
        self.assertEqual(manifest.capability, "test")
        self.assertEqual(manifest.validate(), [])

    def test_missing_owner_is_rejected(self):
        data = base([], {"shadow": {}})
        data["owner"] = ""
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

    def test_unknown_oracle_type_is_rejected(self):
        data = base(
            [{"id": "x", "type": "magic", "payload": {}}],
            {"shadow": {"require": ["x"]}},
        )
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

    def test_policy_references_unknown_oracle(self):
        data = base(
            [command_oracle("ok", "print('ok')")],
            {"shadow": {"require": ["missing"]}},
        )
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

    def test_duplicate_oracle_id_is_rejected(self):
        data = base(
            [command_oracle("x", "print(1)"), command_oracle("x", "print(2)")],
            {"shadow": {"require": ["x"]}},
        )
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)


class OracleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_command_pass_and_fail(self):
        spec = CapabilityManifest.from_dict(
            base(
                [command_oracle("ok", "print('ok')")],
                {"shadow": {"require": ["ok"]}},
            )
        ).oracles[0]
        self.assertEqual(run_oracle(spec, self.root).outcome, "pass")

        failing = CapabilityManifest.from_dict(
            base(
                [command_oracle("bad", "raise SystemExit(3)", expect=0)],
                {"shadow": {"require": ["bad"]}},
            )
        ).oracles[0]
        self.assertEqual(run_oracle(failing, self.root).outcome, "fail")

    def test_missing_command_escalates(self):
        manifest = CapabilityManifest.from_dict(
            base(
                [
                    {
                        "id": "nope",
                        "type": "command",
                        "payload": {"command": ["definitely-not-a-command-xyz"]},
                    }
                ],
                {"shadow": {"require": ["nope"]}},
            )
        )
        self.assertEqual(run_oracle(manifest.oracles[0], self.root).outcome, "escalate")

    def test_file_oracle(self):
        (self.root / "artifact.json").write_text('{"ok": true}', encoding="utf-8")
        manifest = CapabilityManifest.from_dict(
            base(
                [
                    {"id": "f", "type": "file", "payload": {"path": "artifact.json", "mode": "json"}},
                    {"id": "missing", "type": "file", "payload": {"path": "nope.json"}},
                ],
                {"shadow": {"require": ["f", "missing"]}},
            )
        )
        self.assertEqual(run_oracle(manifest.oracles[0], self.root).outcome, "pass")
        self.assertEqual(run_oracle(manifest.oracles[1], self.root).outcome, "fail")

    def test_human_oracle(self):
        (self.root / "approvals.json").write_text(
            json.dumps(
                {"approvals": [{"action": "ddl", "approved": True, "approver": "dba-1"}]}
            ),
            encoding="utf-8",
        )
        manifest = CapabilityManifest.from_dict(
            base(
                [{"id": "dba", "type": "human", "payload": {"action": "ddl"}}],
                {"shadow": {"require": ["dba"]}},
            )
        )
        result = run_oracle(manifest.oracles[0], self.root)
        self.assertEqual(result.outcome, "pass")
        self.assertIn("dba-1", result.evidence)

    def test_missing_approval_escalates(self):
        manifest = CapabilityManifest.from_dict(
            base(
                [{"id": "dba", "type": "human", "payload": {"action": "ddl"}}],
                {"shadow": {"require": ["dba"]}},
            )
        )
        self.assertEqual(
            run_oracle(manifest.oracles[0], self.root).outcome, "escalate"
        )

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_git_oracle(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        (self.root / "a.txt").write_text("a\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "init"],
            cwd=self.root,
            check=True,
        )
        manifest = CapabilityManifest.from_dict(
            base(
                [
                    {"id": "branch", "type": "git", "payload": {"mode": "branch", "expected": "main"}},
                    {"id": "clean", "type": "git", "payload": {"mode": "clean"}},
                ],
                {"shadow": {"require": ["branch", "clean"]}},
            )
        )
        self.assertEqual(run_oracle(manifest.oracles[0], self.root).outcome, "pass")
        self.assertEqual(run_oracle(manifest.oracles[1], self.root).outcome, "pass")


class GateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_shadow_passes_but_cannot_merge(self):
        manifest = CapabilityManifest.from_dict(
            base(
                [command_oracle("ok", "print('ok')")],
                {"shadow": {"require": ["ok"], "allow_merge": False}},
            )
        )
        result = evaluate_gate(manifest, "shadow", self.root)
        self.assertEqual(result.outcome, "pass")
        self.assertFalse(result.merge_allowed)

    def test_canary_fails_on_a_failing_oracle(self):
        manifest = CapabilityManifest.from_dict(
            base(
                [command_oracle("bad", "raise SystemExit(2)")],
                {"canary": {"require": ["bad"], "allow_merge": True}},
            )
        )
        result = evaluate_gate(manifest, "canary", self.root)
        self.assertEqual(result.outcome, "fail")
        self.assertFalse(result.merge_allowed)

    def test_production_escalates_without_approval(self):
        manifest = CapabilityManifest.from_dict(
            base(
                [{"id": "dba", "type": "human", "payload": {"action": "ddl"}}],
                {
                    "production": {
                        "require": [],
                        "approvals": ["dba"],
                        "allow_merge": True,
                        "allow_deploy": True,
                    }
                },
            )
        )
        result = evaluate_gate(manifest, "production", self.root)
        self.assertEqual(result.outcome, "escalate")
        self.assertFalse(result.deploy_allowed)

    def test_missing_stage_policy_escalates(self):
        manifest = CapabilityManifest.from_dict(
            base([command_oracle("ok", "print('ok')")], {"shadow": {"require": ["ok"]}})
        )
        result = evaluate_gate(manifest, "canary", self.root)
        self.assertEqual(result.outcome, "escalate")


class PlaneCliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.path = self.root / "capability.json"
        self.path.write_text(
            json.dumps(
                base(
                    [command_oracle("ok", "print('ok')")],
                    {"shadow": {"require": ["ok"]}},
                )
            ),
            encoding="utf-8",
        )

    def test_capability_validate(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["capability", "validate", "--manifest", str(self.path)])
        self.assertEqual(code, 0)
        self.assertIn("capability test: ok", out.getvalue())

    def test_gate_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "gate",
                    "--manifest",
                    str(self.path),
                    "--stage",
                    "shadow",
                    "--root",
                    str(self.root),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["outcome"], "pass")


if __name__ == "__main__":
    unittest.main()
