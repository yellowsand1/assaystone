"""Owner-signed exceptions for individual criteria."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from assaystone import cli, keys, trail
from assaystone.card import build_card
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.receipt import create_receipt
from assaystone.waiver import (
    WaiverError,
    create_waiver,
    load_waivers,
    verify_waivers,
)

KEY = "owner-key"

try:
    import cryptography  # noqa: F401

    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTO = False


def manifest_data(two_criteria=False):
    criteria = [
        {
            "id": "ok",
            "kind": "postcondition",
            "statement": "it works",
            "oracle": "ok",
            "severity": "critical",
        }
    ]
    if two_criteria:
        criteria.append(
            {
                "id": "also",
                "kind": "invariant",
                "statement": "it still works",
                "oracle": "ok",
                "severity": "high",
            }
        )
    return {
        "capability": "waiver-test",
        "owner": "team",
        "systems": [],
        "data_classes": [],
        "irreversible_actions": ["deploy"],
        "risk": "high",
        "lifecycle": "shadow",
        "waivers": True,
        "criteria": criteria,
        "oracles": [
            {"id": "ok", "type": "command", "payload": {"command": ["false"]}}
        ],
        "policies": {
            "shadow": {"require": ["ok"], "allow_merge": False},
            "canary": {"require": ["ok"], "allow_merge": True},
        },
    }


class WaiverTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.manifest_path = self.root / "capability.json"
        self.manifest_path.write_text(
            json.dumps(manifest_data()), encoding="utf-8"
        )
        self.manifest = CapabilityManifest.load(self.manifest_path)
        self.waiver_path = self.root / "capability.waivers.json"

    def write_waiver(self, expires=None, manifest=None, key=KEY):
        manifest = manifest or self.manifest
        expires = expires or (date.today() + timedelta(days=30)).isoformat()
        entry = create_waiver(
            manifest,
            "ok",
            "accepted for the migration window",
            "owner-1",
            key,
            expires,
            at="2026-11-25T00:00:00Z",
        )
        payload = {
            "version": entry["version"],
            "capability": entry["capability"],
            "manifest_digest": entry["manifest_digest"],
            "waivers": [entry],
        }
        self.waiver_path.write_text(json.dumps(payload), encoding="utf-8")
        return entry

    def test_waiver_round_trip(self):
        entry = self.write_waiver()
        check = verify_waivers(load_waivers(self.waiver_path), KEY, self.manifest)
        self.assertTrue(check.ok, check.errors)
        self.assertIn("ok", check.valid)
        self.assertEqual(entry["approved_by"], "owner-1")

    def test_expired_and_tampered_waivers_are_invalid(self):
        self.write_waiver(expires="2000-01-01")
        check = verify_waivers(load_waivers(self.waiver_path), KEY, self.manifest)
        self.assertFalse(check.ok)
        self.assertTrue(any("expired" in item for item in check.errors))

        self.write_waiver()
        data = load_waivers(self.waiver_path)
        data["waivers"][0]["reason"] = "changed"
        check = verify_waivers(data, KEY, self.manifest)
        self.assertFalse(check.ok)
        self.assertTrue(
            any("signature does not verify" in item for item in check.errors)
        )

    def test_waiver_cannot_be_created_for_an_unknown_criterion(self):
        with self.assertRaises(WaiverError):
            create_waiver(
                self.manifest,
                "missing",
                "reason",
                "owner-1",
                KEY,
                date.today().isoformat(),
            )

    def test_gate_passes_with_a_valid_waiver(self):
        self.write_waiver()
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_key=KEY,
        )
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertTrue(gate.merge_allowed)
        self.assertEqual(gate.waived[0]["criterion"], "ok")
        self.assertEqual(gate.waived[0]["approved_by"], "owner-1")

    def test_gate_fails_without_a_waiver(self):
        gate = evaluate_gate(self.manifest, "canary", self.root, owner_key=KEY)
        self.assertEqual(gate.outcome, "fail")
        self.assertEqual(gate.waived, [])

    def test_expired_waiver_does_not_help(self):
        self.write_waiver(expires="2000-01-01")
        gate = evaluate_gate(self.manifest, "canary", self.root, owner_key=KEY)
        self.assertEqual(gate.outcome, "fail")
        self.assertTrue(any("expired" in reason for reason in gate.reasons))

    def test_missing_owner_key_escalates_when_a_waiver_is_needed(self):
        self.write_waiver()
        gate = evaluate_gate(self.manifest, "canary", self.root)
        self.assertEqual(gate.outcome, "escalate")
        self.assertIn("owner key", gate.reasons[0])

    def test_every_criterion_on_the_oracle_must_be_waived(self):
        data = manifest_data(two_criteria=True)
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        manifest = CapabilityManifest.load(self.manifest_path)
        self.write_waiver(manifest=manifest)
        gate = evaluate_gate(manifest, "canary", self.root, owner_key=KEY)
        self.assertEqual(gate.outcome, "fail")
        self.assertEqual(gate.waived, [])

    def test_waivers_do_not_cover_an_escalation(self):
        data = manifest_data()
        data["oracles"] = [
            {
                "id": "ok",
                "type": "command",
                "payload": {"command": ["definitely-not-a-command-xyz"]},
            }
        ]
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        manifest = CapabilityManifest.load(self.manifest_path)
        self.write_waiver(manifest=manifest)
        gate = evaluate_gate(manifest, "canary", self.root, owner_key=KEY)
        self.assertEqual(gate.outcome, "escalate")

    def test_trail_receipt_and_card_record_the_waiver(self):
        entry = self.write_waiver()
        gate = evaluate_gate(self.manifest, "canary", self.root, owner_key=KEY)
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
        self.assertEqual(receipt["waived"][0]["criterion"], "ok")
        card = build_card(
            self.manifest,
            stage="canary",
            trail_path=trail_path,
            waivers_path=self.waiver_path,
            owner_key=KEY,
        )
        self.assertTrue(card.waivers["ok"])
        self.assertTrue(
            any(
                "is waived until" in risk
                for risk in card.residual_risks
            )
        )
        self.assertEqual(entry["criterion"], "ok")

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
    def test_ed25519_waiver(self):
        private = self.root / "owner.key"
        public = self.root / "owner.pub"
        keys.generate(private, public)
        expires = (date.today() + timedelta(days=30)).isoformat()
        entry = create_waiver(
            self.manifest,
            "ok",
            "migration window",
            "owner-1",
            "",
            expires,
            private_key_path=private,
            at="2026-11-25T00:00:00Z",
        )
        payload = {
            "version": entry["version"],
            "capability": entry["capability"],
            "manifest_digest": entry["manifest_digest"],
            "waivers": [entry],
        }
        self.waiver_path.write_text(json.dumps(payload), encoding="utf-8")
        gate = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=public,
        )
        self.assertEqual(entry["key_id"], keys.key_id(public))
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertEqual(gate.waived[0]["criterion"], "ok")

        missing = evaluate_gate(self.manifest, "canary", self.root)
        self.assertEqual(missing.outcome, "escalate")

        other_private = self.root / "other.key"
        other_public = self.root / "other.pub"
        keys.generate(other_private, other_public)
        wrong = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=other_public,
        )
        self.assertEqual(wrong.outcome, "fail")

        body = {
            key: value
            for key, value in entry.items()
            if key != "signature"
        }
        body["key_id"] = "sha256:not-the-key"
        body["signature"] = keys.sign_body(body, private_key_path=private)
        payload["waivers"] = [body]
        self.waiver_path.write_text(json.dumps(payload), encoding="utf-8")
        mismatch = evaluate_gate(
            self.manifest,
            "canary",
            self.root,
            owner_public_key=public,
        )
        self.assertEqual(mismatch.outcome, "fail")
        self.assertTrue(
            any("key_id" in reason for reason in mismatch.reasons)
        )

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
    def test_cli_ed25519_waive_and_gate(self):
        private = self.root / "owner.key"
        public = self.root / "owner.pub"
        keys.generate(private, public)
        expires = (date.today() + timedelta(days=30)).isoformat()
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "capability",
                        "waive",
                        "--manifest",
                        str(self.manifest_path),
                        "--criterion",
                        "ok",
                        "--reason",
                        "migration window",
                        "--expires",
                        expires,
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
                        "canary",
                        "--root",
                        str(self.root),
                        "--owner-public-key",
                        str(public),
                        "--json",
                    ]
                )
        self.assertEqual(code, 0)

    def test_cli_waive_gate_and_status(self):
        expires = (date.today() + timedelta(days=30)).isoformat()
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ASSAYSTONE_OWNER_KEY": KEY}):
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "capability",
                        "waive",
                        "--manifest",
                        str(self.manifest_path),
                        "--criterion",
                        "ok",
                        "--reason",
                        "migration window",
                        "--expires",
                        expires,
                        "--approver",
                        "owner-1",
                    ]
                )
        self.assertEqual(code, 0, out.getvalue())
        self.assertTrue(self.waiver_path.exists())

        with mock.patch.dict(os.environ, {"ASSAYSTONE_OWNER_KEY": KEY}):
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(
                    [
                        "gate",
                        "--manifest",
                        str(self.manifest_path),
                        "--stage",
                        "canary",
                        "--root",
                        str(self.root),
                        "--json",
                    ]
                )
        self.assertEqual(code, 0)

        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ASSAYSTONE_OWNER_KEY": KEY}):
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "capability",
                        "status",
                        "--manifest",
                        str(self.manifest_path),
                        "--stage",
                        "canary",
                        "--json",
                    ]
                )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["waivers"]["valid"][0]["criterion"], "ok")


if __name__ == "__main__":
    unittest.main()
