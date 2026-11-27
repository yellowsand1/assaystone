"""What the environment still owes the gate."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.drill import run_drill
from assaystone.drill import write_record as write_drill
from assaystone.plane import CapabilityManifest
from assaystone.prepare import prepare, render


def data(policy, oracles, criteria=None):
    return {
        "capability": "prep-test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": [],
        "irreversible_actions": ["deploy"],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": criteria or [],
        "oracles": oracles,
        "policies": {"canary": policy},
    }


HUMAN = {
    "id": "approval",
    "type": "human",
    "payload": {"action": "promote", "record": "approvals.json"},
}


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def manifest(self, oracles=None, policy=None, **extra):
        return CapabilityManifest.from_dict(
            {
                **data(
                    policy or {"require": [], "approvals": ["approval"],
                               "allow_merge": True},
                    oracles or [HUMAN],
                ),
                **extra,
            }
        )

    def test_a_missing_approval_record_is_reported_with_its_shape(self):
        result = prepare(self.manifest(), "canary", self.root)
        self.assertFalse(result.ready)
        need = result.needs[0]
        self.assertEqual(need.kind, "approval-record")
        self.assertEqual(need.actor, "approver")
        payload = json.loads(need.snippet)
        self.assertEqual(payload["approvals"][0]["action"], "promote")
        self.assertIn("approvals.json", render(result))

    def test_an_approval_for_another_action_is_not_enough(self):
        (self.root / "approvals.json").write_text(
            json.dumps({"approvals": [{"action": "refund", "approved": True}]}),
            encoding="utf-8",
        )
        result = prepare(self.manifest(), "canary", self.root)
        self.assertEqual(result.needs[0].kind, "approval-record")
        self.assertIn("no `promote` approval", result.needs[0].detail)

    def test_a_denied_approval_is_reported(self):
        (self.root / "approvals.json").write_text(
            json.dumps(
                {"approvals": [{"action": "promote", "approved": False}]}
            ),
            encoding="utf-8",
        )
        result = prepare(self.manifest(), "canary", self.root)
        self.assertEqual(result.needs[0].kind, "approval-denied")

    def test_an_unsigned_record_when_signing_is_required(self):
        oracle = {
            "id": "approval",
            "type": "human",
            "payload": {
                "action": "promote",
                "record": "approvals.json",
                "hmac_env": "OWNER_KEY",
            },
        }
        (self.root / "approvals.json").write_text(
            json.dumps(
                {"approvals": [{"action": "promote", "approved": True}]}
            ),
            encoding="utf-8",
        )
        result = prepare(self.manifest([oracle]), "canary", self.root)
        self.assertEqual(result.needs[0].kind, "approval-unsigned")

    def test_a_granted_approval_is_ready(self):
        (self.root / "approvals.json").write_text(
            json.dumps(
                {"approvals": [{"action": "promote", "approved": True}]}
            ),
            encoding="utf-8",
        )
        self.assertTrue(prepare(self.manifest(), "canary", self.root).ready)

    def test_a_missing_drill_record_points_at_the_drill(self):
        drill = {
            "id": "check",
            "type": "drill",
            "payload": {"manifest": "capability.json", "id": "build-dist"},
        }
        manifest = self.manifest([drill], {"require": ["check"], "allow_merge": True})
        result = prepare(manifest, "canary", self.root)
        need = result.needs[0]
        self.assertEqual(need.kind, "drill-missing")
        self.assertIn("capability drill", need.command)

    def test_a_failed_drill_is_reported(self):
        (self.root / "artifact.txt").write_text("x\n", encoding="utf-8")
        (self.root / "capability.json").write_text(
            json.dumps(
                {
                    **data(
                        {
                            "require": ["do", "undo", "check"],
                            "allow_merge": True,
                        },
                        [
                            {"id": "do", "type": "command",
                             "payload": {"command": ["sh", "-c", "echo y >> artifact.txt"]}},
                            {"id": "undo", "type": "command",
                             "payload": {"command": ["true"]}},
                            {"id": "check", "type": "drill",
                             "payload": {"manifest": "capability.json",
                                         "id": "make-artifact"}},
                        ],
                    ),
                    "reversibility": [
                        {"id": "make-artifact", "action": "do",
                         "compensation": "undo", "state": ["artifact.txt"]}
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifest = CapabilityManifest.load(self.root / "capability.json")
        failed = run_drill(manifest, "make-artifact", self.root)
        write_drill(manifest, failed, self.root, actor="ci")
        result = prepare(manifest, "canary", self.root)
        self.assertEqual(result.needs[0].kind, "drill-failed")

    def test_a_missing_session_record_points_at_the_hook(self):
        runtime = {
            "id": "session",
            "type": "runtime",
            "payload": {"record": ".assaystone/runtime/last.json"},
        }
        manifest = self.manifest([runtime], {"require": ["session"], "allow_merge": True})
        result = prepare(manifest, "canary", self.root)
        need = result.needs[0]
        self.assertEqual(need.kind, "session-record")
        self.assertIn("hook install", need.command)

    def test_no_policy_is_reported(self):
        manifest = CapabilityManifest.from_dict(
            data({"shadow": {"require": []}}, [HUMAN])
        )
        result = prepare(manifest, "production", self.root)
        self.assertEqual(result.needs[0].kind, "no-policy")

    def test_cli_json(self):
        (self.root / "capability.json").write_text(
            json.dumps(
                data(
                    {"require": [], "approvals": ["approval"], "allow_merge": True},
                    [HUMAN],
                )
            ),
            encoding="utf-8",
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability", "prepare",
                    "--manifest", str(self.root / "capability.json"),
                    "--stage", "canary",
                    "--root", str(self.root),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["needs"][0]["kind"], "approval-record")


if __name__ == "__main__":
    unittest.main()
