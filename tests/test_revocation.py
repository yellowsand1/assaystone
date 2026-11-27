"""Key revocation: a committed list of ids that must no longer be trusted."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from assaystone import cli, keys, trail
from assaystone.approval import approval_path_for, create_approval
from assaystone.card import build_card
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.receipt import create_receipt, verify_receipt
from assaystone.revocation import read_revocations
from assaystone.waiver import create_waiver, waiver_path_for

try:
    import cryptography  # noqa: F401

    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTO = False


def manifest_data():
    return {
        "capability": "revocation-test",
        "owner": "team",
        "systems": [],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "high",
        "lifecycle": "shadow",
        "manifest_approval": True,
        "waivers": True,
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
            {"id": "ok", "type": "command", "payload": {"command": ["false"]}}
        ],
        "policies": {"canary": {"require": ["ok"], "allow_merge": True}},
    }


@unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
class RevocationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.manifest_path = self.root / "capability.json"
        self.manifest_path.write_text(
            json.dumps(manifest_data()), encoding="utf-8"
        )
        self.manifest = CapabilityManifest.load(self.manifest_path)
        self.owner_private = self.root / "owner.key"
        self.owner_public = self.root / "owner.pub"
        keys.generate(self.owner_private, self.owner_public)
        self.owner_id = keys.key_id(self.owner_public)
        self.revocations = self.root / "capability.revocations.json"

    def approve(self):
        approval = create_approval(
            self.manifest,
            "owner-1",
            private_key_path=self.owner_private,
            at="2026-11-25T00:00:00Z",
        )
        approval_path_for(self.manifest).write_text(
            json.dumps(approval), encoding="utf-8"
        )
        return approval

    def waive(self):
        entry = create_waiver(
            self.manifest,
            "ok",
            "migration window",
            "owner-1",
            "",
            (date.today() + timedelta(days=30)).isoformat(),
            private_key_path=self.owner_private,
            at="2026-11-25T00:00:00Z",
        )
        waiver_path_for(self.manifest).write_text(
            json.dumps(
                {
                    "version": entry["version"],
                    "capability": entry["capability"],
                    "manifest_digest": entry["manifest_digest"],
                    "waivers": [entry],
                }
            ),
            encoding="utf-8",
        )
        return entry

    def revoke(self, key_id, reason="laptop lost"):
        self.revocations.write_text(
            json.dumps(
                {
                    "version": 1,
                    "revoked": [
                        {"key_id": key_id, "reason": reason, "at": "2026-11-25"}
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_a_valid_approval_and_waiver_pass(self):
        self.approve()
        self.waive()
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=self.owner_public,
        )
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertEqual(gate.revoked, [])

    def test_a_revoked_owner_key_escalates(self):
        self.approve()
        self.waive()
        self.revoke(self.owner_id)
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=self.owner_public,
        )
        self.assertEqual(gate.outcome, "escalate")
        self.assertTrue(gate.revoked)
        reasons = " ".join(gate.reasons)
        self.assertIn("revoked", reasons)
        self.assertIn("laptop lost", reasons)
        self.assertFalse(gate.merge_allowed)

    def test_an_unreadable_revocation_list_escalates(self):
        self.approve()
        self.waive()
        self.revocations.write_text("{not json", encoding="utf-8")
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=self.owner_public,
        )
        self.assertEqual(gate.outcome, "escalate")
        self.assertIn("revocation list", gate.reasons[0])

    def test_an_unrelated_key_can_be_revoked_safely(self):
        self.approve()
        self.waive()
        other_private = self.root / "other.key"
        other_public = self.root / "other.pub"
        keys.generate(other_private, other_public)
        self.revoke(keys.key_id(other_public))
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=self.owner_public,
        )
        self.assertEqual(gate.outcome, "pass", gate.reasons)

    def test_artifacts_are_checked_per_key(self):
        self.revoke(self.owner_id)
        check = read_revocations(self.revocations)
        self.assertTrue(check.ok)
        self.assertIsNotNone(check.is_revoked(self.owner_id))
        self.assertIsNone(check.is_revoked("sha256:someone-else"))

    def test_a_revocation_needs_a_reason(self):
        self.revocations.write_text(
            json.dumps({"version": 1, "revoked": [{"key_id": self.owner_id}]}),
            encoding="utf-8",
        )
        check = read_revocations(self.revocations)
        self.assertFalse(check.ok)
        self.assertTrue(any("reason" in error for error in check.errors))

    def test_trail_and_receipt_record_the_escalation(self):
        self.approve()
        self.waive()
        self.revoke(self.owner_id)
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=self.owner_public,
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
        self.assertEqual(receipt["outcome"], "escalate")
        self.assertTrue(receipt["revoked"])
        self.assertTrue(verify_receipt(receipt, "receipt-key").ok)

    def test_status_card_reports_a_revoked_artifact(self):
        self.approve()
        self.waive()
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=self.owner_public,
        )
        receipt_path = self.root / "receipt.json"
        receipt_path.write_text(
            json.dumps(
                create_receipt(
                    gate,
                    self.root,
                    "receipt-key",
                    actor="ci",
                    at="2026-11-25T00:01:00Z",
                )
            ),
            encoding="utf-8",
        )
        self.revoke(self.owner_id)
        card = build_card(
            self.manifest,
            stage="canary",
            receipt_path=receipt_path,
            owner_public_key=self.owner_public,
            receipt_key="receipt-key",
        )
        self.assertTrue(card.revocations["revoked_artifacts"])
        self.assertTrue(
            any("revoked key" in risk for risk in card.residual_risks)
        )

    def test_cli_gate_with_revocations(self):
        self.approve()
        self.waive()
        self.revoke(self.owner_id)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "gate",
                    "--manifest",
                    str(self.manifest_path),
                    "--stage",
                    "canary",
                    "--root",
                    str(self.root),
                    "--owner-public-key",
                    str(self.owner_public),
                    "--json",
                ]
            )
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["outcome"], "escalate")
        self.assertTrue(payload["revoked"])


if __name__ == "__main__":
    unittest.main()
