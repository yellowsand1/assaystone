"""The session and the decision it produced must point at each other."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, trail
from assaystone.oracles import OracleSpec, run_oracle
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.receipt import create_receipt, verify_receipt
from assaystone.session_record import load_record, write_record

REPO = Path(__file__).resolve().parent.parent


def manifest_data(require_session=True):
    return {
        "capability": "linked",
        "owner": "team",
        "systems": ["git"],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "low",
        "lifecycle": "shadow",
        "criteria": [],
        "oracles": [
            {"id": "ok", "type": "command", "payload": {"command": ["true"]}},
            {
                "id": "session",
                "type": "runtime",
                "payload": {
                    "record": ".assaystone/runtime/last.json",
                    "trail": "trail.jsonl",
                },
            },
        ],
        "policies": {
            "shadow": {
                "require": ["ok", "session"] if require_session else ["ok"]
            }
        },
    }


class LinkedEvidenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "app.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "one"],
            cwd=self.root,
            check=True,
        )
        self.commit = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.trail = self.root / "trail.jsonl"
        self.manifest = CapabilityManifest.from_dict(manifest_data())

    def decide(self, manifest=None):
        manifest = manifest or self.manifest
        gate = evaluate_gate(manifest, "shadow", self.root, skip_types={"runtime"})
        entry = trail.append(
            self.trail, gate, actor="ci", at="2026-11-25T00:00:00Z"
        )
        return gate, entry

    def record(self, entry_hash="", commit=None, session="sess-1"):
        return write_record(
            self.root,
            session_id=session,
            relative_paths=["app.py"],
            gate=type("G", (), {"capability": "linked", "stage": "shadow",
                                "outcome": "pass", "manifest_digest": "sha256:x",
                                "commit": self.commit}),
            commit=commit or self.commit,
            entry_hash=entry_hash,
        )

    def test_a_session_that_names_its_decision_passes(self):
        gate, entry = self.decide()
        self.assertEqual(gate.outcome, "pass", gate.reasons)
        self.assertEqual(gate.skipped, ["session"])
        self.record(entry_hash=entry["hash"])
        spec = OracleSpec(
            id="session", type="runtime",
            payload={"record": ".assaystone/runtime/last.json",
                     "trail": "trail.jsonl"},
        )
        result = run_oracle(spec, self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertEqual(result.facts["session"], "sess-1")
        self.assertEqual(result.facts["entry"], entry["hash"])
        self.assertTrue(result.facts["record"].startswith("sha256:"))

    def test_a_decision_that_is_not_on_the_trail_escalates(self):
        self.decide()
        self.record(entry_hash="sha256:" + "0" * 64)
        spec = OracleSpec(
            id="session", type="runtime",
            payload={"record": ".assaystone/runtime/last.json",
                     "trail": "trail.jsonl"},
        )
        result = run_oracle(spec, self.root)
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("not on the trail", result.reasons[0])

    def test_a_session_and_decision_about_different_code_escalate(self):
        _, entry = self.decide()
        (self.root / "later.txt").write_text("later\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "two"],
            cwd=self.root,
            check=True,
        )
        self.record(entry_hash=entry["hash"])
        spec = OracleSpec(
            id="session", type="runtime",
            payload={"record": ".assaystone/runtime/last.json"},
        )
        result = run_oracle(spec, self.root)
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("was written for commit", result.reasons[0])

    def test_facts_reach_the_trail_and_the_receipt(self):
        gate, entry = self.decide()
        self.record(entry_hash=entry["hash"])
        verifier = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(verifier.outcome, "pass", verifier.reasons)
        session = next(
            item for item in verifier.results if item.oracle == "session"
        )
        self.assertEqual(session.facts["session"], "sess-1")
        path = self.root / "entry.jsonl"
        trail.append(path, verifier, actor="ci", at="2026-11-25T00:00:00Z")
        stored = json.loads(path.read_text(encoding="utf-8"))
        facts = next(
            item["facts"] for item in stored["oracles"] if item["id"] == "session"
        )
        self.assertEqual(facts["session"], "sess-1")
        receipt = create_receipt(verifier, self.root, "key", actor="ci")
        self.assertEqual(receipt["oracles"][1]["facts"]["session"], "sess-1")

    def test_a_receipt_can_be_checked_against_the_session_it_cites(self):
        gate, entry = self.decide()
        record_path = self.record(entry_hash=entry["hash"])
        verifier = evaluate_gate(self.manifest, "shadow", self.root)
        receipt = create_receipt(verifier, self.root, "key", actor="ci")
        check = verify_receipt(
            receipt, "key", runtime_record=record_path
        )
        self.assertTrue(check.ok, check.errors)

        data = json.loads(record_path.read_text(encoding="utf-8"))
        data["session_id"] = "someone-else"
        record_path.write_text(json.dumps(data), encoding="utf-8")
        changed = verify_receipt(receipt, "key", runtime_record=record_path)
        self.assertFalse(changed.ok)
        self.assertIn("does not match", changed.errors[0])

    def test_a_receipt_without_session_evidence_says_so(self):
        gate = evaluate_gate(
            self.manifest, "shadow", self.root, skip_types={"runtime"}
        )
        receipt = create_receipt(gate, self.root, "key", actor="ci")
        check = verify_receipt(
            receipt, "key", runtime_record=self.root / "absent.json"
        )
        self.assertFalse(check.ok)
        self.assertIn("cites no runtime record", check.errors[0])

    def test_the_hook_does_not_cite_itself(self):
        (self.root / ".assaystone").mkdir()
        (self.root / ".assaystone" / "capability.json").write_text(
            json.dumps(manifest_data()), encoding="utf-8"
        )
        (self.root / ".assaystone" / "hook.json").write_text(
            json.dumps(
                {
                    "mode": "warn",
                    "capability": ".assaystone/capability.json",
                    "stage": "shadow",
                    "trail": ".assaystone/trail.jsonl",
                }
            ),
            encoding="utf-8",
        )
        from assaystone.hooks.claude_code import run_hook

        run_hook(
            {
                "session_id": "sess-hook",
                "transcript_path": str(self.root / "absent.jsonl"),
                "cwd": str(self.root),
            }
        )
        record = load_record(self.root / ".assaystone/runtime/last.json")
        self.assertEqual(record["gate"]["outcome"], "pass")
        self.assertTrue(record["gate"]["entry_hash"])
        entries = [
            json.loads(line)
            for line in (self.root / ".assaystone/trail.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual(entries[-1]["hash"], record["gate"]["entry_hash"])

    def test_the_cli_reports_session_evidence(self):
        gate, entry = self.decide()
        record_path = self.record(entry_hash=entry["hash"])
        verifier = evaluate_gate(self.manifest, "shadow", self.root)
        receipt = create_receipt(verifier, self.root, "key", actor="ci")
        receipt_path = self.root / "receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        import contextlib
        import io
        import os
        from unittest import mock

        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ASSAYSTONE_RECEIPT_KEY": "key"}):
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "receipt", "verify", str(receipt_path),
                        "--runtime-record", str(record_path),
                    ]
                )
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("session evidence: sess-1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
