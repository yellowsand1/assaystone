"""Signed gate receipts: binding, signature, and offline verification."""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assaystone import cli, keys, trail
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.receipt import ReceiptError, create_receipt, verify_receipt

KEY = "receipt-test-key"


def manifest_data():
    return {
        "capability": "receipt-test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": ["internal"],
        "irreversible_actions": ["merge"],
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


try:
    import cryptography  # noqa: F401

    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover
    HAVE_CRYPTO = False


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=a@b.c",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-qm",
                "init",
            ],
            cwd=self.root,
            check=True,
        )
        self.manifest = CapabilityManifest.from_dict(manifest_data())
        self.gate = evaluate_gate(self.manifest, "shadow", self.root)
        self.trail = self.base / "trail.jsonl"
        trail.append(self.trail, self.gate, actor="ci", at="2026-11-25T00:00:00Z")

    def receipt(self, key=KEY):
        return create_receipt(
            self.gate,
            self.root,
            key,
            actor="ci",
            trail_path=self.trail,
            at="2026-11-25T00:01:00Z",
        )

    def test_round_trip_binds_commit_manifest_and_trail(self):
        receipt = self.receipt()
        commit = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        check = verify_receipt(
            receipt,
            KEY,
            expected_commit=commit,
            expected_manifest_digest=self.gate.manifest_digest,
            expected_outcome="pass",
        )
        self.assertTrue(check.ok, check.errors)
        self.assertEqual(receipt["trail_head"], trail.verify(self.trail).head)
        self.assertEqual(receipt["trail_entries"], 1)
        self.assertFalse(receipt["dirty"])
        self.assertEqual(receipt["oracles"][0]["outcome"], "pass")

    def test_tampering_any_field_breaks_the_signature(self):
        receipt = self.receipt()
        receipt["outcome"] = "fail"
        check = verify_receipt(receipt, KEY)
        self.assertFalse(check.ok)
        self.assertIn("signature does not verify", check.errors)

    def test_wrong_key_fails(self):
        check = verify_receipt(self.receipt(), "other-key")
        self.assertFalse(check.ok)

    def test_expected_fields_must_match(self):
        receipt = self.receipt()
        self.assertFalse(
            verify_receipt(receipt, KEY, expected_commit="deadbeef").ok
        )
        self.assertFalse(
            verify_receipt(receipt, KEY, expected_manifest_digest="sha256:0").ok
        )
        self.assertFalse(verify_receipt(receipt, KEY, expected_outcome="fail").ok)

    def test_empty_key_cannot_sign(self):
        with self.assertRaises(ReceiptError):
            self.receipt(key="")

    def test_broken_trail_is_not_signed(self):
        entry = json.loads(self.trail.read_text(encoding="utf-8"))
        entry["outcome"] = "fail"
        self.trail.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        with self.assertRaises(ReceiptError):
            self.receipt()

    def test_receipt_without_trail_has_no_head(self):
        receipt = create_receipt(
            self.gate, self.root, KEY, actor="ci", trail_path=None
        )
        self.assertEqual(receipt["trail_head"], "")
        self.assertTrue(verify_receipt(receipt, KEY).ok)

    def test_cli_gate_writes_and_verifies_receipt(self):
        manifest_path = self.base / "capability.json"
        manifest_path.write_text(json.dumps(manifest_data()), encoding="utf-8")
        receipt_path = self.base / "receipt.json"
        trail_path = self.base / "cli-trail.jsonl"
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ASSAYSTONE_RECEIPT_KEY": KEY}):
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "gate",
                        "--manifest",
                        str(manifest_path),
                        "--stage",
                        "shadow",
                        "--root",
                        str(self.root),
                        "--audit",
                        str(trail_path),
                        "--receipt",
                        str(receipt_path),
                        "--actor",
                        "ci",
                        "--json",
                    ]
                )
        self.assertEqual(code, 0, out.getvalue())
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["outcome"], "pass")
        self.assertIn("receipt", payload)
        self.assertTrue(receipt_path.exists())

        verify_out = io.StringIO()
        with mock.patch.dict(os.environ, {"ASSAYSTONE_RECEIPT_KEY": KEY}):
            with contextlib.redirect_stdout(verify_out):
                code = cli.main(
                    ["receipt", "verify", str(receipt_path), "--outcome", "pass"]
                )
        self.assertEqual(code, 0, verify_out.getvalue())
        self.assertIn("receipt: valid", verify_out.getvalue())

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
    def test_ed25519_receipt_round_trip(self):
        private = self.base / "owner.key"
        public = self.base / "owner.pub"
        keys.generate(private, public)
        receipt = create_receipt(
            self.gate,
            self.root,
            actor="ci",
            trail_path=self.trail,
            at="2026-11-25T00:01:00Z",
            private_key_path=private,
        )
        self.assertTrue(receipt["signature"].startswith("ed25519:"))
        check = verify_receipt(
            receipt,
            expected_outcome="pass",
            public_key_path=public,
        )
        self.assertTrue(check.ok, check.errors)
        missing = verify_receipt(receipt, expected_outcome="pass")
        self.assertFalse(missing.ok)
        receipt["outcome"] = "fail"
        tampered = verify_receipt(receipt, public_key_path=public)
        self.assertFalse(tampered.ok)

    @unittest.skipUnless(HAVE_CRYPTO, "cryptography is not installed")
    def test_bad_public_key_file_is_an_error(self):
        private = self.base / "owner.key"
        keys.generate(private, self.base / "owner.pub")
        receipt = create_receipt(
            self.gate,
            self.root,
            actor="ci",
            trail_path=self.trail,
            private_key_path=private,
        )
        check = verify_receipt(
            receipt, public_key_path=self.base / "absent.pub"
        )
        self.assertFalse(check.ok)
        self.assertTrue(
            any("public key" in error for error in check.errors)
        )

    def test_cli_refuses_a_receipt_without_a_key(self):
        manifest_path = self.base / "capability.json"
        manifest_path.write_text(json.dumps(manifest_data()), encoding="utf-8")
        receipt_path = self.base / "receipt.json"
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stderr(err):
                code = cli.main(
                    [
                        "gate",
                        "--manifest",
                        str(manifest_path),
                        "--stage",
                        "shadow",
                        "--root",
                        str(self.root),
                        "--receipt",
                        str(receipt_path),
                    ]
                )
        self.assertEqual(code, 2)
        self.assertFalse(receipt_path.exists())
        self.assertIn("ASSAYSTONE_RECEIPT_KEY", err.getvalue())


if __name__ == "__main__":
    unittest.main()
