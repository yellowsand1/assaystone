"""Owner approval of the acceptance criteria."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assaystone import cli, keys, trail
from assaystone.approval import (
    ApprovalError,
    approval_path_for,
    create_approval,
    verify_approval,
)
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.receipt import create_receipt

try:
    import cryptography  # noqa: F401

    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTO = False

OWNER_KEY = "owner-key"


def manifest_data(capability="approval-test"):
    return {
        "capability": capability,
        "owner": "team",
        "systems": ["git"],
        "data_classes": ["internal"],
        "irreversible_actions": ["merge"],
        "risk": "high",
        "lifecycle": "shadow",
        "manifest_approval": True,
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


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.manifest_path = self.root / "capability.json"
        self.manifest_path.write_text(
            json.dumps(manifest_data()), encoding="utf-8"
        )
        self.manifest = CapabilityManifest.load(self.manifest_path)

    def approve(self, key=OWNER_KEY, manifest=None):
        manifest = manifest or self.manifest
        return create_approval(manifest, "owner-1", key, at="2026-11-25T00:00:00Z")

    def test_round_trip(self):
        approval = self.approve()
        check = verify_approval(approval, OWNER_KEY, self.manifest)
        self.assertTrue(check.ok, check.errors)
        self.assertTrue(check.info["verified"])
        self.assertEqual(check.info["approved_by"], "owner-1")
        self.assertEqual(
            approval["manifest_digest"], self.manifest and check.info["manifest_digest"]
        )

    def test_tampering_and_wrong_key_fail(self):
        approval = self.approve()
        approval["approved_by"] = "someone-else"
        self.assertFalse(verify_approval(approval, OWNER_KEY, self.manifest).ok)
        fresh = self.approve()
        self.assertFalse(verify_approval(fresh, "other", self.manifest).ok)

    def test_digest_mismatch_fails(self):
        approval = self.approve()
        changed = manifest_data()
        changed["criteria"].append(
            {
                "id": "extra",
                "kind": "invariant",
                "statement": "another rule",
                "oracle": "ok",
                "severity": "high",
            }
        )
        self.manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        manifest = CapabilityManifest.load(self.manifest_path)
        check = verify_approval(approval, OWNER_KEY, manifest)
        self.assertFalse(check.ok)
        self.assertTrue(
            any("digest" in error for error in check.errors)
        )

    def test_manifest_approval_is_part_of_the_digest(self):
        before = CapabilityManifest.load(self.manifest_path)
        data = manifest_data()
        data["manifest_approval"] = False
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        after = CapabilityManifest.load(self.manifest_path)
        from assaystone.plane import manifest_digest

        self.assertNotEqual(manifest_digest(before), manifest_digest(after))
        with self.assertRaises(ApprovalError):
            create_approval(after, "owner-1", OWNER_KEY)

    def test_gate_requires_a_valid_approval(self):
        escalation = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(escalation.outcome, "escalate")
        self.assertIn("approval", escalation.reasons[0])

        approval_path = approval_path_for(self.manifest)
        approval_path.write_text(
            json.dumps(self.approve()), encoding="utf-8"
        )
        no_key = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(no_key.outcome, "escalate")
        self.assertIn("key", no_key.reasons[0])

        allowed = evaluate_gate(
            self.manifest,
            "shadow",
            self.root,
            owner_key=OWNER_KEY,
        )
        self.assertEqual(allowed.outcome, "pass", allowed.reasons)
        self.assertTrue(allowed.manifest_approval["verified"])
        self.assertEqual(allowed.manifest_approval["approved_by"], "owner-1")

    def test_gate_rejects_a_changed_manifest(self):
        approval_path = approval_path_for(self.manifest)
        approval_path.write_text(
            json.dumps(self.approve()), encoding="utf-8"
        )
        data = manifest_data()
        data["criteria"][0]["statement"] = "something else"
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        changed = CapabilityManifest.load(self.manifest_path)
        result = evaluate_gate(
            changed, "shadow", self.root, owner_key=OWNER_KEY
        )
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("digest", " ".join(result.reasons))
        self.assertFalse(result.manifest_approval["verified"])

    def test_receipt_records_the_approval(self):
        approval_path = approval_path_for(self.manifest)
        approval_path.write_text(
            json.dumps(self.approve()), encoding="utf-8"
        )
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, owner_key=OWNER_KEY
        )
        trail_path = self.root / "trail.jsonl"
        trail.append(trail_path, gate, actor="ci", at="2026-11-25T00:00:00Z")
        receipt = create_receipt(
            gate,
            self.root,
            "receipt-key",
            actor="ci",
            trail_path=trail_path,
            at="2026-11-25T00:01:00Z",
        )
        self.assertEqual(
            receipt["manifest_approval"]["approved_by"], "owner-1"
        )
        self.assertTrue(receipt["manifest_approval"]["verified"])

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
    def test_ed25519_owner_approval(self):
        private = self.root / "owner.key"
        public = self.root / "owner.pub"
        keys.generate(private, public)
        approval = create_approval(
            self.manifest,
            "owner-1",
            private_key_path=private,
            at="2026-11-25T00:00:00Z",
        )
        (self.root / "capability.approval.json").write_text(
            json.dumps(approval), encoding="utf-8"
        )
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, owner_public_key=public
        )
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertTrue(gate.manifest_approval["verified"])
        self.assertEqual(gate.manifest_approval["scheme"], "ed25519")

        missing = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(missing.outcome, "escalate")
        self.assertIn("public key", missing.reasons[0])

        other_private = self.root / "other.key"
        other_public = self.root / "other.pub"
        keys.generate(other_private, other_public)
        wrong = evaluate_gate(
            self.manifest, "shadow", self.root, owner_public_key=other_public
        )
        self.assertEqual(wrong.outcome, "escalate")

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
    def test_cli_ed25519_accept_and_gate(self):
        private = self.root / "owner.key"
        public = self.root / "owner.pub"
        keys.generate(private, public)
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "capability",
                        "accept",
                        "--manifest",
                        str(self.manifest_path),
                        "--approver",
                        "owner-1",
                        "--private-key-file",
                        str(private),
                    ]
                )
        self.assertEqual(code, 0)
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "gate",
                        "--manifest",
                        str(self.manifest_path),
                        "--stage",
                        "shadow",
                        "--root",
                        str(self.root),
                        "--owner-public-key",
                        str(public),
                        "--json",
                    ]
                )
        self.assertEqual(code, 0)

    def test_cli_accept_and_gate(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ASSAYSTONE_OWNER_KEY": OWNER_KEY}):
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "capability",
                        "accept",
                        "--manifest",
                        str(self.manifest_path),
                        "--approver",
                        "owner-1",
                    ]
                )
        self.assertEqual(code, 0, out.getvalue())
        self.assertTrue((self.root / "capability.approval.json").exists())

        with mock.patch.dict(os.environ, {"ASSAYSTONE_OWNER_KEY": OWNER_KEY}):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "gate",
                        "--manifest",
                        str(self.manifest_path),
                        "--stage",
                        "shadow",
                        "--root",
                        str(self.root),
                        "--json",
                    ]
                )
        self.assertEqual(code, 0)

        with mock.patch.dict(os.environ, {}, clear=True):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(
                    [
                        "capability",
                        "accept",
                        "--manifest",
                        str(self.manifest_path),
                        "--out",
                        str(self.root / "other.json"),
                    ]
                )
        self.assertEqual(code, 2)
        self.assertIn("ASSAYSTONE_OWNER_KEY", err.getvalue())

    def test_brief_names_the_owner_approval(self):
        from assaystone.brief import render_brief

        text = render_brief(self.manifest)
        self.assertIn("Owner approval: required", text)


if __name__ == "__main__":
    unittest.main()
