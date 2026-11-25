"""A reviewer-facing diff between two manifest versions."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.diff import compare, render_diff
from assaystone.plane import CapabilityManifest, manifest_digest

REPO = Path(__file__).resolve().parent.parent
CAPABILITIES = REPO / "examples" / "capability"


def base():
    return {
        "capability": "diff-test",
        "owner": "team",
        "systems": ["git"],
        "data_classes": ["internal"],
        "irreversible_actions": ["deploy"],
        "risk": "high",
        "lifecycle": "shadow",
        "criteria": [
            {
                "id": "compiles",
                "kind": "postcondition",
                "statement": "it compiles",
                "oracle": "build",
                "severity": "critical",
            }
        ],
        "oracles": [
            {"id": "build", "type": "command", "payload": {"command": ["true"]}},
            {"id": "audit", "type": "command", "payload": {"command": ["true"]}},
        ],
        "policies": {
            "shadow": {"require": ["build"], "allow_merge": False},
            "production": {
                "require": ["build", "audit"],
                "allow_merge": True,
                "allow_deploy": True,
            },
        },
    }


class DiffTest(unittest.TestCase):
    def manifests(self, mutate=None):
        old_data = base()
        new_data = copy.deepcopy(old_data)
        if mutate:
            mutate(new_data)
        old = CapabilityManifest.from_dict(old_data)
        new = CapabilityManifest.from_dict(new_data)
        return old, new

    def test_identical_manifests(self):
        old, new = self.manifests()
        diff = compare(old, new)
        self.assertFalse(diff.changed)
        self.assertEqual(diff.old_digest, diff.new_digest)
        self.assertIn("identical", render_diff(diff, "old", "new"))

    def test_removing_a_criterion_weakens_and_is_reported(self):
        def mutate(data):
            data["criteria"] = []

        old, new = self.manifests(mutate)
        diff = compare(old, new)
        self.assertTrue(diff.changed)
        self.assertTrue(diff.weakened)
        self.assertEqual([item["id"] for item in diff.criteria_removed], ["compiles"])
        text = render_diff(diff, "old", "new")
        self.assertIn("removes or lowers assurance", text)
        self.assertIn("criteria removed", text)

    def test_lowering_severity_weakens(self):
        def mutate(data):
            data["criteria"][0]["severity"] = "medium"

        old, new = self.manifests(mutate)
        diff = compare(old, new)
        self.assertTrue(diff.weakened)
        self.assertEqual(diff.criteria_changed[0]["id"], "compiles")
        self.assertIn(
            "severity: 'critical' -> 'medium'", render_diff(diff, "a", "b")
        )

    def test_tightening_is_not_flagged_as_weakened(self):
        def mutate(data):
            data["criteria"][0]["severity"] = "critical"
            data["criteria"].append(
                {
                    "id": "audited",
                    "kind": "invariant",
                    "statement": "audited",
                    "oracle": "audit",
                    "severity": "high",
                }
            )

        old, new = self.manifests(mutate)
        diff = compare(old, new)
        self.assertTrue(diff.changed)
        self.assertFalse(diff.weakened)
        self.assertEqual([item["id"] for item in diff.criteria_added], ["audited"])

    def test_oracle_changes_are_visible(self):
        def mutate(data):
            data["oracles"][0]["payload"]["command"] = ["false"]

        old, new = self.manifests(mutate)
        diff = compare(old, new)
        self.assertTrue(diff.oracles_changed)
        self.assertIn("~ build:", render_diff(diff, "a", "b"))

        def remove(data):
            data["oracles"] = [item for item in data["oracles"] if item["id"] != "audit"]
            data["policies"]["production"]["require"] = ["build"]

        old, new = self.manifests(remove)
        diff = compare(old, new)
        self.assertTrue(diff.weakened)
        self.assertEqual(diff.oracles_removed, ["audit"])

    def test_policy_changes_are_reported(self):
        def mutate(data):
            data["policies"]["production"]["require"] = ["build"]
            data["policies"]["production"].pop("allow_deploy")
            data["policies"]["canary"] = {"require": ["build"], "allow_merge": True}

        old, new = self.manifests(mutate)
        diff = compare(old, new)
        stages = {item["stage"]: item for item in diff.policies}
        self.assertEqual(stages["canary"]["change"], "added")
        self.assertEqual(
            stages["production"]["require"]["removed"], ["audit"]
        )
        self.assertTrue(diff.weakened)

    def test_removing_a_stage_weakens(self):
        def mutate(data):
            data["policies"].pop("production")

        old, new = self.manifests(mutate)
        diff = compare(old, new)
        self.assertTrue(diff.weakened)
        self.assertEqual(diff.policies[0]["change"], "removed")

    def test_owner_risk_and_approval_changes(self):
        def mutate(data):
            data["owner"] = "another-team"
            data["risk"] = "low"
            data["manifest_approval"] = True
            data["waivers"] = True

        old, new = self.manifests(mutate)
        diff = compare(old, new)
        text = render_diff(diff, "a", "b")
        self.assertIn("owner: 'team' -> 'another-team'", text)
        self.assertIn("risk: high -> low (lowered)", text)
        self.assertIn("owner approval: not required -> required", text)
        self.assertIn("waivers: disabled -> enabled", text)

    def test_digest_changes_with_the_manifest(self):
        old, new = self.manifests(lambda data: data["risk"].__str__())
        self.assertEqual(manifest_digest(old), manifest_digest(new))

    def test_cli_text_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "old.json"
            new_path = Path(tmp) / "new.json"
            old_path.write_text(json.dumps(base()), encoding="utf-8")
            data = base()
            data["criteria"] = []
            new_path.write_text(json.dumps(data), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "capability", "diff",
                        "--manifest", str(new_path),
                        "--old", str(old_path),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["weakened"])
            self.assertEqual(payload["criteria"]["removed"][0]["id"], "compiles")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    [
                        "capability", "diff",
                        "--manifest", str(new_path),
                        "--old", str(old_path),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("removes or lowers assurance", out.getvalue())

    def test_cli_rejects_an_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = Path(tmp) / "old.json"
            new_path = Path(tmp) / "new.json"
            old_path.write_text(json.dumps(base()), encoding="utf-8")
            data = base()
            data["criteria"] = []
            new_path.write_text(json.dumps(data), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cli.main(
                    [
                        "capability", "diff",
                        "--manifest", str(new_path),
                        "--old", str(Path(tmp) / "absent.json"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("not found", err.getvalue())

    def test_examples_compare_cleanly_with_themselves(self):
        for name in ("pricing.json", "support.json", "java.json"):
            path = CAPABILITIES / name
            manifest = CapabilityManifest.load(path)
            diff = compare(manifest, manifest)
            self.assertFalse(diff.changed, name)


if __name__ == "__main__":
    unittest.main()
