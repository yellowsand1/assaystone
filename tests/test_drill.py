"""A drill proves the compensation restores the state, and the oracle checks it."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.drill import (
    DrillError,
    load_record,
    record_path,
    run_drill,
    verify_record,
    write_record,
)
from assaystone.oracles import OracleSpec, run_oracle
from assaystone.plane import CapabilityManifest, PlaneError, evaluate_gate


def manifest_data(compensation="undo", state=("artifact.txt",)):
    return {
        "capability": "drill-test",
        "owner": "team",
        "systems": [],
        "data_classes": [],
        "irreversible_actions": ["write"],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": [],
        "oracles": [
            {
                "id": "do",
                "type": "command",
                "payload": {
                    "command": ["sh", "-c", "echo made > artifact.txt"],
                    "mutates": True,
                },
            },
            {
                "id": "undo",
                "type": "command",
                "payload": {"command": ["rm", "-f", "artifact.txt"], "mutates": True},
            },
            {
                "id": "noop",
                "type": "command",
                "payload": {"command": ["true"], "mutates": True},
            },
        ],
        "reversibility": [
            {
                "id": "write-drill",
                "action": "do",
                "compensation": compensation,
                "state": list(state),
            }
        ],
        "policies": {"shadow": {"require": ["do"]}},
    }


class DrillTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "--allow-empty", "-qm", "one"],
            cwd=self.root,
            check=True,
        )
        (self.root / "capability.json").write_text(
            json.dumps(manifest_data()), encoding="utf-8"
        )
        self.manifest = CapabilityManifest.load(self.root / "capability.json")

    def test_a_working_compensation_passes(self):
        result = run_drill(self.manifest, "write-drill", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertEqual(result.action_outcome, "pass")
        self.assertEqual(result.compensation_outcome, "pass")
        self.assertEqual(result.before, result.after)
        self.assertFalse((self.root / "artifact.txt").exists())

    def test_a_compensation_that_does_nothing_fails(self):
        (self.root / "capability.json").write_text(
            json.dumps(manifest_data(compensation="noop")), encoding="utf-8"
        )
        manifest = CapabilityManifest.load(self.root / "capability.json")
        result = run_drill(manifest, "write-drill", self.root)
        self.assertEqual(result.outcome, "fail")
        self.assertIn("did not restore the state", result.reasons[0])
        self.assertIn("artifact.txt", result.reasons[0])

    def test_an_action_that_changes_nothing_proves_nothing(self):
        data = manifest_data(compensation="noop")
        data["reversibility"][0]["action"] = "noop"
        data["reversibility"][0]["compensation"] = "do"
        data["reversibility"][0]["state"] = ["never-touched.txt"]
        (self.root / "capability.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        manifest = CapabilityManifest.load(self.root / "capability.json")
        result = run_drill(manifest, "write-drill", self.root)
        self.assertEqual(result.outcome, "fail")
        self.assertIn("proves nothing", " ".join(result.reasons))

    def test_a_directory_state_is_hashed_by_content(self):
        data = manifest_data(state=("out",))
        data["oracles"][0]["payload"]["command"] = [
            "sh", "-c", "mkdir -p out && echo x > out/a.txt"
        ]
        data["oracles"][1]["payload"]["command"] = ["rm", "-rf", "out"]
        (self.root / "capability.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        manifest = CapabilityManifest.load(self.root / "capability.json")
        result = run_drill(manifest, "write-drill", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertTrue(result.middle["out"].startswith("dir-sha256:"))
        self.assertEqual(result.after["out"], "absent")

    def test_an_unknown_drill_raises(self):
        with self.assertRaises(DrillError):
            run_drill(self.manifest, "absent", self.root)

    def test_the_manifest_rejects_a_broken_declaration(self):
        data = manifest_data()
        data["reversibility"][0]["action"] = "missing"
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

        data = manifest_data()
        data["reversibility"][0]["compensation"] = "do"
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

        data = manifest_data(state=())
        with self.assertRaises(PlaneError):
            CapabilityManifest.from_dict(data)

    def test_the_record_is_bound_to_rules_and_commit(self):
        result = run_drill(self.manifest, "write-drill", self.root)
        path = write_record(
            self.manifest, result, self.root, actor="ci",
            at="2026-11-25T00:00:00Z",
        )
        record = load_record(path)
        self.assertEqual(record["outcome"], "pass")
        self.assertEqual(record["actor"], "ci")
        self.assertTrue(record["commit"])
        check = verify_record(record, self.manifest, self.root, "write-drill")
        self.assertTrue(check.ok, check.reasons)

    def test_a_drill_for_other_rules_is_not_evidence(self):
        result = run_drill(self.manifest, "write-drill", self.root)
        path = write_record(self.manifest, result, self.root, actor="ci")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["manifest_digest"] = "sha256:other"
        path.write_text(json.dumps(data), encoding="utf-8")
        check = verify_record(
            load_record(path), self.manifest, self.root, "write-drill"
        )
        self.assertFalse(check.ok)
        self.assertIn("different acceptance rules", check.reasons[0])

    def test_a_drill_for_other_code_is_not_evidence(self):
        result = run_drill(self.manifest, "write-drill", self.root)
        path = write_record(self.manifest, result, self.root, actor="ci")
        (self.root / "later.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "two"],
            cwd=self.root,
            check=True,
        )
        check = verify_record(
            load_record(path), self.manifest, self.root, "write-drill"
        )
        self.assertFalse(check.ok)
        self.assertIn("the drill was run on commit", check.reasons[0])

    def test_a_failed_drill_is_a_failure(self):
        (self.root / "capability.json").write_text(
            json.dumps(manifest_data(compensation="noop")), encoding="utf-8"
        )
        manifest = CapabilityManifest.load(self.root / "capability.json")
        result = run_drill(manifest, "write-drill", self.root)
        path = write_record(manifest, result, self.root, actor="ci")
        check = verify_record(load_record(path), manifest, self.root, "write-drill")
        self.assertFalse(check.ok)
        self.assertEqual(check.outcome, "fail")

    def test_the_oracle_decides_from_the_record(self):
        spec = OracleSpec(
            id="drill",
            type="drill",
            payload={"manifest": "capability.json", "id": "write-drill"},
        )
        missing = run_oracle(spec, self.root)
        self.assertEqual(missing.outcome, "escalate")
        self.assertIn("no drill record", missing.reasons[0])

        result = run_drill(self.manifest, "write-drill", self.root)
        write_record(self.manifest, result, self.root, actor="ci")
        passed = run_oracle(spec, self.root)
        self.assertEqual(passed.outcome, "pass", passed.reasons)

    def test_cli_drill_and_exit_code(self):
        out = __import__("io").StringIO()
        import contextlib

        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability", "drill",
                    "--manifest", str(self.root / "capability.json"),
                    "--root", str(self.root),
                ]
            )
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("drill write-drill: pass", out.getvalue())
        self.assertTrue(record_path(self.root, "write-drill").exists())

        (self.root / "capability.json").write_text(
            json.dumps(manifest_data(compensation="noop")), encoding="utf-8"
        )
        with contextlib.redirect_stdout(__import__("io").StringIO()):
            code = cli.main(
                [
                    "capability", "drill",
                    "--manifest", str(self.root / "capability.json"),
                    "--root", str(self.root),
                ]
            )
        self.assertEqual(code, 1)

    def test_the_gate_can_require_a_drill(self):
        data = manifest_data()
        data["criteria"] = [
            {
                "id": "reversible",
                "kind": "invariant",
                "statement": "the write can be undone",
                "oracle": "drill",
                "severity": "critical",
            }
        ]
        data["oracles"].append(
            {
                "id": "drill",
                "type": "drill",
                "payload": {"manifest": "capability.json", "id": "write-drill"},
            }
        )
        data["policies"] = {
            "production": {
                "require": ["drill"],
                "approvals": ["undo"],
                "allow_merge": True,
                "allow_deploy": True,
                "rollback_required": True,
                "rollback": "undo",
            }
        }
        (self.root / "capability.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        manifest = CapabilityManifest.load(self.root / "capability.json")

        blocked = evaluate_gate(manifest, "production", self.root)
        self.assertEqual(blocked.outcome, "escalate")

        result = run_drill(manifest, "write-drill", self.root)
        write_record(manifest, result, self.root, actor="ci")
        allowed = evaluate_gate(manifest, "production", self.root)
        self.assertEqual(allowed.outcome, "pass", allowed.reasons)
        self.assertTrue(allowed.deploy_allowed)


if __name__ == "__main__":
    unittest.main()
