"""The capability status card: evidence summary and residual risk."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, trail
from assaystone.approval import create_approval
from assaystone.card import build_card, render_card
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.receipt import create_receipt

OWNER_KEY = "owner-key"
RECEIPT_KEY = "receipt-key"


def manifest_data(approval=False, unused=False):
    data = {
        "capability": "card-test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": ["internal"],
        "irreversible_actions": ["deploy"],
        "risk": "high",
        "lifecycle": "shadow",
        "manifest_approval": approval,
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
            {"id": "ok", "type": "command", "payload": {"command": ["true"]}},
            {"id": "approve", "type": "command", "payload": {"command": ["true"]}},
            {"id": "rollback", "type": "command", "payload": {"command": ["true"]}},
        ],
        "policies": {
            "shadow": {"require": ["ok"], "allow_merge": False},
            "canary": {"require": ["ok"], "allow_merge": True},
            "production": {
                "require": ["ok"],
                "approvals": ["approve"],
                "allow_merge": True,
                "allow_deploy": True,
                "rollback_required": True,
                "rollback": "rollback",
            },
        },
    }
    if unused:
        data["criteria"].append(
            {
                "id": "unused",
                "kind": "invariant",
                "statement": "never checked",
                "oracle": "unused",
                "severity": "high",
            }
        )
        data["oracles"].append(
            {"id": "unused", "type": "command", "payload": {"command": ["true"]}}
        )
    return data


class CardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        (self.root / "app.py").write_text("x = 1\n", encoding="utf-8")
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
        self.trail = self.base / "trail.jsonl"

    def manifest(self, **kwargs):
        return CapabilityManifest.from_dict(manifest_data(**kwargs))

    def record(self, manifest, stage="shadow"):
        gate = evaluate_gate(manifest, stage, self.root)
        trail.append(self.trail, gate, actor="ci", at="2026-11-25T00:00:00Z")
        return gate

    def test_card_summarizes_evidence_and_risks(self):
        manifest = self.manifest()
        self.record(manifest, "shadow")
        canary = self.record(manifest, "canary")
        receipt_path = self.base / "receipt.json"
        receipt = create_receipt(
            canary,
            self.root,
            RECEIPT_KEY,
            actor="ci",
            trail_path=self.trail,
            at="2026-11-25T00:01:00Z",
        )
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        card = build_card(
            manifest,
            stage="shadow",
            trail_path=self.trail,
            receipt_path=receipt_path,
            receipt_key=RECEIPT_KEY,
        )
        self.assertEqual(card.trail["last"]["shadow"]["outcome"], "pass")
        self.assertEqual(card.trail["last"]["canary"]["outcome"], "pass")
        self.assertTrue(card.receipt["ok"])
        text = render_card(card)
        self.assertIn("chain intact", text)
        self.assertIn("valid: pass", text)
        self.assertNotIn("no recorded `production` gate", " ".join(card.residual_risks))
        self.assertNotIn("does not verify", " ".join(card.residual_risks))

    def test_static_and_stage_gaps_are_reported(self):
        manifest = self.manifest(unused=True)
        card = build_card(manifest, stage="shadow")
        self.assertEqual([item["criterion"] for item in card.never_gated], ["unused"])
        self.assertTrue(
            any("unused" in risk for risk in card.residual_risks)
        )
        self.assertEqual(
            [item["criterion"] for item in card.stage_gap], ["unused"]
        )
        self.assertIn("Stage gap at `shadow`", render_card(card))

    def test_broken_trail_and_wrong_receipt_key_are_risks(self):
        manifest = self.manifest()
        gate = self.record(manifest)
        receipt = create_receipt(
            gate,
            self.root,
            RECEIPT_KEY,
            actor="ci",
            trail_path=self.trail,
            at="2026-11-25T00:01:00Z",
        )
        receipt_path = self.base / "receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        entry = json.loads(self.trail.read_text(encoding="utf-8"))
        entry["outcome"] = "fail"
        self.trail.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        card = build_card(
            manifest,
            trail_path=self.trail,
            receipt_path=receipt_path,
            receipt_key="wrong",
        )
        risks = " ".join(card.residual_risks)
        self.assertIn("trail does not verify", risks)
        self.assertIn("receipt does not verify", risks)

    def test_owner_approval_state_is_reported(self):
        data = manifest_data(approval=True)
        manifest_path = self.base / "capability.json"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        manifest = CapabilityManifest.load(manifest_path)
        approval = create_approval(manifest, "owner-1", OWNER_KEY)
        (self.base / "capability.approval.json").write_text(
            json.dumps(approval), encoding="utf-8"
        )
        without_key = build_card(manifest)
        self.assertFalse(without_key.approval["ok"])
        self.assertTrue(
            any("owner approval is not valid" in risk for risk in without_key.residual_risks)
        )
        with_key = build_card(manifest, owner_key=OWNER_KEY)
        self.assertTrue(with_key.approval["ok"])
        self.assertFalse(
            any("owner approval is not valid" in risk for risk in with_key.residual_risks)
        )

    def test_receipt_for_a_different_head_is_a_risk(self):
        manifest = self.manifest()
        gate = self.record(manifest)
        receipt = create_receipt(
            gate,
            self.root,
            RECEIPT_KEY,
            actor="ci",
            trail_path=self.trail,
            at="2026-11-25T00:01:00Z",
        )
        receipt_path = self.base / "receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        self.record(manifest, "canary")
        card = build_card(
            manifest,
            trail_path=self.trail,
            receipt_path=receipt_path,
            receipt_key=RECEIPT_KEY,
        )
        self.assertTrue(
            any("different trail head" in risk for risk in card.residual_risks)
        )

    def test_a_decision_on_older_code_is_stale(self):
        manifest_path = self.root / "capability.json"
        manifest_path.write_text(json.dumps(manifest_data()), encoding="utf-8")
        loaded = CapabilityManifest.load(manifest_path)
        gate = evaluate_gate(loaded, "shadow", self.root)
        trail.append(self.trail, gate, actor="ci", at="2026-11-25T00:00:00Z")
        card = build_card(loaded, stage="shadow", trail_path=self.trail)
        self.assertFalse(card.trail["last"]["shadow"]["stale"])
        self.assertFalse(
            any("different commit" in risk for risk in card.residual_risks)
        )

        (self.root / "later.txt").write_text("a later change\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "later"],
            cwd=self.root,
            check=True,
        )
        stale = build_card(loaded, stage="shadow", trail_path=self.trail)
        self.assertTrue(stale.trail["last"]["shadow"]["stale"])
        self.assertTrue(
            any("different commit" in risk for risk in stale.residual_risks)
        )
        self.assertIn("[stale commit]", render_card(stale))

    def test_the_card_reports_a_runtime_record(self):
        from assaystone.session_record import write_record

        manifest_path = self.root / "capability.json"
        manifest_path.write_text(json.dumps(manifest_data()), encoding="utf-8")
        loaded = CapabilityManifest.load(manifest_path)
        write_record(
            self.root,
            session_id="card-session",
            relative_paths=["app.py"],
            gate=evaluate_gate(loaded, "shadow", self.root),
            commit=subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip(),
        )
        card = build_card(loaded, stage="shadow", root=self.root)
        self.assertTrue(card.runtime["present"])
        self.assertTrue(card.runtime["ok"], card.runtime.get("reasons"))
        self.assertIn("card-session", render_card(card))

        (self.root / "app.py").write_text("x = 2\n", encoding="utf-8")
        stale = build_card(loaded, stage="shadow", root=self.root)
        self.assertFalse(stale.runtime["ok"])
        self.assertTrue(
            any("runtime record" in risk for risk in stale.residual_risks)
        )
        self.assertIn("NOT CURRENT", render_card(stale))

    def test_cli_json_and_text(self):
        manifest_path = self.base / "capability.json"
        manifest_path.write_text(json.dumps(manifest_data()), encoding="utf-8")
        manifest = CapabilityManifest.load(manifest_path)
        self.record(manifest)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability",
                    "status",
                    "--manifest",
                    str(manifest_path),
                    "--trail",
                    str(self.trail),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["capability"], "card-test")
        self.assertEqual(payload["trail"]["last"]["shadow"]["outcome"], "pass")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability",
                    "status",
                    "--manifest",
                    str(manifest_path),
                    "--trail",
                    str(self.trail),
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("Residual risk", out.getvalue())
        self.assertIn("last shadow: pass", out.getvalue())


if __name__ == "__main__":
    unittest.main()
