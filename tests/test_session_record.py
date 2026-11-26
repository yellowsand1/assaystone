"""A record the supervisor wrote, and the oracle that decides against it."""

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from assaystone.oracles import OracleSpec, run_oracle
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.session_record import (
    RecordError,
    load_record,
    observe,
    verify_record,
    write_record,
)


def manifest_data():
    return {
        "capability": "runtime-test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": [
            {
                "id": "session",
                "kind": "evidence",
                "statement": "the session ended in a passing gate",
                "oracle": "record",
                "severity": "critical",
            }
        ],
        "oracles": [
            {
                "id": "record",
                "type": "runtime",
                "payload": {"record": ".assaystone/runtime/last.json"},
            }
        ],
        "policies": {"shadow": {"require": ["record"]}},
    }


class _Gate:
    capability = "runtime-test"
    stage = "shadow"
    outcome = "pass"
    manifest_digest = "sha256:abc"


class SessionRecordTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "app.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_app.py").write_text("def test(): pass\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "one"],
            cwd=self.root,
            check=True,
        )
        self.head = self.commit()

    def commit(self):
        return subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def record(self, **kwargs):
        gate = kwargs.pop("gate", _Gate())
        return write_record(
            self.root,
            session_id="session-1",
            relative_paths=["app.py", "tests/test_app.py"],
            gate=gate,
            commit=self.head,
            **kwargs,
        )

    def test_a_fresh_record_describes_the_workspace(self):
        path = self.record()
        self.assertTrue(path.exists())
        record = load_record(path)
        self.assertEqual(record["source"], "runtime")
        self.assertEqual(record["commit"], self.head)
        self.assertIn("app.py", record["files"])
        self.assertTrue((self.root / ".assaystone/runtime/session-1.json").exists())

    def test_verify_passes_when_nothing_moved(self):
        self.record()
        check = verify_record(load_record(self.root / ".assaystone/runtime/last.json"),
                              self.root)
        self.assertTrue(check.ok, check.reasons)
        self.assertEqual(check.outcome, "pass")

    def test_a_changed_file_after_the_record_is_drift(self):
        self.record()
        (self.root / "app.py").write_text("x = 2\n", encoding="utf-8")
        check = verify_record(load_record(self.root / ".assaystone/runtime/last.json"),
                              self.root)
        self.assertFalse(check.ok)
        self.assertEqual(check.outcome, "escalate")
        self.assertIn("changed after the session ended", check.reasons[0])

    def test_new_code_makes_the_record_stale(self):
        self.record()
        (self.root / "later.txt").write_text("later\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "two"],
            cwd=self.root,
            check=True,
        )
        check = verify_record(load_record(self.root / ".assaystone/runtime/last.json"),
                              self.root)
        self.assertFalse(check.ok)
        self.assertIn("was written for commit", check.reasons[0])

    def test_a_failed_gate_is_a_failure_not_an_escalation(self):
        gate = type("G", (), {**{k: getattr(_Gate, k) for k in dir(_Gate)
                                if not k.startswith("_")}, "outcome": "fail"})
        self.record(gate=gate)
        check = verify_record(load_record(self.root / ".assaystone/runtime/last.json"),
                              self.root)
        self.assertFalse(check.ok)
        self.assertEqual(check.outcome, "fail")
        self.assertIn("ended with gate outcome 'fail'", check.reasons[0])

    def test_an_old_record_escalates(self):
        path = self.record()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["at"] = (
            datetime.now(timezone.utc) - timedelta(hours=3)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(json.dumps(data), encoding="utf-8")
        check = verify_record(
            load_record(path), self.root, max_age_minutes=60
        )
        self.assertFalse(check.ok)
        self.assertIn("older than", check.reasons[0])

    def test_a_record_that_is_not_runtime_sourced_is_not_trusted(self):
        path = self.record()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source"] = "agent"
        path.write_text(json.dumps(data), encoding="utf-8")
        check = verify_record(load_record(path), self.root)
        self.assertFalse(check.ok)
        self.assertIn("runtime-authored", check.reasons[0])

    def test_a_record_without_an_observation_is_not_evidence(self):
        path = self.record()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["files"] = {}
        path.write_text(json.dumps(data), encoding="utf-8")
        check = verify_record(load_record(path), self.root)
        self.assertFalse(check.ok)
        self.assertIn("observed no files", " ".join(check.reasons))

    def test_observe_marks_absent_files(self):
        files = observe(self.root, ["app.py", "missing.py"])
        self.assertTrue(files["app.py"].startswith("sha256:"))
        self.assertEqual(files["missing.py"], "absent")

    def test_a_missing_record_raises(self):
        with self.assertRaises(RecordError):
            load_record(self.root / "absent.json")

    def test_the_oracle_and_the_gate_use_the_record(self):
        self.record()
        spec = OracleSpec(
            id="record",
            type="runtime",
            payload={"record": ".assaystone/runtime/last.json"},
        )
        result = run_oracle(spec, self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)

        manifest = CapabilityManifest.from_dict(manifest_data())
        gate = evaluate_gate(manifest, "shadow", self.root)
        self.assertEqual(gate.outcome, "pass", gate.reasons)

    def test_the_oracle_escalates_when_the_record_is_missing(self):
        spec = OracleSpec(
            id="record",
            type="runtime",
            payload={"record": ".assaystone/runtime/last.json"},
        )
        result = run_oracle(spec, self.root)
        self.assertEqual(result.outcome, "escalate")
        self.assertIn("no runtime record", result.reasons[0])

    def test_the_oracle_fails_on_a_failed_session(self):
        gate = type("G", (), {"capability": "runtime-test", "stage": "shadow",
                              "outcome": "fail", "manifest_digest": "x"})
        self.record(gate=gate)
        spec = OracleSpec(
            id="record",
            type="runtime",
            payload={"record": ".assaystone/runtime/last.json"},
        )
        result = run_oracle(spec, self.root)
        self.assertEqual(result.outcome, "fail")

    def test_the_oracle_escalates_on_drift(self):
        self.record()
        (self.root / "app.py").write_text("x = 9\n", encoding="utf-8")
        manifest = CapabilityManifest.from_dict(manifest_data())
        gate = evaluate_gate(manifest, "shadow", self.root)
        self.assertEqual(gate.outcome, "escalate")


if __name__ == "__main__":
    unittest.main()
